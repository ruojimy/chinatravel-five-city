"""Read only visible Accor room-card labels; occupancy never becomes bed count."""
import re
from bs4 import BeautifulSoup
def accor_rooms(content):
    soup=BeautifulSoup(content.decode('utf-8','replace'),'html.parser')
    for tag in soup(['script','style','noscript']):tag.decompose()
    text=soup.get_text(' ',strip=True);heading=soup.find('h1')
    gps=re.search(r'\bGPS\s*:\s*([-+]?\d+\.\d+)\s*,\s*([-+]?\d+\.\d+)',text)
    rows=[]
    for title in soup.select('h3.card__title'):
        box=title.find_parent(class_='card__infos')
        if not box:continue
        name=title.get_text(' ',strip=True);bedtexts=[]
        for detail in box.select('.card__details'):
            label=detail.select_one('.sr-only');value=detail.select_one('.ellipsis')
            if label and value and label.get_text(' ',strip=True).casefold().rstrip(':：') in ('床上用品','bedding','bed','寝具'):
                bedtexts.append(value.get_text(' ',strip=True))
        bed=' | '.join(bedtexts)
        if not name or not bed:continue
        alternatives=bool(re.search(r'\bor\b|或者|\s或\s|或[12两一二]|[12两一二].*或',bed,re.I))
        multi=bool(re.search(r'连通|相连|connecting|adjoining|[2-9两二三四]\s*(?:个|间)?\s*(?:卧室|bedrooms?)|two.?bedroom',name,re.I))
        parts=[{'count':int(m[1]),'type':m[2].strip()} for m in re.finditer(r'(\d+)\s*[x×]\s*([^|]+?)(?=\s+(?:and|和|或)\s+|\s+\d+\s*[x×]|$)',bed,re.I)]
        # Every bedding line must explicitly state a count. A missing number
        # before x, a choice, or mixed unparsed text remains an unknown total.
        multipliers=list(re.finditer(r'(?<!\w)(?:(\d+)\s*)?[x×](?=\s)',bed,re.I))
        missing_count=any(m[1] is None for m in multipliers)
        total=sum(p['count'] for p in parts) if parts and not alternatives and not missing_count else None
        room_id=None;button=box.find('button',attrs={'data-popin-url':True})
        if button:
            m=re.search(r'/room/([^/.]+)\.',button['data-popin-url'])
            if m:room_id=m[1]
        rows.append({'room_type_name':name,'provider_room_type_id':room_id,'bed_quote':bed,'bed_configuration':parts,
            'bed_count':total,'room_count':None if multi else 1,'alternatives':alternatives,'multiroom':multi,
            'quote':box.get_text(' ',strip=True),'price':None})
    return {'hotel_name':heading.get_text(' ',strip=True) if heading else None,
        'gps':{'lat':float(gps[1]),'lon':float(gps[2]),'quote':gps[0],'coordinate_system':'publisher_labels_GPS_wgs84_assumed_for_candidate_distance_not_certified'} if gps else None,
        'room_configurations':rows,'price_projection_allowed':False}
