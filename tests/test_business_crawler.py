import json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from shorttrip.business_crawler import BusinessCrawler,page_fields
class Response:
    def __init__(self,status=200,text='<html><h1>公开酒店</h1></html>',headers=None):
        self.status_code=status;self.content=text.encode();self.encoding='utf-8';self.headers=headers or {'Content-Type':'text/html'}
    def iter_content(self,n):yield self.content
class CrawlTests(unittest.TestCase):
    def make(self,tmp,response):
        calls=[]
        def send(url,**kw):calls.append((url,kw));return response
        c=BusinessCrawler(tmp,minimum_interval=0,transport=send);c.seed_robots('https://example.org','User-agent: *\nAllow: /\n')
        c.enqueue([{'url':'https://example.org/hotel/1'}]);return c,calls
    def test_html_is_captured_and_queue_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response());r=c.run();self.assertEqual(r['job_counts'],{'captured':1})
            self.assertEqual(c.run()['events'],[]);self.assertEqual(len(calls),1);c.close()
    def test_crawler_does_not_impersonate_search_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response());c.run();self.assertIn('ShortTripResearchBot',calls[0][1]['headers']['User-Agent']);c.close()
    def test_robots_longest_allow_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response());c.db.execute('DELETE FROM hosts');c.db.commit()
            c.seed_robots('https://example.org','User-agent: *\nDisallow: /\nAllow: /hotel/*.html\n')
            self.assertEqual(c.run()['events'][0]['status'],'robots_disallowed');self.assertEqual(calls,[]);c.close()
    def test_429_stops_host_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response(status=429));c.enqueue([{'url':'https://example.org/hotel/2'}])
            r=c.run();self.assertEqual(len(calls),1);self.assertTrue(all(e['status']=='source_paused' for e in r['events']));c.close()
    def test_local_response_cap_does_not_pause_publisher_or_retry_oversize_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def send(url,**kw):
                calls.append(url);return Response(text='x'*200 if url.endswith('/1') else '<h1>Small</h1>')
            c=BusinessCrawler(tmp,max_bytes=80,minimum_interval=0,transport=send)
            c.seed_robots('https://example.org','User-agent: *\nAllow: /\n')
            c.enqueue([{'url':'https://example.org/hotel/1'},{'url':'https://example.org/hotel/2'}]);result=c.run()
            self.assertEqual(result['job_counts'],{'captured':1,'local_resource_limit':1})
            self.assertEqual(c.db.execute('SELECT status FROM hosts').fetchone()[0],'ready')
            self.assertEqual(result['events'][0]['http_status'],200);self.assertEqual(c.run()['events'],[]);self.assertEqual(len(calls),2);c.close()
    def test_challenge_stops_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response(text='<h1>请完成安全验证</h1>'));r=c.run()
            self.assertEqual(r['events'][0]['reason'],'visible_access_challenge');c.close()
    def test_redirect_requires_review_and_no_cookie_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response(status=302,headers={'Location':'/login'}));r=c.run()
            self.assertEqual(r['events'][0]['status'],'redirect_needs_review');self.assertFalse(calls[0][1]['allow_redirects']);self.assertNotIn('cookies',calls[0][1]);c.close()
    def test_delay_deferred_without_long_sleep(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response());c.db.execute('UPDATE hosts SET last_at=?,delay=120',(time.time(),));c.db.commit()
            t=time.monotonic();r=c.run();self.assertLess(time.monotonic()-t,1);self.assertEqual(calls,[])
            self.assertEqual(r['job_counts'],{'pending':1});c.close()
    def test_no_transactional_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,calls=self.make(tmp,Response())
            with self.assertRaises(ValueError):c.enqueue([{'url':'https://example.org/booking/submit'}])
            c.close()
    def test_money_is_not_projected_as_hotel_price(self):
        p=page_fields('<h1>酒店</h1><p>成人早餐¥194/人，送站每次¥294。</p>')
        self.assertEqual(len(p['unbound_observations']),2)
        self.assertTrue(all(x['status']=='unbound_observation_not_fact' for x in p['unbound_observations']))
    def test_multi_offer_jsonld_preserves_products(self):
        p=page_fields('<script type="application/ld+json">{"@type":"Hotel","offers":[{"@type":"Offer","price":300},{"@type":"Offer","price":500}]}</script>')
        self.assertEqual(len(p['jsonld']),3)
    def test_english_access_challenge_detected(self):
        self.assertTrue(page_fields('<h1>Verify you are human</h1>')['challenge'])
if __name__=='__main__':unittest.main(verbosity=2)
