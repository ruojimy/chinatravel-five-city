"""Build an immutable, provenance-labelled five-city reference dataset offline.

Missing values remain null. Native-field completeness, schema validity, and
current planning eligibility are measured separately. No official data/checker
files or historical catalogue pointers are changed by this builder.
"""
from __future__ import annotations
import argparse,collections,copy,csv,gzip,hashlib,json,re,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import FIELDS,VERSION,validate_record,validate_evidence,validate_claim
from shorttrip.expansion_store import ExpansionStore
from shorttrip.freshness import field_policy,POLICIES,parse_time,canonical
WORK=ROOT/'results/p29_five_city_completion'
CITIES=['西安','厦门','宁波','长沙','青岛']
SLUGS=dict(zip(CITIES,['xian','xiamen','ningbo','changsha','qingdao']))
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def sha(x):return hashlib.sha256(x).hexdigest()
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def known(v):return v is not None and v!=''
def jsongz(p,rows):
 with gzip.open(p,'wt',encoding='utf-8',newline='\n') as f:
  for x in rows:f.write(canonical(x)+'\n')
def dateclock(v):return v if isinstance(v,str) and parse_time(v) else None
def field_unit(field,kind):
 if field in ('price','Cost'):return 'CNY/person' if kind in ('restaurant','attraction') else 'CNY/room/night' if kind=='accommodation' else 'CNY/ticket'
 if field in ('lat','lon'):return 'degrees'
 if field=='Duration':return 'minutes'
 if field.startswith('recommend'):return 'hours'
 if field=='numbed':return 'beds/room'
 return None

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
 dest=Path(a.output)
 if not dest.is_absolute():dest=ROOT/dest
 if dest.exists():raise FileExistsError('Preserve existing version: '+str(dest))
 at=now();pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'))
 oldpath=ROOT/pointer['catalog'];before=sha(oldpath.read_bytes())
 old=sqlite3.connect(oldpath.as_uri()+'?mode=ro',uri=True)
 bases={r['record_id']:r for r in (json.loads(x[0]) for x in old.execute('select payload from records'))}
 evidence={};claims=[];records=[];registry={};events=[];semantic=[];edits=[]
 def source(s):
  raw=s.get('raw_text')
  if not isinstance(raw,str) or not raw.strip():raise ValueError('Evidence requires captured source text')
  url=s.get('url') or s.get('source_url')
  if not url:raise ValueError('Source URL required')
  supplied=s.get('source_id') or urlparse(url).hostname or 'local-archive'
  sid='p29:'+sha((supplied+'|'+url).encode())[:24]
  t={k:dateclock(s.get(k)) for k in ['source_published_at','source_updated_at','observed_at']}
  retrieved=dateclock(s.get('retrieved_at'))
  if not retrieved:raise ValueError('Retrieval clock required: '+url)
  eid='p29-evidence:'+sha(canonical([sid,raw,t,retrieved]).encode())
  e=dict(evidence_id=eid,source_id=sid,source_url=url,raw_text=raw,raw_sha256=sha(raw.encode()),retrieved_at=retrieved,
         authority=s.get('authority','historical_reference'),licence_status=s.get('licence_status','unknown'),**t)
  e['capture_method']=s.get('capture_method','retained_source_snapshot')
  e['original_time_text']={k:s[k] for k in t if s.get(k) is not None and t[k] is None}
  if e['original_time_text']:events.append({'type':'partial_date_preserved_as_text','source_url':url,'original':e['original_time_text']})
  if s.get('raw_sha256') and s['raw_sha256']!=e['raw_sha256']:raise ValueError('Source raw SHA mismatch: '+url)
  evidence[eid]=e
  registry[sid]={'allowed_hosts':[urlparse(url).hostname] if urlparse(url).hostname else [],'authority':e['authority'],
    'independence_group':urlparse(url).hostname or supplied,'supports':list(POLICIES),'licence_status':e['licence_status']}
  return e
 def inherited(b,f):
  p=copy.deepcopy((b.get('field_provenance') or {}).get(f) or {})
  eid=p.get('evidence_id')
  if eid:
   row=old.execute('select payload from evidence where id=?',(eid,)).fetchone()
   if row:
    ev=json.loads(row[0]);evidence[eid]=ev
    return p
  original={k:p.get(k) for k in ('source_id','source_url','status','observed_at','valid_until')}
  ev=source({'source_id':'archive:'+b['record_id']+':'+str(p.get('source_id')),
    'url':p.get('source_url') or b.get('source_url') or 'urn:shorttrip:historical-catalog',
    'raw_text':canonical({'record_id':b['record_id'],'field':f,'value':b['data'].get(f),'original_provenance':original,'source_catalog_sha256':before}),
    'retrieved_at':b['retrieved_at'],'observed_at':p.get('observed_at'),'authority':'historical_catalog_reference',
    'licence_status':b.get('licence_status','unknown'),'capture_method':'provenance_preserving_local_catalog_copy'})
  return dict(source_id=ev['source_id'],source_url=ev['source_url'],observed_at=ev['observed_at'],status=p.get('status','unknown'),
    evidence_id=ev['evidence_id'],valid_until=p.get('valid_until'),upstream_provenance=original)
 def envelope(kind,city,name,data,ref_sources,refs,*,rid=None,base=None,scope=None,coord='unknown',tags=(),locator=None):
  rid=rid or 'p29:'+sha(canonical([kind,city,name,scope or {}]).encode())[:28]
  evs=[source(s) for s in ref_sources]
  primary=evs[0] if evs else None
  sid='p29-entity:'+sha(rid.encode())[:24]
  url=(primary or {}).get('source_url') or (base or {}).get('source_url') or 'urn:shorttrip:local-identity'
  d={f:data.get(f) for f in FIELDS[kind]};provenance={}
  new_id=None
  if 'id' in d and d['id'] is None:new_id=int(sha(rid.encode())[:12],16);d['id']=new_id
  for f in FIELDS[kind]:
   ref=refs.get(f)
   if ref and isinstance(ref.get('source_index'),int):
    i=ref['source_index'];ev=evs[i];quote=ref.get('quote')
    if not isinstance(quote,str) or not quote or quote not in ev['raw_text']:raise ValueError('Unsupported exact quote: '+name+':'+f)
    status=ref.get('status','source_value')
    if status not in ('unknown','source_value','estimated','derived','synthetic'):status='derived'
    provenance[f]=dict(source_id=ev['source_id'],source_url=ev['source_url'],observed_at=ev['observed_at'],status=status,evidence_id=ev['evidence_id'],valid_until=None,quote=quote)
    if known(d[f]):
     unit=field_unit(f,kind)
     if kind=='accommodation' and f=='price':unit=(scope or {}).get('price_unit') or (scope or {}).get('currency_unit') or None
     claims.append(dict(claim_id='p29-claim:'+sha((rid+':'+f+':'+ev['evidence_id']).encode())[:32],entity_id=rid,evidence_id=ev['evidence_id'],field=field_policy(f,kind),native_field=f,value=d[f],unit=unit,quote=quote,
      source_id=ev['source_id'],source_url=ev['source_url'],observed_at=ev['observed_at'],retrieved_at=ev['retrieved_at'],valid_until=None,
      context={'static_reference':True,'native_field':f,'scope':scope or {}},entity_verified=False,extraction_verified=True,licence_status=ev['licence_status']))
   elif base and known(base.get('data',{}).get(f)) and base['data'][f]==d[f]:provenance[f]=inherited(base,f)
   else:
    status='derived' if known(d[f]) else 'unknown'
    ev=source({'source_id':'local_proxy_keys','url':'urn:shorttrip:p29-local-proxy','raw_text':canonical({'record_id':rid,'field':f,'value':d[f],'basis':'deterministic local proxy or representation; not independently verified fact'}),
      'retrieved_at':at,'observed_at':None,'authority':'local_derivation','licence_status':'allowed','capture_method':'local_derivation'})
    provenance[f]=dict(source_id=ev['source_id'],source_url=ev['source_url'],observed_at=None,status=status,evidence_id=ev['evidence_id'],valid_until=None)
  normalized_tags=[dict(tag='kind',value=kind,basis='schema type',status='derived_recall_hint',policy_id='identity',source_time_ref='catalogued_at',valid_until=None)]
  for t in tags:
   tag=copy.deepcopy(t);basis=tag.get('basis');ev=None
   if isinstance(basis,dict) and isinstance(basis.get('source_index'),int):
    ev=evs[basis['source_index']];q=basis.get('quote')
    if not q or q not in ev['raw_text']:raise ValueError('Unsupported TAG quote: '+name+':'+tag['tag'])
    tag['basis']=q;tag['evidence_id']=ev['evidence_id'];tag['source_id']=ev['source_id'];tag['source_url']=ev['source_url']
   elif not isinstance(basis,str):tag['basis']=canonical(basis or {'note':'unverified_recall_hint'})
   tag.update(policy_id=tag.get('policy_id','theme'),source_time_ref='observed_at',valid_until=dateclock(tag.get('valid_until')))
   tag.setdefault('status','source_attribute_reference' if ev else 'derived_recall_hint')
   normalized_tags.append(tag)
  missing=[f for f in FIELDS[kind] if not known(d[f])]
  normalized_tags.append(dict(tag='native_fields_complete',value=not missing,basis='non-null native values only; not fact verification',status='derived_recall_hint',policy_id='identity',source_time_ref='catalogued_at',valid_until=None))
  r=dict(schema_version=VERSION,record_id=rid,language='zh',kind=kind,city=city,name=name,data=d,tags=normalized_tags,
    source_id=sid,source_url=url,source_locator=locator or {'provider_city_match':bool((base or {}).get('source_locator',{}).get('provider_city_match',False)),
      'city_assignment':'curated_city_with_provenance_pending_independent_identity','upstream_record_id':(base or {}).get('record_id')},
    source_published_at=(primary or {}).get('source_published_at'),source_updated_at=(primary or {}).get('source_updated_at'),observed_at=None,retrieved_at=at,catalogued_at=at,
    valid_from=None,valid_until=None,field_policies={f:field_policy(f,kind) for f in FIELDS[kind]},field_provenance=provenance,
    authority=(primary or {}).get('authority','historical_catalog_reference'),licence_status=(primary or {}).get('licence_status',(base or {}).get('licence_status','unknown')),
    coordinate_system=coord,coordinate_order={'poi':'latitude,longitude','metro_station':'longitude,latitude','train':'not_applicable','flight':'not_applicable'}.get(kind,'named_lat_lon_columns'),
    trust_status='reference_only',entity_verified=False,needs_live_verification=True,uncertainty_flags=['static_reference_not_live_confirmation'],synthetic=False,
    scope=scope or {},field_freshness_notes='Unknown source clocks stay null; retrieval does not renew old facts.')
  if new_id is not None:r['proxy_id_policy']='SHA256(record_id) first 48 bits, local surrogate, not provider certification'
  records.append(r);return r

 reviews=json.loads((WORK/'geocode_review.json').read_text(encoding='utf-8')) if (WORK/'geocode_review.json').exists() else {'reviews':[]}
 reviewmap={(x['city'],x['name']):x for x in reviews['reviews']}
 entity_rows=[]
 for bp in sorted((WORK/'workers').glob('*/bundle.json')):
  pack=json.loads(bp.read_text(encoding='utf-8'))
  for e in pack['entities']:
   e['city']=e.get('city') or pack.get('city')
   e['worker_file']=str(bp.relative_to(ROOT));entity_rows.append(e)
 for e in entity_rows:
  city,kind,name=e['city'],e['kind'],e['name'];base=bases.get(e.get('existing_record_id'))
  d=copy.deepcopy(e['data']);refs=copy.deepcopy(e.get('field_refs',{}));src=copy.deepcopy(e.get('sources',[]));scope=copy.deepcopy(e.get('scope',{}));coord=e.get('coordinate_system','unknown')
  # Never merge a new entity by fuzzy name or distance.
  rv=reviewmap.get((city,name))
  if rv and rv['status']=='accepted' and (d.get('lat') is None or d.get('lon') is None):
   cp=ROOT/rv['raw_file'];raw=cp.read_text(encoding='utf-8');obj=json.loads(raw)
   idx=len(src);src.append(dict(source_id='nominatim_fixed_selection',url=obj['url'],raw_text=raw,observed_at=None,source_published_at=None,source_updated_at=None,retrieved_at=obj['_retrieved_at'],authority='community_geocoder',licence_status='odbl',capture_method='fixed_selected_entity_geocoder_response'))
   lon,lat=rv['coordinates'];d.update(lat=lat,lon=lon);coord='WGS84'
   for f in ['lat','lon']:refs[f]=dict(source_index=idx,quote=rv['quote'],status='source_value')
   scope['coordinate_role']='representative feature/area centroid, not a verified route entrance';scope['geocoder_review']=rv
  if base and d.get('name') is None:d['name']=name
  if kind not in ('train','flight'):d['name']=name
  r=envelope(kind,city,name,d,src,refs,base=base,coord=coord,scope=scope,tags=e.get('tags',[]))
  r['source_locator']['worker_file']=e['worker_file'];r['research_notes']=e.get('notes',[])
  for k in ('start_city','end_city'):
   if e.get(k):r[k]=e[k]
  if kind not in ('train','flight'):
   pos=[d.get('lat'),d.get('lon')] if d.get('lat') is not None and d.get('lon') is not None else None
   pd={'name':name,'position':pos}
   pr=envelope('poi',city,name,pd,[],{},coord=coord,scope={'activity_record_id':r['record_id'],'coordinate_role':scope.get('coordinate_role','source representative point; not entrance proof')})
   pr['source_locator']['activity_record_id']=r['record_id']
   if pos is not None:
    # Two original coordinate references retained; representation is derived.
    pr['field_provenance']['position']['upstream_coordinate_provenance']={f:r['field_provenance'][f] for f in ('lat','lon')}

 # Public CC0 metro relationship snapshot. Network affiliation is NOT proof of
 # municipal boundaries, current opening, complete network coverage or routes.
 wpath=WORK/'capture/wikidata_metro.json';w=json.loads(wpath.read_text(encoding='utf-8'))
 receipt=json.loads((WORK/'capture/wikidata_metro_receipt.json').read_text(encoding='utf-8'))
 seen=set();metro_counts=collections.Counter();metro_stations=collections.defaultdict(set)
 for row in w['results']['bindings']:
  system=row['systemLabel']['value'];city=next((c for c in CITIES if c in system),None)
  if not city:semantic.append({'type':'unmapped_metro_system','row':row});continue
  station=row['station']['value'];line=row['line']['value'];coords=row['coord']['value']
  key=(station,line,coords)
  if key in seen:continue
  seen.add(key)
  match=re.fullmatch(r'Point\(([-\d.]+) ([-\d.]+)\)',coords)
  if not match:raise ValueError('Unsupported Wikidata coordinate '+coords)
  lon,lat=map(float,match.groups());source_name=row['stationLabel']['value'];linename=row['lineLabel']['value']
  if re.fullmatch(r'Q\d+',source_name) or re.fullmatch(r'Q\d+',linename):
   semantic.append({'type':'unlabelled_metro_relationship','station':station,'line':line});continue
  name=source_name.removesuffix('站')+'-地铁站';raw=canonical(row)
  src=dict(source_id='wikidata_metro_snapshot',url=station,raw_text=raw,source_published_at=None,source_updated_at=None,observed_at=None,retrieved_at=receipt['retrieved_at'],authority='community_structured_data',licence_status='cc0',capture_method='public_sparql_response_projection')
  data={'name':name,'position':str(lon)+','+str(lat),'line':linename}
  refs={f:dict(source_index=0,quote=raw,status='derived' if f=='name' else 'source_value') for f in data}
  r=envelope('metro_station',city,name,data,[src],refs,rid='p29-wd:'+sha(canonical(key).encode())[:28],coord='WGS84',
   scope={'station_qid':station,'line_qid':line,'system_label':system,'source_station_label':source_name,'administrative_city_verified':False,'operational_status':'unknown','coordinate_role':'station representative point'},
   locator={'provider_city_match':False,'city_assignment':'metro_network_scope_unverified_administration','network_membership_verified_from_source':True,'source_file':str(wpath.relative_to(ROOT))},
   tags=[dict(tag='metro_network',value=system,basis={'source_index':0,'quote':raw}),dict(tag='metro_line',value=linename,basis={'source_index':0,'quote':raw})])
  r['uncertainty_flags']+=['metro_operational_status_unknown','metro_administrative_city_unverified']
  metro_counts[city]+=1;metro_stations[city].add(station)

 # Validate every record and every evidence edge before any database is created.
 by_id={r['record_id']:r for r in records}
 if len(by_id)!=len(records):raise ValueError('Duplicate record identity')
 gates={r['record_id']:validate_record(r,now=at) for r in records}
 errors=[{'record_id':rid,'errors':g['errors']} for rid,g in gates.items() if not g['discovery_ok']]
 for ev in evidence.values():
  g=validate_evidence(ev)
  if not g['ok']:errors.append({'evidence_id':ev['evidence_id'],'errors':g['errors']})
 for c in claims:
  g=validate_claim(c,evidence,now=at,registry=registry)
  if not g['ok']:errors.append({'claim_id':c['claim_id'],'errors':g['errors']})
  if c['entity_id'] not in by_id:errors.append({'claim_entity_missing':c['claim_id']})
 if errors:
  dump(WORK/'build_errors.json',errors);raise ValueError('Validation failed; see build_errors.json')
 dest.mkdir(parents=True)
 store=ExpansionStore(dest/'catalog.sqlite3',create=True)
 store.load_evidence(list(evidence.values()),[],registry=registry,now=at)
 imported=store.load(records,now=at)
 store.load_evidence([],claims,registry=registry,now=at)
 fk=list(store.db.execute('pragma foreign_key_check'));integrity=store.db.execute('pragma integrity_check').fetchone()[0]
 store.close()
 jsongz(dest/'records.jsonl.gz',records);jsongz(dest/'evidence.jsonl.gz',evidence.values());jsongz(dest/'claims.jsonl.gz',claims)
 dump(dest/'source_registry.json',registry)
 candidates=[r for r in bases.values() if r['city'] in CITIES]
 jsongz(dest/'historical_candidates.jsonl.gz',candidates)
 rows=[];gaps=[];fieldstats=collections.defaultdict(collections.Counter)
 for city in CITIES:
  for kind in FIELDS:
   rr=[r for r in records if r['city']==city and r['kind']==kind]
   rows.append(dict(city=city,kind=kind,records=len(rr),native_all_keys=sum(set(FIELDS[kind]).issubset(r['data']) for r in rr),
     all_native_values_nonempty=sum(all(known(r['data'][f]) for f in FIELDS[kind]) for r in rr),
     critical_values_nonempty=sum(not gates[r['record_id']]['missing_planning_fields'] for r in rr),planning_ready=sum(gates[r['record_id']]['planning_ready'] for r in rr),
     metro_unique_stations=len(metro_stations[city]) if kind=='metro_station' else ''))
   for r in rr:
    missing=[f for f in FIELDS[kind] if not known(r['data'][f])]
    if missing:gaps.append(dict(city=city,kind=kind,name=r['name'],record_id=r['record_id'],missing_fields=missing,scope=r['scope']))
    for f in FIELDS[kind]:
     ctr=fieldstats[(city,kind,f)];ctr['records']+=1;ctr['nonempty']+=known(r['data'][f]);ctr['observation_clock_known']+=bool(dateclock(r['field_provenance'][f].get('observed_at')))
 with (dest/'city_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)
 with (dest/'field_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=['city','kind','field','records','nonempty','observation_clock_known']);wr.writeheader()
  for (city,kind,field),ct in fieldstats.items():wr.writerow({'city':city,'kind':kind,'field':field,**ct})
 dump(dest/'completion_gaps.json',gaps);dump(dest/'normalization_events.json',events);dump(dest/'semantic_review.json',semantic)
 # Native-shaped exports live outside the original sandbox. Null-bearing rows
 # remain in reference_database; complete references are a separate export.
 for directory,complete_only in [('reference_database',False),('complete_reference_database',True)]:
  dr=dest/directory
  for city in CITIES:
   slug=SLUGS[city]
   for kind,sub,fn in [('attraction','attractions','attractions.csv'),('restaurant','restaurants','restaurants_'+slug+'.csv'),('accommodation','accommodations','accommodations.csv')]:
    rr=[r for r in records if r['city']==city and r['kind']==kind and (not complete_only or all(known(v) for v in r['data'].values()))]
    fp=dr/sub/slug/fn;fp.parent.mkdir(parents=True,exist_ok=True)
    with fp.open('w',encoding='utf-8-sig',newline='') as f:
     wr=csv.DictWriter(f,fieldnames=FIELDS[kind]);wr.writeheader();wr.writerows(r['data'] for r in rr)
   for kind,sub,fn in [('poi','poi','poi.json'),('metro_station','subway_stations','subway_stations.json')]:
    rr=[r for r in records if r['city']==city and r['kind']==kind and (not complete_only or all(known(v) for v in r['data'].values()))]
    dump(dr/sub/slug/fn,[r['data'] for r in rr])
   for kind,fn in [('train','train.json'),('flight','airplane.json')]:
    rr=[r for r in records if r['city']==city and r['kind']==kind and (not complete_only or all(known(v) for v in r['data'].values()))]
    dump(dr/'intercity_transport'/slug/fn,[dict(**r['data'],start_city=r.get('start_city'),end_city=r.get('end_city')) for r in rr])
 validation={'checked_at':at,'records':len(records),'discovery_ok':sum(g['discovery_ok'] for g in gates.values()),'planning_ready':sum(g['planning_ready'] for g in gates.values()),
  'all_records_have_all_native_keys':all(set(FIELDS[r['kind']]).issubset(r['data']) for r in records),'evidence':len(evidence),'claims':len(claims),'tags':sum(len(r['tags']) for r in records),
  'all_evidence_claim_contracts_valid':not errors,'sqlite_integrity':integrity,'foreign_key_errors':fk,'historical_catalog_unchanged':sha(oldpath.read_bytes())==before,
  'historical_candidate_records_reused':len(candidates),'network_calls_by_builder':0,'full_five_city_fact_completion':False,'official_checker_or_route_injection_performed':False,
  'metro_relationships_by_city':dict(metro_counts),'metro_unique_stations_by_city':{c:len(v) for c,v in metro_stations.items()},'all_values_nonempty_records':sum(all(known(v) for v in r['data'].values()) for r in records)}
 dump(dest/'validation.json',validation)
 files={str(p.relative_to(dest)):sha(p.read_bytes()) for p in dest.rglob('*') if p.is_file()}
 manifest=dict(version=dest.name,built_at=at,cities=CITIES,source_catalog=str(oldpath.relative_to(ROOT)),source_catalog_sha256=before,validation=validation,files=files,
   readme_note='Reference snapshot only. complete_reference_database means nonempty scalar values, not current prices, source freshness, entity truth, complete city POIs, route availability or official benchmark acceptance.')
 dump(dest/'manifest.json',manifest)
 dump(WORK/'current_five_city_catalog.json',{'catalog':str((dest/'catalog.sqlite3').relative_to(ROOT)),'manifest':str((dest/'manifest.json').relative_to(ROOT)),'built_at':at,'full_completion':False})
 dump(WORK/'summary.json',{'version':dest.name,'validation':validation,'city_coverage':rows,'gaps_file':str((dest/'completion_gaps.json').relative_to(ROOT))})
 print(json.dumps(validation,ensure_ascii=True))

if __name__=='__main__':main()
