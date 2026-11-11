import copy
import unittest

from shorttrip.strict_multiday_candidates import generate_multiday_candidate_proposals


DATES = ["2026-11-15", "2026-11-16", "2026-11-17"]


def occurrence(entity_id, kind, day, start="10:00", end="11:00", **extra):
    return {"entity_id": entity_id, "kind": kind, "date": day,
            "start": f"{day}T{start}:00+08:00", "end": f"{day}T{end}:00+08:00",
            **extra}


def days():
    return [
        {"date": DATES[0], "slots": [
            {"slot_id": "morning", "candidates": [
                occurrence("att-1", "attraction", DATES[0]),
                occurrence("att-2", "attraction", DATES[0])]},
            {"slot_id": "lunch", "candidates": [
                occurrence("rest-1", "restaurant", DATES[0])]},
        ]},
        {"date": DATES[1], "slots": [
            {"slot_id": "visit", "candidates": [
                occurrence("att-3", "attraction", DATES[1])]},
        ]},
        {"date": DATES[2], "slots": [
            {"slot_id": "stay", "candidates": [
                occurrence("hotel-1", "accommodation", DATES[2])]},
        ]},
    ]


class StrictMultidayCandidateTests(unittest.TestCase):
    def build(self, data=None, **kwargs):
        return generate_multiday_candidate_proposals(
            days() if data is None else data,
            expected_dates=kwargs.pop("expected_dates", DATES), **kwargs)

    def test_enumerates_only_supplied_choices_and_never_certifies_feasibility(self):
        data = days()
        # These explicit slots overlap. The generator enumerates candidates; it
        # does not attempt chronology or feasibility checks.
        out = self.build(data)
        self.assertEqual(out["status"], "candidate_proposal_unverified")
        self.assertEqual(out["combination_count"], 2)
        self.assertEqual(len(out["proposals"]), 2)
        self.assertEqual(out["proposals"][0]["occurrences"][0]["entity_id"], "att-1")
        self.assertEqual(out["proposals"][1]["occurrences"][0]["entity_id"], "att-2")
        self.assertTrue(out["enumeration_exhaustive_over_supplied_slots"])
        self.assertFalse(out["task_coverage_verified"])
        self.assertFalse(out["plan_complete"])
        self.assertIsNone(out["feasibility"])
        self.assertFalse(out["facts_verified"])
        self.assertFalse(out["infeasibility_proven"])
        self.assertFalse(out["planner_invoked"])
        self.assertFalse(out["execution_confirmed"])

    def test_non_three_day_horizon_and_expected_date_mismatch_block(self):
        out = self.build(days()[:2], expected_dates=DATES)
        self.assertEqual(out["reason"], "unsupported_candidate_horizon")
        self.assertEqual(out["proposals"], [])
        out = self.build(expected_dates=[DATES[0], DATES[1]])
        self.assertEqual(out["reason"], "three_explicit_expected_dates_required")
        out = self.build(expected_dates=[DATES[0], "2026-11-17", "2026-11-18"])
        self.assertEqual(out["reason"], "expected_dates_not_three_consecutive_days")
        data = days()
        data[1]["date"] = "2026-11-18"
        out = self.build(data)
        self.assertEqual(out["reason"], "day_date_mismatch")

    def test_missing_slot_or_candidate_input_does_not_get_filled(self):
        data = days()
        data[0]["slots"] = []
        self.assertEqual(self.build(data)["reason"], "day_slots_missing")
        data = days()
        data[0]["slots"][0]["candidates"] = []
        self.assertEqual(self.build(data)["reason"], "slot_candidates_missing")
        data = days()
        del data[0]["slots"][0]["candidates"][0]["start"]
        self.assertEqual(self.build(data)["reason"], "occurrence_shape_invalid")

    def test_exact_date_timezone_and_positive_interval_are_required(self):
        data = days()
        data[0]["slots"][0]["candidates"][0]["start"] = "10:00"
        self.assertEqual(self.build(data)["reason"], "occurrence_time_invalid_or_timezone_missing")
        data = days()
        data[0]["slots"][0]["candidates"][0]["start"] = "2026-11-15T10:00:00"
        self.assertEqual(self.build(data)["reason"], "occurrence_time_invalid_or_timezone_missing")
        data = days()
        data[0]["slots"][0]["candidates"][0]["date"] = DATES[1]
        self.assertEqual(self.build(data)["reason"], "occurrence_date_mismatch")
        data = days()
        data[0]["slots"][0]["candidates"][0]["end"] = "2026-11-16T11:00:00+08:00"
        self.assertEqual(self.build(data)["reason"], "occurrence_time_outside_declared_day")
        data = days()
        data[0]["slots"][0]["candidates"][0] = occurrence(
            "att-1", "attraction", DATES[0], start="11:00", end="10:00")
        self.assertEqual(self.build(data)["reason"], "occurrence_interval_nonpositive")
        data = days()
        data[0]["slots"][0]["candidates"][0]["end"] = f"{DATES[0]}T11:00:00+09:00"
        self.assertEqual(self.build(data)["reason"], "occurrence_timezone_offset_mismatch")

    def test_combination_cap_blocks_without_returning_partial_enumeration(self):
        data = days()
        data[0]["slots"][0]["candidates"].append(
            occurrence("att-4", "attraction", DATES[0]))
        out = self.build(data, max_combinations=2)
        self.assertEqual(out["reason"], "candidate_combination_limit_exceeded")
        self.assertEqual(out["detail"]["combination_count"], 3)
        self.assertEqual(out["proposals"], [])
        self.assertFalse(out["enumeration_exhaustive_over_supplied_slots"])
        self.assertFalse(out["infeasibility_proven"])

    def test_duplicate_slots_or_occurrences_and_extra_fact_fields_block(self):
        data = days()
        data[0]["slots"].append(copy.deepcopy(data[0]["slots"][0]))
        self.assertEqual(self.build(data)["reason"], "slot_id_duplicate_within_day")
        data = days()
        data[0]["slots"][0]["candidates"].append(
            copy.deepcopy(data[0]["slots"][0]["candidates"][0]))
        self.assertEqual(self.build(data)["reason"], "duplicate_slot_occurrence")
        data = days()
        data[0]["slots"][0]["candidates"][0]["price"] = 0
        self.assertEqual(self.build(data)["reason"], "occurrence_shape_invalid")

    def test_bad_limit_and_invalid_kind_block_structurally(self):
        self.assertEqual(self.build(max_combinations=True)["reason"],
                         "combination_limit_invalid")
        self.assertEqual(self.build(max_combinations=10**12)["reason"],
                         "combination_limit_exceeds_hard_cap")
        data = days()
        data[0]["slots"][0]["candidates"][0]["kind"] = "unknown"
        self.assertEqual(self.build(data)["reason"], "occurrence_kind_invalid")

    def test_blocked_detail_is_detached_from_caller_input(self):
        bad_date = []
        expected_dates = [DATES[0], bad_date, DATES[2]]
        out = self.build(expected_dates=expected_dates)
        self.assertEqual(out["reason"], "expected_date_invalid")
        out["detail"]["date"].append("changed")
        self.assertEqual(bad_date, [])

        bad_actual_date = []
        data = days()
        data[1]["date"] = bad_actual_date
        out = self.build(data)
        self.assertEqual(out["reason"], "day_date_mismatch")
        out["detail"]["actual_date"].append("changed")
        self.assertEqual(bad_actual_date, [])

    def test_blocked_detail_copy_failure_discards_detail(self):
        class Uncopyable:
            def __deepcopy__(self, memo):
                raise RuntimeError("cannot copy")

        out = self.build(expected_dates=[DATES[0], Uncopyable(), DATES[2]])
        self.assertEqual(out["reason"], "expected_date_invalid")
        self.assertIsNone(out["detail"])

    def test_slot_and_candidate_input_sizes_have_fixed_caps(self):
        data = days()
        data[0]["slots"] = [
            {"slot_id": f"slot-{i}", "candidates": [
                occurrence(f"id-{i}", "attraction", DATES[0])]} for i in range(37)]
        out = self.build(data)
        self.assertEqual(out["reason"], "slot_count_exceeds_limit")
        data = days()
        data[0]["slots"][0]["candidates"] = [
            occurrence(f"att-{i}", "attraction", DATES[0]) for i in range(33)]
        out = self.build(data)
        self.assertEqual(out["reason"], "slot_candidate_count_exceeds_limit")
        self.assertEqual(out["proposals"], [])
        data = days()
        data[0]["slots"] = [
            {"slot_id": f"bulk-{slot}", "candidates": [
                occurrence(f"bulk-{slot}-{candidate}", "attraction", DATES[0])
                for candidate in range(32)]}
            for slot in range(17)]
        out = self.build(data)
        self.assertEqual(out["reason"], "occurrence_count_exceeds_limit")
        self.assertEqual(out["proposals"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
