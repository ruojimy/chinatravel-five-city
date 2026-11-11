"""Materialize labelled easy/medium/human-style query schemas; no network."""
import copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_task_schema import task_schema,validate_cohort

def constraint(cid,op,args,strength='hard'):
 return {'id':cid,'strength':strength,'scope':{'trip':'whole'},
  'expression':{'op':op,'args':args},'compiler_status':'unmapped'}

def main():
 common={'purpose':'schema_example','start_city':'北京','target_city':'西安','days':3,'people_number':2,
  'start_date':'2027-03-15','required_kinds':['attraction','restaurant','accommodation','train'],
  'mode':'collection_static_reference','evidence_policy_id':'static-reference-policy-to-be-reviewed',
  'generation':{'seed':20261029,'budget_sampling':'illustrative fixed request; never inferred from candidate costs','feasibility_claim':'not_checked'},
  'candidate_selection':{'policy':'cover declared business chains including incomplete candidates','required_entity_ids':[]},'split':'example'}
 budget=constraint('budget','total_cost_at_most',{'CNY':3000,'people':2,'includes':['intercity','local_transport','tickets','meals','rooms']})
 easy={**copy.deepcopy(common),'uid':'SCHEMA-E1','level':'easy','task_origin':'researcher_generated',
  'nature_language':'两个人从北京到西安玩三天，2027年3月15日出发，交通、住宿、门票和餐饮总预算3000元。',
  'additional_constraints':[copy.deepcopy(budget)]}
 medium={**copy.deepcopy(common),'uid':'SCHEMA-M1','level':'medium','task_origin':'researcher_generated','medium_variant':'paper_main_3_5',
  'nature_language':'两个人2027年3月15日从北京出发去西安三天，总预算3000元，至少吃一顿陕西菜，第二天19点前回到酒店。',
  'additional_constraints':[copy.deepcopy(budget),constraint('local_food','count_at_least',{'kind':'restaurant','cuisine':'陕西菜','count':1}),
   constraint('early_return','arrive_by',{'day':2,'destination':'selected_accommodation','time':'19:00'})]}
 human={**copy.deepcopy(common),'uid':'SCHEMA-H1','level':'human','task_origin':'synthetic_human_style',
  'nature_language':'两个人3月15日从北京去西安三天，总共最多3000。想尝陕西菜，第二晚七点前回酒店；尽量少换酒店。如果第三天上午去了博物馆，返程就选下午的车。',
  'additional_constraints':[copy.deepcopy(budget),constraint('local_food','count_at_least',{'kind':'restaurant','cuisine':'陕西菜','count':1}),
   constraint('early_return','arrive_by',{'day':2,'destination':'selected_accommodation','time':'19:00'}),
   constraint('hotel_changes','minimize',{'quantity':'accommodation_changes'},'soft'),
   constraint('conditional_return','implies',{'if':{'day':3,'period':'morning','activity_tag':'museum'},'then':{'return_train_departure_not_before':'12:00'}})]}
 examples=[easy,medium,human];result=validate_cohort(examples)
 for path,value in [(ROOT/'collector_agent/schemas/query-cohort.schema.json',task_schema()),
                    (ROOT/'collector_agent/examples/query_templates.json',examples)]:
  path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({**result,'synthetic_examples_only':True},ensure_ascii=True))
if __name__=='__main__':main()
