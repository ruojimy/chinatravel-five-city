"""Offline scheduler lease and time gate; no account-usage gating."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.collection_session import SessionLedger
from shorttrip.collection_weekly_budget import WeeklyBudgetCampaign

def main():
 ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
 for name in ('begin','check'):
  p=sub.add_parser(name);p.add_argument('run_id');p.add_argument('--usage-file',help='Required only for weekly-budget mode')
 p=sub.add_parser('campaign-init');p.add_argument('campaign_id');p.add_argument('--usage-file',required=True);p.add_argument('--budget-points',type=float,default=20)
 p=sub.add_parser('campaign-status');p.add_argument('campaign_id')
 p=sub.add_parser('end');p.add_argument('run_id');p.add_argument('--reason',required=True);p.add_argument('--workers-stopped',action='store_true');p.add_argument('--stop-report')
 a=ap.parse_args();home=ROOT/'collector_agent';cfg=json.loads((home/'config.json').read_text(encoding='utf-8'))
 ledger=SessionLedger(home/'memory/agent.sqlite3',cfg['scheduled_run_policy']);sys.stdout.reconfigure(encoding='utf-8')
 try:
  if a.command in ('campaign-init','campaign-status'):
   campaign=WeeklyBudgetCampaign(home/'memory/agent.sqlite3')
   try:result=campaign.initialize(a.campaign_id,json.loads(Path(a.usage_file).read_text(encoding='utf-8')),a.budget_points) if a.command=='campaign-init' else campaign.status(a.campaign_id)
   finally:campaign.close()
  elif a.command=='end':result=ledger.end(a.run_id,a.reason,workers_stopped=a.workers_stopped,stop_report=json.loads(Path(a.stop_report).read_text(encoding='utf-8')) if a.stop_report else None)
  else:
   raw=json.loads(Path(a.usage_file).read_text(encoding='utf-8')) if cfg['scheduled_run_policy'].get('control_mode')=='weekly_budget' and a.usage_file else None
   result=ledger.begin(a.run_id,raw) if a.command=='begin' else ledger.checkpoint(a.run_id,raw)
  print(json.dumps(result,ensure_ascii=False,indent=2))
 finally:ledger.close()
if __name__=='__main__':main()
