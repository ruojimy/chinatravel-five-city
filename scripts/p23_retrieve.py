"""Public-only supplemental retrieval: fuzzy names and semantic field coverage."""
import difflib,hashlib,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p23_scaled_llm'
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'ChinaTravel')]
from shorttrip.env import get_env

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
TYPE_CUES={'大学校园':['大学','校园'],'人文景观':['人文','历史','古迹','文化'],'自然风光':['风景','自然','山水','湖光'],'创意菜':['创意','创新'],'自助餐':['自助'],'火锅':['火锅'],'粤菜':['粤菜','广式'],'经济型':['经济','便宜','实惠'],'豪华型':['高档','豪华','五星'],'舒适型':['舒适'],'客栈':['民宿','客栈'],'湖景酒店':['湖景','看湖']}
def norm(s):return re.sub(r'[\W_]','',str(s))

def main():
 env=get_env('zh');audit=[]
 for split in ('easy','medium','human'):
  queries=read(OUT/'public'/split/'queries.json');packets=[]
  for q in queries:
   nl=q['nature_language'];n=norm(nl);city=q['target_city'];extra={};detail=[]
   for kind,table,fields in [('attractions',env.attraction_table(city),('name','type','price','recommendmintime','opentime','endtime')),('restaurants',env.restaurant_table(city),('name','cuisine','price','opentime','endtime')),('hotels',env.accommodation_table(city),('name','featurehoteltype','price','numbed'))]:
    rows=json.loads(table.to_json(orient='records',force_ascii=False));existing={x['name'] for x in q['retrieved_candidates'][kind]};scored=[]
    for row in rows:
     if row['name'] in existing:continue
     name=norm(row['name']);m=difflib.SequenceMatcher(None,name,n,autojunk=False).find_longest_match(0,len(name),0,len(n));match=name[m.a:m.a+m.size]
     score=m.size*2 if m.size>=3 and match not in ('一个人','两个人','三个人','酒店','博物馆','经济型','舒适型','豪华型') else 0
     why=[]
     if score:why.append('partial_name_match:'+match)
     for value in [str(row.get(k,'')) for k in ('type','cuisine','featurehoteltype')]:
      for label,cues in TYPE_CUES.items():
       if label in value and any(c in nl for c in cues):score+=7;why.append('semantic_field:'+label)
     if score>=6:scored.append((score,row,why))
    scored.sort(key=lambda x:(-x[0],float(x[1].get('price') or 0),x[1]['name']))
    kept=scored[:8]
    extra[kind]=[{**{k:r.get(k) for k in fields},'retrieval_basis':why} for _,r,why in kept]
    detail.append({'kind':kind,'scanned':len(rows),'matching_additional_candidates':len(scored),'added':len(kept)})
   packets.append({'uid':q['uid'],'nature_language':nl,'additional_candidates':extra,'scope':'Official frozen sandbox rows. Fuzzy retrieval is a clue, not a statement that similarly named venues are identical. Unknown room subcategories remain unknown.'})
   audit.append({'split':split,'uid':q['uid'],'retrieval':detail})
  write(OUT/'public_v2'/split/'supplement.json',packets)
  source=OUT/'intents'/(split+'.json');assert source.exists();write(OUT/'private'/('first_intent_hash_'+split+'.json'),{'file':str(source.relative_to(ROOT)),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'count':len(read(source))})
 write(OUT/'retrieval_audit.json',{'cases':audit,'query_count':150,'new_network_calls':0,'algorithm':'public natural-language longest partial name match + field-synonym expansion, preserve original candidates, at most 8 additions per kind','no_hidden_labels_used':True})
 print(json.dumps({'queries':150,'added_candidates':sum(x['added'] for c in audit for x in c['retrieval'])}))

if __name__=='__main__':main()
