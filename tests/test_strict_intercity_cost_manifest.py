import copy
import unittest

from shorttrip.strict_intercity_cost_manifest import evaluate_intercity_cost_manifest


def fixture():
    dates = ["2026-11-15", "2026-11-16", "2026-11-17"]
    outbound = {"segment_id": "leg-out", "direction": "outbound",
        "origin_city": "Alpha", "destination_city": "Beta",
        "origin_station": "Alpha Central", "destination_station": "Beta East",
        "travel_date": dates[0], "departure_time": "09:00", "clock_zone": "+08:00",
        "seat_class": "second", "passenger_count": 2, "date_scope_exception": None}
    returning = {"segment_id": "leg-back", "direction": "return",
        "origin_city": "Beta", "destination_city": "Alpha",
        "origin_station": "Beta East", "destination_station": "Alpha Central",
        "travel_date": dates[2], "departure_time": "09:00", "clock_zone": "+08:00",
        "seat_class": "second", "passenger_count": 2, "date_scope_exception": None}
    policy = {"origin_city": "Alpha", "destination_city": "Beta",
        "currency": "CNY", "return_policy": "required",
        "required_segments": [outbound, returning]}
    task = {"uid": "task-i", "target_city": "Beta",
        "start_date": dates[0], "days": 3, "people_number": 2,
        "intercity_policy": policy}
    plan_segments, fares = [], []
    for leg in (outbound, returning):
        origin_city = "Alpha" if leg["direction"] == "outbound" else "Beta"
        destination_city = "Beta" if leg["direction"] == "outbound" else "Alpha"
        expense_id = "fare-" + leg["segment_id"]
        plan_segment = {"segment_id": leg["segment_id"], "direction": leg["direction"],
            "origin_city": origin_city, "destination_city": destination_city,
            "origin_station": leg["origin_station"],
            "destination_station": leg["destination_station"],
            "travel_date": leg["travel_date"], "departure_time": leg["departure_time"],
            "clock_zone": leg["clock_zone"], "seat_class": leg["seat_class"],
            "passenger_count": leg["passenger_count"], "arrival_time": "11:00",
            "arrival_day_offset": 0, "Duration": 2, "Duration_unit": "hours",
            "expense_id": expense_id}
        plan_segments.append(plan_segment)
        timetable_claim = {key: plan_segment[key] for key in (
            "origin_city", "destination_city", "origin_station", "destination_station",
            "travel_date", "departure_time", "clock_zone", "arrival_time",
            "arrival_day_offset", "Duration", "Duration_unit")}
        fare_claim = {key: plan_segment[key] for key in (
            "segment_id", "direction", "origin_city", "destination_city",
            "origin_station", "destination_station", "travel_date", "seat_class",
            "departure_time", "clock_zone", "passenger_count")}
        fare_claim.update({"currency": "CNY", "unit": "CNY/person/segment",
            "unit_price": "100.25", "taxes_included": True,
            "mandatory_fees_included": True, "conflict": False,
            "evidence": {"source_ref": "fixture-source-" + leg["segment_id"],
                         "retrieved_at": "2026-11-01T00:00:00Z", "licence": "fixture-only"}})
        fares.append({"segment_id": leg["segment_id"], "expense_id": expense_id,
                      "timetable_claim": timetable_claim, "fare_claim": fare_claim})
    plan = {"uid": "task-i", "days": [
        {"date": day, "city": "Beta", "timeline": []} for day in dates],
        "intercity_segments": plan_segments}
    return task, plan, {"fares": fares}


def run(args, **overrides):
    callbacks = {"policy_verifier": lambda *_: True,
        "inventory_verifier": lambda *_: True,
        "segment_verifier": lambda *_: True,
        "timetable_verifier": lambda *_: True,
        "fare_verifier": lambda *_: True}
    callbacks.update(overrides)
    return evaluate_intercity_cost_manifest(*args, **callbacks)


