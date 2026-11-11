"""Synthetic end-to-end integration coverage for strict_plan_diagnostics.

All records and verifiers here are test fixtures. Passing component checks do
not establish real-world truth, full-plan feasibility, or execution readiness.
"""
import unittest
from datetime import datetime, timezone, timedelta

from shorttrip.strict_plan_diagnostics import diagnose_plan


NOW = "2026-10-30T10:00:00+08:00"
ROUTE_CONTEXT = {
    "origin": "synthetic:hotel", "destination": "synthetic:attraction",
    "origin_entry": "lobby", "destination_entry": "east-gate",
    "coord_system": "GCJ02", "mode": "walking", "travel_date": "2026-10-30",
    "departure_at": "2026-10-30T10:30:00+08:00",
}


def route_evidence():
    return {"context": dict(ROUTE_CONTEXT), "duration_minutes": 20, "unit": "minutes",
            "observed_at": "2026-10-30T09:55:00+08:00",
            "valid_until": "2026-10-30T10:10:00+08:00",
            "provider_id": "synthetic-provider", "raw_response": {"duration": 20},
            "permission": "test-only"}


def candidate_payload(*, costs=(100, 200, 300), budget=1000, activity_start=None,
                      activity_end=None, windows=None):
    from tests.test_strict_v4_adapter import bind_schedule_scope
    tz = timezone(timedelta(hours=8))
    activity = {
        "start": activity_start or datetime(2026, 11, 2, 11, 30, tzinfo=tz),
        "end": activity_end or datetime(2026, 11, 2, 12, 30, tzinfo=tz),
        "windows": windows if windows is not None else [
            {"weekday": 0, "open": "09:00", "close": "10:00", "end_day_offset": 0},
            {"weekday": 0, "open": "11:00", "close": "18:00", "end_day_offset": 0},
        ],
        "schedule_complete": True,
    }
    bind_schedule_scope(activity)
    return {
        "activity": activity,
        "schedule_verifier": lambda _activity, _scope: True,
        "route_requirement": {"context": dict(ROUTE_CONTEXT)},
        "route_evidence": route_evidence(),
        "route_verifier": lambda _req, evidence: evidence.get("provider_id") == "synthetic-provider",
        "required_costs": list(costs), "budget": budget,
        "cost_verifier": lambda _costs: True,
    }


def item(kind, item_id, tag, present):
    return {"item_id": item_id, "item_kind": kind, "tag": tag, "present": present,
            "scope": {"domain": "trip", "item_kind": kind}}


def itinerary():
    return [{"date": "2026-11-02", "timeline": [
        {"type": "travel", "start": "09:00", "end": "09:30",
         "origin_id": "synthetic:hotel", "origin_entrance_id": "lobby",
         "destination_id": "synthetic:attraction", "destination_entrance_id": "east-gate"},
        {"type": "visit", "start": "09:30", "end": "10:00",
         "entity_id": "synthetic:attraction", "entrance_id": "east-gate"},
        {"type": "travel", "start": "10:00", "end": "10:30",
         "origin_id": "synthetic:attraction", "origin_entrance_id": "east-gate",
         "destination_id": "synthetic:restaurant", "destination_entrance_id": "front"},
        {"type": "lunch", "start": "10:30", "end": "11:00",
         "entity_id": "synthetic:restaurant", "entrance_id": "front"},
        {"type": "travel", "start": "11:00", "end": "11:30",
         "origin_id": "synthetic:restaurant", "origin_entrance_id": "front",
         "destination_id": "synthetic:hotel", "destination_entrance_id": "lobby"},
        {"type": "visit", "start": "11:30", "end": "12:00",
         "entity_id": "synthetic:hotel", "entrance_id": "lobby"},
    ]}]


