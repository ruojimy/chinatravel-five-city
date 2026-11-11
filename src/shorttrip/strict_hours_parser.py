"""Parse a narrowly specified schedule notation without certifying evidence.

This parser requires an explicitly supplied weekday scope; it does not infer
daily opening, holiday exceptions, validity dates, or source authority.
"""
import re

_INTERVAL = re.compile(r'^([0-2]\d:[0-5]\d)\s*[-~至]\s*([0-2]\d:[0-5]\d)$')


def _clock(value, *, end=False):
    hour, minute = (int(x) for x in value.split(':'))
    if hour == 24 and minute == 0 and end:
        return 1440
    if hour > 23:
        raise ValueError('invalid clock')
    return hour * 60 + minute


def parse_explicit_intervals(text, *, weekdays):
    """Return proposed structured windows only when every fragment is parsed.

    Caller must independently establish that the text and weekday scope apply
    to the entity and date, and separately assess schedule completeness.
    Overnight windows are anchored to their opening weekday.
    """
    result = {'windows': None, 'parse_status': 'unsupported',
              'schedule_complete': False, 'evidence_qualified': False}
    if (not isinstance(text, str) or not text.strip() or not isinstance(weekdays, list)
        or not weekdays or any(type(x) is not int or x not in range(7) for x in weekdays)
        or len(set(weekdays)) != len(weekdays)):
        return result
    parts = re.split(r'[;；、]', text.strip())
    windows = []
    for part in parts:
        match = _INTERVAL.fullmatch(part.strip())
        if not match:
            return result
        start, end = match.groups()
        try:
            a, b = _clock(start), _clock(end, end=True)
        except ValueError:
            return result
        if a == b:
            return result  # 00:00-00:00 is ambiguous, not automatic 24 hours.
        offset = 1 if b < a else 0
        for weekday in weekdays:
            windows.append({'weekday': weekday, 'open': start, 'close': end,
                            'end_day_offset': offset})
    return {'windows': windows, 'parse_status': 'parsed_explicit_intervals',
            'schedule_complete': False, 'evidence_qualified': False}
