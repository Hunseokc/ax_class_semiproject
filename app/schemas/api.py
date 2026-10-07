"""요청·응답 스키마 (Swagger 문서의 근거)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import Num, Schema


# ------------------------------------------------------------------ 시장
class SparkPoint(Schema):
    date: date
    close: Num


class IndexOut(Schema):
    code: str
    name: str
    country: str | None
    currency: str | None
    as_of: date | None
    close: Num | None
    prev_close: Num | None
    change: Num | None
    change_rate: Num | None
    sparkline: list[SparkPoint]


class IndicesOut(Schema):
    as_of: date | None
    indices: list[IndexOut]


class FxPointOut(Schema):
    date: date
    usd_krw: Num


class FxOut(Schema):
    pair: str = "USD/KRW"
    currency: str = "KRW"
    usd_krw: Num
    rate_at: datetime
    granularity: str
    fx_stale: bool
    prev_close: Num | None
    change: Num | None
    change_rate: Num | None
    history: list[FxPointOut]
    as_of: datetime


class RefreshJobOut(Schema):
    job_type: str
    status: str
    detail: str | None = None
    last_success_at: datetime | None = None
    counts: dict[str, int] = {}


class RefreshOut(Schema):
    refreshed_at: datetime | None
    next_refresh_available_at: datetime
    ttl_hours: float
    jobs: list[RefreshJobOut]
    basis: str = "일봉 기준"


# ------------------------------------------------------------------ 종목
class StockRow(Schema):
    rank: int
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    name_en: str | None
    as_of: date | None
    close: Num | None
    change: Num | None
    change_rate: Num | None
    volume: int | None
    market_cap: Num | None
    market_cap_krw: Num | None
    score: Num | None
    is_watched: bool
    coverage: str                    # featured(노출) / benchmark(매력도 비교군 — 검색 시에만 목록에 나옴)


class StockListOut(Schema):
    total: int
    limit: int
    offset: int
    sort: str
    order: str
    preset: str
    fx_rate_at: datetime | None
    items: list[StockRow]


class GroupRef(Schema):
    group_id: int
    name: str


class StockDetailOut(Schema):
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    name_en: str | None
    corp_code: str | None
    cik: str | None
    as_of: date | None
    close: Num | None
    prev_close: Num | None
    change: Num | None
    change_rate: Num | None
    volume: int | None
    close_krw: Num | None
    fx_rate: Num | None
    fx_rate_at: datetime | None
    fx_stale: bool
    valuation_as_of: date | None
    valuation_source: str | None
    per: Num | None
    pbr: Num | None
    eps: Num | None
    bps: Num | None
    market_cap: Num | None
    market_cap_krw: Num | None
    shares_outstanding: int | None
    score: Num | None
    score_as_of: date | None
    preset: str
    groups: list[GroupRef]
    is_watched: bool
    coverage: str
    detail_status: str               # ready / loading(비교군 상세 데이터 받는 중) / failed


class Candle(Schema):
    date: date
    open: Num
    high: Num
    low: Num
    close: Num
    volume: int


class CandlesOut(Schema):
    market: str
    ticker: str
    currency: str
    range: str
    as_of: date | None
    candles: list[Candle]


class FinancialOut(Schema):
    period_end: date
    period_type: str
    revenue: Num | None
    operating_income: Num | None
    net_income: Num | None
    total_assets: Num | None
    total_equity: Num | None
    total_debt: Num | None
    operating_margin: Num | None
    roe: Num | None
    data_source: str
    accounting_std: str | None


class FinancialsOut(Schema):
    market: str
    ticker: str
    currency: str
    as_of: date | None
    items: list[FinancialOut]


class DisclosureOut(Schema):
    rcept_no: str
    title: str
    report_type: str | None
    filed_at: datetime
    url: str | None
    data_source: str


class DisclosuresOut(Schema):
    market: str
    ticker: str
    as_of: datetime | None
    items: list[DisclosureOut]


# ------------------------------------------------------------------ 관심종목
class WatchlistCreate(Schema):
    market: str = Field(examples=["KOSPI"])
    ticker: str = Field(examples=["005930"])


class WatchlistOrderItem(Schema):
    market: str
    ticker: str
    sort_order: int


class WatchlistOrder(Schema):
    items: list[WatchlistOrderItem] = Field(min_length=1)


class WatchlistCard(Schema):
    sort_order: int
    added_at: datetime
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    as_of: date | None
    close: Num | None
    change: Num | None
    change_rate: Num | None
    score: Num | None


class WatchlistOut(Schema):
    user_id: int
    preset: str
    count: int
    items: list[WatchlistCard]


# ------------------------------------------------------------------ 포트폴리오
class PortfolioCreate(Schema):
    name: str = Field(min_length=1, max_length=100, examples=["반도체 집중"])
    seed_krw: Decimal = Field(gt=0, max_digits=20, decimal_places=0, examples=[10_000_000])


class PortfolioUpdate(Schema):
    name: str = Field(min_length=1, max_length=100)
    seed_krw: Decimal = Field(gt=0, max_digits=20, decimal_places=0)


class PortfolioOut(Schema):
    portfolio_id: int
    user_id: int
    name: str
    currency: str = "KRW"
    seed_krw: Num
    used_krw: Num
    remaining_krw: Num
    item_count: int
    created_at: datetime
    updated_at: datetime


class ItemInput(Schema):
    mode: Literal["quantity", "amount", "weight"] = Field(
        description="quantity=수량(주), amount=금액(원), weight=시드 대비 비중(%)")
    value: Decimal = Field(gt=0, examples=[3_000_000])
    memo: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "quantity" and self.value != self.value.to_integral_value():
            raise ValueError("quantity 모드의 value는 정수여야 합니다")
        if self.mode == "weight" and self.value > 100:
            raise ValueError("weight 모드의 value는 0 초과 100 이하(%)여야 합니다")
        return self


class ItemCreate(ItemInput):
    market: str = Field(examples=["KOSPI"])
    ticker: str = Field(examples=["005930"])


class ItemOut(Schema):
    item_id: int
    portfolio_id: int
    stock_id: int
    market: str
    ticker: str
    name: str
    currency: str
    quantity: int
    ref_price: Num
    ref_fx_rate: Num
    ref_date: date
    cost_krw: Num
    memo: str | None
    created_at: datetime
    updated_at: datetime


class ValuedItem(Schema):
    item_id: int
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    quantity: int
    ref_price: Num
    ref_fx_rate: Num
    ref_date: date
    memo: str | None
    score: Num | None
    cost_krw: Num
    weight: Num | None = None
    current_price: Num | None
    price_date: date | None
    current_fx_rate: Num
    value_krw: Num | None
    pnl_krw: Num | None
    pnl_rate: Num | None
    local_return: Num | None
    fx_return: Num
    price_effect_krw: Num | None
    fx_effect_krw: Num | None
    groups: list[str]


class ItemsOut(Schema):
    portfolio_id: int
    currency: str = "KRW"
    fx_rate: Num | None
    fx_rate_at: datetime | None
    fx_stale: bool
    items: list[ValuedItem]


class WeightRow(Schema):
    cost_krw: Num
    weight: Num | None


class MarketWeight(WeightRow):
    country: str


class GroupWeight(WeightRow):
    group: str


class SummaryOut(Schema):
    portfolio_id: int
    name: str
    currency: str
    seed_krw: Num
    used_krw: Num
    remaining_krw: Num
    usage_rate: Num | None
    items: list[ValuedItem]
    market_weights: list[MarketWeight]
    group_weights: list[GroupWeight]
    weighted_score: Num | None
    total_value_krw: Num
    total_pnl_krw: Num
    total_pnl_rate: Num | None
    price_effect_krw: Num
    fx_effect_krw: Num
    fx_rate: Num | None
    fx_rate_at: datetime | None
    fx_stale: bool
    as_of: date | None
    disclaimer: str


class ErrorBody(Schema):
    code: str
    message: str
    detail: Any = None


class ErrorOut(Schema):
    error: ErrorBody
