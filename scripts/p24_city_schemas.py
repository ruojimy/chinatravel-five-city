"""Generate reusable city/chain-specific profiles over the shared plan contract."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p24_dynamic_feedback'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.retrieval_benchmark import schemas
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
    protocol=read(OUT/'protocol.json');base=schemas()['plan'];profiles=[]
    for i,city in enumerate(protocol['new_cities'],1):
        schema={'$schema':base['$schema'],
            'title':city+'单城行程','allOf':[{'$ref':'../public/schemas/plan.schema.json'},
                {'properties':{'start_city':{'const':city},'city_sequence':{'const':[city]},
                    'itinerary':{'minItems':1,'maxItems':1,'items':{'properties':{'city':{'const':city}}}}}}]}
        file=f'city_{i:02d}.schema.json';save(OUT/'profiles'/file,schema);profiles.append({'profile':file,'city_sequence':[city],'scope':'new_city'})
    for i,(old,new) in enumerate(protocol['mixed_routes'],1):
        schema={'$schema':base['$schema'],
            'title':old+' → '+new+'串联','allOf':[{'$ref':'../public/schemas/plan.schema.json'},
                {'properties':{'start_city':{'const':old},'city_sequence':{'const':[old,new]},'itinerary':{'minItems':2,'maxItems':2,
                    'prefixItems':[{'properties':{'city':{'const':old}}},{'properties':{'city':{'const':new}}}]}}}]}
        file=f'chain_{i:02d}.schema.json';save(OUT/'profiles'/file,schema);profiles.append({'profile':file,'city_sequence':[old,new],'scope':'old_new_chain'})
    save(OUT/'profiles/index.json',{'profiles':profiles,'generation_stage':'Added after public first-stage packets; reusable profiles do not change participant schema or hidden labels',
        'semantics':'Schema binds cities/day order; cross-day intercity direction, quantities and evidence consistency are independently checked by evaluator.'})
    print(json.dumps({'city_profiles':30,'chain_profiles':6}))
if __name__=='__main__':main()
