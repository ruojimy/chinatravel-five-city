"""Install the existing date-aware evaluator in the frozen twelve-city sandbox."""
import json
from pathlib import Path
import shutil
import tempfile

from g3_sandbox12_repaired import REPO
from g3_sandbox12_repaired_v16 import PROFILE as PARENT, configure as configure_parent
from g3_sandbox12_repaired_v17 import PROFILE
from g3_sandbox12_xiamen import digest

MODULES = Path('engine/chinatravel/symbol_verification')
SOURCE = REPO / 'src/sandbox_runtime/evaluator'
CHECKER = MODULES / 'commonsense_constraint.py'
SCORER = Path('runtime/evaluator/score_tristate.py')


def replace(source, before, after):
    if source.count(before) != 1:
        raise ValueError(f'Unexpected predecessor code near {before[:70]!r}')
    return source.replace(before, after, 1)


def install_timeline(stage):
    timeline = (SOURCE / 'date_timeline.py').read_text(encoding='utf-8')
    start = timeline.index('                    actual_end=absolute_start+elapsed')
    end = timeline.index('            if declared is not None:', start)
    timeline = timeline[:start] + '''                    # Compare the rounded duration to the recorded end clock
                    # and derive the integer day offset. This also handles
                    # trips over 24 hours whose end clock appears later.
                    delta = start + elapsed - end
                    offset = round(delta / 1440)
                    if offset < 0 or abs(delta - offset * 1440) > 1:
                        issue('unknown', 'source_duration_clock_conflict', day, index)
                        duration = None
                    else:
                        observed_day = day + offset
                        if declared is not None and declared != observed_day:
                            issue('fail', 'arrival_day_conflicts_with_source_duration', day, index,
                                  {'declared': declared, 'source_day': observed_day})
                        declared = observed_day
            if intercity and duration is None:
                issue('unknown', 'intercity_duration_evidence_missing', day, index)
''' + timeline[end:]
    timeline = replace(
        timeline, "                issue('fail','activity_overlaps_previous',day,index)",
        """                issue('fail','activity_overlaps_previous',day,index,
                      {'starts_at_minute':absolute_start,'previous_ends_at_minute':prior_end})""",
    )
    timeline = replace(
        timeline, "                if prior_end is not None and ls<prior_end:issue('fail','transport_overlaps_previous',day,index,leg_no)",
        """                if prior_end is not None and ls<prior_end:
                    issue('fail','transport_overlaps_previous',day,index,
                          {'leg':leg_no,'departs_at_minute':ls,'previous_ends_at_minute':prior_end})""",
    )
    timeline = replace(
        timeline, "{'requested_days':days})",
        "{'requested_days':days,'ends_on_day':int((absolute_end-1e-6)//1440)+1})",
    )
    (stage / MODULES / 'date_timeline.py').write_text(timeline, encoding='utf-8')
    source = (SOURCE / 'source_duration.py').read_text(encoding='utf-8')
    source = replace(source, 'from date_timeline import parse_amap_rail_clock',
                     'from .date_timeline import parse_amap_rail_clock')
    (stage / MODULES / 'source_duration.py').write_text(source, encoding='utf-8')

    path = stage / CHECKER
    common = path.read_text(encoding='utf-8')
    start = common.index('def Is_time_correct(')
    end = common.index('def Is_space_correct(', start)
    common = common[:start] + '''from functools import lru_cache


@lru_cache(maxsize=1)
def _duration_resolver():
    from pathlib import Path
    from chinatravel.symbol_verification.source_duration import DurationResolver

    return DurationResolver(Path(__file__).resolve().parents[2])


def Is_time_correct(symbolic_input, plan_json, verbose=False):
    from chinatravel.symbol_verification.date_timeline import validate_timeline

    result = validate_timeline(symbolic_input, plan_json, _duration_resolver())
    table = pd.DataFrame([[0, int(result['state'] == 'fail')]], columns=[
        'Invalid duration information of each activity', 'Does not follow Chronological Order',
    ])
    table.attrs['time_state'] = result['state']
    table.attrs['time_issues'] = result['issues']
    messages = result['issues']
    if verbose:
        print(messages if messages else "Time passed!")
    return table, messages


''' + common[end:]
    path.write_text(common, encoding='utf-8')

    path = stage / SCORER
    scorer = path.read_text(encoding='utf-8')
    scorer = replace(scorer, "            state = table.attrs.get('space_state') if name == 'Is_space_correct' else None",
                     """            state_attr = {'Is_space_correct': 'space_state', 'Is_time_correct': 'time_state'}.get(name)
            state = table.attrs.get(state_attr)""")
    path.write_text(scorer, encoding='utf-8')


def main():
    if PROFILE.exists():
        raise FileExistsError(PROFILE)
    parent = configure_parent()
    receipt = json.loads((PARENT / 'receipt.json').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='.timeline-repair-', dir=PROFILE.parent) as tmp:
        stage = Path(tmp) / PROFILE.name
        shutil.copytree(PARENT, stage, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        install_timeline(stage)
        inventory = {p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob('*')
                     if p.is_file() and p != stage / 'receipt.json'}
        changed = {key for key in set(inventory) | set(receipt['files'])
                   if inventory.get(key) != receipt['files'].get(key)}
        expected = {p.as_posix() for p in (CHECKER, SCORER, MODULES / 'date_timeline.py', MODULES / 'source_duration.py')}
        if changed != expected:
            raise ValueError(f'Unexpected file changes: {changed ^ expected}')
        receipt.update(parent_receipt_sha256=parent['receipt_sha256'],
                       scoring_revision='verified_intercity_arrival_day_v17', files=inventory)
        (stage / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
        stage.rename(PROFILE)
    print(f'Installed {PROFILE} ({digest(PROFILE / "receipt.json")})')


if __name__ == '__main__':
    main()
