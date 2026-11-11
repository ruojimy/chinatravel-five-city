"""Exact nonnegative monetary values; binary floats lose source precision."""
import re
from decimal import Decimal, InvalidOperation

_DECIMAL = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z')


def exact_money(value):
    """Return Decimal for an integer or canonical decimal text, otherwise None.

    A float cannot preserve the original JSON token and is deliberately rejected.
    Text is bounded to prevent unbounded parsing from untrusted inputs.
    """
    try:
        if (type(value) is int and value >= 0 and value.bit_length() <= 3402
                and len(str(value)) <= 1024):
            return Decimal(value)
        if isinstance(value, str) and len(value) <= 1024 and _DECIMAL.fullmatch(value):
            return Decimal(value)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    return None
