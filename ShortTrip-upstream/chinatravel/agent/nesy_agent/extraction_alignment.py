"""Source coverage and bounded, item-wise extraction repair; no search logic."""
import ast
import difflib
import json
import re
from copy import deepcopy
from .translation_contract import TranslationValidationError,extraction_output_options
from .constraint_compiler import comparison,_catalog,_validate_extraction_items

CATEGORY_ALIASES={
 '博物馆':'博物馆/纪念馆','历史景点':'历史古迹','历史人文景点':'历史古迹',
 '历史人文':'历史古迹','历史':'历史古迹','自然景点':'自然风光','自然风光':'自然风光',
 '大学校园':'大学校园','大学里':'大学校园','大学':'大学校园',
 'museum':'Museum/Memorial Hall','museums':'Museum/Memorial Hall'}

def literal(values):return '{'+', '.join(repr(v) for v in sorted(values))+'}'
def set_code(field,values,any_of=False):
    if any_of and len(values)>1:
        return '('+' or '.join(literal({v})+'<='+field for v in sorted(values))+')'
    return literal(values)+'<='+field

def aliases(names):
    result={}
    for name in sorted(names):
        result.setdefault(name,set()).add(name)
        for suffix in ('风景名胜区','风景区','景区','游船'):
            if name.endswith(suffix) and len(name)>len(suffix)+1:
                if suffix=='游船' and not name[:-len(suffix)].endswith('号'):continue
                result.setdefault(name[:-len(suffix)],set()).add(name)
        match=re.fullmatch(r'(.+?)[(（][^()（）]*校区[)）]',name)
        if match:result.setdefault(match[1],set()).add(name)
    return result

def resolve_name(value,field,catalog):
    mapping=aliases(catalog[field]);options=mapping.get(value)
    if options is None:
        normalized=re.sub(r'\s+','',value).casefold()
        options={name for alias,names in mapping.items() if re.sub(r'\s+','',alias).casefold()==normalized for name in names}
    if options:
        if len(options)==1:return set(options),False
        # Multiple campuses of an explicitly named university are alternatives.
        if all(re.fullmatch(re.escape(value)+r'[(（][^()（）]*校区[)）]',n) for n in options):
            return set(options),True
    candidates=sorted(options or {n for n in catalog[field] if value in n})
    if not candidates:candidates=difflib.get_close_matches(value,sorted(catalog[field]),n=5,cutoff=.35)
    raise TranslationValidationError(f'Ambiguous or unresolved {field} {value!r}; canonical candidates: {candidates[:5]}; do not select arbitrarily')

def positive(text,start,modality='hard'):
    return source_modality(text,text[start:start+1],start)[0]==modality


SOFT_WORDS = re.compile(r'最好|尽量|尽可能|优先|主要|如果有时间|如果方便|喜欢|\bprefer(?:red|ably|ence)?\b|\bmainly\b|\bprimarily\b|as much as possible|if possible',re.I)
NEGATIVE_WORDS = re.compile(r'不去|不坐|不用|不乘|不要|不想|无需|不需要|\bavoid\b|\bdo not\b|\bmust not\b',re.I)
HARD_WORDS = re.compile(r'必须|只能|务必|一定要|\bmust\b|\brequire(?:d)?\b|\bonly\b',re.I)


def verbatim_source(text, source):
    if not isinstance(source,str) or not source.strip():
        raise TranslationValidationError('Evidence must be a verbatim source quote')
    if source in text:
        return source
    pattern=r'\s*'.join(re.escape(part) for part in source.split())
    match=re.search(pattern,text,re.I)
    if match is None:
        raise TranslationValidationError('Evidence must be a verbatim source quote; only whitespace/case formatting can be normalized')
    return match[0]


def source_context(text, source, start=None):
    """Recover the clause so a short evidence quote cannot hide a modifier."""
    if not isinstance(source,str) or not source or source not in text:
        raise TranslationValidationError('Evidence must be a verbatim source quote')
    start=text.index(source) if start is None else start
    before=re.split(r'[，,。;；\n]|\.(?=\s|$)',text[:start])[-1]
    after=re.split(r'[，,。;；\n]|\.(?=\s|$)',text[start+len(source):])[0]
    return before+source+after


