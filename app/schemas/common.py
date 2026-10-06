"""공통 응답 타입.

금액·비율은 서버에서 Decimal로 계산하고, JSON에서는 숫자로 내보낸다(정수면 int, 아니면 float).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _num(v: Decimal | None):
    if v is None:
        return None
    return int(v) if v == v.to_integral_value() else float(v)


Num = Annotated[Decimal, PlainSerializer(_num, when_used="json")]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