class StrictIntercityCostManifestTests(unittest.TestCase):
    def test_extreme_passenger_count_is_unknown_without_exception(self):
        task, plan, manifest = fixture()
        huge = 10 ** 5000
        task['people_number'] = huge
        for segment in task['intercity_policy']['required_segments']:
            segment['passenger_count'] = huge
        for segment in plan['intercity_segments']:
            segment['passenger_count'] = huge
        for entry in manifest['fares']:
            entry['fare_claim']['passenger_count'] = huge
        self.assertEqual(run((task, plan, manifest))['state'], 'unknown')

    def test_unresolved_identifiers_cannot_be_verified(self):
        args = fixture()
        args[0]['uid'] = args[1]['uid'] = 'unresolved_id'
        self.assertEqual(run(args)['state'], 'unknown')

        args = fixture()
        args[1]['intercity_segments'][0]['expense_id'] = 'unresolved_id'
        args[2]['fares'][0]['expense_id'] = 'unresolved_id'
        self.assertEqual(run(args)['state'], 'unknown')

        args = fixture()
        args[0]['intercity_policy']['required_segments'][0]['origin_station'] = 'unresolved_id'
        self.assertEqual(run(args)['state'], 'unknown')

    def test_all_verifiers_cannot_mutate_original_inputs_through_closure(self):
        for name in ('policy_verifier', 'segment_verifier', 'timetable_verifier',
                     'fare_verifier', 'inventory_verifier'):
            with self.subTest(verifier=name):
                args = fixture()
                def mutate(*_args):
                    args[0]['people_number'] = 1
                    return True
                result = run(args, **{name: mutate})
                self.assertEqual(result['state'], 'unknown')
                self.assertEqual(result['reason'], 'intercity_original_inputs_mutated')

    def test_explicit_round_trip_prices_all_people_with_decimal_total(self):
        result = run(fixture())
        self.assertEqual(result["state"], "pass")
        self.assertEqual(result["return_policy"], "required")
        self.assertEqual(result["total_decimal"], "401.00")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual([row["passenger_count"] for row in result["segments"]], [2, 2])
        self.assertFalse(result["truth_certified"])

    def test_missing_origin_or_explicit_return_policy_is_unknown(self):
        task, plan, manifest = fixture()
        task["start_city"] = "Beta"
        del task["intercity_policy"]["origin_city"]
        self.assertEqual(run((task, plan, manifest))["state"], "unknown")
        task, plan, manifest = fixture()
        task["intercity_policy"]["return_policy"] = None
        self.assertEqual(run((task, plan, manifest))["reason"],
                         "intercity_return_policy_missing_or_invalid")

    def test_task_and_plan_uid_start_date_day_count_and_dates_are_exactly_bound(self):
        for mutate in (
            lambda args: args[0].update(start_date="2026-11-16"),
            lambda args: args[0].update(days=2),
            lambda args: args[0].update(days=True),
            lambda args: args[1]["days"][0].update(date="2026-11-16"),
            lambda args: (args[0].update(uid="unknown"), args[1].update(uid="unknown")),
        ):
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args)
                self.assertEqual(run(args)["state"], "unknown")

    def test_date_arithmetic_overflow_fails_closed(self):
        args = fixture()
        args[0]["start_date"] = "9999-12-31"
        args[0]["days"] = 2
        args[1]["days"] = [
            {"date": "9999-12-31", "city": "Beta", "timeline": []},
            {"date": "9999-12-31", "city": "Beta", "timeline": []},
        ]
        result = run(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "intercity_plan_date_scope_invalid")

    def test_all_segment_passengers_must_equal_task_party_even_with_true_callbacks(self):
        args = fixture()
        for leg in args[0]["intercity_policy"]["required_segments"]:
            leg["passenger_count"] = 1
        for segment in args[1]["intercity_segments"]:
            segment["passenger_count"] = 1
        for fare in args[2]["fares"]:
            fare["fare_claim"]["passenger_count"] = 1
        result = run(args)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "intercity_policy_segment_scope_incomplete")

    def test_unknown_placeholders_are_rejected_before_verifiers(self):
        for mutate in (
            lambda args: args[0]["intercity_policy"].update(origin_city="unknown"),
            lambda args: args[0]["intercity_policy"]["required_segments"][0].update(origin_station="未提供"),
            lambda args: args[0]["intercity_policy"]["required_segments"][0].update(seat_class="unspecified"),
        ):
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args)
                self.assertEqual(run(args)["state"], "unknown")

    def test_required_return_cannot_be_satisfied_by_outbound_only(self):
        task, plan, manifest = fixture()
        task["intercity_policy"]["required_segments"].pop()
        plan["intercity_segments"].pop()
        manifest["fares"].pop()
        result = run((task, plan, manifest))
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "intercity_required_return_segment_missing_or_ambiguous")

    def test_one_way_requires_explicit_not_required_return_policy(self):
        task, plan, manifest = fixture()
        outbound = task["intercity_policy"]["required_segments"][0]
        task["intercity_policy"]["return_policy"] = "not_required"
        task["intercity_policy"]["required_segments"] = [outbound]
        plan["intercity_segments"] = plan["intercity_segments"][:1]
        manifest["fares"] = manifest["fares"][:1]
        self.assertEqual(run((task, plan, manifest))["state"], "pass")

    def test_same_city_direction_and_direction_or_station_mismatches_are_unknown(self):
        task, plan, manifest = fixture()
        task["intercity_policy"]["destination_city"] = "Alpha"
        self.assertEqual(run((task, plan, manifest))["reason"], "intercity_task_direction_invalid")

        for mutate in (
            lambda args: args[1]["intercity_segments"][0].update(direction="return"),
            lambda args: args[1]["intercity_segments"][0].update(origin_station="Alpha West"),
            lambda args: args[2]["fares"][0]["fare_claim"].update(destination_station="Beta West"),
        ):
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args)
                self.assertEqual(run(args)["state"], "unknown")

    def test_timetable_uses_existing_hour_timezone_and_direction_checks(self):
        for mutate in (
            lambda args: args[2]["fares"][0]["timetable_claim"].update(Duration_unit="minutes"),
            lambda args: args[2]["fares"][0]["timetable_claim"].update(clock_zone="local"),
            lambda args: args[2]["fares"][0]["timetable_claim"].update(arrival_time="08:00"),
        ):
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args)
                self.assertEqual(run(args)["state"], "unknown")

    def test_fare_scope_seat_passengers_unit_charges_and_source_are_required(self):
        mutations = (
            lambda fare: fare.update(seat_class="first"),
            lambda fare: fare.update(passenger_count=1),
            lambda fare: fare.update(unit="CNY/segment"),
            lambda fare: fare.update(taxes_included=False),
            lambda fare: fare.update(mandatory_fees_included=False),
            lambda fare: fare.update(evidence={}),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                args = fixture()
                mutate(args[2]["fares"][0]["fare_claim"])
                self.assertEqual(run(args)["state"], "unknown")

    def test_ambiguous_same_name_station_needs_independent_city_station_verification(self):
        args = fixture()
        args[0]["intercity_policy"]["required_segments"][0]["origin_station"] = "Central"
        args[1]["intercity_segments"][0]["origin_station"] = "Central"
        args[2]["fares"][0]["timetable_claim"]["origin_station"] = "Central"
        args[2]["fares"][0]["fare_claim"]["origin_station"] = "Central"
        def reject_ambiguous_station(task, _plan, policy_leg, _segment, _claim):
            return not (policy_leg["origin_station"] == "Central" and
                        task["intercity_policy"]["origin_city"] !=
                        task["intercity_policy"]["destination_city"])
        self.assertEqual(run(args, fare_verifier=reject_ambiguous_station)["state"], "unknown")

    def test_out_of_itinerary_segment_date_is_not_implicitly_accepted(self):
        args = fixture()
        args[0]["intercity_policy"]["required_segments"][0]["travel_date"] = "2026-11-14"
        self.assertEqual(run(args)["state"], "unknown")

    def test_duplicate_expense_and_price_precision_or_negative_errors_are_unknown(self):
        args = fixture()
        args[2]["fares"][1]["expense_id"] = args[2]["fares"][0]["expense_id"]
        self.assertEqual(run(args)["reason"],
                         "intercity_fare_segment_or_expense_id_duplicate_or_invalid")
        for value in ("-1", "NaN", 0.1, "1e-3", "01.00"):
            args = fixture()
            args[2]["fares"][0]["fare_claim"]["unit_price"] = value
            self.assertEqual(run(args)["state"], "unknown", value)

    def test_unhashable_segment_ids_fail_closed_at_every_inventory_boundary(self):
        # These values are rejected before a set/dict membership or key operation.
        for bad_id in ([], ["leg-out"], {}, {"id": "leg-out"}, set(), {"leg-out"}):
            with self.subTest(where="policy", bad_id=repr(bad_id)):
                args = fixture()
                args[0]["intercity_policy"]["required_segments"][0]["segment_id"] = bad_id
                self.assertEqual(run(args)["state"], "unknown")
            with self.subTest(where="plan", bad_id=repr(bad_id)):
                args = fixture()
                args[1]["intercity_segments"][0]["segment_id"] = bad_id
                self.assertEqual(run(args)["state"], "unknown")
            with self.subTest(where="fare", bad_id=repr(bad_id)):
                args = fixture()
                args[2]["fares"][0]["segment_id"] = bad_id
                self.assertEqual(run(args)["state"], "unknown")

    def test_unhashable_policy_direction_and_return_policy_fail_closed(self):
        for bad_value in ([], {}, set()):
            args = fixture()
            args[0]["intercity_policy"]["required_segments"][0]["direction"] = bad_value
            self.assertEqual(run(args)["state"], "unknown")
            args = fixture()
            args[0]["intercity_policy"]["return_policy"] = bad_value
            self.assertEqual(run(args)["state"], "unknown")

    def test_callbacks_are_all_required_and_mutation_fails_closed(self):
        args = fixture()
        self.assertEqual(run(args, fare_verifier=None)["state"], "unknown")
        args = fixture()
        before = copy.deepcopy(args)
        def mutate(_task, _plan, _policy, _segment, fare):
            fare["unit_price"] = "0"
            return True
        result = run(args, fare_verifier=mutate)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(args, before)
        args = fixture()
        def mutate_policy(_task, policy):
            policy["return_policy"] = "not_required"
            return True
        self.assertEqual(run(args, policy_verifier=mutate_policy)["state"], "unknown")

    def test_return_must_follow_outbound_arrival_and_task_plan_scope_must_match(self):
        args = fixture()
        args[0]["intercity_policy"]["required_segments"][1]["travel_date"] = "2026-11-15"
        args[0]["intercity_policy"]["required_segments"][1]["departure_time"] = "10:00"
        args[1]["intercity_segments"][1]["travel_date"] = "2026-11-15"
        args[1]["intercity_segments"][1]["departure_time"] = "10:00"
        args[1]["intercity_segments"][1]["arrival_time"] = "12:00"
        fare = args[2]["fares"][1]
        fare["timetable_claim"]["travel_date"] = "2026-11-15"
        fare["timetable_claim"]["departure_time"] = "10:00"
        fare["timetable_claim"]["arrival_time"] = "12:00"
        for key in ("travel_date", "departure_time", "clock_zone"):
            fare["fare_claim"][key] = args[1]["intercity_segments"][1][key]
        self.assertEqual(run(args)["reason"], "intercity_return_time_not_after_outbound_arrival")

        args = fixture()
        args[1]["uid"] = "other-plan"
        self.assertEqual(run(args)["reason"], "intercity_task_plan_uid_mismatch")


if __name__ == "__main__":
    unittest.main()
