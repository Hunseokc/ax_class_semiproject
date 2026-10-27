"""외부 데이터 소스 인터페이스.

수집 로직은 이 인터페이스에만 의존하고, 구현(pykrx·yfinance·DART·SEC)은 factory에서 고른다.
테스트는 fake 구현을 주입한다. 반환값은 전처리 전 원본에 가까운 레코드이며 금액은 Decimal이다.

Stage 1은 일봉·지수·환율만 둔다. 밸류에이션·재무·공시·대량 조회 인터페이스는 Stage 3에서 추가했다.
Bar·FxPoint는 Stage 2에서 preprocess.py로부터 이곳으로 옮겼다(서비스·provider가 전처리 모듈에 기대지 않도록).
Stage 5-D: 미국 기초값(ValuationBase)과 ReferenceDataProvider. 2차: 국내 업종 코드 KrReferenceProvider(KSIC).
Stage 6-B: 배당(Valuation.dps)·상장 목록(Listing·ListingProvider).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

__all__ = ["Bar", "FxPoint", "Valuation", "Financial", "Disclosure", "StockRef", "IndexRef",
           "PriceProvider", "IndexProvider", "FxProvider", "ValuationProvider", "FinancialProvider",
           "DisclosureProvider", "MarketBulkProvider", "BatchPriceProvider", "ProviderError",
           "ValuationBase", "ReferenceDataProvider", "KrReferenceProvider", "Listing", "ListingProvider"]


# ------------------------------------------------------------------ 레코드
@dataclass
class Bar:
    trade_date: date                 # 시장 현지 날짜
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None = None
    change_rate: Decimal | None = None   # 날짜별 전 종목 조회의 거래소 등락률(%, 기준가 대비) — 수정주가 이벤트 감지용


@dataclass
class FxPoint:
    rate_at: datetime                # tz-aware
    usd_krw: Decimal | None


# ── [S3-D] 밸류에이션·재무·공시 레코드 ──
@dataclass
class Valuation:
    as_of: date
    per: Decimal | None = None
    pbr: Decimal | None = None
    eps: Decimal | None = None
    bps: Decimal | None = None
    market_cap: Decimal | None = None
    shares_outstanding: int | None = None
    dps: Decimal | None = None       # 주당배당금(연간). 0 = 무배당, None = 미제공


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
    currency: str | None = None      # 공시 표시통화(DART 행의 currency). 원화가 아니면 적재 때 결산일 환율로 환산(D-026)
    fx_rate: Decimal | None = None   # 환산에 쓴 환율(환산하지 않았으면 None)


# ── [S5-D] 미국 밸류에이션 기초값 ──
@dataclass(frozen=True)
class ValuationBase:
    """미국 밸류에이션 기초값: PER·PBR·시가총액·배당수익률을 '기초값 × 종가'로 계산할 때 쓴다."""
    shares_outstanding: int | None
    shares_as_of: date | None
    dps: Decimal | None = None
    dps_period_end: date | None = None


@dataclass
class Disclosure:
    rcept_no: str
    title: str
    report_type: str | None
    filed_at: datetime
    url: str | None


# ── [S6-B] 상장 목록 레코드 ──
@dataclass(frozen=True)
class Listing:
    """상장 보통주 목록 1행 (검색용 마스터). 상세 데이터는 종목을 열 때 받는다."""
    market: str                      # markets.code
    ticker: str
    name: str
    name_en: str | None = None
    cik: str | None = None           # US: SEC 목록에 함께 온다


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


# ── [S3-D] 밸류에이션·재무·공시·대량 조회 인터페이스 ──
class ValuationProvider(Protocol):
    source: str
    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]: ...


class FinancialProvider(Protocol):
    source: str
    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]: ...


class DisclosureProvider(Protocol):
    source: str
    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]: ...


class MarketBulkProvider(Protocol):
    """국내: 날짜 하나에 전 종목 (호출 1회). 수정주가가 아니므로 증분에만 쓰고 이벤트는 등락률로 감지한다."""
    source: str
    def get_bars_by_date(self, day: date) -> dict[str, Bar]: ...
    def get_valuations_by_date(self, day: date) -> dict[str, Valuation]: ...


class BatchPriceProvider(Protocol):
    """미국: 여러 종목 일봉을 한 번에(묶음 다운로드)."""
    source: str
    def get_daily_prices_batch(self, stocks: list[StockRef], start: date, end: date) -> dict[str, list[Bar]]: ...


# ── [S5-D] 미국 참조 데이터 ──
class ReferenceDataProvider(Protocol):
    """미국 참조 데이터(SEC): 시장 전체 발행주식수, 업종 SIC, 밸류에이션 기초값."""
    source: str
    def get_shares_frame(self, as_of: date) -> dict[str, int]: ...
    def get_sic(self, cik: str) -> tuple[int | None, str | None]: ...
    def get_valuation_base(self, stock: StockRef) -> ValuationBase: ...


class KrReferenceProvider(Protocol):
    """국내 참조 데이터(DART 기업개황): 업종 코드 KSIC."""
    source: str
    def get_ksic(self, corp_code: str) -> str | None: ...


# ── [S6-B] 상장 목록 ──
class ListingProvider(Protocol):
    source: str
    def get_listed_stocks(self, as_of: date) -> list[Listing]: ...


class ProviderError(Exception):
    """외부 소스 호출 실패 (재시도 후에도 실패)."""
