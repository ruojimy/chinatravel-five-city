"""Save the original DFS with the documented experimental integration hooks."""
import ast
import difflib
from pathlib import Path
import textwrap

ROOT=Path(__file__).resolve().parent
PROJECT=Path(__file__).resolve().parents[2]
source=(PROJECT/'chinatravel/agent/nesy_agent/nesy_agent.py').read_text(encoding='utf-8')
node=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='NesyAgent')
method=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='dfs_poi')
original=textwrap.dedent('\n'.join(source.splitlines()[method.lineno-1:method.end_lineno]))+'\n'
updated=original
def replace(old,new,count=1):
    global updated
    assert updated.count(old)==count,(old,updated.count(old))
    updated=updated.replace(old,new)
replace('new_time = poi_plan["go_transport"]["EndTime"]','current_day, new_time = self.outbound_next(poi_plan["go_transport"])')
replace('if current_time == "00:00":','if False:  # Experimental breakfast is a searchable meal, not unconditional.')
replace('candidates_type = ["attraction"]','candidates_type = ["attraction"]\n        if not any(a["type"] == "breakfast" for a in plan[current_day]["activities"]):\n            candidates_type.append("breakfast")')
replace('elif poi_type in ["lunch", "dinner", "attraction"]:','elif poi_type in ["breakfast", "lunch", "dinner", "attraction"]:')
replace('if poi_type in ["lunch", "dinner"]:','if poi_type in ["breakfast", "lunch", "dinner"]:')
replace('elif poi_type == "hotel":','elif poi_type == "hotel":\n\n            if not self.close_day_allowed(plan, poi_plan, current_day):\n                candidates_type.remove("hotel")\n                continue')
replace('elif self.query["days"] > 1:','elif self.query["days"] > 1 and self.close_day_allowed(plan, poi_plan, current_day):')
replace('                            poi_time = self.select_poi_time(','                            if not self.allow_wait(arrived_time, act_start_time):\n                                continue\n\n                            poi_time = self.select_poi_time(')
replace('''                            if time_compare_if_earlier_equal(
                                arrived_time, opentime
                            ):
                                act_start_time = opentime
                            else:
                                act_start_time = arrived_time''','''                            preliminary_slot = self.attraction_slot(arrived_time, opentime, endtime, 1)
                            if preliminary_slot is None:
                                continue
                            act_start_time = preliminary_slot[0]''')
replace('''                            act_end_time = add_time_delta(act_start_time, poi_time)
                            if time_compare_if_earlier_equal(endtime, act_end_time):
                                act_end_time = endtime''','''                            actual_slot = self.attraction_slot(arrived_time, opentime, endtime, poi_time)
                            if actual_slot is None:
                                continue
                            act_start_time, act_end_time = actual_slot''')
replace('        print(\n            "POI planning, day {} {}, {}, next-poi type: {}".format(','        if not candidates_type:\n            return False, plan\n\n        print(\n            "POI planning, day {} {}, {}, next-poi type: {}".format(')
header='''"""Original DFS snapshot with explicit B/C meal/date/wait hooks; see dfs_changes.diff."""
from chinatravel.agent.nesy_agent.nesy_agent import *
'''
(ROOT/'dfs_snapshot.py').write_text(header+updated,encoding='utf-8')
(ROOT/'dfs_original.py.txt').write_text(original,encoding='utf-8')
(ROOT/'dfs_changes.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),updated.splitlines(True),fromfile='original DFS',tofile='experimental DFS')),encoding='utf-8')
ast.parse(header+updated)
print('DFS snapshot generated; architecture retained, changes recorded.')
