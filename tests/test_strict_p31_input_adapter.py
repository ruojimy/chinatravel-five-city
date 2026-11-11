import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from p31_static import build_plan

from shorttrip.strict_p31_input_adapter import prepare_legacy_p31_input


def task(days=1, *, auxiliary_kind="poi"):
    ids = {"attraction": "att-1", "restaurant": "rest-1",
           "accommodation": "hotel-1", auxiliary_kind: "aux-1"}
    selected = {kind: {"id": entity_id, "stored_name_unverified": kind + " label"}
                for kind, entity_id in ids.items()}
    return {"uid": "dev-local", "level": "easy", "split": "development",
            "purpose": "development", "start_city": "北京", "target_city": "北京",
            "start_date": "2026-11-15", "days": days, "people_number": 2,
            "nature_language": "synthetic request", "required_kinds": list(ids),
            "additional_constraints": [{"id": "budget", "strength": "hard",
                "scope": {"currency": "CNY"}, "expression": {"op": "opaque", "args": {}},
                "compiler_status": "unmapped"}],
            "candidate_selection": {"required_entity_ids": list(ids.values())},
            "generation": {"selected_entities_by_kind": selected}}


def candidates(t):
    result = {}
    for kind, selected in t["generation"]["selected_entities_by_kind"].items():
        entity_id = selected["id"]
        data = {"lat": 47.0, "lon": -122.0, "price": 500}
        if kind == "attraction":
            data.update(opentime="09:00", endtime="18:00", recommendmintime=1.5)
        if kind == "restaurant":
            data.update(opentime="09:00", endtime="18:00")
        result[entity_id] = {"entity_id": entity_id, "kind": kind, "name": selected["stored_name_unverified"],
                             "city": "北京", "coordinate_system": "WGS84", "data": data,
                             "entity_verified": True}
    return result


def context(t):
    start_id = t["generation"]["selected_entities_by_kind"]["poi"]["id"]
    return {"start": {"entity_id": start_id, "name": "poi label", "city": "北京",
                       "coordinate_system": "WGS84", "position_wgs84": [47.0, -122.0]},
            "dates": ["2026-11-15"], "city_sequence": ["北京"],
            "constraints": {"window": ["09:00", "18:00"], "start_time": "09:00",
                            "mode": "walking", "return_to_start": True, "budget": 1000},
            "static_estimate": {"budget_limit": 1000}}


