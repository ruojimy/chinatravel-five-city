"""Read-only ticket duration lookup for a common A/B/C absolute-date audit."""
from functools import lru_cache
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[2]/'chinatravel/environment/database/intercity_transport'

@lru_cache(maxsize=1)
def durations():
    found={}
    for path in (ROOT/'train').glob('*.json'):
        rows=json.loads(path.read_text(encoding='utf-8-sig'))
        for row in rows:
            found[(row['TrainID'],row['From'],row['To'],row['BeginTime'],row['EndTime'])]=row.get('Duration')
    with (ROOT/'airplane.jsonl').open(encoding='utf-8-sig') as file:
        for line in file:
            row=json.loads(line)
            found[(row['FlightID'],row['From'],row['To'],row['BeginTime'],row['EndTime'])]=row.get('Duration')
    return found

def lookup(activity):
    identifier=activity.get('TrainID') or activity.get('FlightID')
    if not identifier:return None
    key=(identifier,activity.get('start'),activity.get('end'),activity['start_time'],activity['end_time'])
    return durations().get(key)
