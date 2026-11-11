"""Ground extracted requirements and compile the existing standard vocabulary."""
import ast
import math
import re
from .translation_contract import TranslationValidationError

EXTRACTION_CONTRACT = '''
Extraction validation (overrides examples): Do not invent constraints or use 0
for unspecified budgets, rooms or bed types. Leave unspecified fields absent/null.
For every non-derived hard_logic item add hard_logic_evidence containing
{"constraint":"the exact hard_logic string", "source":"verbatim user quote"}.
days/people_number may come from input metadata; tickets and taxi_cars may be
derived from people_number. Rooms and room_type may NOT be derived from people.
Distinguish attraction_names/spot_type and restaurant_names/food_type: named
places are names, not categories. Do not make vague/optional wishes such as
"尽可能多体验当地美食" into a mandatory cuisine category named 美食.
Preserve all explicit requirements, including specific named places and modes.
Separate hard_logic from soft_logic before generating any checking code.
An explicit unqualified request (budget cap, room count, named visit) is hard.
最好/尽量/尽可能/优先/主要/如果方便 and prefer/mainly/primarily/as much as
possible identify preferences. Preserve them in soft_logic with verbatim
soft_logic_evidence; never put them into hard_logic. Keep complete clauses so
modifiers and negations cannot disappear from evidence. Do not put mandatory
requirements into soft_logic. If there are no preferences, return empty lists.
For example, "酒店最好有管家服务" -> soft_logic ["{'管家服务'}<=hotel_feature"],
while "酒店必须有管家服务" -> hard_logic ["{'管家服务'}<=hotel_feature"].
"主要坐地铁" -> soft_logic ["transport_type<={'metro'}"], whereas "只能坐地铁"
is hard. Soft expressions record preferences only and are not feasibility tests.
Explicit room counts and bed counts are independent: "三间大床房" means
rooms==3 and room_type==1; "住大床房" specifies room_type==1 but no room count.
"双床房" means room_type==2. "单人房" and "双人间" describe occupancy,
not a proven bed count; preserve explicit room counts without inventing beds.
For example, "住一间有桑拿的酒店，双人间就行" requires rooms==1 and
{'桑拿'}<=hotel_feature. Do NOT emit room_type==2: two occupants do not prove
two beds. Keep the occupancy wording in the original query.
Use numeric equality for rooms/room_type, never a set of room-name strings.
When the local JSON schema requests only four logic/evidence arrays, emit
exactly those arrays. City/day/people metadata already exists in the input.
Do not invent symbolic start_city/target_city set-membership constraints.
If extraction is rejected, correct the extraction itself, not Python code.
'''

def comparison(text):
    try:
        node=ast.parse(text,mode='eval').body
        if not isinstance(node,ast.Compare) or len(node.ops)!=1:return None
        left,right=node.left,node.comparators[0]
        if isinstance(left,ast.Name):return left.id,node.ops[0],ast.literal_eval(right),'scalar'
        if isinstance(right,ast.Name):return right.id,node.ops[0],ast.literal_eval(left),'set'
    except (ValueError,SyntaxError,TypeError):pass
    return None

def _catalog(city):
    from chinatravel.symbol_verification.concept_func import _tools_for_lang
    from chinatravel.environment.language import CITY_NAMES
    lang=next((lang for lang in ('zh','en') if city in CITY_NAMES[lang]),None)
    if lang is None:raise TranslationValidationError('Unknown target city for extraction: '+str(city))
    tools=_tools_for_lang(lang)
    result={}
    for tool,names,types,column in (
        ('attractions','attraction_names','spot_type','type'),
        ('restaurants','restaurant_names','food_type','cuisine'),
        ('accommodations','hotel_names','hotel_feature','featurehoteltype')):
        rows=tools[tool].data[city]
        result[names]=set(rows['name'].dropna().astype(str))
        result[types]=set(rows[column].dropna().astype(str))
    return result

def _norm(value):return re.sub(r'\s+','',value).lower()

