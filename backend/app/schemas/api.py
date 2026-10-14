"""요청·응답 스키마 (Swagger 문서의 근거).

공유 파일: 각 팀원은 자기 구역(`# ── [S{단계}-{팀원}] ... ──`) 아래에만 추가한다. 다른 구역은 수정하지 않는다.
구역에서 필요한 import(date·Decimal·Field·Num·Market·Ticker 등)는 이 파일 맨 위에 추가한다.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import Market, Num, Schema, Ticker


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
# Stage 1에서 뺀 칸: 지수·환율의 52주 범위·장 상태, 리스트·상세의 매력도(score·preset)·관심(is_watched)·비교군(coverage·detail_status)·업종(sector·industry)

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


class StockListOut(Schema):
    total: int
    limit: int
    offset: int
    sort: str
    order: str
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
    groups: list[GroupRef]                   # 소속 경쟁 그룹(없으면 빈 목록)


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
# Stage 2에서 뺀 칸: 카드의 매력도(score)·메모·목표가·괴리율(target_gap)·updated_at, 목록의 preset, 메모·목표가 수정 요청(PUT)

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


class WatchlistOut(Schema):
    user_id: int
    count: int
    items: list[WatchlistCard]

# ── [S2-C] portfolios ─────────────────────────────────────────────

# ── [S3-B] financials·disclosures ─────────────────────────────────

# ── [S4-A] 매력도·프리셋 ──────────────────────────────────────────

# ── [S4-B] 비교군·분석 ────────────────────────────────────────────

# ── [S5] 메모·통계·검색·홈 위젯 ───────────────────────────────────
