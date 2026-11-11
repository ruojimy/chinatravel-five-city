"""Query envelope for collection experiments, not the official ChinaTravel DSL.

Expressions are inert data. A planner adapter must explicitly compile/support
each operator; JSON validity alone never establishes travel feasibility.
"""
from __future__ import annotations
from jsonschema import Draft202012Validator,FormatChecker

KINDS=['attraction','restaurant','accommodation','poi','metro_station','train','flight']

def task_schema():
 text={'type':'string','minLength':1}
 constraint={'type':'object','additionalProperties':False,
  'required':['id','strength','scope','expression','compiler_status'],
  'properties':{'id':text,'strength':{'enum':['hard','soft']},'scope':{'type':'object'},
   'expression':{'type':'object','additionalProperties':False,'required':['op','args'],
    'properties':{'op':text,'args':{'type':'object'}}},
   'compiler_status':{'enum':['unmapped','supported','unsupported']}}}
 task={'type':'object','additionalProperties':False,
  'required':['uid','level','task_origin','purpose','nature_language','start_city','target_city',
   'days','people_number','start_date','additional_constraints','required_kinds','mode',
   'evidence_policy_id','generation','candidate_selection','split'],
  'properties':{'uid':text,'level':{'enum':['easy','medium','human']},
   'task_origin':{'enum':['researcher_generated','human_authored','synthetic_human_style']},
   'purpose':{'enum':['schema_example','development','holdout','regression']},
   'nature_language':text,'start_city':text,'target_city':text,
   'days':{'type':'integer','minimum':1},'people_number':{'type':'integer','minimum':1},
   'start_date':{'type':'string','format':'date'},
   'additional_constraints':{'type':'array','items':constraint},
   'required_kinds':{'type':'array','minItems':1,'uniqueItems':True,'items':{'enum':KINDS}},
   'mode':{'enum':['collection_static_reference','benchmark_frozen','live_delivery']},
   'evidence_policy_id':text,'medium_variant':{'enum':['paper_main_3_5','paper_appendix_2_5']},
   'generation':{'type':'object','required':['seed','budget_sampling','feasibility_claim'],
    'properties':{'seed':{'type':['integer','null']},'budget_sampling':text,
     'feasibility_claim':{'enum':['not_checked','witness_verified','infeasibility_proof_verified']}}},
   'candidate_selection':{'type':'object','required':['policy','required_entity_ids'],
    'properties':{'policy':text,'required_entity_ids':{'type':'array','uniqueItems':True,'items':text}}},
   'split':{'enum':['development','holdout','regression','example']},
   'human_source':{'type':'object','required':['reference','consent_status'],
    'properties':{'reference':text,'consent_status':text}}},
  'allOf':[
   {'if':{'properties':{'level':{'const':'easy'}}},'then':{'properties':{'additional_constraints':{'minItems':1,'maxItems':1},'task_origin':{'const':'researcher_generated'}}}},
   {'if':{'properties':{'level':{'const':'medium'}}},'then':{'required':['medium_variant'],'properties':{'task_origin':{'const':'researcher_generated'},'additional_constraints':{'maxItems':5}}}},
   {'if':{'properties':{'level':{'const':'medium'},'medium_variant':{'const':'paper_main_3_5'}},'required':['medium_variant']},'then':{'properties':{'additional_constraints':{'minItems':3}}}},
   {'if':{'properties':{'level':{'const':'medium'},'medium_variant':{'const':'paper_appendix_2_5'}},'required':['medium_variant']},'then':{'properties':{'additional_constraints':{'minItems':2}}}},
   {'if':{'properties':{'level':{'const':'human'}}},'then':{'properties':{'task_origin':{'enum':['human_authored','synthetic_human_style']}}}},
   {'if':{'properties':{'task_origin':{'const':'human_authored'}}},'then':{'required':['human_source']}}
  ]}
 return {'$schema':'https://json-schema.org/draft/2020-12/schema',
  '$id':'urn:shorttrip:collection-query-cohort:v1','type':'array','minItems':1,'items':task,
  '$comment':'Top-level constraints count logical requirements, not clauses or expression tree nodes. Native storage/plan contracts remain separate.'}

def validate_cohort(tasks):
 validator=Draft202012Validator(task_schema(),format_checker=FormatChecker())
 errors=[str(list(e.absolute_path))+': '+e.message for e in validator.iter_errors(tasks)]
 if errors:raise ValueError('Invalid query cohort: '+'; '.join(errors[:8]))
 keys=[(t['level'],t['uid']) for t in tasks]
 if len(set(keys))!=len(keys):raise ValueError('Duplicate query key')
 for t in tasks:
  ids=[c['id'] for c in t['additional_constraints']]
  if len(set(ids))!=len(ids):raise ValueError('Duplicate constraint ID in '+t['uid'])
  if t['purpose']=='schema_example' and t['split']!='example':raise ValueError('Schema examples cannot enter a scored split')
 return {'schema_ok':True,'tasks':len(tasks),'logical_compilation_verified':False,'feasibility_verified':False}
