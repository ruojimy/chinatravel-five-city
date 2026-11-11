"""Preserve explicit non-geographic food/service categories without dietary guarantees."""
import gzip,hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants/food_category_001'
sys.path.insert(0,str(ROOT/'src'));from shorttrip.freshness import utcnow
LABELS={'pizza_restaurant':'披萨','asian_restaurant':'亚洲餐饮（大类）','steakhouse':'牛排馆','barbecue_restaurant':'烧烤',
 'seafood_restaurant':'海鲜','breakfast_and_brunch_restaurant':'早餐与早午餐','chicken_restaurant':'鸡肉料理',
 'burger_restaurant':'汉堡','ramen_restaurant':'拉面','cafeteria':'食堂/自助取餐','dumpling_restaurant':'饺子',
 'bar_and_grill_restaurant':'酒吧与烧烤','sushi_restaurant':'寿司','dim_sum_restaurant':'点心','soup_restaurant':'汤品',
 'salad_bar':'沙拉','buffet_restaurant':'自助餐','pancake_house':'煎饼','pan_asian_restaurant':'泛亚洲餐饮',
 'asian_fusion_restaurant':'亚洲融合菜','texmex_restaurant':'德州墨西哥风味','hot_dog_restaurant':'热狗',
 'international_fusion_restaurant':'国际融合菜','soul_food':'美国南方传统食物','live_and_raw_food_restaurant':'生食类餐饮'}
DIET={'halal_restaurant':'来源类别标称清真（未核实认证）','vegetarian_restaurant':'来源类别标称素食（未核实菜单）','kosher_restaurant':'来源类别标称犹太洁食（未核实认证）'}
def main():
 OUT.mkdir(exist_ok=True);packet=OUT/'field_assertions.json'
 if packet.exists():raise FileExistsError('Immutable tag batch')
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text(encoding='utf-8'));db=sqlite3.connect(ROOT/pointer['catalog']);records={}
 for payload, in db.execute("SELECT payload FROM records WHERE kind='restaurant'"):
  r=json.loads(payload)
  if r['record_id'].startswith('overture:'):records[r['record_id']]={k:r.get(k) for k in ('record_id','name','source_url','retrieved_at','source_locator','licence_status')}
 db.close();sources=[];assertions=[];diet=0
 for file in sorted((ROOT/'data/expansion_v1_20261022/raw').glob('*.jsonl.gz')):
  with gzip.open(file,'rb') as stream:
   for ordinal,line in enumerate(stream,1):
    raw=line.rstrip(b'\r\n');row=json.loads(raw);rid='overture:'+row['id'];r=records.get(rid)
    if not r:continue
    code=(row.get('taxonomy') or {}).get('primary')
    if code not in LABELS and code not in DIET:continue
    loc=r['source_locator'];digest=hashlib.sha256(raw).hexdigest()
    if Path(loc['raw_file'])!=file.relative_to(ROOT):continue
    if loc['raw_line']!=ordinal or loc['raw_sha256']!=digest or row['names']['primary']!=r['name']:raise ValueError('Original row mismatch')
    out=OUT/(row['id']+'.json');out.write_bytes(raw);sid='p17-food-category:'+row['id'];quote=json.dumps({'primary':code},separators=(',',':'))[1:-1]
    assert quote in raw.decode('utf-8');is_diet=code in DIET;diet+=is_diet
    sources.append({'source_id':sid,'source_url':r['source_url'],'retrieved_at':r['retrieved_at'],'source_published_at':None,'source_updated_at':None,'observed_at':None,
     'authority':'structured_provider','licence_status':r['licence_status'],'content_file':out.name,'content_sha256':digest,
     'representation':'saved_original_json_row','source_locator':{'raw_file':loc['raw_file'],'raw_line':ordinal,'raw_sha256':digest,'gers_id':row['id'],'source_category':code}})
    assertions.append({'entity_id':rid,'field':'dietary_category_unverified' if is_diet else 'food_category','value':DIET[code] if is_diet else LABELS[code],
     'unit':None,'quote':quote,'scope':'Original provider category only; useful for soft candidate pruning. Never a current menu, allergy, ingredient or religious-certification guarantee.',
     'source_id':sid,'status':'derived_reference','identity_match_basis':'Same GERS ID, original name and immutable source row/hash; no independent reality check.',
     'native_provenance_status':'derived','dietary_not_verified':True,'allergy_not_verified':True,'no_geographic_cuisine_projection':True,'native_projection_permitted':False})
 packet.write_text(json.dumps({'created_at':utcnow(),'sources':sources,'assertions':assertions,'network_requests':0,'source_clocks_refreshed':0,'native_fields_filled':0},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'food_or_service_categories':len(assertions)-diet,'unverified_dietary_source_categories':diet,'native_cuisine_fields_filled':0}))
if __name__=='__main__':main()
