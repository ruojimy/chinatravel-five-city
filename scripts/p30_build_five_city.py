"""Build an immutable, provenance-labelled five-city reference dataset offline.

Missing values remain null. Native-field completeness, schema validity, and
current planning eligibility are measured separately. No official data/checker
files or historical catalogue pointers are changed by this builder.
"""
from __future__ import annotations
import argparse,collections,copy,csv,gzip,hashlib,json,math,re,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.expansion_contract import FIELDS,VERSION,validate_record,validate_evidence,validate_claim
from shorttrip.expansion_store import ExpansionStore
from shorttrip.freshness import field_policy,POLICIES,parse_time,canonical
P29=ROOT/'results/p29_five_city_completion'
WORK=ROOT/'results/p30_five_city_fill'
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
 if field=='Duration':return 'hours'
 if field.startswith('recommend'):return 'hours'
 if field=='numbed':return 'beds/room'
 return None

def _gcj_offset(lat,lon):
 a=6378245.0;ee=0.00669342162296594323;x=lon-105.0;y=lat-35.0
 dlat=-100.0+2.0*x+3.0*y+0.2*y*y+0.1*x*y+0.2*math.sqrt(abs(x))+(20.0*math.sin(6.0*x*math.pi)+20.0*math.sin(2.0*x*math.pi))*2.0/3.0+(20.0*math.sin(y*math.pi)+40.0*math.sin(y/3.0*math.pi))*2.0/3.0+(160.0*math.sin(y/12.0*math.pi)+320*math.sin(y*math.pi/30.0))*2.0/3.0
 dlon=300.0+x+2.0*y+0.1*x*x+0.1*x*y+0.1*math.sqrt(abs(x))+(20.0*math.sin(6.0*x*math.pi)+20.0*math.sin(2.0*x*math.pi))*2.0/3.0+(20.0*math.sin(x*math.pi)+40.0*math.sin(x/3.0*math.pi))*2.0/3.0+(150.0*math.sin(x/12.0*math.pi)+300.0*math.sin(x/30.0*math.pi))*2.0/3.0
 r=lat/180.0*math.pi;m=1-ee*math.sin(r)**2;s=math.sqrt(m)
 return dlat*180.0/((a*(1-ee))/(m*s)*math.pi),dlon*180.0/(a/s*math.cos(r)*math.pi)
