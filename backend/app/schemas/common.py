"""공통 응답 타입.

금액·비율은 서버에서 Decimal로 계산하고, JSON에서는 숫자로 내보낸다(정수면 int, 아니면 float).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _num(v: Decimal | None):
    if v is None:
        return None
    return int(v) if v == v.to_integral_value() else float(v)


Num = Annotated[Decimal, PlainSerializer(_num, when_used="json")]

# ------------------------------------------------------------------ 입력 제약 (근거: ASSUMPTIONS A-112)
MARKET_PATTERN = r"^[A-Za-z]{2,10}$"                   # markets.code VARCHAR(10) — KOSPI·KOSDAQ·NASDAQ·NYSE
TICKER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,15}$"  # stocks.ticker VARCHAR(16) — 005930·AAPL·BRK.B
INT_MAX = 2_147_483_647                                # PostgreSQL INT (id·수량·정렬 순서)
MONEY_MAX = Decimal(10**15)                            # 시드·금액 상한 1,000조 원

Market = Annotated[str, Field(pattern=MARKET_PATTERN, examples=["KOSPI"])]
Ticker = Annotated[str, Field(pattern=TICKER_PATTERN, examples=["005930"])]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
