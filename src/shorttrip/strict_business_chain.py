"""Check an explicitly requested ordered chain against verified plan events."""
import copy
from .strict_snapshot import strict_snapshot_equal
from .strict_scope import identifier_is_known


def check_business_chain(chain, events, *, inventory_verifier=None, event_verifier=None):
    """Prove a selected entity/kind subsequence only within a complete event list.

    The inventory verifier must independently attest complete ordered plan
    coverage; the event verifier must verify every event's identity, kind and
    order. Catalog labels and self-asserted flags are not evidence.
    """
    def result(state,reason):
        return {'state':state,'reason':reason,'execution_confirmed':False}
    if not isinstance(chain,list) or not chain or not isinstance(events,list):
        return result('unknown','chain_or_plan_events_missing')
    if any(not isinstance(x,dict) or not identifier_is_known(x.get('kind')) or
           not identifier_is_known(x.get('entity_id')) for x in chain):
        return result('unknown','chain_identity_invalid')
    if len({x['entity_id'] for x in chain}) != len(chain):
        return result('unknown','chain_entity_duplicate')
    if any(not isinstance(x,dict) or not identifier_is_known(x.get('kind')) or
           not identifier_is_known(x.get('entity_id')) for x in events):
        return result('unknown','plan_event_identity_invalid')
    try:
        chain_snapshot, events_snapshot = copy.deepcopy(chain), copy.deepcopy(events)
        verifier_chain, verifier_events=copy.deepcopy(chain_snapshot),copy.deepcopy(events_snapshot)
        inventory_ok=(callable(inventory_verifier) and inventory_verifier(verifier_chain,verifier_events) is True
                      and strict_snapshot_equal(verifier_chain, chain_snapshot)
                      and strict_snapshot_equal(verifier_events, events_snapshot)
                      and strict_snapshot_equal(chain, chain_snapshot)
                      and strict_snapshot_equal(events, events_snapshot))
        events_ok=callable(event_verifier)
        for event in events_snapshot:
            candidate=copy.deepcopy(event)
            if (not callable(event_verifier) or event_verifier(candidate) is not True
                    or not strict_snapshot_equal(candidate, event)
                    or not strict_snapshot_equal(chain, chain_snapshot)
                    or not strict_snapshot_equal(events, events_snapshot)):
                events_ok=False
                break
    except Exception:
        inventory_ok=events_ok=False
    if not inventory_ok or not events_ok:
        return result('unknown','independent_plan_inventory_or_event_verifier_required')
    pos=0
    for item in events_snapshot:
        if pos < len(chain_snapshot) and item['entity_id']==chain_snapshot[pos]['entity_id'] and item['kind']==chain_snapshot[pos]['kind']:
            pos += 1
    return result('pass' if pos == len(chain_snapshot) else 'fail',
                  'verified_ordered_chain' if pos == len(chain_snapshot) else 'verified_chain_not_in_plan_order')
