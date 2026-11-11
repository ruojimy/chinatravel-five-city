"""Independently recheck a bounded finite route-domain failure certificate.

This does not certify the real world or the completeness of a user's full
travel problem. Evidence acceptance still requires a separate verifier.
"""
import copy
import itertools
import json

from .strict_route_solver import CONTEXT_FIELDS, route_evidence_gate
from .strict_snapshot import strict_snapshot_equal
from .strict_money import exact_money as _exact_duration

_MAX_ASSIGNMENTS = 10000
_MAX_CANDIDATES = 10000
_MAX_EVIDENCE = 20000
_MAX_TOTAL_LEGS = 50000
_MAX_EVIDENCE_PER_CONTEXT = 64
_MAX_CONTEXT_CHARS_TOTAL = 2_000_000


def _canonical(value):
    result = json.dumps(value, sort_keys=True, ensure_ascii=False,
                        separators=(',', ':'), allow_nan=False)
    result.encode('utf-8', errors='strict')
    return result


def _valid_limit(value):
    return _exact_duration(value) is not None


def verify_route_domain_failure(*, dimensions, candidates, evidence, now,
                                evidence_verifier=None, max_assignments=10000):
    """Independently enumerate declared choices and recheck each failed route.

    All assignments must appear exactly once, each must have all route legs
    independently qualified, and at least one leg must exceed its limit. A
    proof applies only to the exact caller-supplied domain-to-leg mapping and
    per-leg duration rules. It does not verify that the mapping represents the
    true or complete routes for each choice.
    """
    def fail(reason):
        return {'verified': False, 'reason': reason, 'proof_scope': None,
                'execution_confirmed': False}
    if (not isinstance(dimensions, dict) or not dimensions or
        type(max_assignments) is not int or max_assignments < 1 or max_assignments > _MAX_ASSIGNMENTS or
        any(not isinstance(k, str) or not k.strip() or not isinstance(v, list) or not v
            for k, v in dimensions.items()) or not isinstance(candidates, list) or
        not isinstance(evidence, list) or not callable(evidence_verifier) or
        len(candidates) > _MAX_CANDIDATES or len(evidence) > _MAX_EVIDENCE):
        return fail('invalid_domain_or_verifier')
    try:
        original_inputs = (dimensions, candidates, evidence)
        original_snapshot = copy.deepcopy(original_inputs)
    except Exception:
        return fail('route_inputs_cannot_be_snapshotted')
    size = 1
    try:
        for values in dimensions.values():
            if any(v is None or type(v) not in (str, int, float, bool) or
                   (type(v) is str and not v.strip()) for v in values):
                return fail('invalid_domain_value')
            size *= len(values)
            if size > max_assignments:
                return fail('domain_limit_exceeded')
            if any(isinstance(v, str) and len(v) > 512 for v in values):
                return fail('input_limit_exceeded')
            encoded = [_canonical(v) for v in values]
            if len(set(encoded)) != len(encoded):
                return fail('duplicate_domain_value')
        names = sorted(dimensions)
        domain = {_canonical(dict(zip(names, vals)))
                  for vals in itertools.product(*(dimensions[n] for n in names))}
        assignments = {}
        total_legs = 0
        context_chars = 0
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get('choices'), dict):
                return fail('candidate_malformed')
            key = _canonical(candidate['choices'])
            if key not in domain or key in assignments:
                return fail('candidate_outside_domain_or_duplicate')
            legs = candidate.get('legs')
            if not isinstance(legs, list) or not legs:
                return fail('candidate_legs_missing')
            total_legs += len(legs)
            if total_legs > _MAX_TOTAL_LEGS:
                return fail('input_limit_exceeded')
            for leg in legs:
                if not isinstance(leg, dict) or not _valid_route_context(leg.get('context')):
                    return fail('leg_context_malformed')
                context_chars += len(_canonical(leg['context']))
                if context_chars > _MAX_CONTEXT_CHARS_TOTAL:
                    return fail('input_limit_exceeded')
                limit = leg.get('max_duration_minutes')
                if not _valid_limit(limit):
                    return fail('leg_limit_invalid')
            assignments[key] = candidate
        if set(assignments) != domain:
            return fail('domain_not_exhaustive')
    except (ValueError, TypeError, RecursionError):
        return fail('domain_serialization_failed')
    evidence_index = {}
    try:
        for item in evidence:
            if not isinstance(item, dict) or not _valid_route_context(item.get('context')):
                return fail('evidence_malformed')
            ctx_key = _canonical(item['context'])
            context_chars += len(ctx_key)
            if context_chars > _MAX_CONTEXT_CHARS_TOTAL:
                return fail('input_limit_exceeded')
            indexed = evidence_index.setdefault(ctx_key, [])
            if len(indexed) >= _MAX_EVIDENCE_PER_CONTEXT:
                return fail('input_limit_exceeded')
            indexed.append(item)
    except (TypeError, ValueError, RecursionError):
        return fail('evidence_malformed')

    for key in sorted(domain):
        legs = assignments[key]['legs']
        failed = False
        for leg in legs:
            accepted = []
            for item in evidence_index.get(_canonical(leg['context']), []):
                gate = route_evidence_gate({'context': leg['context']}, item, now=now,
                                           evidence_verifier=evidence_verifier)
                if not strict_snapshot_equal(original_inputs, original_snapshot):
                    return fail('route_original_inputs_mutated')
                if gate['usable']:
                    accepted.append(gate['duration_minutes'])
            # Conflicting durations are unknown; do not pick the one that
            # happens to establish a violation.
            exact_accepted = [_exact_duration(value) for value in accepted]
            if not accepted or None in exact_accepted or any(value != exact_accepted[0] for value in exact_accepted):
                return fail('route_evidence_missing_or_conflicting')
            failed |= exact_accepted[0] > _exact_duration(leg['max_duration_minutes'])
        if not failed:
            return fail('candidate_not_shown_to_fail')
    return {'verified': True, 'reason': 'all_declared_assignments_fail',
            'proof_scope': 'declared_cartesian_route_domain', 'domain_size': size,
            'candidate_domain_mapping_independently_verified': False,
            'execution_confirmed': False}


