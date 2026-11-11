import concurrent.futures,hashlib,sqlite3,sys,tempfile,threading,time,unittest
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from shorttrip.business_crawler import BusinessCrawler,LocalCrawlBudget
from p16_web_worker_pool import SharedBudget

class Response:
 def __init__(self,status=200,text='<html><h1>Venue</h1></html>'):
  self.status_code=status;self.content=text.encode();self.encoding='utf-8';self.headers={'Content-Type':'text/html'}
 def iter_content(self,n):yield self.content

class PoolTests(unittest.TestCase):
 def test_invalid_partition(self):
  for i,n in ((0,0),(3,3),(-1,3),(True,3)):
   with tempfile.TemporaryDirectory() as tmp:
    with self.assertRaises(ValueError):BusinessCrawler(tmp,partition_index=i,partition_count=n)
 def test_host_ownership_is_unique_and_path_independent(self):
  with tempfile.TemporaryDirectory() as tmp:
   cs=[BusinessCrawler(tmp,partition_index=i,partition_count=3) for i in range(3)]
   for h in ('a.example','b.example','www.example.org'):
    owners=[[i for i,c in enumerate(cs) if c.owns_url(u)] for u in (f'https://{h}/1',f'https://{h}/robots.txt',f'https://{h.upper()}/2')]
    self.assertTrue(all(len(x)==1 for x in owners));self.assertEqual(owners[0],owners[1]);self.assertEqual(owners[1],owners[2])
   for c in cs:c.close()
 def setup_queue(self,tmp,urls,delay=0):
  c=BusinessCrawler(tmp,minimum_interval=delay)
  for h in {urlsplit(u).netloc for u in urls}:c.seed_robots('https://'+h,'User-agent: *\nAllow: /\n')
  c.enqueue({'url':u} for u in urls);c.close()
 def test_local_budget_not_a_host_pause(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.setup_queue(tmp,['https://a.example/1']);calls=[]
   c=BusinessCrawler(tmp,minimum_interval=0,request_gate=lambda u:False,transport=lambda *a,**kw:calls.append(a))
   with self.assertRaises(LocalCrawlBudget):c.run()
   self.assertEqual(calls,[]);self.assertEqual(c.db.execute('SELECT status FROM hosts').fetchone()[0],'ready')
   self.assertEqual(c.db.execute('SELECT status FROM jobs').fetchone()[0],'pending');c.close()
 def test_local_budget_before_robots_does_not_create_pause(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=BusinessCrawler(tmp,request_gate=lambda u:False);c.enqueue([{'url':'https://new.example/1'}])
   with self.assertRaises(LocalCrawlBudget):c.run()
   self.assertEqual(c.db.execute('SELECT count(*) FROM hosts').fetchone()[0],0);c.close()
 def test_shared_budget_is_atomic_across_threads(self):
  with tempfile.TemporaryDirectory() as tmp:
   b=SharedBudget(9,60,Path(tmp)/'STOP')
   with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:answers=list(pool.map(b.reserve,['https://a.example']*200))
   self.assertEqual(sum(answers),9);self.assertEqual(b.spent,9)
 def test_stop_and_deadline_do_not_consume_requests(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'STOP';p.write_text('stop');b=SharedBudget(9,60,p)
   self.assertFalse(b.reserve('x'));self.assertEqual(b.spent,0);p.unlink();b.deadline=time.monotonic()-1
   self.assertFalse(b.reserve('x'));self.assertEqual(b.spent,0)
 def test_distinct_hosts_parallel_no_duplicate_job_or_host(self):
  with tempfile.TemporaryDirectory() as tmp:
   hosts={}
   for i in range(100):
    h=f'h{i}.example';owner=int(hashlib.sha256(h.encode()).hexdigest(),16)%3;hosts.setdefault(owner,h)
    if len(hosts)==3:break
   urls=[f'https://{h}/{j}' for h in hosts.values() for j in range(2)];self.setup_queue(tmp,urls)
   barrier=threading.Barrier(3);lock=threading.Lock();seen=[];active=set();peak=[0];first=set()
   def transport(url,**kw):
    host=urlsplit(url).hostname
    with lock:
     self.assertNotIn(host,active);active.add(host);peak[0]=max(peak[0],len(active));seen.append(url);initial=host not in first;first.add(host)
    if initial:barrier.wait(timeout=5)
    with lock:active.remove(host)
    return Response()
   def worker(index):
    c=BusinessCrawler(tmp,minimum_interval=0,partition_index=index,partition_count=3,transport=transport)
    try:return c.run(max_requests=10)
    finally:c.close()
   with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(worker,range(3)))
   self.assertEqual(set(seen),set(urls));self.assertEqual(len(seen),len(urls));self.assertEqual(peak[0],3)
   db=sqlite3.connect(Path(tmp)/'queue.sqlite3');self.assertEqual(db.execute("SELECT count(*) FROM jobs WHERE status='captured'").fetchone()[0],6);db.close()
 def test_same_host_delay_not_shortened(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.setup_queue(tmp,['https://a.example/1','https://a.example/2']);calls=[]
   owner=int(hashlib.sha256(b'a.example').hexdigest(),16)%3
   c=BusinessCrawler(tmp,minimum_interval=0,partition_index=owner,partition_count=3,transport=lambda u,**kw:(calls.append(u) or Response()))
   c.db.execute('UPDATE hosts SET delay=120,last_at=0');c.db.commit();c.run()
   self.assertEqual(len(calls),1);self.assertEqual(c.db.execute("SELECT count(*) FROM jobs WHERE status='pending'").fetchone()[0],1);c.close()
 def test_pause_and_captured_rows_persist_across_pool_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   self.setup_queue(tmp,['https://a.example/1','https://a.example/2']);owner=int(hashlib.sha256(b'a.example').hexdigest(),16)%3;calls=[]
   c=BusinessCrawler(tmp,minimum_interval=0,partition_index=owner,partition_count=3,transport=lambda u,**kw:(calls.append(u) or Response(429)))
   c.run();c.close();c=BusinessCrawler(tmp,minimum_interval=0,partition_index=owner,partition_count=3,transport=lambda *a,**kw:self.fail('paused host retried'))
   c.enqueue([{'url':'https://a.example/3'}]);c.run();self.assertEqual(len(calls),1);self.assertEqual(c.db.execute('SELECT status FROM hosts').fetchone()[0],'paused');c.close()
if __name__=='__main__':unittest.main(verbosity=2)