def _number_present(value,source):
    numbers=[float(x)*{'':1,'万':10000,'千':1000}[unit]
             for x,unit in re.findall(r'(\d+(?:\.\d+)?)\s*([万千]?)',source)]
    if value in numbers:return True
    # Common Chinese number forms used for room counts and prices.
    digits={'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    for token in re.findall('[零一二两三四五六七八九十百千万]+',source):
        total=part=current=0
        for ch in token:
            if ch in digits:current=digits[ch]
            elif ch=='万':total+=(part+current)*10000;part=current=0
            else:part+=(current or 1)*{'十':10,'百':100,'千':1000}[ch];current=0
        if total+part+current==value:return True
    words={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10}
    for word,unit in re.findall(r'\b(one|two|three|four|five|six|seven|eight|nine|ten)\b(?:\s+(hundred|thousand))?',source,re.I):
        if words[word.lower()]*{'':1,'hundred':100,'thousand':1000}[unit.lower()]==value:return True
    return False

def _validate_extraction_items(query,parsed):
    codes=parsed.get('hard_logic',[])
    quotes={e.get('constraint'):e.get('source') for e in parsed.get('hard_logic_evidence',[])
            if isinstance(e,dict)}
    text=query['nature_language'];catalog=None;evidence=[]
    derived={'days':query.get('days'),'people_number':query.get('people_number'),
             'tickets':query.get('people_number')}
    if query.get('people_number') is not None:derived['taxi_cars']=(query['people_number']+3)//4
    for index,code in enumerate(codes):
        fact=comparison(code)
        if fact and fact[0] in derived and fact[3]=='scalar' and isinstance(fact[1],ast.Eq):
            if derived[fact[0]] is not None and (isinstance(fact[2],bool) or fact[2]!=derived[fact[0]]):
                raise TranslationValidationError(f'Extraction constraint {index+1} {code}: conflicts with input people/day counts')
            evidence.append(dict(constraint=code,source='input metadata / passenger-count derivation',derived=True))
            continue
        source=quotes.get(code)
        if not isinstance(source,str) or not source.strip() or _norm(source) not in _norm(text):
            raise TranslationValidationError(f'Extraction constraint {index+1} {code}: missing verbatim hard_logic_evidence; do not invent unspecified requirements')
        if fact:
            field,op,value,shape=fact
            if field in ('cost','hotel_price','food_price','rooms','room_type'):
                if (not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0):
                    raise TranslationValidationError(f'Extraction {code}: unspecified numeric requirements must be absent, not 0')
                cue=(r'间|rooms?\b' if field=='rooms' else r'床|beds?\b|\btwin\b|\bking\b|\bqueen\b' if field=='room_type'
                     else r'预算|元|人民币|块|¥|￥|budget|yuan|rmb|cost|price|cny')
                if not re.search(cue,source,re.I):
                    raise TranslationValidationError(f'Extraction {code}: quote does not explicitly request this budget/room/bed constraint')
                if field=='room_type':
                    explicit_beds=set()
                    if re.search(r'单床|大床|\b(?:single|double|king|queen)[ -]bed\b',source,re.I):
                        explicit_beds.add(1)
                    if re.search(r'双床|\btwin\b|\btwo beds\b',source,re.I):
                        explicit_beds.add(2)
                    if explicit_beds and (len(explicit_beds)!=1 or value not in explicit_beds):
                        raise TranslationValidationError('Bed count must match the explicit bed wording, not the number of rooms')
                bedword=field=='room_type' and ((value==1 and re.search(r'单床|大床|single|double[ -]bed|king|queen',source,re.I)) or (value==2 and re.search(r'双床|twin|two beds',source,re.I)))
                if not bedword and not _number_present(value,source):
                    raise TranslationValidationError(f'Extraction {code}: numeric value not supported by quote {source!r}')
            if field in ('attraction_names','restaurant_names','hotel_names','spot_type','food_type','hotel_feature'):
                if not isinstance(value,set) or not value or not all(isinstance(v,str) for v in value):
                    raise TranslationValidationError(f'Extraction {code}: expected a nonempty set of names/types')
                catalog=catalog if catalog is not None else _catalog(query.get('target_city',parsed.get('target_city')))
                for item in value:
                    if item not in catalog[field]:
                        actual=[k for k,values in catalog.items() if item in values]
                        raise TranslationValidationError(f'Extraction {code}: {item!r} is not a valid {field} in the target city; use {actual or "an exact database name/type, never an invented category"}')
                    if field.endswith('_names') and not (_norm(item) in _norm(source) or _norm(source) in _norm(item)):
                        raise TranslationValidationError(f'Extraction {code}: named place is not supported by its source quote')
                    if field in ('spot_type','food_type','hotel_feature'):
                        terms={item}
                        if field=='spot_type':
                            from .extraction_alignment import CATEGORY_ALIASES
                            terms.update(alias for alias,canonical in CATEGORY_ALIASES.items() if canonical==item)
                        if not any(_norm(term) in _norm(source) for term in terms):
                            raise TranslationValidationError(f'Extraction {code}: category/feature is not supported by its source quote {source!r}')
        evidence.append(dict(constraint=code,source=source,derived=False))
    out=dict(parsed);out['hard_logic_evidence']=evidence
    return out

def validate_extraction(query,parsed):
    from .extraction_alignment import grounded_extraction
    return grounded_extraction(query,parsed)

def compile_constraint(text):
    try:tree=ast.parse(text,mode='eval').body
    except SyntaxError:return None
    if isinstance(tree,ast.BoolOp) and isinstance(tree.op,ast.Or):
        options=[comparison(ast.unparse(node)) for node in tree.values]
        if (all(o and o[0]=='attraction_names' and o[3]=='set' and isinstance(o[1],ast.LtE)
                and isinstance(o[2],set) and o[2] and all(isinstance(n,str) for n in o[2]) for o in options)):
            clauses=['('+('{'+', '.join(repr(n) for n in sorted(o[2]))+'}')+'<=seen)' for o in options]
            return "seen=set()\nfor activity in allactivities(plan):\n  if activity_type(activity)=='attraction': seen.add(activity_position(activity))\nresult=("+' or '.join(clauses)+')'
    fact=comparison(text)
    if not fact:return None
    field,op,value,shape=fact
    symbols={ast.Eq:'==',ast.LtE:'<=',ast.Lt:'<',ast.GtE:'>=',ast.Gt:'>'}
    symbol=symbols.get(type(op))
    if field=='return_start_time' and shape=='scalar' and isinstance(op,(ast.LtE,ast.Lt)) and isinstance(value,str):
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):return None
        return "found=False\nresult=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['train','airplane'] and intercity_transport_origin(activity)==target_city(plan):\n    found=True\n    if not (activity_start_time(activity)"+symbol+repr(value)+"): result=False\nresult=(found and result)"
    if shape=='scalar' and isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
        if field in ('days','people_number') and isinstance(op,ast.Eq):
            return f'result=({"day_count" if field=="days" else "people_count"}(plan)=={value!r})'
        if field=='cost' and symbol:
            return 'total_cost=0\nfor activity in allactivities(plan):\n  total_cost+=activity_cost(activity)+innercity_transport_cost(activity_transports(activity))\nresult=(total_cost'+symbol+repr(value)+')'
        if field in ('rooms','room_type','hotel_price','food_price') and symbol:
            fn={'rooms':'room_count','room_type':'room_type','hotel_price':'activity_price','food_price':'activity_price'}[field]
            kinds=['breakfast','lunch','dinner'] if field=='food_price' else ['accommodation']
            return f'result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in {kinds!r} and not ({fn}(activity){symbol}{value!r}): result=False'
        if field=='tickets' and isinstance(op,ast.Eq):
            return f"result=True\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['attraction','train','airplane'] and activity_tickets(activity)!={value!r}: result=False\n  for leg in activity_transports(activity):\n    if leg['mode']=='metro' and metro_tickets(activity_transports(activity))!={value!r}: result=False"
        if field=='taxi_cars' and isinstance(op,ast.Eq):
            return f"result=True\nfor activity in allactivities(plan):\n  for leg in activity_transports(activity):\n    if leg['mode']=='taxi' and taxi_cars(activity_transports(activity))!={value!r}: result=False"
    if not isinstance(value,set) or not value or not all(isinstance(v,str) for v in value):return None
    literal='{'+', '.join(repr(v) for v in sorted(value))+'}'
    if shape=='set' and field=='intercity_transport' and isinstance(op,ast.LtE):
        return "modes=set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['train','airplane']: modes.add(activity_type(activity))\nresult=("+literal+'<=modes)'
    if shape=='scalar' and field=='transport_type' and isinstance(op,(ast.LtE,ast.Eq)):
        return "modes=set()\nfor activity in allactivities(plan):\n  if activity_transports(activity): modes.add(innercity_transport_type(activity_transports(activity)))\nresult=(modes"+symbol+literal+')'
    if shape=='scalar' and field=='intercity_transport' and isinstance(op,ast.Eq):
        return "modes=set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in ['train','airplane']: modes.add(activity_type(activity))\nresult=(modes=="+literal+')'
    if shape=='scalar' and field=='train_type' and isinstance(op,ast.Eq):
        return "found=False\nresult=True\nfor activity in allactivities(plan):\n  if activity_type(activity)=='train':\n    found=True\n    if activity['TrainID'][0] not in "+literal+": result=False\nresult=(found and result)"
    kinds={'attraction_names':['attraction'],'spot_type':['attraction'],
           'restaurant_names':['breakfast','lunch','dinner'],'food_type':['breakfast','lunch','dinner'],
           'hotel_names':['accommodation'],'hotel_feature':['accommodation']}
    if shape=='set' and isinstance(op,ast.LtE) and field in kinds:
        fn={'spot_type':'attraction_type','food_type':'restaurant_type','hotel_feature':'accommodation_type'}.get(field)
        expression=f'{fn}(activity,target_city(plan))' if fn else 'activity_position(activity)'
        return f'seen=set()\nfor activity in allactivities(plan):\n  if activity_type(activity) in {kinds[field]!r}: seen.add({expression})\nresult=({literal}<=seen)'
    return None

def template_programs(query):return [compile_constraint(c) for c in query['hard_logic']]
