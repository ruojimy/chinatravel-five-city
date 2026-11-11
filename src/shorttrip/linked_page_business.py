"""Conservative field extraction from named, nearby schema.org venue objects."""
import math,re
from .scoped_business import matching_aliases
from .business_archives import parse_hours

KINDS={'restaurant':{'Restaurant','CafeOrCoffeeShop','FastFoodRestaurant'},
       'attraction':{'TouristAttraction','Museum','Park','LandmarksOrHistoricalBuildings'},
       'accommodation':{'Hotel','LodgingBusiness','Resort'}}
DAYS={'Mo','Tu','We','Th','Fr','Sa','Su'}
def extract(target,objects):
    candidates=[]
    for item in objects:
        obj=item.get('data',{});types=obj.get('@type',[])
        if isinstance(types,str):types=[types]
        if not isinstance(types,list):continue
        if not KINDS[target['kind']]&{x for x in types if isinstance(x,str)}:continue
        names=[obj.get('name')];alt=obj.get('alternateName',[])
        names+=alt if isinstance(alt,list) else [alt]
        if not any(isinstance(n,str) and matching_aliases(n)&matching_aliases(target['name']) for n in names):continue
        geo=obj.get('geo') or {}
        if not isinstance(geo,dict):continue
        try:
            lon=float(geo['longitude']);lat=float(geo['latitude'])
            if not -180<=lon<=180 or not -90<=lat<=90:continue
            d=111195*math.hypot(lat-target['latitude_wgs84'],(lon-target['longitude_wgs84'])*math.cos(math.radians(lat)))
        except (TypeError,ValueError,KeyError):continue
        if d<=150:candidates.append((obj,round(d,3)))
    if len(candidates)!=1:return {'matched':False,'reason':'ambiguous' if candidates else 'no_exact_near_schema_venue','native_values':{}}
    obj,distance=candidates[0];values={};notes={};kind=target['kind']
    if kind=='restaurant':
        cuisine=obj.get('servesCuisine')
        if isinstance(cuisine,list) and all(isinstance(x,str) for x in cuisine):cuisine=';'.join(cuisine)
        if isinstance(cuisine,str) and cuisine.strip():values['cuisine']=cuisine.strip();notes['cuisine']='explicit schema.org servesCuisine'
        price=obj.get('priceRange')
        if isinstance(price,str):
            m=re.fullmatch(r'人均[：:\s]*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*元?',price)
            if m:values['price']=float(m[1]);notes['price']='explicit per-person CNY reference, not a bill'
    if kind=='attraction' and obj.get('isAccessibleForFree') is True:
        values['price']=0.0;notes['price']='Venue schema declares free access; paid ancillary products not included'
    # A repeated full-week rule may project to one native pair. All split,
    # overnight, seasonal and incomplete weekday descriptions remain unprojected.
    hours=obj.get('openingHours',[])
    if isinstance(hours,str):hours=[hours]
    covered=set();pairs=set();supported=bool(hours)
    if isinstance(hours,list):
        for rule in hours:
            if not isinstance(rule,str):supported=False;break
            m=re.fullmatch(r'(Mo-Su|Mo,Tu,We,Th,Fr,Sa,Su)\s+(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})',rule)
            if not m:supported=False;break
            pair,_=parse_hours(m[2])
            if not pair or pair['opentime']>=pair['endtime']:supported=False;break
            pairs.add((pair['opentime'],pair['endtime']));covered|=DAYS
    else:supported=False
    if supported and covered==DAYS and len(pairs)==1:
        a,b=next(iter(pairs));values.update(opentime=a,endtime=b)
        notes.update(opentime='Explicit uniform full-week schema openingHours; unknown update clock and exceptional dates require recheck',
                     endtime='Explicit uniform full-week schema openingHours; unknown update clock and exceptional dates require recheck')
    if kind=='accommodation':values={};notes={} # No generic hotel price or capacity-to-bed conversion.
    return {'matched':True,'entity_verified':False,'method':'unique_schema_name_and_near_geo_candidate',
            'coordinate_assumption':'schema_geo_decimal_coordinates_interpreted_as_WGS84_not_independently_certified',
            'distance_metres':distance,'native_values':values,'field_notes':notes,
            'source_object':obj,'room_prices_or_beds_inferred':False}
