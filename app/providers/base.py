"""외부 데이터 소스 인터페이스.

수집 로직은 이 인터페이스에만 의존하고, 구현(pykrx·yfinance·DART·SEC)은 factory에서 고른다.
테스트는 fake 구현을 주입한다. 반환값은 전처리 전 원본에 가까운 레코드이며 금액은 Decimal이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


# ------------------------------------------------------------------ 레코드
@dataclass(frozen=True)
class StockRef:
    """수집 대상 종목 식별 정보 (universe.yaml + DB 매핑)."""
    stock_id: int
    market: str          # markets.code
    country: str         # KR / US
    ticker: str
    yf_symbol: str
    timezone: str
    corp_code: str | None = None
    cik: str | None = None


@dataclass(frozen=True)
class IndexRef:
    index_id: int
    code: str
    country: str
    timezone: str
    pykrx_code: str | None
    yf_symbol: str | None


@dataclass
class Bar:
    trade_date: date                 # 시장 현지 날짜
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None = None


@dataclass
class FxPoint:
    rate_at: datetime                # tz-aware
    usd_krw: Decimal | None


@dataclass
class Valuation:
    as_of: date
    per: Decimal | None = None
    pbr: Decimal | None = None
    eps: Decimal | None = None
    bps: Decimal | None = None
    market_cap: Decimal | None = None
    shares_outstanding: int | None = None


@dataclass
class Financial:
    period_end: date
    period_type: str                 # FY
    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    total_assets: Decimal | None = None
    total_equity: Decimal | None = None
    total_debt: Decimal | None = None
    data_source: str = ""
    accounting_std: str | None = None
    notes: list[str] = field(default_factory=list)   # 대체 계정 사용 등 추적 정보


@dataclass
class Disclosure:
    rcept_no: str
    title: str
    report_type: str | None
    filed_at: datetime
    url: str | None


# ------------------------------------------------------------------ 인터페이스
class PriceProvider(Protocol):
    source: str
    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]: ...


class IndexProvider(Protocol):
    source: str
    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]: ...


class FxProvider(Protocol):
    source: str
    def get_daily_rates(self, start: date, end: date) -> list[FxPoint]: ...
    def get_current_rate(self) -> FxPoint: ...


class ValuationProvider(Protocol):
    source: str
    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]: ...


class FinancialProvider(Protocol):
    source: str
    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]: ...


class DisclosureProvider(Protocol):
    source: str
    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]: ...


class ProviderError(Exception):
    """외부 소스 호출 실패 (재시도 후에도 실패)."""
