"""Fail-closed type-sensitive comparison for verifier snapshots."""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


MAX_SNAPSHOT_DEPTH = 256


def strict_snapshot_equal(left: Any, right: Any) -> bool:
    """Compare copied values without coercion, cycles, or unbounded recursion.

    Container and scalar types must match exactly, so ``True`` is not equal to
    ``1``. Mappings ignore insertion order; lists/tuples and sets are compared
    by shape and value. Same-type leaves use their native equality, preserving
    normal ``datetime`` equality. Unchanged NaNs compare equal for snapshot
    purposes; consumers still validate whether NaN is permitted. Cycles,
    excessive depth, and comparison exceptions fail closed.
    """
    try:
        return _equal(left, right, active=set(), depth=0)
    except Exception:
        return False


def _equal(left: Any, right: Any, *, active: set[tuple[int, int]], depth: int) -> bool:
    if depth > MAX_SNAPSHOT_DEPTH or type(left) is not type(right):
        return False
    if type(left) is float and math.isnan(left) and math.isnan(right):
        return True

    is_container = isinstance(left, (Mapping, list, tuple, set, frozenset))
    if not is_container:
        return left == right

    pair = (id(left), id(right))
    if pair in active:
        return False
    active.add(pair)
    try:
        if isinstance(left, Mapping):
            if len(left) != len(right):
                return False
            unmatched = list(right.items())
            for left_key, left_value in left.items():
                for index, (right_key, right_value) in enumerate(unmatched):
                    if (_equal(left_key, right_key, active=active, depth=depth + 1) and
                            _equal(left_value, right_value, active=active, depth=depth + 1)):
                        unmatched.pop(index)
                        break
                else:
                    return False
            return not unmatched

        if isinstance(left, (list, tuple)):
            return len(left) == len(right) and all(
                _equal(a, b, active=active, depth=depth + 1)
                for a, b in zip(left, right))

        if len(left) != len(right):
            return False
        unmatched = list(right)
        for value in left:
            for index, other in enumerate(unmatched):
                if _equal(value, other, active=active, depth=depth + 1):
                    unmatched.pop(index)
                    break
            else:
                return False
        return not unmatched
    finally:
        active.remove(pair)
