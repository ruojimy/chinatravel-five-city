"""Build reviewed public excerpts into scoped assertions, never current facts."""
import hashlib,json,sqlite3
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p17_continuous/restaurants'
SPECS=[
 ['haijiao','haijiaoxuan_ctrip.txt','https://gs.ctrip.com/html5/you/foods/fooddetail/61/132111.html','Ctrip','ctrip_food','overture:9b7aa56d-0549-4b07-a4c3-4b3fb1a96a59',
  'Same city/name, exact raw address 榆海路12号1层 and linked Mandarin Oriental restaurant. Independent coordinates not verified.',
  [['average_price',754,'CNY/person','人均¥754 西餐','Displayed average, not bill; tax/inclusions and update time unknown.'],['cuisine','西餐',None,'人均¥754 西餐','Explicit catalogue cuisine label.'],['opening_rules','18:00-22:00','local_time','营业中 18:00-22:00','Displayed interval, date exceptions and future applicability unknown.']]],
 ['longquan','longquan_ctrip.txt','https://you.ctrip.com/food/sanya61/5612595-dianping119844372.html','Ctrip','ctrip_food','overture:e5a7b920-3101-404d-a1d9-24473c6fb8de',
  'Same city/name, exact raw address 解放四路143号, exact phone0898-88661842; operator page supports phone but uses road alias解放西路143号.',
  [['average_price',109,'CNY/person','人 均：¥109(来自用户反馈)','User-feedback aggregate, not guaranteed bill. Review dates do not update aggregate clock.'],['cuisine','海南菜',None,'海南菜','Explicit catalogue cuisine.']]],
 ['guiyuan','guiyuan_feinfood.txt','https://www.feinfood.com/restaurant/ff8080814b76a96d014bbf588fe30470.xhtml','Feinfood','feinfood','overture:04ab4918-d3f0-44ca-9554-1d96160a82e0',
  'Same city/exact name/exact raw address成都道103号. Independent Hongchumao instead says成都道62号 and96/person; relocation/stale listing unresolved.',
  [['average_price',50,'CNY/person','人均: RMB 50','Address103 reference. Conflicts with address62/96 listing; no current budget projection.'],['cuisine','天津菜',None,'地道的天津菜馆','Explicit prose, branch/current status unresolved.'],['opening_rules','工作日11:00-14:00/17:00-21:00','local_time','营业时间(工作日)  | 11:00-14:00/17:00-21:00','Weekdays only, split intervals, weekend unknown; address103 stale/relocation conflict retained.']]],
 ['zecheng','zecheng_ctrip.txt','https://you.ctrip.com/food/huhehaote156/16606428.html','Ctrip','ctrip_food','overture:27152875-8297-41df-9b0b-ce56c2787ed0',
  'Same city, exact complete unique branch name泽成冰煮羊(非·遗大盛魁店); no independent identity certificate.',
  [['average_price',96,'CNY/person','人 均：¥96(来自用户反馈)','User-feedback aggregate; source time and bill contents unknown.'],['cuisine','火锅',None,'火锅','Explicit food type, not nationality or halal certificate.']]],
 ['dintaifung_closed','dintaifung_closed.txt','https://finance.sina.cn/2025-05-28/detail-ineyauth8080309.d.html','界面新闻官方账号经新浪转载','jiemian_news_republished','overture:3237b441-e1bb-44e4-8f9d-44433cd78438',
  'Same city/named Ningbo IFC国金中心 branch. Article quotes operator WeChat announcement, original not independently opened.',
  [['opening_rules','2025-05-28起停止营业','reported_closure','鼎泰丰宁波国金中心将于5月28日起停止营业','Historical reported closure; no fabricated current interval. Reopening not independently ruled out.']]],
]
def main():
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());db=sqlite3.connect(ROOT/pointer['catalog']);sources=[];assertions=[]
 for slug,file,url,publisher,group,rid,binding,fields in SPECS:
  r=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(rid,)).fetchone()[0]);raw=(OUT/file).read_bytes();text=raw.decode('utf-8');digest=hashlib.sha256(raw).hexdigest();sid='p17_web_'+slug
  published='2025-05-28T11:25:00+08:00' if slug=='dintaifung_closed' else None
  retrieved='2026-10-22T16:08:07.331+00:00' if slug not in ('zecheng','dintaifung_closed') else '2026-10-22T16:09:46+00:00'
  sources.append({'source_id':sid,'source_url':url,'publisher':publisher,'independent_source_group':group,'authority':'publisher_report_operator_original_unopened' if published else 'independent_catalogue_not_operator','representation':'web_tool_text_excerpt','content_file':file,'content_sha256':digest,'retrieved_at':retrieved,'retrieval_clock_basis':'local bounded excerpt capture; exact fetch clock not separately retained; never a fact update','source_published_at':published,'source_updated_at':None,'observed_at':None,'valid_from':None,'valid_until':None,'licence_status':'public_webpage_reuse_unverified_bounded_research_excerpt'})
  for field,value,unit,quote,scope in fields:
   if quote not in text:raise ValueError('Uncaptured quote '+slug+': '+quote)
   assertions.append({'assertion_id':sid+'_'+field,'entity_id':rid,'entity_name':r['name'],'city':r['city'],'field':field,'value':value,'unit':unit,'source_id':sid,'source_url':url,'evidence_file':file,'evidence_sha256':digest,'retrieved_at':retrieved,'source_published_at':published,'source_updated_at':None,'observed_at':None,'valid_from':None,'valid_until':None,'scope':scope,'quote':quote,'status':'conflicting_reference' if slug=='guiyuan' else 'historical_reported_closure' if published else 'candidate_reference','identity_match_basis':binding,'entity_verified':False,'planning_ready':False,'native_projection_permitted':False,'ttl_seconds':15552000 if field=='cuisine' else 86400,'freshness_status':'historical_reported_event' if published else 'unknown_fact_clock','applicability':{'start_date':'2025-05-28','status':'reported_closed','operator_original_unopened':True} if published else None,'evidence_locator':{'method':'exact_substring','quote':quote},'notes':['Source reference does not certify reality or current planning readiness.'],'tags':[{'tag':field,'value':value,'scope':scope,'source_id':sid,'evidence_sha256':digest,'status':'source_attribute_unverified','observed_at':None,'valid_until':None}]})
 package={'schema_version':'p16-field-assertions-v1','created_at':datetime.now(timezone.utc).isoformat(),'catalogue_basis':pointer,'sources':sources,'assertions':assertions,'formal_database_modified':False}
 (OUT/'web_batch_01_assertions.json').write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf-8')
 failures=[{'entity_id':'overture:d82cbeeb-7493-463a-a3fe-0b1e9704a6be','entity_name':'林姐香味海鲜','source_url':'https://gs.ctrip.com/html5/you/foods/fooddetail/61/132042.html','result':'wrong_branch_rejected','reason':'Target龙溪路6号亚龙湾壹号小镇, source新民街139号第一市场. Never attach price120/hours.','evidence_file':'linjie_wrong_branch.txt'}, {'entity_id':'overture:04ab4918-d3f0-44ca-9554-1d96160a82e0','result':'conflict_retained_no_projection','evidence_file':'guiyuan_hongchumao_conflict.txt','reason':'96/person成都道62号 vs50/address103. No relocation inferred.'}, {'source_url':'https://gs.ctrip.com/html5/you/foods/fooddetail/61/132325.html','result':'web_tool_inaccessible_url','provider_restriction_proven':False,'automatic_retry':False}, {'source_url':'https://www.mcdonalds.com.cn/about','result':'web_tool_inaccessible_url','provider_restriction_proven':False,'automatic_retry':False}]
 (OUT/'web_review_failures.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'entities':len(SPECS),'sources':len(sources),'assertions':len(assertions),'failures_recorded':len(failures)}))
if __name__=='__main__':main()
