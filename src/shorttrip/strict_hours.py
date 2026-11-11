"""Conservative opening-window primitives; not yet a planner adapter.

The input is explicitly structured evidence, not free-form business text. Each
window is anchored to a weekday (Monday=0), with an end day offset of 0 or 1.
Missing schedules and unsupported input must remain unknown to the caller.
"""
from datetime import date, datetime, time, timedelta


def _clock(value, allow_24=False):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        raise ValueError('expected HH:MM')
    if not (value[:2].isdigit() and value[3:].isdigit()):
        raise ValueError('expected HH:MM')
    h, m = int(value[:2]), int(value[3:])
    if allow_24 and (h, m) == (24, 0):
        return 1440
    if h > 23 or m > 59:
        raise ValueError('invalid clock')
    return h * 60 + m


def check_interval(windows, start, end, *, schedule_complete=False):
    """Return open, closed, or unknown for the entire activity interval.

    None means no evidence; [] means closed only when schedule_complete is true.
    A window has
    weekday, open, close, end_day_offset and optional last_admission. Timezone
    aware and naive datetimes must not be mixed by the caller. Invalid or
    unrecognized schedule data is unknown, never silently treated as closed.
    Continuous adjacent windows may jointly cover an activity. If joining
    windows would require composing last-admission cutoffs, the result is
    unknown. This primitive has no effective-date range input; callers must
    independently establish that the schedule applies to the requested date.
    Intervals spanning over 14 calendar days are outside this short-activity
    primitive and remain unknown.
    """
    if not isinstance(start, datetime) or not isinstance(end, datetime) or start.tzinfo != end.tzinfo or end <= start:
        raise ValueError('invalid activity interval')
    if type(schedule_complete) is not bool:
        return 'unknown'
    if windows is None:
        return 'unknown'
    if not isinstance(windows, list):
        return 'unknown'
    parsed = []
    try:
        for w in windows:
            if not isinstance(w, dict) or set(w) - {'weekday', 'open', 'close', 'end_day_offset', 'last_admission'}:
                raise ValueError('unsupported schedule')
            day, offset = w['weekday'], w['end_day_offset']
            if type(day) is not int or day not in range(7) or type(offset) is not int or offset not in (0, 1):
                raise ValueError('invalid weekday or offset')
            a, b = _clock(w['open']), _clock(w['close'], True) + offset * 1440
            if b <= a or b > a + 1440:
                raise ValueError('invalid window')
            last = w.get('last_admission')
            last = _clock(last) if last is not None else None
            if last is not None and last < a:
                last += 1440
            if last is not None and not a <= last <= b:
                raise ValueError('invalid admission')
            parsed.append((day, a, b, last))
    except (KeyError, ValueError, TypeError):
        return 'unknown'

    # Materialize relevant weekday windows so adjacent entries such as
    # 09:00-12:00 and 12:00-17:00 can jointly cover an interval. A bounded
    # span prevents hostile datetime inputs from causing an unbounded loop;
    # dates outside this short-activity domain remain unknown.
    try:
        first_anchor = start.date() - timedelta(days=1)
        span_days = (end.date() - first_anchor).days
        if span_days < 0 or span_days > 14:
            return 'unknown'
    except (OverflowError, ValueError):
        return 'unknown'
    intervals = []
    for offset_day in range(span_days + 1):
        try:
            anchor = first_anchor + timedelta(days=offset_day)
            midnight = datetime.combine(anchor, time.min, tzinfo=start.tzinfo)
            for day, a, b, last in parsed:
                if anchor.weekday() != day:
                    continue
                opens = midnight + timedelta(minutes=a)
                closes = midnight + timedelta(minutes=b)
                admission = midnight + timedelta(minutes=last) if last is not None else None
                intervals.append((opens, closes, admission))
        except (OverflowError, ValueError):
            return 'unknown'

    # Preserve the unambiguous single-window last-admission rule: admission
    # cutoff constrains entry time. Do not infer how such a cutoff composes
    # across adjacent windows.
    ordered = sorted(intervals, key=lambda value: (value[0], value[1]))

    def has_continuous_cover(candidates):
        starts = [(opens, closes) for opens, closes, _ in candidates
                  if opens <= start <= closes]
        if not starts:
            return False
        covered_until = max(closes for _, closes in starts)
        while covered_until < end:
            extensions = [(opens, closes) for opens, closes, _ in candidates
                          if opens <= covered_until < closes]
            if not extensions:
                return False
            next_until = max(closes for _, closes in extensions)
            if next_until <= covered_until:
                return False
            covered_until = next_until
        return True

    # Conflicting cutoff assertions are themselves unresolved. Do this before
    # accepting any alternative route through the schedule, including a
    # no-cutoff chain.
    complete_windows = [(opens, closes, admission) for opens, closes, admission in intervals
                        if opens <= start and end <= closes]
    cutoff_decisions = [start <= admission for _, _, admission in complete_windows
                        if admission is not None]
    if any(cutoff_decisions) and not all(cutoff_decisions):
        return 'unknown'
    rejecting_active_cutoff = any(
        admission is not None and opens <= start < closes and start > admission
        for opens, closes, admission in ordered)

    # An omitted cutoff is not evidence that entry is unrestricted when an
    # overlapping full-span window explicitly rejects entry. Without a scope
    # distinguishing those windows, their combined meaning remains unknown.
    no_cutoff = [item for item in ordered if item[2] is None]
    if has_continuous_cover(no_cutoff):
        return 'unknown' if rejecting_active_cutoff else 'open'

    # Inspect every single window that fully covers the activity. Conflicting
    # cutoff decisions cannot be resolved by taking the permissive one. A
    # no-cutoff path does not override a conflicting explicit cutoff.
    if cutoff_decisions:
        if all(cutoff_decisions):
            return 'unknown' if rejecting_active_cutoff else 'open'
        # All complete cutoff-bearing windows reject this entry. A separate
        # adjacent path may still cover the activity, but composing its own
        # admission cutoffs is not defined. Exclude the rejecting full-span
        # windows first and keep any remaining complete path unknown.
        rejected_full_windows = [item for item in complete_windows
                                 if item[2] is not None and start > item[2]]
        alternate_windows = [item for item in ordered if item not in rejected_full_windows]
        if has_continuous_cover(alternate_windows):
            return 'unknown'
        # Preserve the complete-schedule closed result only when no alternate
        # cutoff-bearing continuous path remains.
        return 'closed' if schedule_complete else 'unknown'

    if has_continuous_cover(ordered):
        # Reaching this branch means a cutoff-bearing window is needed to
        # compose the full coverage; its semantics across windows are unknown.
        return 'unknown'
    return 'closed' if schedule_complete else 'unknown'
