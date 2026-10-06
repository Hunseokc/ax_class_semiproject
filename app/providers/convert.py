"""원본 값 → Decimal/int 변환 (NaN·빈 문자열·'-'은 None)."""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from typing import Any


def to_dec(v: Any, places: int | None = None) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.replace(",", "").strip()
        if v in ("", "-", "N/A"):
            return None
    elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite():
        return None
    return round(d, places) if places is not None else d


def to_int(v: Any) -> int | None:
    d = to_dec(v)
    return int(d) if d is not None else None


def positive_or_none(d: Decimal | None) -> Decimal | None:
    return d if d is not None and d > 0 else None
