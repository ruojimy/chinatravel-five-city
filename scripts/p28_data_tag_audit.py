"""Read-only provenance/collection/TAG audit. Does not collect, normalize or republish data."""
import collections,hashlib,json,sqlite3,sys
from datetime import datetime
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'src'))
from shorttrip.visitor_tags import extract_mentions,describe
O=R/'results/p28_data_collection_tag_audit';O.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as s:
  for b in iter(lambda:s.read(1048576),b''):h.update(b)
 return h.hexdigest()
def db(path):
 c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c
def rows(c,sql):return [dict(r) for r in c.execute(sql)]
audit={'at':datetime.now().astimezone().isoformat(),'mode':'offline read-only audit; no business-source collection, no database updates, no new human labels'}
baseline=R/'data/catalog_v1_1_20261022';m=read(baseline/'manifest.json');c=db(baseline/'catalog.sqlite3')
integrity=[{'file':f['file'],'ok':digest(R/f['file'])==f['sha256']} for f in m['source_files']]
audit['original_annotation']={'records':rows(c,'select lang,kind,count(*) n from records group by lang,kind'),'tags':rows(c,'select tag,count(*) n from tags group by tag'),'records_total':c.execute('select count(*) from records').fetchone()[0],'tags_total':c.execute('select count(*) from tags').fetchone()[0],'source_files':len(integrity),'all_original_files_match_sidecar_manifest':all(x['ok'] for x in integrity),'integrity_checks':integrity}
c.close()
pointer=read(R/'results/p15_whole_catalog/current_catalog.json');p=R/pointer['catalog'];before=digest(p);c=db(p)
audit['expanded_catalog']={'path':pointer['catalog'],'sha256':before,'matches_published_pointer':before==pointer['sha256'],'counts':rows(c,'select kind,count(*) n,sum(provider_city_match) city_supported,sum(planning_ready) planning_ready from records group by kind'),'tag_counts':rows(c,'select tag,count(*) n from tags group by tag'),'sources':{},'tag_statuses':{},'tables':{}}
src=collections.Counter();clock=collections.Counter();tagstatus=collections.Counter()
for row in c.execute('select payload from records'):
 x=json.loads(row[0]);src[x['source_id']]+=1;clock['known_record_observed_at' if x.get('observed_at') else 'unknown_record_observed_at']+=1
for row in c.execute('select payload from tags'):
 x=json.loads(row[0]);tagstatus[x.get('status','unspecified')]+=1
for row in c.execute("select name from sqlite_master where type='table'"):
 name=row[0];audit['expanded_catalog']['tables'][name]=c.execute('select count(*) from "'+name+'"').fetchone()[0]
audit['expanded_catalog'].update(sources=dict(src),record_clock=dict(clock),tag_statuses=dict(tagstatus),sqlite_integrity=c.execute('pragma integrity_check').fetchone()[0]);c.close()
audit['expanded_catalog']['unchanged_during_audit']=before==digest(p)
collection=read(R/'data/expansion_v1_20261022/collection_manifest.json');counts=collections.Counter();skipped=collections.Counter()
for city in collection['cities']:counts.update(city.get('counts',{}));skipped.update(city.get('skipped',{}))
exp=read(R/'results/p12_expansion/expansion_summary.json')
audit['overture_collection']={'release':collection['release'],'city_windows':collection['city_windows'],'counts':dict(counts),'logged_skips':dict(skipped),'city_status':[(x['city'],x['status']) for x in collection['cities']],'dedup_by_gers_removed':exp['dedup_by_gers_removed'],'dedup_by_name_30m_removed':exp['dedup_by_name_30m_removed'],'post_dedup_records':exp['counts']['records'],'post_dedup_tags':exp['tags'],'provider_city_assertion_counts':exp['provider_city_assertion_counts'],'city_attribution_unverified':exp['city_attribution_unverified']}
audit['tag_stores']={}
for name in ['tag_store.sqlite','tag_store_v2.sqlite']:
 c=db(R/'data'/name);audit['tag_stores'][name]={'snapshots':rows(c,'select * from snapshots'),'records':rows(c,'select evidence_kind,status,count(*) n,count(distinct local_poi_id) pois from tags group by evidence_kind,status')};c.close()
audit['review_normalization']=read(R/'data/visitor_reviews_raw/zhangjiajie_stats.json');audit['review_normalization'].pop('sample',None)
frozen=read(R/'results/p5_visitor_tag/extract_report.json');audit['p5_frozen']={'extractor':frozen['extraction']['extractor'],'mentions':frozen['extraction']['mentions'],'aggregate_records':frozen['extraction']['records'],'decisions':frozen['extraction']['by_decision'],'reviews_sampled':frozen['corpus']['reviews_sampled']}
audit['current_review_extractor']=describe()
audit['synthetic_semantic_probes']={'purpose':'diagnostic phrases only, not actual reviews, no publication to TAG store','items':[]}
for sentence in ['This place is not suitable for children.','There are no toilets here.','The bus was late.']:
 found=extract_mentions({'review_id':'synthetic-diagnostic','poi_hint':'synthetic-diagnostic','text':sentence})
 audit['synthetic_semantic_probes']['items'].append({'text':sentence,'outputs':[x.to_dict() for x in found]})
p10=read(R/'results/p10_tag_matching/refined_semantics/real_review_probe.json');audit['p10_real_probe']={k:v for k,v in p10.items() if k!='evidence'}
v2=read(R/'results/p6_matching/p2_v2/tag_summary.json');audit['p6_open_tag_v2']=v2['records']
(O/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'original_rows':audit['original_annotation']['records_total'],'original_tags':audit['original_annotation']['tags_total'],'original_files':len(integrity),'original_files_unchanged':all(x['ok'] for x in integrity),'catalog_unchanged':audit['expanded_catalog']['unchanged_during_audit'],'expanded_tables':audit['expanded_catalog']['tables'],'tag_statuses':dict(tagstatus),'synthetic_diagnostics':audit['synthetic_semantic_probes'],'current_review_extractor':describe()},ensure_ascii=False,indent=2))