def source_modality(text, source, start=None):
    if not isinstance(source,str) or not source or source not in text:
        raise TranslationValidationError('Evidence must be a verbatim source quote')
    positions=[start] if start is not None else [m.start() for m in re.finditer(re.escape(source),text)]
    results=[]
    for position in positions:
        context=source_context(text,source,position)
        prefix=re.split(r'[，,。;；\n]|\.(?=\s|$)',text[:position])[-1]+source
        suffix=context[len(prefix):]
        suffix=re.split(r'\band\b|\bbut\b|并且|但是|而且|且',suffix,flags=re.I)[0]
        modifiers=[(m.start(),'soft') for m in SOFT_WORDS.finditer(prefix)]
        modifiers += [(m.start(),'hard') for m in HARD_WORDS.finditer(prefix)]
        modifiers += [(m.start(),'negative') for m in NEGATIVE_WORDS.finditer(prefix)]
        modality=max(modifiers,default=(-1,'hard'),key=lambda item:(item[0],item[1]=='negative'))[1]
        if SOFT_WORDS.search(suffix):
            modality='soft'
        results.append((modality,context))
    return next((result for result in results if result[0]=='hard'),results[0])


def room_number(value):
    if value.isdigit():
        return int(value)
    digits={'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
    if '十' in value:
        tens,ones=value.split('十',1)
        return digits.get(tens,1)*10+digits.get(ones,0)
    return digits.get(value)


def preference_coverage(query,catalog):
    return coverage(query,catalog,modality='soft')

def coverage(query,catalog,modality='hard'):
    text=query['nature_language'];entries=[];occupied=[]
    def add(code,source,field,values=None,any_of=False):
        if not any(e['code']==code for e in entries):
            entries.append(dict(code=code,source=source,field=field,values=sorted(values) if values else None,any_of=any_of))
    for field in ('attraction_names','restaurant_names','hotel_names'):
        mapping=aliases(catalog[field]);mentions=[]
        for alias,options in mapping.items():
            if len(alias)<2:continue
            for match in re.finditer(re.escape(alias),text):
                if positive(text,match.start(),modality):mentions.append((match.start(),match.end(),alias))
        selected=[]
        for start,end,alias in sorted(mentions,key=lambda x:-(x[1]-x[0])):
            if any(start<e and end>s for s,e,_ in selected):continue
            selected.append((start,end,alias))
        for start,end,alias in sorted(selected):
            try:values,any_of=resolve_name(alias,field,catalog)
            except TranslationValidationError as exc:
                entries.append(dict(code=None,source=alias,field=field,values=None,any_of=False,pending=str(exc)))
                occupied.append((start,end));continue
            add(set_code(field,values,any_of),alias,field,values,any_of);occupied.append((start,end))
    masked=list(text)
    for start,end in occupied:masked[start:end]=' '* (end-start)
    remaining=''.join(masked)
    used=[]
    for alias,canonical in sorted(CATEGORY_ALIASES.items(),key=lambda x:-len(x[0])):
        for match in re.finditer(re.escape(alias),remaining):
            if any(match.start()<e and match.end()>s for s,e in used):continue
            if positive(text,match.start(),modality) and canonical in catalog['spot_type']:
                add(set_code('spot_type',{canonical}),alias,'spot_type',{canonical});used.append(match.span())
    for cuisine in sorted(catalog['food_type'],key=lambda v:-len(v)):
        if len(cuisine)>1:
            match=re.search(re.escape(cuisine),remaining)
            if match and positive(text,match.start(),modality):add(set_code('food_type',{cuisine}),cuisine,'food_type',{cuisine})
    for feature in sorted(catalog['hotel_feature'],key=lambda value:-len(value)):
        for match in re.finditer(re.escape(feature),text,re.I):
            if positive(text,match.start(),modality):
                add(set_code('hotel_feature',{feature}),match[0],'hotel_feature',{feature})
    budget=re.search(r'(?:预算(?:在|为|是|约|大概|大约)?|budget\s*(?:of|is)?\s*)\s*(\d+(?:\.\d+)?)\s*([万千]?)',text,re.I)
    if budget and positive(text,budget.start(),modality):
        amount=float(budget[1])*{'':1,'万':10000,'千':1000}[budget[2]]
        if amount.is_integer():amount=int(amount)
        add('cost<='+repr(amount),budget[0],'cost')
    for match in re.finditer(r'(\d+|[一二两三四五六七八九十]+)\s*间(?=\s*(?:单床房|双床房|大床房|客房|房间|房|单人房|双人间|酒店|有[^，。;；\n]{0,20}酒店))',text):
        if positive(text,match.start(),modality):
            number=room_number(match[1])
            if number:
                prefix=text[max(0,match.start()-5):match.start()]
                operator='>=' if re.search(r'至少|不少于',prefix) else '<=' if re.search(r'至多|不超过',prefix) else '=='
                add('rooms'+operator+str(number),match[0],'rooms')
    for match in re.finditer(r'\b(one|two|three|four|five|\d+)\s+(?:(?:single|twin|double|king|queen)[ -]?(?:bed)?\s+)?rooms?\b',text,re.I):
        if positive(text,match.start(),modality):
            number=int(match[1]) if match[1].isdigit() else {'one':1,'two':2,'three':3,'four':4,'five':5}[match[1].lower()]
            add('rooms=='+str(number),match[0],'rooms')
    for pattern,beds in [(r'单床|大床|\b(?:single|double|king|queen)[ -]bed(?:ded)?\b',1),
                         (r'双床|\btwin(?:[ -]bed(?:ded)?)?\b|\btwo beds\b',2)]:
        for match in re.finditer(pattern,text,re.I):
            if positive(text,match.start(),modality):
                add('room_type=='+str(beds),match[0],'room_type')
    for pattern,field,mode in [(r'火车|高铁|动车|\btrain\b','intercity_transport','train'),
                               (r'飞机|航班|\bflight\b','intercity_transport','airplane'),
                               (r'地铁|\bmetro\b|\bsubway\b','transport_type','metro')]:
        for match in re.finditer(pattern,text,re.I):
            if positive(text,match.start(),modality):
                operator='==' if field=='intercity_transport' else '<='
                add(field+operator+literal({mode}),match[0],field,{mode})
    prefix=re.search(r'高铁\s*[(（]?\s*(G)(?![A-Za-z])|(?<![A-Za-z])(G)\s*(?:字头|字首)',text,re.I)
    if prefix and positive(text,prefix.start(),modality):add("train_type=={'G'}",prefix[0],'train_type',{'G'})
    deadline=re.search(r'(?:不超过|不晚于|最晚|\bby\s+|\bbefore\s+)\s*(\d{1,2})(?:[:：](\d{2})|点(?:钟)?)',text,re.I)
    if deadline and positive(text,deadline.start(),modality) and re.search(r'返|回来|上火车|上车|return',text,re.I):
        hour=int(deadline[1]);minute=int(deadline[2] or 0)
        if hour>23 or minute>59:raise TranslationValidationError('Invalid explicit return deadline')
        add("return_start_time<="+repr(f'{hour:02d}:{minute:02d}'),deadline[0],'return_start_time')
    for field in ('rooms','room_type'):
        equalities=[e['code'] for e in entries if e['field']==field and comparison(e['code']) and isinstance(comparison(e['code'])[1],ast.Eq)]
        if len(set(equalities))>1:
            raise TranslationValidationError('Multiple room configurations cannot be represented by a single global '+field+' constraint; preserve the original request for clarification')
    return entries

def facts_in(code):
    fact=comparison(code)
    if fact:return [fact]
    try:tree=ast.parse(code,mode='eval').body
    except SyntaxError:return []
    if isinstance(tree,ast.BoolOp) and isinstance(tree.op,ast.Or):
        facts=[comparison(ast.unparse(node)) for node in tree.values]
        if all(facts):return facts
    return []

def ast_key(code):
    try:return ast.dump(ast.parse(code,mode='eval'))
    except (SyntaxError,TypeError):return None

class ExtractionState:
    def __init__(self,query):
        self.query=deepcopy(query);self.catalog=_catalog(query['target_city'])
        self.checklist=coverage(query,self.catalog);self.locked={};self.errors=[]
        self.preference_checklist=preference_coverage(query,self.catalog)
        self.preferences={}
        self.derived={}
        for field,value in [('days',query.get('days')),('people_number',query.get('people_number')),
                            ('tickets',query.get('people_number')),
                            ('taxi_cars',(query['people_number']+3)//4 if query.get('people_number') else None)]:
            if value is not None:self.derived[field]=value
        for field,value in self.derived.items():
            code=field+'=='+str(value)
            self.locked[code]=dict(constraint=code,source='input metadata / passenger-count derivation',derived=True)

    def instructions(self):
        return ('\nSource coverage checklist (all explicit items must remain; alternatives use OR):\n'
                +json.dumps(self.checklist,ensure_ascii=False)
                +'\nAlready validated constraints (locked; do not remove or alter):\n'
                +json.dumps(list(self.locked),ensure_ascii=False)
                +'\nEvidence for those validated constraints:\n'
                +json.dumps(list(self.locked.values()),ensure_ascii=False)
                +'\nPreferences to preserve separately in soft_logic, never in hard_logic:\n'
                +json.dumps(self.preference_checklist,ensure_ascii=False)
                +'\nReturn hard_logic and soft_logic as arrays of STRINGS, never arrays of evidence objects. Put constraint/source objects only in hard_logic_evidence or soft_logic_evidence. Return missing/incorrect items only, or all items. No invented requirements.\n')

    def normalize(self,code,source):
        fact=comparison(code)
        if not fact:return [(code,source)]
        field,op,value,shape=fact
        if field in self.derived:
            if not isinstance(op,ast.Eq) or value!=self.derived[field]:
                raise TranslationValidationError(f'{field} must match authoritative input {self.derived[field]}')
            return [(field+'=='+str(value),None)]
        if shape=='set' and field in ('attraction_names','restaurant_names','hotel_names','spot_type','food_type','hotel_feature') and isinstance(value,set):
            result=[]
            for item in sorted(value):
                if field.endswith('_names'):
                    family=next((e for e in self.checklist if e['field']==field and e['any_of'] and (item==e['source'] or item in e['values'])),None)
                    values,any_of=(set(family['values']),True) if family else resolve_name(item,field,self.catalog)
                else:values={CATEGORY_ALIASES.get(item,item) if field=='spot_type' else item};any_of=False
                canonical=set_code(field,values,any_of)
                entry=next((e for e in self.checklist if e['code']==canonical),None)
                result.append((canonical,source if source is not None else entry['source'] if entry else source))
            return result
        entry=next((e for e in self.checklist if ast_key(e['code'])==ast_key(code) and ast_key(code)),None)
        return [(entry['code'],source if source is not None else entry['source'])] if entry else [(code,source)]

    def covered(self,entry):
        if entry['code'] is None:return False
        if entry['any_of']:
            return any(len(facts_in(c))>1 and all(f[0]==entry['field'] for f in facts_in(c))
                       and set(entry['values'])<={v for f in facts_in(c) for v in f[2]} for c in self.locked)
        expected=comparison(entry['code'])
        for code in self.locked:
            actual=comparison(code)
            if not actual:continue
            if expected[0]!=actual[0] or type(expected[1])!=type(actual[1]) or expected[3]!=actual[3]:continue
            if isinstance(expected[2],set) and isinstance(actual[2],set):
                if expected[2]<=actual[2]:return True
            elif expected[2]==actual[2]:return True
        return False

    def accept(self,parsed):
        if not isinstance(parsed,dict) or not isinstance(parsed.get('hard_logic'),list):
            raise TranslationValidationError('Expected extraction JSON object with hard_logic list')
        quotes={e.get('constraint'):e.get('source') for e in parsed.get('hard_logic_evidence',[]) if isinstance(e,dict)}
        errors=[]
        for code in parsed['hard_logic']:
            try:
                if not isinstance(code,str) or not code.strip():raise TranslationValidationError('Constraint must be a nonempty string')
                for normalized,source in self.normalize(code,quotes.get(code)):
                    if normalized in self.locked:continue
                    # Recognize an explicitly supplied OR form from the checklist.
                    entry=next((e for e in self.checklist if ast_key(e['code'])==ast_key(normalized) and ast_key(normalized)),None)
                    source=source if source is not None else entry['source'] if entry else source
                    if source is not None:
                        source=verbatim_source(self.query['nature_language'],source)
                    evidence=dict(constraint=normalized,source=source)
                    fact=comparison(normalized)
                    if fact and fact[0] in ('cost','rooms','room_type','hotel_price','food_price'):
                        references=[comparison(e['code']) for e in self.checklist if e['field']==fact[0]]
                        if references and not any(type(reference[1])==type(fact[1]) and reference[2]==fact[2] for reference in references):
                            raise TranslationValidationError(f'{normalized}: conflicts with the explicit source value/operator for {fact[0]}')
                    if source is not None:
                        modality,context=source_modality(self.query['nature_language'],source)
                        if modality!='hard':
                            raise TranslationValidationError(f'{normalized}: {context!r} is {modality}; preferences belong in soft_logic and negative requirements must not become positive constraints')
                    if entry and entry['any_of']:
                        # Every option came from the same explicit DB campus family.
                        self.locked[normalized]=evidence
                    else:
                        _validate_extraction_items(self.query,dict(hard_logic=[normalized],hard_logic_evidence=[evidence]))
                        self.locked[normalized]=evidence
            except (ValueError,TypeError,KeyError) as exc:errors.append(f'{code}: {exc}')
        soft_codes=parsed.get('soft_logic',[])
        soft_quotes={e.get('constraint'):e.get('source') for e in parsed.get('soft_logic_evidence',[]) if isinstance(e,dict)}
        if not isinstance(soft_codes,list):
            errors.append('soft_logic must be a list of constraint strings')
            soft_codes=[]
        for code in soft_codes:
            try:
                source=soft_quotes.get(code)
                for normalized,source in self.normalize(code,source):
                    source=verbatim_source(self.query['nature_language'],source)
                    modality,context=source_modality(self.query['nature_language'],source)
                    if modality!='soft':
                        raise TranslationValidationError('Only explicit preferences may enter soft_logic')
                    _validate_extraction_items(self.query,dict(hard_logic=[normalized],hard_logic_evidence=[dict(constraint=normalized,source=source)]))
                    self.preferences[normalized]=dict(constraint=normalized,source=context)
            except (ValueError,TypeError,KeyError) as exc:
                errors.append(f'Soft requirement {code}: {exc}')
        missing=[e for e in self.checklist if not self.covered(e)]
        if missing:errors.append('Missing explicit requirements: '+json.dumps(missing,ensure_ascii=False))
        missing_preferences=[e for e in self.preference_checklist if not any(ast_key(e['code'])==ast_key(code) for code in self.preferences)]
        if missing_preferences:
            errors.append('Missing preferences in soft_logic: '+json.dumps(missing_preferences,ensure_ascii=False))
        self.errors=errors
        if errors:raise TranslationValidationError('\n'.join(errors))
        result=dict(parsed);result['hard_logic']=list(self.locked)
        result['hard_logic_evidence']=list(self.locked.values());result['source_coverage']=self.checklist
        result['soft_logic']=list(self.preferences)
        result['soft_logic_evidence']=list(self.preferences.values())
        return result

def grounded_extraction(query,parsed):
    try:return ExtractionState(query).accept(parsed)
    except TranslationValidationError as exc:
        raise TranslationValidationError('Translation extraction validation: '+str(exc)) from exc

def extract_with_repair(query,llm,prompt):
    state=ExtractionState(query)
    error=None
    for attempt in range(3):
        content=prompt+state.instructions()
        if error:content+='\nRepair only the following errors/missing items; validated constraints remain locked:\n'+str(error)
        response=llm([{'role':'user','content':content}],one_line=False,json_mode=True,**extraction_output_options(llm))
        try:
            parsed=json.loads(response)
            if not isinstance(parsed,dict):raise TranslationValidationError('Extraction must be a JSON object')
            for key in ('uid','days','people_number','start_city','target_city'):
                if key in query and key in parsed and query[key]!=parsed[key]:
                    raise TranslationValidationError('Extraction changed input field '+key)
            result=state.accept(parsed)
            # Preserve the input and only update translation-owned fields.
            for key in ('hard_logic','hard_logic_evidence','source_coverage','soft_logic','soft_logic_evidence'):query[key]=result[key]
            query['extraction_repair_count']=attempt
            return query
        except (ValueError,TypeError,KeyError) as exc:error=exc
    raise TranslationValidationError('Translation stage 1 failed after 3 attempts: '+str(error))
