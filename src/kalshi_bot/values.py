"""Strict exact values at trust boundaries; never silently round exchange data."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re

# Review #5: constants built once; these validators run hundreds of thousands
# of times per hour on the event loop. Semantics are unchanged.
_LIMIT = Decimal("1000000000000")
_CENT = Decimal("0.01")
_CONTROL = re.compile(r"[\x00-\x1f]")


class InvalidData(ValueError):
    pass


def decimal(value: object) -> Decimal:
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise InvalidData("exact decimal string, integer or Decimal required")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidData("invalid decimal") from exc
    if not result.is_finite() or abs(result) > _LIMIT:
        raise InvalidData("decimal is non-finite or outside safety range")
    # Derived Decimal accounting can carry average basis beyond wire precision.
    minimum_exponent = -60 if isinstance(value, Decimal) else -12
    if result.as_tuple().exponent < minimum_exponent:
        raise InvalidData("unsupported precision")
    return result


def count(value: object, *, zero: bool = False) -> Decimal:
    result = decimal(value)
    if result < 0 or (not zero and result == 0) or result % _CENT:
        raise InvalidData("count must be positive and aligned to 0.01")
    return result


def price(value: object) -> Decimal:
    result = decimal(value)
    if not 0 < result < 1:
        raise InvalidData("price must be strictly between zero and one")
    return result


def integer(value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidData("integer outside allowed bounds")
    return value


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InvalidData("timezone-aware datetime required")
    if value.tzinfo is timezone.utc:
        return value  # Already UTC: astimezone would only copy it.
    return value.astimezone(timezone.utc)


def identity(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 200 or _CONTROL.search(value):
        raise InvalidData("invalid identifier")
    return value