class StrictP31InputAdapterTests(unittest.TestCase):
    def call(self, t=None, *, legacy_context=None, candidates_by_id=None):
        t = task() if t is None else t
        return prepare_legacy_p31_input(t,
            legacy_context=context(t) if legacy_context is None else legacy_context,
            candidates_by_id=candidates(t) if candidates_by_id is None else candidates_by_id)

    def test_three_day_v6_shape_is_rejected_before_context_or_candidates(self):
        out = prepare_legacy_p31_input(task(days=3))
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["reason"], "unsupported_legacy_horizon")
        self.assertFalse(out["planner_invoked"])
        self.assertIsNone(out["legacy_input"])

    def test_holdout_and_non_task_inputs_are_rejected(self):
        t = task()
        t.update(split="holdout", purpose="holdout")
        self.assertEqual(self.call(t)["reason"], "development_task_required")
        self.assertEqual(prepare_legacy_p31_input(None)["reason"], "task_not_object")

    def test_missing_explicit_context_or_candidate_mapping_blocks(self):
        t = task()
        self.assertEqual(prepare_legacy_p31_input(t, legacy_context=context(t))["reason"],
                         "explicit_candidate_mapping_required")
        self.assertEqual(prepare_legacy_p31_input(t, candidates_by_id=candidates(t))["reason"],
                         "explicit_legacy_context_required")
        self.assertEqual(self.call(t, candidates_by_id={1: {}})["reason"],
                         "candidate_mapping_keys_invalid")
        ctx = context(t)
        ctx[1] = "malformed key"
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"],
                         "legacy_context_shape_invalid")

    def test_exact_explicit_local_binding_prepares_input_without_execution(self):
        t = task()
        source_candidates = candidates(t)
        out = self.call(t, candidates_by_id=source_candidates)
        self.assertEqual(out["status"], "legacy_shape_built_for_engineering_only")
        self.assertFalse(out["planning_equivalence"])
        self.assertFalse(out["v6_task_plannability_established"])
        self.assertEqual(out["legacy_input"]["dates"], [t["start_date"]])
        self.assertEqual({x["entity_id"] for x in out["legacy_input"]["candidates"]},
                         set(t["candidate_selection"]["required_entity_ids"]))
        self.assertFalse(out["planner_invoked"])
        self.assertFalse(out["v6_constraints_translated"])
        self.assertFalse(out["intercity_inferred"])
        self.assertFalse(out["estimates_verified"])
        self.assertFalse(out["truth_certified"])
        self.assertNotIn("intercity", out["legacy_input"])
        self.assertNotIn("old_city", out["legacy_input"])
        self.assertTrue(source_candidates["att-1"]["entity_verified"])
        self.assertNotIn("entity_verified", out["legacy_input"]["candidates"][0])

    def test_explicit_local_input_has_the_legacy_build_plan_shape(self):
        out = self.call()
        self.assertEqual(out["status"], "legacy_shape_built_for_engineering_only")
        plan = build_plan(out["legacy_input"])
        self.assertEqual(len(plan["days"]), 1)
        self.assertTrue(plan["days"][0]["timeline"])
        # Calling the old planner in this interface test does not certify its
        # estimate or translate the V6 constraints.
        self.assertFalse(out["estimates_verified"])
        self.assertFalse(out["v6_constraints_translated"])

    def test_candidate_ids_must_match_exactly_and_names_or_kinds_cannot_substitute(self):
        t = task()
        cs = candidates(t)
        cs.pop("att-1")
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "candidate_mapping_id_set_mismatch")
        cs = candidates(t)
        cs["att-1"]["name"] = "another venue"
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"], "candidate_binding_mismatch")
        cs = candidates(t)
        cs["att-1"]["kind"] = "restaurant"
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"], "candidate_binding_mismatch")

    def test_duplicate_candidate_names_block_legacy_next_by_name_resolution(self):
        t = task()
        t["generation"]["selected_entities_by_kind"]["restaurant"]["stored_name_unverified"] = "attraction label"
        cs = candidates(t)
        cs["rest-1"]["name"] = "attraction label"
        out = self.call(t, candidates_by_id=cs)
        self.assertEqual(out["reason"], "candidate_name_ambiguous_for_legacy_planner")
        self.assertIsNone(out["legacy_input"])

    def test_missing_data_used_by_legacy_planner_blocks_preparation(self):
        t = task()
        cs = candidates(t)
        del cs["att-1"]["data"]["recommendmintime"]
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_candidate_visit_duration_missing_or_invalid")
        cs = candidates(t)
        del cs["hotel-1"]["data"]["price"]
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_candidate_required_data_missing_or_invalid")

    def test_transport_auxiliary_is_never_promoted_to_intercity(self):
        t = task(auxiliary_kind="train")
        out = prepare_legacy_p31_input(t, candidates_by_id=candidates(t))
        self.assertEqual(out["reason"], "auxiliary_transport_is_not_a_route")
        self.assertFalse(out["intercity_inferred"])
        self.assertIsNone(out["legacy_input"])

    def test_start_binding_and_coordinates_must_be_explicit_and_exact(self):
        t = task()
        ctx = context(t)
        ctx["start"]["entity_id"] = "att-1"
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"], "legacy_start_binding_invalid")
        ctx["start"]["entity_id"] = ["att-1"]
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"], "legacy_start_id_undeclared")
        ctx = context(t)
        ctx["start"]["position_wgs84"] = [0, 0]
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"],
                         "legacy_start_coordinate_binding_mismatch")

    def test_schedule_coordinates_and_coordinate_system_are_not_guessed(self):
        t = task()
        cs = candidates(t)
        cs["att-1"]["data"].pop("lat")
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_core_candidate_coordinates_missing_or_invalid")
        cs = candidates(t)
        cs["att-1"]["coordinate_system"] = "GCJ02"
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_core_candidate_coordinate_system_unsupported")

    def test_unbounded_integer_price_and_coordinates_fail_closed(self):
        t = task()
        cs = candidates(t)
        cs["att-1"]["data"]["price"] = 10 ** 1000
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_candidate_required_data_missing_or_invalid")

        cs = candidates(t)
        cs["att-1"]["data"]["lat"] = 10 ** 1000
        self.assertEqual(self.call(t, candidates_by_id=cs)["reason"],
                         "legacy_core_candidate_coordinates_missing_or_invalid")

    def test_context_date_city_constraints_and_estimates_are_not_inferred(self):
        t = task()
        ctx = context(t)
        ctx["dates"] = ["2026-11-16"]
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"],
                         "legacy_date_or_city_sequence_mismatch")
        ctx = context(t)
        ctx["constraints"].pop("window")
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"],
                         "legacy_constraints_shape_invalid")
        ctx = context(t)
        ctx["static_estimate"]["budget_limit"] = None
        self.assertEqual(self.call(t, legacy_context=ctx)["reason"], "legacy_static_estimate_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