class StrictCompleteFlowTests(unittest.TestCase):
    def test_verified_synthetic_components_pass_without_certifying_whole_plan(self):
        from tests.test_strict_intercity import inputs as intercity_inputs
        from tests.test_strict_lodging import inputs as lodging_inputs
        from tests.test_strict_business_chain import CHAIN

        record = {"id": "synthetic-record-1", "city": "X", "kind": "attraction",
                  "name": "test fixture only", "payload": {"data": {}}, "claims": []}
        lodging_requirement, lodging_claim = lodging_inputs()
        intercity_requirement, intercity_claim = intercity_inputs()
        budget_constraint = {
            "id": "trip_budget", "strength": "hard", "compiler_status": "supported",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 6000, "people": 2,
                "includes": ["rooms", "meals", "intercity", "local_transport", "tickets"]}},
        }
        exclusion = {
            "id": "no_night_activity", "strength": "hard", "compiler_status": "supported",
            "scope": {"domain": "trip", "quantifier": "all", "item_kind": "attraction"},
            "expression": {"op": "exclude_tag", "args": {"tag": "night_activity"}},
        }
        preference = {
            "id": "local_food_preference", "strength": "soft", "compiler_status": "supported",
            "scope": {"domain": "trip", "quantifier": "any", "item_kind": "restaurant"},
            "expression": {"op": "prefer_tag", "args": {"tag": "local_food"}},
        }
        budget_fact = {"value": 5400, "unit": "CNY",
                       "context": {"people": 2, "includes": ["rooms", "meals", "intercity",
                                                                      "local_transport", "tickets"]}}
        tag_facts = [item("attraction", "synthetic:attraction", "night_activity", False),
                     item("restaurant", "synthetic:restaurant", "local_food", True)]
        tag_evidence = {
            "no_night_activity": {"scope_items": ["synthetic:attraction"],
                                  "tag_facts": [tag_facts[0]]},
            "local_food_preference": {"scope_items": ["synthetic:restaurant"],
                                      "tag_facts": [tag_facts[1]]},
        }
        chain = [dict(x) for x in CHAIN]
        domain_evidence_item = {"context": dict(ROUTE_CONTEXT), "duration_minutes": 20,
            "unit": "minutes", "observed_at": "2026-10-30T09:55:00+08:00",
            "valid_until": "2026-10-30T10:10:00+08:00"}
        result = diagnose_plan(
                uid="synthetic-positive", city="X", record_requirements=[(record, [])],
            registry={}, now=NOW, identity_verifier=lambda r: r["id"] == "synthetic-record-1",
            candidate=[{"diagnostic_kind": "activity", "candidate": candidate_payload()},
                       {"diagnostic_kind": "route", "candidate": candidate_payload()},
                       {"diagnostic_kind": "budget", "candidate": candidate_payload()}],
            constraints=[budget_constraint, exclusion, preference],
            constraint_facts={"trip_budget": budget_fact},
            constraint_fact_verifier=lambda *_: True,
            tag_evidence=tag_evidence, tag_scope_verifier=lambda *_: True,
            lodging={"requirement": lodging_requirement, "claim": lodging_claim},
            lodging_verifier=lambda *_: True,
            intercity={"requirement": intercity_requirement, "claim": intercity_claim},
            intercity_verifier=lambda *_: True,
            itinerary_days=itinerary(), itinerary_interval_verifier=lambda _: True,
            itinerary_endpoint_verifier=lambda _: True,
            business_chain={"chain": chain, "events": chain},
            chain_inventory_verifier=lambda *_: True, chain_event_verifier=lambda _: True,
            finite_route_domain={"dimensions": {"route": ["synthetic-route"]},
                "candidates": [{"choices": {"route": "synthetic-route"},
                    "legs": [{"context": dict(ROUTE_CONTEXT), "max_duration_minutes": 25}]}],
                "evidence": [domain_evidence_item]},
                finite_route_evidence_verifier=lambda *_: True,
        )

        passed = result["passed_checks"]
        # The typed envelopes expose only the component field each candidate
        # represents: activity -> opening_hours, route -> route, budget -> budget.
        # Each synthetic payload contains all three inputs, but the wrapper
        # must not let those unrelated values leak into the integrated result.
        component_passes = [x["field"] for x in passed if x["field"] in
                            ("opening_hours", "route", "budget")]
        self.assertCountEqual(component_passes, ["opening_hours", "route", "budget"])
        self.assertEqual(next(x for x in passed if x["field"] == "constraint:trip_budget")["state"], "pass")
        night = next(x for x in result['unknown_checks'] if x['field'] == 'constraint:no_night_activity')
        self.assertEqual(night['reason'], 'night_activity_semantics_or_time_unresolved')
        self.assertEqual(result["soft_checks"][0]["field"], "constraint:local_food_preference")
        self.assertEqual(result["soft_checks"][0]["state"], "satisfied")
        self.assertEqual(result["lodging_check"]["state"], "pass")
        self.assertEqual(result["intercity_check"]["state"], "pass")
        self.assertEqual(result["itinerary_checks"]["chronology"]["state"], "pass")
        self.assertEqual(result["itinerary_checks"]["continuity"]["state"], "pass")
        self.assertEqual(result["business_chain_check"]["state"], "pass")
        self.assertEqual(result["route_domain_check"]["status"], "candidate_feasible")
        self.assertTrue(result["axes"]["solver"])  # whole-task proof is still unavailable
        self.assertNotEqual(result["outcome"], "complete_under_declared_policy")
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])

    def test_simultaneous_data_budget_failures_and_wrong_scopes_remain_visible(self):
        missing_record = {"id": "synthetic-missing", "city": "X", "kind": "restaurant",
                          "name": "test fixture only", "payload": {"data": {"price": 40}}, "claims": []}
        wrong_budget_scope = {
            "id": "wrong_budget_scope", "strength": "hard", "compiler_status": "supported",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 500, "people": 2, "includes": ["rooms", "meals"]}},
        }
        over_budget = {
            "id": "over_budget", "strength": "hard", "compiler_status": "supported",
            "scope": {"currency": "CNY", "people": 2, "unit": "total_trip_cost"},
            "expression": {"op": "total_cost_at_most", "args": {
                "CNY": 300, "people": 2, "includes": ["rooms"]}},
        }
        wrong_tag_scope = {
            "id": "wrong_tag_scope", "strength": "hard", "compiler_status": "supported",
            "scope": {"domain": "trip", "quantifier": "all", "item_kind": "restaurant"},
            "expression": {"op": "exclude_tag", "args": {"tag": "night_activity"}},
        }
        fact_rooms = {"value": 400, "unit": "CNY", "context": {"people": 2, "includes": ["rooms"]}}
        fact_wrong_scope = {"value": 200, "unit": "CNY",
                            "context": {"people": 2, "includes": ["tickets", "meals"]}}
        bad_tag_fact = item("attraction", "synthetic:attraction", "night_activity", True)
        result = diagnose_plan(
            uid="synthetic-negative", city="X",
            record_requirements=[(missing_record, [{"native_field": "price", "policy_field": "price",
                                                     "scope": {"ticket": "adult"}}])],
            registry={}, now=NOW, identity_verifier=lambda _: True,
            candidate=[{"diagnostic_kind": "budget", "candidate": candidate_payload(costs=(200,), budget=100)},
                       {"diagnostic_kind": "route", "candidate": candidate_payload()},
                       {"diagnostic_kind": "budget", "candidate": candidate_payload()}],
            constraints=[over_budget, wrong_budget_scope, wrong_tag_scope],
            constraint_facts={"over_budget": fact_rooms, "wrong_budget_scope": fact_wrong_scope},
            constraint_fact_verifier=lambda *_: True,
            tag_evidence={"wrong_tag_scope": {"scope_items": ["synthetic:attraction"],
                                               "tag_facts": [bad_tag_fact]}},
            tag_scope_verifier=lambda *_: True,
        )
        failures = {check["field"] for check in result["hard_failures"]}
        unknowns = {check["field"] for check in result["unknown_checks"]}
        self.assertTrue(result["axes"]["data"])
        self.assertIn("missing_evidence", {gap["reason"] for gap in result["axes"]["data"]})
        self.assertIn("constraint:over_budget", failures)
        self.assertIn("budget", failures)  # candidate-level sum also exceeds its declared limit
        self.assertIn("constraint:wrong_budget_scope", unknowns)
        self.assertIn("constraint:wrong_tag_scope", unknowns)
        self.assertTrue(result["axes"]["adapter"])
        self.assertNotEqual(result["outcome"], "complete_under_declared_policy")
        self.assertFalse(result["execution_confirmed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
