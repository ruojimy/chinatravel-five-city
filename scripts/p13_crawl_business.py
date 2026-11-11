"""Run a bounded public-page batch; delayed jobs persist without blocking sleeps."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.business_crawler import BusinessCrawler
def main():
    p=argparse.ArgumentParser();p.add_argument('--enqueue',type=Path)
    p.add_argument('--directory',type=Path,default=ROOT/'results/p13_business_completion/crawler')
    p.add_argument('--max-requests',type=int,default=6);p.add_argument('--max-seconds',type=int,default=45)
    args=p.parse_args();crawler=BusinessCrawler(args.directory)
    seed=ROOT/'results/p13_business_completion/crawl_probe'
    if (seed/'robots_probe.json').exists():
        for record in json.loads((seed/'robots_probe.json').read_text(encoding='utf-8')):
            if record.get('http_status')==200 and record.get('looks_like_robots'):
                text=(seed/(record['host'].split('//')[1]+'.robots.txt')).read_text(encoding='utf-8')
                crawler.seed_robots(record['host'],text,retrieved_at=record['retrieved_at'])
    if args.enqueue:crawler.enqueue(json.loads(args.enqueue.read_text(encoding='utf-8')))
    try:report=crawler.run(max_requests=args.max_requests,max_seconds=args.max_seconds)
    finally:crawler.close()
    output=args.directory/('run_'+report['executed_at'].replace(':','').replace('+','_')+'.json')
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
