import copy
import unittest

from shorttrip.strict_plan_assembler import assemble_strict_plan


def inputs():
    context = {"uid": "synthetic-trip-1", "level": "easy",
               "start_city": "A", "target_city": "A",
               "start_date": "2026-11-15", "days": 3,
               "people_number": 2, "start_location_id": "home"}
    entity_kinds = {"home": "poi", "hotel": "accommodation",
                    "attraction-1": "attraction", "attraction-2": "attraction",
                    "attraction-3": "attraction", "restaurant-1": "restaurant",
                    "restaurant-2": "restaurant", "restaurant-3": "restaurant"}

    def travel(occurrence_id, origin, origin_kind, origin_entrance,
               destination, destination_kind, destination_entrance, start, end):
        return {"occurrence_id": occurrence_id, "type": "travel",
                "origin_id": origin, "origin_kind": origin_kind,
                "origin_entrance_id": origin_entrance,
                "destination_id": destination, "destination_kind": destination_kind,
                "destination_entrance_id": destination_entrance,
                "start": start, "end": end, "mode": "walk"}

    daily = []
    for day_index, date in enumerate(("2026-11-15", "2026-11-16", "2026-11-17")):
        attraction = f"attraction-{day_index + 1}"
        restaurant = f"restaurant-{day_index + 1}"
        start_id, start_kind, start_gate = ("home", "poi", "entrance") if day_index == 0 else (
            "hotel", "accommodation", "lobby")
        timeline = [
            travel(f"d{day_index + 1}-to-attraction", start_id, start_kind, start_gate,
                   attraction, "attraction", "main", "09:00:00+08:00", "09:30:00+08:00"),
            {"occurrence_id": f"d{day_index + 1}-visit", "type": "visit",
             "entity_id": attraction, "entity_kind": "attraction", "entrance_id": "main",
             "start": "09:30:00+08:00", "end": "11:00:00+08:00", "entity": attraction},
            travel(f"d{day_index + 1}-to-meal", attraction, "attraction", "main",
                   restaurant, "restaurant", "front", "11:00:00+08:00", "11:30:00+08:00"),
            {"occurrence_id": f"d{day_index + 1}-lunch", "type": "lunch",
             "entity_id": restaurant, "entity_kind": "restaurant", "entrance_id": "front",
             "start": "11:30:00+08:00", "end": "12:30:00+08:00"},
            travel(f"d{day_index + 1}-to-hotel", restaurant, "restaurant", "front",
                   "hotel", "accommodation", "lobby", "12:30:00+08:00", "13:00:00+08:00"),
        ]
        daily.append({"date": date, "city": "A",
                      "start_location": {"entity_id": start_id, "kind": start_kind,
                                         "entrance_id": start_gate},
                      "timeline": timeline})
    return context, daily, entity_kinds, {"allow_repeated_occurrence_entities": False}


