"""Deep, unique, bounded candidate storage with stable minimum selection."""
import hashlib
import json
from chinatravel.data.load_datasets import NpEncoder

PLAN_FIELDS = ('people_number', 'start_city', 'target_city', 'itinerary')


def snapshot(plan):
    return json.loads(json.dumps({k: plan[k] for k in PLAN_FIELDS}, ensure_ascii=False, cls=NpEncoder))


def fingerprint(plan):
    text = json.dumps(snapshot(plan), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class CandidatePool:
    def __init__(self, limit=20, scorer=None):
        if not isinstance(limit, int) or limit < 1:
            raise ValueError('candidate limit must be a positive integer')
        self.limit, self.scorer = limit, scorer
        self.items, self.seen = [], set()
        self.duplicate_count = 0

    @property
    def full(self):
        return len(self.items) >= self.limit

    def add(self, plan):
        if self.full:
            return False
        frozen = snapshot(plan)
        key = fingerprint(frozen)
        if key in self.seen:
            self.duplicate_count += 1
            return False
        score = self.scorer(frozen)
        self.seen.add(key)
        self.items.append({'ordinal': len(self.items) + 1, 'fingerprint': key,
                           'plan': frozen, 'score': score})
        return True

    def best(self):
        return min(self.items, key=lambda c: (c['score']['total_penalty'], c['ordinal'])) if self.items else None
