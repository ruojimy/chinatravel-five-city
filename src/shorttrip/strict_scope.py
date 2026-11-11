"""Shared completeness checks for explicitly requested evidence scopes."""
from __future__ import annotations

import math
import unicodedata
from collections.abc import Mapping
from typing import Any


MAX_SCOPE_DEPTH = 128


def identifier_is_known(value: Any) -> bool:
    """Reject identity placeholders without banning literal values in other scopes."""
    if not isinstance(value, str) or not scope_is_complete({'identifier': value}):
        return False
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        return False
    return unicodedata.normalize('NFKC', value).strip().casefold() not in {
        'unresolved', 'missing', 'none', 'null', 'unknown_entity',
        'unresolved_id', 'missing_id', 'unknown_id', 'unverified', 'not verified',
        'pending', 'pending_verification', 'tbd', 'to be determined',
        'not available', 'placeholder', '未核实', '未验证', '待核验', '待确认'}


def scope_identifiers_are_known(scope: Any) -> bool:
    """Validate identity-shaped values inside an otherwise complete scope."""
    if not scope_is_complete(scope):
        return False
    def check(value):
        if isinstance(value, Mapping):
            for key, item in value.items():
                label = unicodedata.normalize('NFKC', key).strip().casefold()
                if label == 'entity' and isinstance(item, Mapping):
                    if not check(item):
                        return False
                    continue
                if label in {'id', 'uid', 'city', 'station', 'entity'} or label.endswith(
                        ('_id', '_uid', '_city', '_station')):
                    if not identifier_is_known(item):
                        return False
                elif isinstance(item, (Mapping, list, tuple)) and not check(item):
                    return False
        elif isinstance(value, (list, tuple)):
            return all(check(item) for item in value)
        return True
    try:
        return check(scope)
    except (TypeError, ValueError, RecursionError):
        return False


def scope_is_complete(scope: Any) -> bool:
    """Check a non-empty JSON-like scope for recursively missing values.

    Numeric zero and boolean false are valid values. Nulls, blank strings,
    explicit unknown markers, empty containers, unsupported objects, cycles,
    and non-finite floats fail.
    """
    if not isinstance(scope, Mapping) or not scope:
        return False
    try:
        return _value_is_complete(scope, active=set(), depth=0)
    except Exception:
        return False


def _value_is_complete(value: Any, *, active: set[int], depth: int) -> bool:
    if depth > MAX_SCOPE_DEPTH or value is None:
        return False
    if isinstance(value, str):
        normalized = unicodedata.normalize('NFKC', value).strip().casefold()
        return bool(normalized) and normalized not in {
            'unknown', 'unspecified', 'not_known', 'not known', 'n/a', '未知', '不明', '未提供'}
    if type(value) in (bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)

    if isinstance(value, Mapping):
        if not value:
            return False
        ident = id(value)
        if ident in active:
            return False
        active.add(ident)
        try:
            return all(isinstance(key, str) and key.strip()
                       and _value_is_complete(item, active=active, depth=depth + 1)
                       for key, item in value.items())
        finally:
            active.remove(ident)

    if isinstance(value, (list, tuple)):
        if not value:
            return False
        ident = id(value)
        if ident in active:
            return False
        active.add(ident)
        try:
            return all(_value_is_complete(item, active=active, depth=depth + 1)
                       for item in value)
        finally:
            active.remove(ident)

    return False
