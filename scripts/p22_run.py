"""Generate and validate one P22 itinerary with bounded external-model repair."""
import json
import sys
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/p22_adaptive_delivery'
sys.path.insert(0,str(ROOT/'src'))
from shorttrip.adaptive_delivery import evaluate_delivery, normalize_delivery_anchors

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    target=OUT/'plans/D01/deliverable.json'
    assert not target.exists(),'Do not overwrite first accepted output'
    inp=read(OUT/'participant_input.json')
    messages=[{'role':'system','content':'你是旅行计划编排器。仅使用输入已提供的候选和证据。将决策与事实分开，不能将待预约写成已预约，不能把预算上限写成商家报价。只输出完整JSON。'},
              {'role':'user','content':json.dumps(inp,ensure_ascii=False)}]
    key=(ROOT/'.secrets/deepseek.key').read_text(encoding='ascii').strip()
    usage={'calls':0,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0}
    previous=sorted((OUT/'logs').glob('participant_*.json'))
    for log in previous:
        prior=read(log);usage['calls']+=1
        for k in ('prompt_tokens','completion_tokens','total_tokens'):usage[k]+=prior.get('usage',{}).get(k,0)
    for step in range(len(previous)+1,len(previous)+4):
        payload={'model':'deepseek-flash','messages':messages,'temperature':0,'response_format':{'type':'json_object'},'max_tokens':6000,'thinking':{'type':'disabled'}}
        req=urllib.request.Request('https://api.deepseek.com/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=180) as response:data=json.loads(response.read().decode())
        except Exception as e:
            save(OUT/f'logs/failure_{step}.json',{'type':type(e).__name__,'note':'Stopped without dumping request headers or credentials.'});raise
        choice=data['choices'][0];content=choice['message']['content']
        usage['calls']+=1
        for k in ('prompt_tokens','completion_tokens','total_tokens'):usage[k]+=data.get('usage',{}).get(k,0)
        save(OUT/f'logs/participant_{step:02d}.json',{'at':datetime.now(timezone.utc).isoformat(),'model':data.get('model'),'thinking':'disabled','finish_reason':choice.get('finish_reason'),'usage':data.get('usage'),'content':content})
        try:
            answer=json.loads(content)
            answer,compiled_edits=normalize_delivery_anchors(answer,inp['request'])
            checked=evaluate_delivery(answer,inp['request'],entities=inp['entities'],references=inp['references'])
        except Exception as e:
            checked={'proposal_ok':False,'validation_error':str(e)}
        save(OUT/f'logs/check_{step:02d}.json',checked)
        if checked['proposal_ok']:
            answer['_meta']={'at':datetime.now(timezone.utc).isoformat(),'model':data.get('model'),'usage':usage,'proposal_only':True,'compiled_edits':compiled_edits}
            save(target,answer);save(OUT/'delivery_evaluation.json',checked)
            print(json.dumps({'status':'proposal_validated','checks':len(checked['proposal_checks']),'usage':usage},ensure_ascii=False));return
        messages += [{'role':'assistant','content':content},{'role':'user','content':'VALIDATION_FEEDBACK: '+json.dumps(checked,ensure_ascii=False)+'。只修改失败项，保留证据等级，重新输出完整JSON。'}]
    raise RuntimeError('Bounded repair exhausted; logs preserved')

if __name__=='__main__':main()
