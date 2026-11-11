import unittest

from shorttrip.route_context_ttl import verify_route_context_ttl

NOW = "2026-10-30T10:00:00+08:00"
CTX = {
    "origin": "poi:A", "destination": "poi:B", "origin_entry": "east gate",
    "destination_entry": "main gate", "coord_system": "GCJ02", "mode": "walking",
    "travel_date": "2026-10-30", "departure_at": "2026-10-30T10:30:00+08:00",
}


def evidence(**overrides):
    value = {"context": dict(CTX), "observed_at": "2026-10-30T09:55:00+08:00",
             "valid_until": "2026-10-30T10:10:00+08:00",
             "duration_minutes": 20, "provider_verified": True}
    value.update(overrides)
    return value


class RouteContextTTLTests(unittest.TestCase):
    def test_matching_unknown_endpoint_or_mode_is_not_a_complete_context(self):
        for field in ('origin', 'destination', 'origin_entry', 'destination_entry', 'mode'):
            for placeholder in ('unknown', 'unresolved'):
                with self.subTest(field=field, placeholder=placeholder):
                    context = dict(CTX, **{field: placeholder})
                    result = self.check(ctx=context, ev=evidence(context=context))
                    self.assertFalse(result['context_ttl_ok'])
                    self.assertIn('route_context_missing:' + field, result['reasons'])

    def test_compact_date_does_not_count_as_canonical_trip_date(self):
        context = dict(CTX, travel_date='20261030')
        self.assertIn('route_departure_context_invalid', self.check(
            ctx=context, ev=evidence(context=context))['reasons'])

    def test_unrepresentable_utc_conversion_fails_closed(self):
        out = self.check(now='0001-01-01T00:00:00+14:00')
        self.assertFalse(out['context_ttl_ok'])
        self.assertIn('route_clock_missing_or_invalid', out['reasons'])

    def test_non_string_endpoint_cannot_be_qualified(self):
        context = dict(CTX, origin=123)
        result = self.check(ctx=context, ev=evidence(context=context))
        self.assertIn('route_context_missing:origin', result['reasons'])
        self.assertFalse(result['context_ttl_ok'])
    def check(self, ctx=CTX, ev=None, now=NOW, **kwargs):
        return verify_route_context_ttl({"context": ctx}, ev or evidence(), now=now, **kwargs)

    def test_matching_recent_context_passes_but_never_authenticates(self):
        result = self.check()
        self.assertTrue(result["context_ttl_ok"])
        self.assertFalse(result["eligible_for_planning"])
        self.assertFalse(result["provider_identity_verified"])
        self.assertFalse(result["response_value_binding_verified"])

    def test_exact_endpoint_direction_entries_and_mode_are_required(self):
        for field, wrong in (("origin", "poi:B"), ("destination", "poi:A"),
                             ("origin_entry", "west gate"), ("destination_entry", "side gate"),
                             ("mode", "driving")):
            with self.subTest(field=field):
                ev = evidence(context=dict(CTX, **{field: wrong}))
                self.assertIn("route_context_mismatch:" + field,
                              self.check(ev=ev)["reasons"])

    def test_missing_context_and_unknown_coordinate_system_rejected(self):
        ctx = dict(CTX); del ctx["destination_entry"]
        result = self.check(ctx=ctx, ev=evidence(context=ctx))
        self.assertIn("route_context_missing:destination_entry", result["reasons"])
        bad = dict(CTX, coord_system="GCJ-02")
        self.assertIn("route_coordinate_system_unknown",
                      self.check(ctx=bad, ev=evidence(context=bad))["reasons"])

    def test_request_and_evidence_context_reject_extra_dimensions(self):
        request = dict(CTX, avoid_tolls=True)
        result = self.check(ctx=request, ev=evidence(context=request))
        self.assertFalse(result["context_ttl_ok"])
        self.assertIn("route_request_context_keys_missing_or_unsupported", result["reasons"])

        extra_evidence = dict(CTX, avoid_tolls=True)
        result = self.check(ev=evidence(context=extra_evidence))
        self.assertFalse(result["context_ttl_ok"])
        self.assertIn("route_evidence_context_keys_missing_or_unsupported", result["reasons"])

    def test_departure_date_consistency_and_timezone_are_required(self):
        mismatch = dict(CTX, travel_date="2026-10-31")
        self.assertIn("route_departure_date_mismatch",
                      self.check(ctx=mismatch, ev=evidence(context=mismatch))["reasons"])
        naive = dict(CTX, departure_at="2026-10-30T10:30:00")
        self.assertIn("route_departure_context_invalid",
                      self.check(ctx=naive, ev=evidence(context=naive))["reasons"])

    def test_expiry_boundary_future_observation_and_nonpositive_ttl_rejected(self):
        self.assertIn("route_evidence_expired",
                      self.check(ev=evidence(valid_until=NOW))["reasons"])
        future = evidence(observed_at="2026-10-30T10:01:00+08:00")
        self.assertIn("route_observation_from_future", self.check(ev=future)["reasons"])
        zero = evidence(valid_until="2026-10-30T09:55:00+08:00")
        reasons = self.check(ev=zero)["reasons"]
        self.assertIn("route_ttl_nonpositive", reasons)
        self.assertIn("route_evidence_expired", reasons)

    def test_ttl_longer_than_policy_and_invalid_clock_rejected(self):
        long = evidence(valid_until="2026-10-30T10:11:00+08:00")
        self.assertIn("route_ttl_exceeds_policy", self.check(ev=long)["reasons"])
        bad = evidence(observed_at="not-a-time")
        self.assertIn("route_clock_missing_or_invalid", self.check(ev=bad)["reasons"])
        self.assertIn("route_max_ttl_invalid", self.check(max_ttl_seconds=True)["reasons"])

    def test_malformed_objects_fail_closed(self):
        result = verify_route_context_ttl(None, evidence(), now=NOW)
        self.assertFalse(result["context_ttl_ok"])
        result = verify_route_context_ttl({"context": []}, evidence(), now=NOW)
        self.assertFalse(result["context_ttl_ok"])


if __name__ == "__main__":
    unittest.main()
