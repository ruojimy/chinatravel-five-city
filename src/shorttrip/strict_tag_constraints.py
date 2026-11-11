"""Conservative three-valued checks for explicit, reviewed TAG facts.

These operators are deliberately independent of catalog categories and planner
compilation. A caller must provide complete scoped facts and an independent
fact verifier; this module does not establish truth or feasibility.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from .strict_snapshot import strict_snapshot_equal as _strict_snapshot_equal
from .strict_scope import identifier_is_known


def evaluate_tag_constraint(
    constraint: Any,
    *,
    scope_items: Sequence[str],
    tag_facts: Sequence[Mapping[str, Any]],
    condition_facts: Sequence[Mapping[str, Any]] = (),
    fact_verifier: Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None = None,
    scope_verifier: Callable[[Mapping[str, Any], Sequence[str]], Any] | None = None,
) -> dict[str, Any]:
    """Evaluate isolated inputs; invalidate results if caller objects change."""
    original = (constraint, scope_items, tag_facts, condition_facts)
    def changed_result():
        strength = constraint.get('strength') if isinstance(constraint, Mapping) else None
        return {'state':'unknown', 'hard_state':'unknown' if strength == 'hard' else 'not_applicable',
                'soft_state':'unknown' if strength == 'soft' else 'not_applicable',
                'condition_state':'unknown', 'quantifier':None,
                'reasons':['tag_original_inputs_mutated_or_unavailable'],
                'execution_confirmed':False, 'truth_certified':False}
    try:
        snapshot = copy.deepcopy(original)
        isolated = copy.deepcopy(snapshot)
    except Exception:
        return changed_result()
    result = _evaluate_tag_constraint(isolated[0], scope_items=isolated[1],
        tag_facts=isolated[2], condition_facts=isolated[3],
        fact_verifier=fact_verifier, scope_verifier=scope_verifier)
    return result if _strict_snapshot_equal(original, snapshot) else changed_result()


def _evaluate_tag_constraint(
    constraint: Any, *, scope_items: Sequence[str], tag_facts: Sequence[Mapping[str, Any]],
    condition_facts: Sequence[Mapping[str, Any]] = (), fact_verifier=None, scope_verifier=None,
) -> dict[str, Any]:
    """Evaluate a single tag constraint with separate hard and soft results.

    Scope must explicitly contain ``domain='trip'`` and ``quantifier='all'`` or
    ``'any'``. For ``all``, the predicate must hold for every selected scope
    item; for ``any``, it must hold for at least one. In particular, an
    ``exclude_tag`` with ``any`` means at least one item is tag-free, which is
    weaker than excluding the tag from the entire trip; choose ``all`` for the
    latter intent. All scope items need verified facts even for ``any``.

    A separate ``scope_verifier(constraint, scope_items)`` must return literal
    ``True`` to attest that the supplied item inventory is complete. When
    ``scope.item_kind`` is present, it must attest the complete inventory after
    filtering the selected trip items to that exact kind. Per-fact verification
    cannot establish inventory completeness or item kind membership.

    Tag facts have ``item_id``, ``tag``, ``present``, and ``scope={'domain':
    'trip'}`` for legacy broad scopes. Kind-scoped facts must additionally
    carry the exact ``item_kind`` on both the fact and its scope. A condition
    fact has ``key``, ``value`` and trip scope. The verifier is called
    separately for every relevant fact and must return literal ``True``.
    Embedded booleans or catalog categories do not count as verification.
    """
    reasons: list[str] = []
    result = {"state": "unknown", "hard_state": "not_applicable",
              "soft_state": "not_applicable", "condition_state": "not_applicable",
              "quantifier": None, "reasons": reasons,
              "execution_confirmed": False, "truth_certified": False}

    if not isinstance(constraint, Mapping):
        return _unknown(result, "constraint_not_object")
    if constraint.get("strength") == "hard":
        result["hard_state"] = "unknown"
    elif constraint.get("strength") == "soft":
        result["soft_state"] = "unknown"
    expression = constraint.get("expression")
    if not isinstance(expression, Mapping) or not isinstance(expression.get("args"), Mapping):
        return _unknown(result, "expression_or_args_missing")
    op, args = expression.get("op"), expression["args"]
    if op == "conditional_prefer_tag":
        result["condition_state"] = "unknown"
    if op not in {"prefer_tag", "conditional_prefer_tag", "exclude_tag"}:
        return _unknown(result, "operator_unsupported")
    scope = constraint.get("scope")
    if not isinstance(scope, Mapping) or scope.get("domain") != "trip":
        return _unknown(result, "trip_scope_missing_or_invalid")
    if set(scope) not in ({"domain", "quantifier"}, {"domain", "quantifier", "item_kind"}):
        return _unknown(result, "trip_scope_has_unsupported_dimensions")
    quantifier = scope.get("quantifier")
    if quantifier not in {"all", "any"}:
        return _unknown(result, "trip_scope_quantifier_underspecified")
    item_kind = scope.get("item_kind")
    if "item_kind" in scope:
        from .collection_task_schema import KINDS
        if not isinstance(item_kind, str) or item_kind not in KINDS:
            return _unknown(result, "trip_scope_item_kind_invalid")
    result["quantifier"] = quantifier
    if not isinstance(scope_items, Sequence) or isinstance(scope_items, (str, bytes)) or not scope_items:
        return _unknown(result, "scope_items_missing")
    if any(not identifier_is_known(item) for item in scope_items) or len(set(scope_items)) != len(scope_items):
        return _unknown(result, "scope_items_invalid_or_duplicated")
    checked_items = tuple(scope_items)
    if not callable(scope_verifier):
        return _unknown(result, "independent_scope_verifier_required")
    try:
        constraint_copy = copy.deepcopy(dict(constraint))
        items_copy = list(checked_items)
        constraint_snapshot = copy.deepcopy(constraint_copy)
        items_snapshot = list(items_copy)
        scope_verified = scope_verifier(constraint_copy, items_copy) is True
    except Exception:
        constraint_snapshot = items_snapshot = None
        scope_verified = False
    if (not scope_verified or not _strict_snapshot_equal(constraint_snapshot, constraint_copy) or
            not _strict_snapshot_equal(items_snapshot, items_copy)):
        return _unknown(result, "independent_scope_verification_failed")
    if not callable(fact_verifier):
        return _unknown(result, "independent_fact_verifier_required")

    strength = constraint.get("strength")
    if op in {"prefer_tag", "conditional_prefer_tag"} and strength != "soft":
        return _unknown(result, "preference_strength_must_be_soft")
    if op == "exclude_tag" and strength != "hard":
        return _unknown(result, "exclusion_strength_must_be_hard")

    if op == "conditional_prefer_tag":
        if set(args) != {"if", "prefer"}:
            return _unknown(result, "conditional_expression_has_unsupported_dimensions")
        condition = args.get("if")
        preferred = args.get("prefer")
        if not isinstance(condition, Mapping) or len(condition) != 1 or not isinstance(preferred, Mapping) or len(preferred) != 1:
            return _unknown(result, "conditional_expression_malformed")
        key, expected_condition = next(iter(condition.items()))
        tag = _tag_value(next(iter(preferred.items())))
        if not isinstance(key, str) or not key.strip() or tag is None or not _valid_scalar(expected_condition):
            return _unknown(result, "conditional_expression_malformed")
        condition_fact, why = _verified_condition(constraint, condition_facts, key, scope, fact_verifier)
        if condition_fact is None:
            return _unknown(result, why)
        if not _scalar_compatible(condition_fact["value"], expected_condition):
            return _unknown(result, "condition_fact_expected_type_mismatch")
        result["condition_state"] = "true" if _scalar_equal(condition_fact["value"], expected_condition) else "false"
        if result["condition_state"] == "false":
            result["state"] = result["soft_state"] = "not_applicable"
            reasons.append("condition_verified_false_preference_not_triggered")
            return result
        verdict, why = _tag_predicate(constraint, tag_facts, checked_items, tag, quantifier, fact_verifier)
        if verdict is None:
            return _unknown(result, why)
        result["state"] = result["soft_state"] = "satisfied" if verdict else "unsatisfied"
        reasons.append("verified_conditional_preference_" + result["soft_state"])
        return result

    tag = args.get("tag")
    if set(args) != {"tag"} or not identifier_is_known(tag):
        return _unknown(result, "tag_missing_or_invalid")
    verdict, why = _tag_predicate(constraint, tag_facts, checked_items, tag, quantifier, fact_verifier)
    if verdict is None:
        return _unknown(result, why)
    if op == "prefer_tag":
        result["soft_state"] = result["state"] = "satisfied" if verdict else "unsatisfied"
        reasons.append("verified_soft_preference_" + result["soft_state"])
    else:
        result["hard_state"] = result["state"] = "pass" if verdict else "fail"
        reasons.append("verified_hard_exclusion_" + result["hard_state"])
    return result


def _tag_value(pair: tuple[Any, Any]) -> str | None:
    key, value = pair
    if not identifier_is_known(key) or not identifier_is_known(value):
        return None
    return value if key == "tag" else f"{key}:{value}"


def _tag_predicate(constraint: Mapping[str, Any], facts: Sequence[Mapping[str, Any]],
                   scope_items: Sequence[str], tag: str, quantifier: str,
                   verifier: Callable[[Mapping[str, Any], Mapping[str, Any]], Any]) -> tuple[bool | None, str]:
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        return None, "tag_facts_not_sequence"
    relevant: dict[str, Mapping[str, Any]] = {}
    for fact in facts:
        if not isinstance(fact, Mapping):
            return None, "tag_fact_not_object"
        if fact.get("tag") != tag:
            continue
        item = fact.get("item_id")
        if not identifier_is_known(item):
            return None, "tag_fact_item_id_invalid"
        if item not in scope_items:
            # Facts outside the requested scope are never allowed to satisfy it.
            continue
        if item in relevant:
            return None, "duplicate_tag_fact_for_scope_item"
        expected_scope = ({"domain": "trip", "item_kind": constraint["scope"]["item_kind"]}
                          if "item_kind" in constraint["scope"] else {"domain": "trip"})
        if (type(fact.get("present")) is not bool or fact.get("scope") != expected_scope
                or ("item_kind" in constraint["scope"]
                    and fact.get("item_kind") != constraint["scope"]["item_kind"])):
            return None, "tag_fact_value_or_scope_invalid"
        snapshot = (fact.get("item_id"), fact.get("present"), copy.deepcopy(fact.get("scope")),
                    fact.get("item_kind"), fact.get("tag"))
        try:
            constraint_copy = copy.deepcopy(dict(constraint))
            fact_copy = copy.deepcopy(dict(fact))
            constraint_snapshot = copy.deepcopy(constraint_copy)
            fact_snapshot = copy.deepcopy(fact_copy)
            verified = verifier(constraint_copy, fact_copy) is True
        except Exception:
            constraint_snapshot = fact_snapshot = None
            verified = False
        if not verified:
            return None, "independent_tag_fact_verification_failed"
        if not _strict_snapshot_equal(constraint_snapshot, constraint_copy):
            return None, "constraint_mutated_during_verification"
        if not _strict_snapshot_equal(fact_snapshot, fact_copy):
            return None, "tag_fact_mutated_during_verification"
        if snapshot != (fact.get("item_id"), fact.get("present"), fact.get("scope"),
                        fact.get("item_kind"), fact.get("tag")):
            return None, "tag_fact_mutated_during_verification"
        relevant[item] = {"present": snapshot[1]}
    if set(relevant) != set(scope_items):
        return None, "tag_fact_scope_incomplete"
    present = [fact["present"] for fact in (relevant[item] for item in scope_items)]
    if constraint["expression"]["op"] == "exclude_tag":
        predicate = [not x for x in present]
    else:
        predicate = present
    return (all(predicate) if quantifier == "all" else any(predicate)), ""


def _verified_condition(constraint: Mapping[str, Any], facts: Sequence[Mapping[str, Any]],
                        key: str, scope: Mapping[str, Any],
                        verifier: Callable[[Mapping[str, Any], Mapping[str, Any]], Any]) -> tuple[Mapping[str, Any] | None, str]:
    if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes)):
        return None, "condition_facts_not_sequence"
    if any(not isinstance(fact, Mapping) for fact in facts):
        return None, "condition_fact_not_object"
    matched = [fact for fact in facts if fact.get("key") == key]
    if len(matched) != 1:
        return None, "condition_fact_missing_or_duplicated"
    fact = matched[0]
    value = fact.get("value")
    unknown_values = {"", "unknown", "unspecified", "not_known", "n/a", "未知", "不明"}
    if (fact.get("scope") != {"domain": "trip"}
            or value is None
            or not _valid_scalar(value)
            or (isinstance(value, str) and value.strip().lower() in unknown_values)):
        return None, "condition_fact_scope_or_value_invalid"
    snapshot = (fact.get("key"), fact.get("value"), copy.deepcopy(fact.get("scope")))
    try:
        constraint_copy = copy.deepcopy(dict(constraint))
        fact_copy = copy.deepcopy(dict(fact))
        constraint_snapshot = copy.deepcopy(constraint_copy)
        fact_snapshot = copy.deepcopy(fact_copy)
        verified = verifier(constraint_copy, fact_copy) is True
    except Exception:
        constraint_snapshot = fact_snapshot = None
        verified = False
    if not verified:
        return None, "independent_condition_fact_verification_failed"
    if not _strict_snapshot_equal(constraint_snapshot, constraint_copy):
        return None, "constraint_mutated_during_verification"
    if not _strict_snapshot_equal(fact_snapshot, fact_copy):
        return None, "condition_fact_mutated_during_verification"
    if snapshot != (fact.get("key"), fact.get("value"), fact.get("scope")):
        return None, "condition_fact_mutated_during_verification"
    return fact, ""


def _valid_scalar(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if type(value) in (int, bool):
        return True
    if type(value) is float:
        import math
        return math.isfinite(value)
    return False


def _scalar_equal(left: Any, right: Any) -> bool:
    # Python considers True == 1; condition domains must keep booleans distinct
    # from numeric values. Integer/float equality remains numeric equality.
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool and left is right
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    return type(left) is str and type(right) is str and left == right


def _scalar_compatible(left: Any, right: Any) -> bool:
    if type(left) is bool or type(right) is bool:
        return type(left) is bool and type(right) is bool
    if type(left) in (int, float) or type(right) in (int, float):
        return type(left) in (int, float) and type(right) in (int, float)
    return type(left) is str and type(right) is str


def _unknown(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["state"] = "unknown"
    if result["hard_state"] != "not_applicable":
        result["hard_state"] = "unknown"
    if result["soft_state"] != "not_applicable":
        result["soft_state"] = "unknown"
    if result["condition_state"] not in {"not_applicable", "true", "false"}:
        result["condition_state"] = "unknown"
    result["reasons"].append(reason)
    return result