def diagnose_finite_route_domain(*, dimensions, candidates, evidence, now,
                                 evidence_verifier=None, max_assignments=10000):
    """Run the candidate enumerator and independently check its failure claim.

    The returned scoped status is not a general itinerary infeasibility verdict;
    an immutable certificate and controller review are still required before
    routing it through the workflow's `infeasible_proven` category.
    """
    from .strict_route_solver import solve_finite_route_domain
    try:
        original_inputs = (dimensions, candidates, evidence)
        original_snapshot = copy.deepcopy(original_inputs)
    except Exception:
        return {'status': 'solver_incomplete', 'proof_scope': None,
                'reason': 'route_inputs_cannot_be_snapshotted', 'execution_confirmed': False}
    proof = verify_route_domain_failure(dimensions=dimensions, candidates=candidates,
        evidence=evidence, now=now, evidence_verifier=evidence_verifier,
        max_assignments=max_assignments)
    # Only run the secondary enumerator when the proof checker established a
    # fully qualified non-failing candidate. All malformed/unknown inputs stop.
    if not proof.get('verified') and proof.get('reason') != 'candidate_not_shown_to_fail':
        return {'status': 'solver_incomplete', 'proof_check': proof,
                'proof_scope': None, 'execution_confirmed': False}
    search = solve_finite_route_domain(dimensions=dimensions, candidates=candidates,
        evidence=evidence, now=now, evidence_verifier=evidence_verifier)
    if not strict_snapshot_equal(original_inputs, original_snapshot):
        return {'status': 'solver_incomplete', 'proof_scope': None,
                'reason': 'route_original_inputs_mutated', 'execution_confirmed': False}
    independently_checked = (proof.get('verified') is True and
        search.get('status') == 'solver_incomplete' and
        search.get('reason') == 'independent_infeasibility_verifier_required')
    status = ('finite_route_domain_failure_verified' if independently_checked else
              'candidate_feasible' if search.get('status') == 'candidate_feasible'
              and proof.get('reason') == 'candidate_not_shown_to_fail' else 'solver_incomplete')
    return {'status': status,
            'search': search, 'proof_check': proof,
            'proof_scope': proof.get('proof_scope') if independently_checked else None,
            'controller_certificate_issued': False, 'execution_confirmed': False}


def _valid_route_context(context):
    if not isinstance(context, dict) or set(context) != set(CONTEXT_FIELDS):
        return False
    return all(isinstance(context.get(key), str) and context[key].strip()
               and len(context[key]) <= 512
               for key in CONTEXT_FIELDS)
