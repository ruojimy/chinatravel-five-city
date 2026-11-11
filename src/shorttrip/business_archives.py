"""Conservative parsing of dated reference fields; no defaults or age renewal."""
import ast,re,unicodedata

def normalize_name(value):
    text=unicodedata.normalize('NFKC',value or '')
    return ''.join(x.casefold() for x in text if x.isalnum())

def name_aliases(value):
    """Full label and a Chinese title followed by an explicit Latin suffix."""
    aliases={normalize_name(value)}
    match=re.fullmatch(r'([^A-Za-z]+)([A-Za-z].*)',value or '')
    if match and any('\u4e00'<=c<='\u9fff' for c in match.group(1)):
        aliases.add(normalize_name(match.group(1)))
    return aliases-{''}

def parse_duration(text):
    clean=re.sub(r'^建议游览时间[：:]\s*','',(text or '').strip())
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*小时\s*[-—~至]\s*(\d+(?:\.\d+)?)\s*小时',clean)
    if match:
        low,high=map(float,match.groups())
        if 0<low<=high<=24:return {'recommendmintime':low,'recommendmaxtime':high},[]
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*小时',clean)
    if match and 0<float(match[1])<=24:
        number=float(match[1]);return {'recommendmintime':number,'recommendmaxtime':number},['single_source_recommendation_not_measured_duration']
    return {},['duration_unknown_or_complex']

def parse_hours(text):
    clean=(text or '').strip()
    # A native HH:MM pair cannot represent seasonal, weekly, split or last-entry rules.
    match=re.fullmatch(r'(?:全年\s*)?(\d{1,2}):([0-5]\d)\s*[-—~至]{1,2}\s*(\d{1,2}):([0-5]\d)',clean)
    if match:
        a,b,c,d=map(int,match.groups())
        if 0<=a<24 and 0<=c<24 and (a,b)!=(c,d):
            return {'opentime':f'{a:02}:{b:02}','endtime':f'{c:02}:{d:02}'},[]
    return {},['hours_unknown_or_complex_keep_raw_rule']

def parse_ticket(text):
    clean=(text or '').strip();options=[];flags=[];native={}
    if clean in ('免费','免费开放','门票免费','免门票'):
        return {'price':0.0},[{'label':clean,'amount':0.0,'currency':'CNY','scope':'explicit_free_entry','lower_bound':False}],[]
    simple=re.fullmatch(r'(?:(?:门票|成人票|成人门票)[：:]?\s*)?[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*元(?:/人)?',clean)
    if simple:
        amount=float(simple[1]);return {'price':amount},[{'label':clean,'amount':amount,'currency':'CNY','scope':'unqualified_entry_reference','lower_bound':False}],['historical_price_not_current_quote']
    try:obj=ast.literal_eval(clean) if clean.startswith('{') else None
    except (ValueError,SyntaxError):obj=None
    if isinstance(obj,dict):
        for label,values in obj.items():
            if not isinstance(label,str):continue
            for raw in values if isinstance(values,list) else [values]:
                if not isinstance(raw,str):continue
                match=re.fullmatch(r'\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(元)?\s*(起)?\s*',raw)
                if match:
                    options.append({'label':label.strip(),'amount':float(match[1]),'currency':'CNY',
                        'scope':'source_product_option','lower_bound':bool(match[3]),'raw_price':raw})
        flags.append('ticket_product_scope_requires_review_no_native_projection')
    else:flags.append('ticket_unknown_or_complex')
    return native,options,flags

def parse_reference(row):
    native={};issues=[]
    for parser,key in ((parse_hours,'开放时间'),(parse_duration,'建议游玩时间')):
        values,flags=parser(row.get(key));native.update(values);issues+=flags
    values,options,flags=parse_ticket(row.get('门票'));native.update(values);issues+=flags
    return {'native_values':native,'ticket_options':options,'uncertainty_flags':issues,
        'complete_operational_fields':all(k in native for k in ('price','opentime','endtime','recommendmintime','recommendmaxtime')),
        'current_freshness_certified':False}
