"""Explicit IATA/city associations and display names from the frozen records."""
import re

_GROUPS = (
    (('北京', 'beijing'), ('PEK', 'PKX')),
    (('上海', 'shanghai'), ('SHA', 'PVG')),
    (('南京', 'nanjing'), ('NKG',)),
    (('杭州', 'hangzhou'), ('HGH',)),
    (('深圳', 'shenzhen'), ('SZX',)),
    (('成都', 'chengdu'), ('CTU', 'TFU')),
    (('武汉', 'wuhan'), ('WUH',)),
    (('广州', 'guangzhou'), ('CAN',)),
    (('重庆', 'chongqing'), ('CKG',)),
    (('西安', "xi'an", 'xian'), ('XIY',)),
)

def airport_matches(value, city, source_name=None):
    if not isinstance(city, str):
        return False
    wanted = city.strip().casefold()
    raw = str(value or '').strip()
    name = str(source_name or '').strip()
    aliases, codes = next(((names, cs) for names, cs in _GROUPS
                           if wanted in {x.casefold() for x in names}), ((city,), ()))
    if raw.upper() in codes:
        return True
    return any(raw.casefold().startswith(x.casefold()) or name.casefold().startswith(x.casefold())
               for x in aliases if x)

def airport_display(value, source_name=None):
    raw = str(value or '').strip()
    name = str(source_name or '').strip()
    if re.fullmatch(r'[A-Z]{3}', raw) and name and name.lower() not in {'nan', 'none'}:
        return name
    return raw