class StrictPlanAssemblerTests(unittest.TestCase):
    def test_unknown_location_and_occurrence_do_not_form_a_proposal(self):
        for change in ('city', 'entrance', 'occurrence'):
            context, daily, kinds, policy = inputs()
            if change == 'city':
                context['target_city'] = 'unknown'
            elif change == 'entrance':
                daily[0]['start_location']['entrance_id'] = 'unresolved_id'
            else:
                daily[0]['timeline'][0]['occurrence_id'] = 'missing_id'
            result = assemble_strict_plan(context, daily, entity_kinds=kinds, repeat_policy=policy)
            self.assertEqual(result['status'], 'blocked')
            self.assertIsNone(result['plan'])

    def test_preserves_explicit_intercity_segment_without_certifying_it(self):
        from tests.test_strict_intercity_cost_manifest import fixture
        context, daily, kinds, policy = inputs()
        _, intercity_plan, _ = fixture()
        segment = copy.deepcopy(intercity_plan['intercity_segments'][0])
        event = daily[0]['timeline'][0]
        event['end'] = '11:00:00+08:00'
        daily[0]['timeline'][1].update(start='11:00:00+08:00', end='11:30:00+08:00')
        daily[0]['timeline'][2].update(start='11:30:00+08:00', end='12:00:00+08:00')
        daily[0]['timeline'][3].update(start='12:00:00+08:00', end='12:30:00+08:00')
        event['entity_id'] = 'explicit-trip-event'
        event['intercity_segment'] = segment
        result = assemble_strict_plan(context, daily, entity_kinds=kinds, repeat_policy=policy)
        self.assertEqual(result['status'], 'synthetic_plan_assembled_unverified')
        self.assertEqual(result['plan']['intercity_segments'], [segment])
        actual = result['plan']['days'][0]['timeline'][0]
        self.assertEqual(actual['segment_id'], segment['segment_id'])
        self.assertEqual(actual['date'], segment['travel_date'])
        self.assertEqual(actual['entity_id'], 'explicit-trip-event')
        self.assertFalse(result['facts_verified'])
        event['intercity_segment']['departure_time'] = '09:05'
        self.assertEqual(assemble_strict_plan(context, daily, entity_kinds=kinds,
                         repeat_policy=policy)['reason'], 'intercity_event_time_scope_mismatch')
        event['intercity_segment']['departure_time'] = '09:00'
        duplicate = copy.deepcopy(segment)
        duplicate['travel_date'] = daily[1]['date']
        duplicate['arrival_time'] = '09:30'
        daily[1]['timeline'][0]['entity_id'] = 'another-trip-event'
        daily[1]['timeline'][0]['intercity_segment'] = duplicate
        self.assertEqual(assemble_strict_plan(context, daily, entity_kinds=kinds,
                         repeat_policy=policy)['reason'], 'intercity_segment_id_duplicate')
        del daily[1]['timeline'][0]['intercity_segment']
        event.pop('entity_id')
        self.assertEqual(assemble_strict_plan(context, daily, entity_kinds=kinds,
                         repeat_policy=policy)['reason'], 'intercity_event_scope_missing_or_unsupported')
        event['entity_id'] = 'explicit-trip-event'
        event['intercity_segment']['arrival_day_offset'] = 1
        self.assertEqual(assemble_strict_plan(context, daily, entity_kinds=kinds,
                         repeat_policy=policy)['reason'], 'intercity_event_scope_missing_or_unsupported')

    def test_trip_horizon_overflow_fails_closed(self):
        context, daily, kinds, policy = inputs()
        context['start_date'] = '9999-12-31'
        result = assemble_strict_plan(context, daily, entity_kinds=kinds, repeat_policy=policy)
        self.assertEqual(result['reason'], 'plan_context_trip_dates_out_of_range')
        self.assertIsNone(result['plan'])

    def test_rejects_absolute_time_reversal_between_days(self):
        context, daily, kinds, policy = inputs()
        for item in daily[0]['timeline']:
            item['start'] = item['start'].replace('+08:00', '-12:00')
            item['end'] = item['end'].replace('+08:00', '-12:00')
        for item in daily[1]['timeline']:
            item['start'] = item['start'].replace('+08:00', '+14:00')
            item['end'] = item['end'].replace('+08:00', '+14:00')
        result = assemble_strict_plan(context, daily, entity_kinds=kinds, repeat_policy=policy)
        self.assertEqual(result['reason'], 'cross_day_absolute_time_order_conflict')

    def test_builds_caller_supplied_three_day_p31_proposal_without_certification(self):
        context, daily, kinds, policy = inputs()
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["status"], "synthetic_plan_assembled_unverified")
        self.assertEqual(result["plan"]["uid"], "synthetic-trip-1")
        self.assertEqual(len(result["plan"]["days"]), 3)
        self.assertEqual(result["plan"]["days"][1]["timeline"][0]["origin_id"], "hotel")
        self.assertTrue(result["synthetic_proposal"])
        self.assertFalse(result["feasibility"])
        self.assertFalse(result["facts_verified"])
        self.assertFalse(result["domain_complete"])
        self.assertFalse(result["truth_certified"])
        self.assertFalse(result["execution_confirmed"])
        self.assertFalse(any("price" in item for day in result["plan"]["days"]
                             for item in day["timeline"]))

    def test_rejects_missing_transition_instead_of_inserting_a_route(self):
        context, daily, kinds, policy = inputs()
        del daily[0]["timeline"][2]
        result = assemble_strict_plan(context, daily, entity_kinds=kinds, repeat_policy=policy)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "transition_missing_or_endpoint_mismatch")
        self.assertIsNone(result["plan"])

    def test_rejects_wrong_day_and_nonconsecutive_dates(self):
        context, daily, kinds, policy = inputs()
        daily[1]["date"] = "2026-11-18"
        wrong_date = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                          repeat_policy=policy)
        self.assertEqual(wrong_date["reason"], "day_date_mismatch")

        context, daily, kinds, policy = inputs()
        daily[1]["date"] = "2026-11-15"
        duplicate_date = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                              repeat_policy=policy)
        self.assertEqual(duplicate_date["reason"], "day_date_mismatch")

    def test_rejects_duplicate_occurrences_and_repeated_entities_when_policy_forbids(self):
        context, daily, kinds, policy = inputs()
        daily[1]["timeline"][1]["occurrence_id"] = daily[0]["timeline"][1]["occurrence_id"]
        duplicate_event = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                               repeat_policy=policy)
        self.assertEqual(duplicate_event["reason"], "occurrence_id_duplicate")

        context, daily, kinds, policy = inputs()
        repeated = copy.deepcopy(daily[1]["timeline"][1])
        repeated["entity_id"] = "attraction-1"
        repeated["entity_kind"] = "attraction"
        repeated["occurrence_id"] = "d2-repeat-attraction"
        daily[1]["timeline"][1] = repeated
        daily[1]["timeline"][0]["destination_id"] = "attraction-1"
        daily[1]["timeline"][0]["destination_kind"] = "attraction"
        daily[1]["timeline"][2]["origin_id"] = "attraction-1"
        daily[1]["timeline"][2]["origin_kind"] = "attraction"
        repeated_entity = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                               repeat_policy=policy)
        self.assertEqual(repeated_entity["reason"], "repeated_occurrence_entity_forbidden")

    def test_rejects_type_and_identity_mapping_mismatch(self):
        context, daily, kinds, policy = inputs()
        daily[0]["timeline"][3]["entity_kind"] = "attraction"
        mismatch = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                        repeat_policy=policy)
        self.assertEqual(mismatch["reason"], "event_scope_missing_or_kind_mismatch")

        context, daily, kinds, policy = inputs()
        daily[0]["start_location"]["entity_id"] = "not-declared"
        mismatch = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                        repeat_policy=policy)
        self.assertEqual(mismatch["reason"], "day_start_location_invalid")

    def test_rejects_naive_or_missing_time_without_synthesizing(self):
        context, daily, kinds, policy = inputs()
        daily[0]["timeline"][0]["start"] = "09:00"
        naive = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                     repeat_policy=policy)
        self.assertEqual(naive["reason"], "timeline_timezone_missing_or_mismatched")

        context, daily, kinds, policy = inputs()
        del daily[0]["timeline"][0]["end"]
        missing = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                       repeat_policy=policy)
        self.assertEqual(missing["reason"], "timeline_time_missing")

    def test_requires_day_one_start_anchor_and_explicit_cross_day_location(self):
        context, daily, kinds, policy = inputs()
        daily[0]["start_location"]["entity_id"] = "hotel"
        daily[0]["start_location"]["kind"] = "accommodation"
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["reason"], "first_day_anchor_does_not_match_context_start")

        context, daily, kinds, policy = inputs()
        daily[1]["start_location"]["entity_id"] = "home"
        daily[1]["start_location"]["kind"] = "poi"
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["reason"],
                         "overnight_transition_not_explicit_or_endpoint_mismatch")

    def test_malformed_unhashable_values_fail_closed(self):
        context, daily, kinds, policy = inputs()
        context["level"] = []
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["status"], "blocked")

        context, daily, kinds, policy = inputs()
        daily[0]["timeline"][0]["type"] = []
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["status"], "blocked")

        context, daily, kinds, policy = inputs()
        daily[0]["timeline"][0]["origin_kind"] = []
        result = assemble_strict_plan(context, daily, entity_kinds=kinds,
                                      repeat_policy=policy)
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
