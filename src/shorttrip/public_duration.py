"""Business recommendations in preserved anonymous public HTML, not browser state."""
import json,re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from opencc import OpenCC
from .business_archives import normalize_name

def extract_public_duration(raw):
    soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
    node=soup.select_one('script#__NEXT_DATA__')
    if node is None:raise ValueError('Public duration container missing')
    poi=json.loads(node.string or node.get_text())['props']['pageProps']['initialState']['poiDetail']
    value=(poi.get('openInfo') or {}).get('playSpendTime')
    if not isinstance(value,str) or not value.strip():raise ValueError('Explicit suggested visit duration missing')
    projection={key:poi.get(key) for key in ('poiName','districtName','address','businessId','poiId')}
    projection['playSpendTime']=value
    normalize=lambda text:normalize_name(OpenCC('t2s').convert(text or ''))
    if not any(normalize(h.get_text(' ',strip=True))==normalize(projection['poiName']) for h in soup.find_all('h1')):
        raise ValueError('Public title and duration property name disagree')
    return projection

def verify_public_duration(raw,projection,record,url):
    actual=extract_public_duration(raw)
    if actual!=projection:raise ValueError('Duration projection differs from original public HTML')
    normalize=lambda text:normalize_name(OpenCC('t2s').convert(text or ''))
    if normalize(actual['poiName'])!=normalize(record['name']) or actual['districtName']!=record['city']:
        raise ValueError('Duration is bound to another name or city')
    match=re.fullmatch(r'/sight/[a-z0-9]+/(\d+)\.html',urlsplit(url).path)
    if not match or str(actual['businessId'])!=match[1]:raise ValueError('Same-page provider ID does not match captured URL')
    pair=re.fullmatch(r'(\d+(?:\.\d+)?)(?:\s*[-–—~至]\s*(\d+(?:\.\d+)?))?小时',actual['playSpendTime'].strip())
    if pair:
        low=float(pair[1]);high=float(pair[2] or pair[1])
        if 0<low<=high<=24:return {'recommendmintime':low,'recommendmaxtime':high}
    return {}
