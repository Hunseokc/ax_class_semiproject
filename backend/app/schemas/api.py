"""요청·응답 스키마 (Swagger 문서의 근거).

공유 파일: 각 팀원은 자기 구역(`# ── [S{단계}-{팀원}] ... ──`) 아래에만 추가한다. 다른 구역은 수정하지 않는다.
구역에서 필요한 import(date·Decimal·Field·Num·Market·Ticker 등)는 이 파일 맨 위에 추가한다.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.common import INT_MAX, MONEY_MAX, Market, Num, Schema, Ticker


# ------------------------------------------------------------------ 공통 오류
class ErrorBody(Schema):
    code: str
    message: str
    detail: Any = None


class ErrorOut(Schema):
    error: ErrorBody


# ------------------------------------------------------------------ 헬스체크
class HealthOut(Schema):
    status: Literal["ok"] = "ok"


class HealthDbOut(Schema):
    status: Literal["ok"] = "ok"
    db: Literal["ok"] = "ok"


# ── [S1-B] stocks·market ──────────────────────────────────────────
# (시장 지수·환율, 종목 목록·상세·candles·peer-groups 응답)
# Stage 1에서 뺀 칸: 지수·환율의 52주 범위·장 상태, 리스트·상세의 비교군(coverage·detail_status)·업종(sector·industry)
# Stage 2에서 넣은 칸: 리스트·상세의 관심(is_watched) / Stage 4: 리스트·상세의 매력도(score·preset), 상세의 score_as_of

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
    sparkline: list[SparkPoint]              # 최근 1년 종가, 오래된 순 (일봉이 없으면 빈 목록)
    high_52w: Num | None = None              # 52주 종가 최고·최저 — 1년치가 없으면 null
    low_52w: Num | None = None
    position_52w: Num | None = None          # (현재 − 저점) / (고점 − 저점), 0~1
    session_status: Literal["today", "holiday", "previous_session"] | None = None   # 거래소 달력 기준 장 상태


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
    history: list[FxPointOut]                # 최근 1년 DAILY (오래된 순)
    as_of: datetime
    high_52w: Num | None = None              # 52주 최고·최저(현재 값 포함) — 1년치가 없으면 null
    low_52w: Num | None = None
    position_52w: Num | None = None


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
    fx_stale: bool                           # Stage 1은 DB 값만 읽어 항상 false
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
    groups: list[GroupRef]                   # 소속 경쟁 그룹(없으면 빈 목록)
    is_watched: bool
    coverage: str
    detail_status: str              # ready / loading(비교군 상세 데이터 받는 중) / failed


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

# ── [S2-B] watchlist ──────────────────────────────────────────────
# (관심종목 추가·순서 변경 요청, 카드·목록 응답. 요청에는 user_id를 받지 않는다 — 사용자는 get_current_user_id가 정한다)
# Stage 2에서 뺀 칸: 카드의 메모·목표가·괴리율(target_gap)·updated_at, 메모·목표가 수정 요청(PUT) / Stage 4: 카드의 매력도(score), 목록의 preset

# ------------------------------------------------------------------ 관심종목
class WatchlistCreate(Schema):
    market: Market
    ticker: Ticker


class WatchlistOrderItem(Schema):
    market: Market
    ticker: Ticker
    sort_order: int = Field(ge=0, le=9999)


class WatchlistOrder(Schema):
    items: list[WatchlistOrderItem] = Field(min_length=1, max_length=500)


class WatchlistCard(Schema):
    sort_order: int
    added_at: datetime
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    as_of: date | None          # 시세가 아직 없는 종목은 아래 가격 칸과 함께 None
    close: Num | None
    change: Num | None
    change_rate: Num | None
    score: Num | None
    memo: str | None = None                  # [S5] migration 004 — 메모·목표가는 PUT /watchlist/{market}/{ticker}로 수정
    target_price: Num | None = None          # 종목 통화(currency) 기준
    target_gap: Num | None = None            # (목표가 − 현재가) / 현재가
    updated_at: datetime | None = None


class WatchlistOut(Schema):
    user_id: int
    preset: str
    count: int
    items: list[WatchlistCard]

# ── [S2-C] portfolios ─────────────────────────────────────────────
# ------------------------------------------------------------------ 포트폴리오
class PortfolioCreate(Schema):
    # pattern \S: 공백만으로 된 이름 거부 / 100자: portfolios.name VARCHAR(100)
    name: str = Field(min_length=1, max_length=100, pattern=r"\S", examples=["반도체 집중"])
    seed_krw: Decimal = Field(gt=0, le=MONEY_MAX, max_digits=20, decimal_places=0, examples=[10_000_000])


class PortfolioUpdate(Schema):
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    seed_krw: Decimal = Field(gt=0, le=MONEY_MAX, max_digits=20, decimal_places=0)


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
    value: Decimal = Field(gt=0, le=MONEY_MAX, examples=[3_000_000])
    memo: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "quantity" and self.value != self.value.to_integral_value():
            raise ValueError("quantity 모드의 value는 정수여야 합니다")
        if self.mode == "quantity" and self.value > INT_MAX:
            raise ValueError(f"quantity 모드의 value는 {INT_MAX:,} 이하여야 합니다")
        if self.mode == "weight" and self.value > 100:
            raise ValueError("weight 모드의 value는 0 초과 100 이하(%)여야 합니다")
        return self


class ItemCreate(ItemInput):
    market: Market
    ticker: Ticker


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


# ── [S3-B] financials·disclosures ─────────────────────────────────
# (응답 모양은 D가 껍데기와 함께 원본 그대로 넣었다 — B는 이 클래스를 그대로 쓴다)
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


# ── [S3-D] market refresh ─────────────────────────────────────────
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


# ── [S4-A] 매력도·프리셋 ──────────────────────────────────────────

# ── [S4-B] 비교군·분석 ────────────────────────────────────────────

# ── [S5] 메모·통계·검색·홈 위젯 ───────────────────────────────────
# (관심종목 수정 요청·균등 배분 미리보기 — 요청·응답 모양은 D가 껍데기와 함께 원본 그대로 넣었다. B·C는 이 클래스를 그대로 쓴다)
class WatchlistUpdate(Schema):
    """보낸 필드만 바꾼다. null을 보내면 그 값을 지운다(A-116)."""
    memo: str | None = Field(default=None, max_length=200, description="메모(200자). 앞뒤 공백 제거, 빈 문자열은 지움")
    target_price: Decimal | None = Field(default=None, gt=0, max_digits=20, decimal_places=4,
                                         description="목표가(종목 통화 — KRW 종목은 원, USD 종목은 달러). 0 이하는 422")

    @field_validator("memo")
    @classmethod
    def _blank_memo_is_none(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set & {"memo", "target_price"}:
            raise ValueError("memo 또는 target_price 중 하나 이상을 보내야 합니다")
        return self


class StockKey(Schema):
    market: Market
    ticker: Ticker


class EqualWeightRequest(Schema):
    stocks: list[StockKey] | None = Field(default=None, min_length=1, max_length=100,
                                          description="대상 종목. 생략하면 내 관심종목 전체")
    budget_krw: Decimal | None = Field(default=None, gt=0, le=MONEY_MAX, max_digits=20, decimal_places=0,
                                       description="배분할 금액(원). 생략하면 포트폴리오 잔여 시드, 잔여 시드 초과는 409")

    @field_validator("stocks")
    @classmethod
    def _no_duplicates(cls, v: list[StockKey] | None):
        if v is not None and len({(x.market.upper(), x.ticker.upper()) for x in v}) != len(v):
            raise ValueError("같은 종목이 두 번 들어 있습니다")
        return v


class EqualWeightItem(Schema):
    market: str
    ticker: str
    name: str
    currency: str
    price: Num                       # 종목 통화 최신 종가
    price_date: date
    fx_rate: Num                     # KRW 종목은 1
    unit_cost_krw: Num               # 1주 원가(원)
    quantity: int                    # 균등 몫 ÷ 1주 원가 내림
    cost_krw: Num
    weight: Num | None               # 실제 배분 비중 = cost / total_cost


class EqualWeightSkipped(Schema):
    market: str
    ticker: str
    name: str
    reason: Literal["ALREADY_IN_PORTFOLIO", "NO_PRICE", "PRICE_ABOVE_SHARE"]
    message: str
    unit_cost_krw: Num | None = None
    share_krw: Num | None = None


class EqualWeightOut(Schema):
    portfolio_id: int
    seed_krw: Num
    used_krw: Num
    remaining_krw: Num
    budget_krw: Num
    target_count: int                # 균등 몫을 나눈 종목 수(이미 담은·시세 없는 종목 제외)
    share_krw: Num                   # 종목당 균등 몫
    items: list[EqualWeightItem]
    total_cost_krw: Num
    leftover_krw: Num                # 예산 − 총 사용 금액
    skipped: list[EqualWeightSkipped]
    fx_rate: Num | None
    fx_rate_at: datetime | None
    saved: bool = False              # 계산 전용 — 저장하려면 담기 API를 종목별로 호출


# ── [S6] 검색·홈 위젯 ─────────────────────────────────────────────
# 응답 모양은 원본 그대로 — 본문은 Stage 6 담당자(B: 검색·홈 순위, C: 섹터·심리 지수)
class HomeRankItem(Schema):
    rank: int
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    value: Num                               # 거래량 급증: 배수(2.4 = 2.4배) / 매력도: 점수(0~100)
    as_of: date | None
    is_watched: bool


class HomeRankingOut(Schema):
    kind: Literal["volume_surge", "attractiveness"]
    country: str
    preset: str | None                       # 매력도 순위일 때만
    items: list[HomeRankItem]


SessionStatus = Literal["today", "holiday", "previous_session"]


class SectorTileOut(Schema):
    code: str                                # 미국 섹터 ETF 티커 / KRX 섹터 지수 코드
    name: str
    weight: float                            # 타일 크기용 근사 비중(%) — 코드 상수
    change_pct: Num | None                   # 전일 대비 %(1.23 = 1.23%), 그날 값이 없으면 null


class SectorsOut(Schema):
    country: Literal["KR", "US"]
    available: bool                          # 저장된 값이 하나도 없으면 false('데이터 준비 중')
    as_of: date | None
    session_status: SessionStatus | None
    fetched_at: datetime | None
    sectors: list[SectorTileOut]


class SentimentPointOut(Schema):
    trade_date: date
    score: Num
    label: str


class SentimentComponentsOut(Schema):
    price_position: Num | None               # 52주 범위 안 위치
    ma_gap_score: Num | None                 # 125일 이동평균 괴리
    rsi_score: Num | None                    # RSI(14)
    vix_score: Num | None                    # VIX(미국만)


class SentimentOut(Schema):
    market: Literal["KR", "US"]
    index_code: str                          # 기준 지수 (KOSPI · SPX)
    formula_version: int
    as_of: date | None
    session_status: SessionStatus | None
    score: Num | None                        # 0~100, 높을수록 탐욕. 구성요소 2개 미만이면 null
    label: str
    components: SentimentComponentsOut
    previous: SentimentPointOut | None       # 직전 거래일
    week_ago: SentimentPointOut | None       # 5거래일 전


class SearchItem(Schema):
    stock_id: int
    market: str
    country: str
    currency: str
    ticker: str
    name: str
    name_en: str | None
    coverage: str                    # featured / benchmark / listed(상장 종목 목록 — 열면 데이터를 받는다)


class SearchOut(Schema):
    q: str
    items: list[SearchItem]