def gcj02_to_wgs84(lat,lon):
 # Iterate the forward offset until WGS84+offset reproduces the GCJ02 input.
 wlat,wlon=lat,lon
 for _ in range(10):
  dlat,dlon=_gcj_offset(wlat,wlon);wlat,wlon=lat-dlat,lon-dlon
 return round(wlat,6),round(wlon,6)

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
  if (not isinstance(raw,str) or not raw.strip()) and s.get('raw_file') and s.get('_base'):
   fp=Path(s['_base'])/s['raw_file']
   if fp.is_file():raw=s['raw_text']=fp.read_text(encoding='utf-8')
  if (not isinstance(raw,str) or not raw.strip()) and s.get('excerpt'):raw=s['raw_text']=s['excerpt']
  if not isinstance(raw,str) or not raw.strip():raise ValueError('Evidence requires captured source text')
  url=s.get('url') or s.get('source_url')
  if not url:raise ValueError('Source URL required')
  supplied=s.get('source_id') or urlparse(url).hostname or 'local-archive'
  sid='p30:'+sha((supplied+'|'+url).encode())[:24]
  t={k:dateclock(s.get(k)) for k in ['source_published_at','source_updated_at','observed_at']}
  retrieved=dateclock(s.get('retrieved_at'))
  if not retrieved:raise ValueError('Retrieval clock required: '+url)
  eid='p30-evidence:'+sha(canonical([sid,raw,t,retrieved]).encode())
  lic=s.get('licence_status') or 'unknown'
  if isinstance(lic,str) and lic.lower().startswith('odbl'):lic='odbl'
  e=dict(evidence_id=eid,source_id=sid,source_url=url,raw_text=raw,raw_sha256=sha(raw.encode()),retrieved_at=retrieved,
         authority=s.get('authority') or 'historical_reference',licence_status=lic,**t)
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
  rid=rid or 'p30:'+sha(canonical([kind,city,name,scope or {}]).encode())[:28]
  evs=[source(s) for s in ref_sources]
  primary=evs[0] if evs else None
  sid='p30-entity:'+sha(rid.encode())[:24]
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
     claims.append(dict(claim_id='p30-claim:'+sha((rid+':'+f+':'+ev['evidence_id']).encode())[:32],entity_id=rid,evidence_id=ev['evidence_id'],field=field_policy(f,kind),native_field=f,value=d[f],unit=unit,quote=quote,
      source_id=ev['source_id'],source_url=ev['source_url'],observed_at=ev['observed_at'],retrieved_at=ev['retrieved_at'],valid_until=None,
      context={'static_reference':True,'native_field':f,'scope':scope or {}},entity_verified=False,extraction_verified=True,licence_status=ev['licence_status']))
   elif base and known(base.get('data',{}).get(f)) and base['data'][f]==d[f]:provenance[f]=inherited(base,f)
   else:
    status='derived' if known(d[f]) else 'unknown'
    ev=source({'source_id':'local_proxy_keys','url':'urn:shorttrip:p30-local-proxy','raw_text':canonical({'record_id':rid,'field':f,'value':d[f],'basis':'deterministic local proxy or representation; not independently verified fact'}),
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

 reviews=json.loads((P29/'geocode_review.json').read_text(encoding='utf-8')) if (P29/'geocode_review.json').exists() else {'reviews':[]}
 reviewmap={(x['city'],x['name']):x for x in reviews['reviews']}
 entity_rows={};rejected=[];shadow={}
 # P29 bundles first, then P30 round 1, then round-N (*_rN) workers override the same key.
 for bp in sorted((P29/'workers').glob('*/bundle.json'))+sorted((WORK/'workers').glob('*/bundle.json'),key=lambda q:(int(re.search(r'_r(\d+)$',q.parent.name).group(1)) if re.search(r'_r(\d+)$',q.parent.name) else 1,q.parent.name)):
  pack=json.loads(bp.read_text(encoding='utf-8'))
  for e in pack['entities']:
   e['city']=e.get('city') or pack.get('city')
   for s in e.get('sources',[]):s['_base']=str(bp.parent)
   e['worker_file']=str(bp.relative_to(ROOT));tid=e.get('data',{}).get('TrainID') or e.get('data',{}).get('FlightID')
   # Transport is keyed by its ID and destination city, so a later round that renames
   # or refines a leg replaces it, while one ID serving two destinations stays two legs.
   k=(e['city'],e['kind'],str(tid),e.get('end_city') or e.get('data',{}).get('To') or '') if e['kind'] in ('train','flight') and tid else (e['city'],e['kind'],e['name'],'')
   if k in entity_rows:shadow[k]=entity_rows[k]
   entity_rows[k]=e
 # Root review: sources reached by switching method/host after that site showed a
 # verification page or 4xx block break the contract. (worker, host suffix, fetched at/after)
 EXCLUDED=[('xian','trip.com','2026-10-25T00:00','WebFetch after curl hit trip.com verification page'),
  ('xiamen','m.ctrip.com','2026-10-25T11:48:31','mobile-site fetch right after you.ctrip.com verification redirect'),
  ('xiamen','you.ctrip.com','2026-10-25T11:48:31','fetched after you.ctrip.com verification redirect'),
  ('xiamen','gs.ctrip.com','2026-10-25T11:48:31','H5 fetch after you.ctrip.com verification redirect'),
  ('changsha','gs.ctrip.com','2026-10-25T11:48:49','H5 fetch after you.ctrip.com verification redirect'),
  ('changsha','you.ctrip.com','2026-10-25T11:48:49','fetched after you.ctrip.com verification redirect'),
  ('changsha','nz.trip.com','2026-10-25T11:52:28','subdomain switch after www.trip.com HTTP 432'),
  ('flights_r2','chahangxian.com','2026-10-26T02:06:42','loop kept requesting the host after its first TLS timeout at 02:06:41')]
 def excluded(e,s):
  if 'p30_five_city_fill' not in e['worker_file']:return None
  h=urlparse(s.get('url') or '').hostname or '';t=s.get('retrieved_at') or ''
  for w,suffix,since,why in EXCLUDED:
   if Path(e['worker_file']).parent.name==w and (h==suffix or h.endswith('.'+suffix)) and t>=since:return why
  return None
 for k,e in list(entity_rows.items()):
  srcs=e.get('sources',[]);drop={i:excluded(e,s) for i,s in enumerate(srcs)};drop={i:w for i,w in drop.items() if w}
  if not drop:continue
  keep=[i for i in range(len(srcs)) if i not in drop];remap={old:new for new,old in enumerate(keep)}
  nulled=[]
  for f,ref in list((e.get('field_refs') or {}).items()):
   i=ref.get('source_index') if isinstance(ref,dict) else None
   if i in drop:
    del e['field_refs'][f]
    if f in e['data']:e['data'][f]=None;nulled.append(f)
   elif i in remap:ref['source_index']=remap[i]
  tags=[]
  for t in e.get('tags',[]):
   i=(t.get('basis') or {}).get('source_index') if isinstance(t.get('basis'),dict) else None
   if i in drop:continue
   if i in remap:t['basis']['source_index']=remap[i]
   tags.append(t)
  e['tags']=tags;e['sources']=[srcs[i] for i in keep]
  if e['data'].get('lat') is None and e['data'].get('lon') is None and e['kind'] in ('attraction','restaurant','accommodation'):e['coordinate_system']='unknown'
  info={'worker_file':e['worker_file'],'city':e['city'],'kind':e['kind'],'name':e['name'],'dropped_sources':[srcs[i].get('url') for i in drop],'reason':sorted(set(drop.values())),'nulled_fields':nulled}
  if not keep:
   info['error']='all_sources_excluded';rejected.append(info);del entity_rows[k]
   if k in shadow:entity_rows[k]=shadow[k];info['restored_previous_version']=shadow[k]['worker_file']
  else:events.append({'type':'excluded_sources_stripped',**info})
 # A P30 entity that names its P29/historical base replaces it even if renamed.
 p30_bases={e.get('existing_record_id') for e in entity_rows.values() if 'p30_five_city_fill' in e['worker_file'] and e.get('existing_record_id')}
 superseded=[k for k,e in entity_rows.items() if 'p29_five_city_completion' in e['worker_file'] and e.get('existing_record_id') in p30_bases]
 for k in superseded:events.append({'type':'p29_entity_superseded_by_p30','key':list(k)});del entity_rows[k]
 entity_rows=list(entity_rows.values())
 for e in entity_rows:
  city,kind,name=e['city'],e['kind'],e['name'];base=bases.get(e.get('existing_record_id'))
  d=copy.deepcopy(e['data']);refs=copy.deepcopy(e.get('field_refs',{}));src=copy.deepcopy(e.get('sources',[]));scope=copy.deepcopy(e.get('scope',{}));coord=e.get('coordinate_system') or 'unknown'
  if coord=='GCJ-02':coord='GCJ02'
  if coord=='GCJ02' and kind in ('attraction','restaurant','accommodation') and known(d.get('lat')) and known(d.get('lon')):
   lat,lon=gcj02_to_wgs84(d['lat'],d['lon'])
   scope=dict(scope) if isinstance(scope,dict) else {'original_scope':scope}
   scope['coordinate_conversion']={'from':'GCJ02','original_lat':d['lat'],'original_lon':d['lon'],'method':'iterative inverse of the public GCJ-02 offset formula, ~1e-6 deg'}
   events.append({'type':'gcj02_converted_to_wgs84','city':city,'kind':kind,'name':name,'from':[d['lat'],d['lon']],'to':[lat,lon]})
   d['lat'],d['lon']=lat,lon;coord='WGS84'
   for f in ('lat','lon'):
    if isinstance(refs.get(f),dict):refs[f]=dict(refs[f],status='derived')
  for f in ('opentime','endtime','BeginTime','EndTime'):
   # ChinaTravel writes end-of-day as 24:00; the HH:MM gate stops at 23:59.
   if d.get(f)=='24:00':
    d[f]='23:59';scope=dict(scope) if isinstance(scope,dict) else {'original_scope':scope};scope[f+'_original_text']='24:00'
    events.append({'type':'end_of_day_24_00_as_23_59','city':city,'kind':kind,'name':name,'field':f})
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
  rid=None
  if kind in ('train','flight'):
   # The checker keys transport by its ID; keep From/To in the identity so one ID on two legs stays distinct.
   idf={'train':'TrainID','flight':'FlightID'}[kind]
   if known(d.get(idf)) and d[idf]!=name:
    events.append({'type':'transport_name_set_to_id','city':city,'original_name':name,'id':d[idf]})
    rid='p30:'+sha(canonical([kind,city,d[idf],d.get('From'),d.get('To'),e.get('start_city'),e.get('end_city')]).encode())[:28]
    name=d[idf]
  try:r=envelope(kind,city,name,d,src,refs,rid=rid,base=base,coord=coord,scope=scope,tags=e.get('tags',[]))
  except (ValueError,IndexError,KeyError,TypeError) as x:rejected.append({'worker_file':e['worker_file'],'city':city,'kind':kind,'name':name,'error':repr(x)});continue
  r['source_locator']['worker_file']=e['worker_file'];r['research_notes']=e.get('notes',[])
  # WebFetch returns a model's rendering of the page; quotes match it, not the page bytes.
  if any('model' in str(s.get('capture_method') or '') for s in src):r['uncertainty_flags'].append('model_extracted_source_text')
  for k in ('start_city','end_city'):
   if e.get(k):r[k]=e[k]
  if kind in ('attraction','restaurant','accommodation'):
   pos=[d.get('lat'),d.get('lon')] if d.get('lat') is not None and d.get('lon') is not None else None
   pd={'name':name,'position':pos}
   pr=envelope('poi',city,name,pd,[],{},coord=coord,scope={'activity_record_id':r['record_id'],'coordinate_role':scope.get('coordinate_role','source representative point; not entrance proof')})
   pr['source_locator']['activity_record_id']=r['record_id']
   if pos is not None:
    # Two original coordinate references retained; representation is derived.
    pr['field_provenance']['position']['upstream_coordinate_provenance']={f:r['field_provenance'][f] for f in ('lat','lon')}

 # Public CC0 metro relationship snapshot. Network affiliation is NOT proof of
 # municipal boundaries, current opening, complete network coverage or routes.
 wpath=P29/'capture/wikidata_metro.json';w=json.loads(wpath.read_text(encoding='utf-8'))
 receipt=json.loads((P29/'capture/wikidata_metro_receipt.json').read_text(encoding='utf-8'))
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
 dump(WORK/'rejected_entities.json',rejected)
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
 blockers=collections.defaultdict(collections.Counter)
 for r in records:
  for b in set(x.split(':')[0] for x in gates[r['record_id']]['planning_blockers']):blockers[r['kind']][b]+=1
 dump(dest/'planning_blockers.json',{k:dict(v.most_common()) for k,v in blockers.items()})
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
  'metro_relationships_by_city':dict(metro_counts),'metro_unique_stations_by_city':{c:len(v) for c,v in metro_stations.items()},'rejected_entities':len(rejected),'all_values_nonempty_records':sum(all(known(v) for v in r['data'].values()) for r in records)}
 dump(dest/'validation.json',validation)
 files={str(p.relative_to(dest)):sha(p.read_bytes()) for p in dest.rglob('*') if p.is_file()}
 manifest=dict(version=dest.name,built_at=at,cities=CITIES,source_catalog=str(oldpath.relative_to(ROOT)),source_catalog_sha256=before,validation=validation,files=files,
   readme_note='Reference snapshot only. complete_reference_database means nonempty scalar values, not current prices, source freshness, entity truth, complete city POIs, route availability or official benchmark acceptance.')
 dump(dest/'manifest.json',manifest)
 dump(WORK/'current_five_city_catalog.json',{'catalog':str((dest/'catalog.sqlite3').relative_to(ROOT)),'manifest':str((dest/'manifest.json').relative_to(ROOT)),'built_at':at,'full_completion':False})
 dump(WORK/'summary.json',{'version':dest.name,'validation':validation,'city_coverage':rows,'gaps_file':str((dest/'completion_gaps.json').relative_to(ROOT))})
 print(json.dumps(validation,ensure_ascii=True))

if __name__=='__main__':main()
