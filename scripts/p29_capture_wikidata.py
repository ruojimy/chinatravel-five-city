"""One small public Wikidata query, no retries or alternate services."""
import sys,json,hashlib,time
from pathlib import Path
from datetime import datetime,timezone
import requests
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/p29_five_city_completion/capture'
QUERY='''SELECT DISTINCT ?system ?systemLabel ?station ?stationLabel ?coord ?line ?lineLabel ?cityVerified ?adminLabel ?opened ?closed WHERE {
 VALUES ?sysname { "西安地铁"@zh "厦门轨道交通"@zh "厦门地铁"@zh "宁波轨道交通"@zh "长沙地铁"@zh "青岛地铁"@zh }
 ?system rdfs:label ?sysname .
 { ?line wdt:P361+ ?system . } UNION { ?system wdt:P527 ?line . }
 ?station wdt:P81 ?line; wdt:P625 ?coord .
 OPTIONAL { ?system wdt:P131 ?syscity . }
 BIND(EXISTS { ?station wdt:P131* ?syscity . FILTER(BOUND(?syscity)) } AS ?cityVerified)
 OPTIONAL { ?station wdt:P131 ?admin . }
 OPTIONAL { ?station wdt:P1619 ?opened . }
 OPTIONAL { ?station wdt:P576 ?closed . }
 SERVICE wikibase:label { bd:serviceParam wikibase:language "zh,en". }
} LIMIT 2500'''
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 fp=OUT/'wikidata_metro_scoped.json'
 if fp.exists():raise FileExistsError('Preserve captured response')
 receipt={'endpoint':'https://query.wikidata.org/sparql','query':QUERY,'requested_at':datetime.now(timezone.utc).isoformat(),'no_retry':True}
 try:
  response=requests.get(receipt['endpoint'],params={'query':QUERY,'format':'json'},headers={'User-Agent':'ShortTripResearch/1.0 (small public transport dataset snapshot)','Accept':'application/sparql-results+json'},timeout=55)
  receipt.update(http_status=response.status_code,retrieved_at=datetime.now(timezone.utc).isoformat(),sha256=hashlib.sha256(response.content).hexdigest())
  (OUT/'wikidata_metro_scoped_raw.txt').write_bytes(response.content)
  if response.status_code==200:
   obj=response.json();receipt['status']='captured';receipt['rows']=len(obj.get('results',{}).get('bindings',[]));fp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
  else:receipt['status']='paused_http_failure'
 except Exception as e:receipt.update(status='paused_error',error_type=type(e).__name__)
 (OUT/'wikidata_metro_scoped_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(receipt,ensure_ascii=True))
if __name__=='__main__':main()
