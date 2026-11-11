"""Bridge strict trip-cost arithmetic to a compiled total-cost constraint.

The bridge binds cost policy to task constraint syntax, then retains the
constraint evaluator's independent fact-verifier gate. It does not certify a
trip or allow component data to redefine the task's requested budget.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import date, timedelta

from .strict_constraint_compiler import compile_constraint
from .strict_constraints import evaluate_constraint
from .strict_snapshot import strict_snapshot_equal
from .strict_trip_cost_aggregation import aggregate_trip_costs


def evaluate_cost_constraint(constraint, policy, components, *, scope,
                             evidence_verifier, inventory_verifier,
                             fact_verifier, task_context, context_verifier,
                             task_input, plan_input,
                             lodging_manifest=None,
                             lodging_claim_verifier=None,
                             lodging_inventory_verifier=None,
                             intercity_manifest=None,
                             intercity_policy_verifier=None,
                             intercity_inventory_verifier=None,
                             intercity_segment_verifier=None,
                             intercity_timetable_verifier=None,
                             intercity_fare_verifier=None,
                             existing_check=None):
    """Evaluate verified aggregate costs against one compiled budget constraint.

    ``policy`` is accepted only when categories, currency, party size, and
    limit exactly match the compiled ``total_cost_at_most`` expression.
    ``existing_check`` may carry a prior diagnostic result; an existing unknown
    is preserved and cannot be upgraded by this optional input.
    ``task_context`` is mechanically derived by the diagnosis caller from the
    task/plan and must include task UID, plan UID, target city, and all ordered
    itinerary dates. Raw task and plan objects must structurally match that
    context, and the independent verifier receives them with the constraint,
    policy, complete cost list, and requested scope.
    Monetary values are nonnegative integers or original decimal strings;
    the fact verifier receives the exact aggregate as a decimal string.
    """
    def unknown(reason, *, aggregate=None, preserve=False):
        return {"state": "unknown", "reason": reason, "aggregate": aggregate,
                "existing_unknown_preserved": preserve,
                "truth_certified": False, "real_trip_conclusion": False}

    if (isinstance(existing_check, Mapping)
            and existing_check.get("state") == "unknown"):
        return unknown("existing_unknown_preserved", preserve=True)
    if not isinstance(constraint, Mapping) or not isinstance(policy, Mapping):
        return unknown("constraint_or_policy_missing")
    try:
        protected_inputs = (constraint, policy, components, scope, task_context,
                            task_input, plan_input, lodging_manifest, intercity_manifest,
                            existing_check)
        protected_snapshot = copy.deepcopy(protected_inputs)
    except Exception:
        return unknown("cost_constraint_inputs_cannot_be_snapshotted")

    def originals_unchanged():
        return strict_snapshot_equal(protected_inputs, protected_snapshot)
    try:
        if constraint.get("compiler_status") != "supported":
            return unknown("constraint_not_compiled")
        compiled = compile_constraint(dict(constraint))
    except Exception:
        return unknown("constraint_compilation_failed")
    if compiled.get("status") != "supported":
        return unknown("constraint_compilation_failed")
    task_constraint = compiled["constraint"]
    expression = task_constraint.get("expression", {})
    args = expression.get("args") if isinstance(expression, Mapping) else None
    if expression.get("op") != "total_cost_at_most" or not isinstance(args, Mapping):
        return unknown("total_cost_constraint_required")

    context_keys = {"task_uid", "plan_uid", "target_city", "itinerary_dates"}
    if not isinstance(task_context, Mapping) or set(task_context) != context_keys:
        return unknown("cost_task_context_missing_or_malformed")
    if any(not isinstance(task_context.get(key), str) or not task_context[key].strip()
           for key in ("task_uid", "plan_uid", "target_city")):
        return unknown("cost_task_context_incomplete")
    if task_context['task_uid'] != task_context['plan_uid']:
        return unknown("cost_task_or_plan_context_mismatch")
    dates = task_context.get("itinerary_dates")
    try:
        parsed_dates = [date.fromisoformat(value) for value in dates]
    except (TypeError, ValueError):
        return unknown("cost_itinerary_dates_invalid")
    try:
        dates_valid = (isinstance(dates, list) and bool(dates) and
            all(day.isoformat() == value for day, value in zip(parsed_dates, dates)) and
            all(following == previous + timedelta(days=1)
                for previous, following in zip(parsed_dates, parsed_dates[1:])))
    except OverflowError:
        dates_valid = False
    if not dates_valid:
        return unknown("cost_itinerary_dates_incomplete_or_unordered")
    if not isinstance(task_input, Mapping) or not isinstance(plan_input, Mapping):
        return unknown("cost_task_or_plan_input_missing")
    if (task_input.get("uid") != task_context["task_uid"] or
            task_input.get("target_city") != task_context["target_city"] or
            task_input.get("start_date") != dates[0] or
            type(task_input.get("days")) is not int or task_input.get("days") != len(dates) or
            plan_input.get("uid") != task_context["plan_uid"]):
        return unknown("cost_task_or_plan_context_mismatch")
    plan_days = plan_input.get("days")
    if (not isinstance(plan_days, list) or len(plan_days) != len(dates) or
            [day.get("date") if isinstance(day, Mapping) else None for day in plan_days] != dates or
            not isinstance(plan_days[-1], Mapping) or
            plan_days[-1].get("city") != task_context["target_city"]):
        return unknown("cost_plan_dates_or_target_mismatch")
    task_constraints = task_input.get("additional_constraints")
    budget_constraints = []
    if isinstance(task_constraints, list):
        for raw_constraint in task_constraints:
            raw_expression = raw_constraint.get("expression") if isinstance(raw_constraint, Mapping) else None
            if isinstance(raw_expression, Mapping) and raw_expression.get("op") == "total_cost_at_most":
                budget_constraints.append(raw_constraint)
    if len(budget_constraints) != 1:
        return unknown("cost_task_budget_constraint_missing_or_ambiguous")
    raw_budget = budget_constraints[0]
    try:
        raw_compiled = compile_constraint(dict(raw_budget))
    except Exception:
        return unknown("cost_task_constraint_compilation_failed")
    if (raw_compiled.get("status") != "supported" or
            any(not strict_snapshot_equal(raw_budget.get(key), task_constraint.get(key))
                for key in ("id", "strength", "scope", "expression", "compiler_status"))):
        return unknown("cost_constraint_not_bound_to_task")

    # Exact binding prevents data from inventing/replacing the requested scope.
    if (not strict_snapshot_equal(policy.get("required_categories"), args.get("includes"))
            or not strict_snapshot_equal(policy.get("currency"), "CNY")
            or not strict_snapshot_equal(policy.get("currency"), task_constraint.get("scope", {}).get("currency"))
            or type(policy.get("party_size")) is not int
            or not strict_snapshot_equal(policy.get("party_size"), args.get("people"))
            or not strict_snapshot_equal(policy.get("party_size"), task_constraint.get("scope", {}).get("people"))
            or not strict_snapshot_equal(policy.get("total_limit"), args.get("CNY"))
            or not strict_snapshot_equal(
                task_constraint.get("scope"),
                {"currency": "CNY", "people": args.get("people"),
                 "unit": "total_trip_cost"})):
        return unknown("cost_policy_constraint_mismatch")

    if (not strict_snapshot_equal(policy.get("trip_scope"), dict(task_context))
            or not strict_snapshot_equal(scope, dict(task_context))):
        return unknown("cost_scope_not_bound_to_task_plan")
    if not callable(context_verifier):
        return unknown("independent_cost_context_verifier_required")
    try:
        context_inputs = copy.deepcopy((dict(task_context), dict(task_input),
                                        dict(plan_input), task_constraint,
                                        dict(policy), components, dict(scope)))
        context_before = copy.deepcopy(context_inputs)
        context_accepted = context_verifier(*context_inputs)
        if not originals_unchanged():
            return unknown("cost_constraint_original_inputs_mutated")
        if not strict_snapshot_equal(context_inputs, context_before):
            return unknown("cost_context_verifier_mutated_input")
        if context_accepted is not True:
            return unknown("cost_task_context_unverified")
    except Exception:
        return unknown("cost_context_verifier_failed")

    aggregate = aggregate_trip_costs(
        policy, components, scope=scope,
        evidence_verifier=evidence_verifier,
        inventory_verifier=inventory_verifier, plan=plan_input,
        task=task_input, lodging_manifest=lodging_manifest,
        lodging_claim_verifier=lodging_claim_verifier,
        lodging_inventory_verifier=lodging_inventory_verifier,
        intercity_manifest=intercity_manifest,
        intercity_policy_verifier=intercity_policy_verifier,
        intercity_inventory_verifier=intercity_inventory_verifier,
        intercity_segment_verifier=intercity_segment_verifier,
        intercity_timetable_verifier=intercity_timetable_verifier,
        intercity_fare_verifier=intercity_fare_verifier)
    if not originals_unchanged():
        return unknown("cost_constraint_original_inputs_mutated")
    if aggregate.get("status") != "arithmetic_evaluated":
        return unknown("cost_aggregate_unknown", aggregate=aggregate)

    # Keep the evaluated fact's context exactly in the compiler vocabulary.
    # The provenance envelope is visible to, but cannot replace, fact_verifier.
    fact = {
        "value": aggregate["total_decimal"],
        "unit": aggregate["currency"],
        "context": {"people": policy["party_size"],
                    "includes": list(policy["required_categories"])},
        "cost_aggregation": {
            "policy": copy.deepcopy(dict(policy)),
            "components": copy.deepcopy(components),
            "scope": copy.deepcopy(dict(scope)),
            "aggregate": copy.deepcopy(aggregate),
            "lodging_manifest": copy.deepcopy(lodging_manifest),
            "intercity_manifest": copy.deepcopy(intercity_manifest),
        },
    }
    evaluated = evaluate_constraint(task_constraint, fact,
                                    fact_verifier=fact_verifier)
    if not originals_unchanged():
        return unknown("cost_constraint_original_inputs_mutated")
    if evaluated.get("state") == "unknown":
        return unknown("constraint_fact_unverified:" + str(evaluated.get("reason")),
                       aggregate=aggregate)
    if isinstance(existing_check, Mapping) and existing_check.get("state") == "fail":
        return {"state": "fail", "reason": "existing_failure_preserved",
                "new_constraint_state": evaluated["state"], "aggregate": aggregate,
                "truth_certified": False, "real_trip_conclusion": False}
    expected_state = {"within_limit": "pass", "over_limit": "fail"}.get(
        aggregate.get("comparison"))
    if expected_state is None or evaluated.get("state") != expected_state:
        return unknown("aggregate_constraint_comparison_mismatch", aggregate=aggregate)
    return {"state": evaluated["state"], "reason": evaluated.get("reason"),
            "aggregate": aggregate, "fact_verifier_required": True,
            "truth_certified": False, "real_trip_conclusion": False,
            "execution_confirmed": False}

