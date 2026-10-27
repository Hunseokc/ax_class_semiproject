"""SQLAlchemy ORM 모델 — db/schema.sql과 1:1 매핑 (DDL의 원본은 schema.sql).

Stage 1 테이블 10개 + Stage 2 테이블 4개(users·watchlist_items·portfolios·portfolio_items)
+ Stage 3 테이블 2개(financial_statements·disclosures)
+ Stage 4 테이블 4개(scoring_presets·scoring_weights·stock_metric_values·stock_scores)
+ Stage 5-D 테이블 2개(data_freshness·fundamental_bases)
+ Stage 6 테이블 2개(sector_performance_daily·market_sentiment_daily)
+ 추가 기능 테이블 1개(ingest_cursor)
+ 2차 로그인 테이블 1개(user_preferences).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CHAR, BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Integer,
                        Numeric, SmallInteger, String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # schema.sql의 시각 컬럼은 모두 TIMESTAMPTZ
    type_annotation_map = {datetime: DateTime(timezone=True)}


# ------------------------------------------------------------------ 마스터
class Market(Base):
    __tablename__ = "markets"
    market_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True)
    country: Mapped[str] = mapped_column(CHAR(2))
    currency: Mapped[str] = mapped_column(CHAR(3))
    timezone: Mapped[str] = mapped_column(String(40))
    __table_args__ = (CheckConstraint("country IN ('KR','US')"), CheckConstraint("currency IN ('KRW','USD')"))


class Stock(Base):
    __tablename__ = "stocks"
    stock_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.market_id"))
    ticker: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str | None] = mapped_column(String(128))
    corp_code: Mapped[str | None] = mapped_column(String(16))
    cik: Mapped[str | None] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    coverage: Mapped[str] = mapped_column(String(10), server_default="featured")
    detail_synced_at: Mapped[datetime | None] = mapped_column()
    industry: Mapped[str | None] = mapped_column(String(64))
    sic: Mapped[int | None] = mapped_column(SmallInteger)
    ksic: Mapped[str | None] = mapped_column(String(10))          # 국내 KSIC(DART induty_code) — migration 012
    sector: Mapped[str | None] = mapped_column(String(32))
    industry_checked_at: Mapped[datetime | None] = mapped_column()
    cap_rank: Mapped[int | None] = mapped_column(Integer)          # 미국 시가총액 순위(상위 1,500개) — migration 009
    cap_ranked_at: Mapped[datetime | None] = mapped_column()
    market: Mapped[Market] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("market_id", "ticker"), CheckConstraint("coverage IN ('featured','benchmark','listed')"))


class PeerGroup(Base):
    __tablename__ = "peer_groups"
    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(10), server_default="theme")
    sector: Mapped[str | None] = mapped_column(String(32))        # 부모 섹터 — migration 012
    scoring: Mapped[str] = mapped_column(String(10), server_default="general")
    commodity_linked: Mapped[bool] = mapped_column(Boolean, server_default="false")
    __table_args__ = (CheckConstraint("kind IN ('theme','sector')"),
                      CheckConstraint("scoring IN ('general','financial','none')"))


class PeerGroupMember(Base):
    __tablename__ = "peer_group_members"
    group_id: Mapped[int] = mapped_column(ForeignKey("peer_groups.group_id", ondelete="CASCADE"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")


# ------------------------------------------------------------------ 종목별 사실
class DailyPrice(Base):
    __tablename__ = "daily_prices"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    volume: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (CheckConstraint("volume >= 0"), CheckConstraint("high >= low"), CheckConstraint("low > 0"))


class ValuationSnapshot(Base):
    __tablename__ = "valuation_snapshots"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    per: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    pbr: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    eps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    bps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    market_cap: Mapped[Decimal | None] = mapped_column(Numeric(26, 0))
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(20))
    dps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))


# ------------------------------------------------------------------ 지수·환율
class Index(Base):
    __tablename__ = "indices"
    index_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.market_id"))
    source_symbol: Mapped[str] = mapped_column(String(32))
    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    category: Mapped[str] = mapped_column(String(10), server_default="index")   # index / commodity — migration 012
    unit: Mapped[str | None] = mapped_column(String(16))
    __table_args__ = (CheckConstraint("category IN ('index','commodity')"),)


class IndexDailyPrice(Base):
    __tablename__ = "index_daily_prices"
    index_id: Mapped[int] = mapped_column(ForeignKey("indices.index_id", ondelete="CASCADE"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal] = mapped_column(Numeric(18, 4))


class FxRate(Base):
    __tablename__ = "fx_rates"
    fx_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rate_at: Mapped[datetime] = mapped_column()
    usd_krw: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    granularity: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(20), server_default="YFINANCE")
    __table_args__ = (UniqueConstraint("granularity", "rate_at"),)


# ------------------------------------------------------------------ 운영 로그
class IngestionLog(Base):
    __tablename__ = "ingestion_logs"
    log_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    job_type: Mapped[str] = mapped_column(String(30))
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.stock_id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10))
    rows_loaded: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()


# ── [S2-D] 사용자·관심종목·모의 포트폴리오 ── (updated_at은 DB 트리거 set_updated_at이 갱신한다. watchlist의 memo·target_price·updated_at은 Stage 5)
class User(Base):
    """계정 = email이 있는 사용자(비밀번호·Google 중 하나 이상, 2차 로그인). 게스트·demo는 email이 NULL."""
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str] = mapped_column(String(50), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    last_login_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (CheckConstraint("email = lower(email)"),
                      CheckConstraint("email IS NULL AND password_hash IS NULL AND google_sub IS NULL OR email IS NOT NULL "
                                      "AND (password_hash IS NOT NULL OR google_sub IS NOT NULL)", name="users_account_check"))


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    memo: Mapped[str | None] = mapped_column(String(200))
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))          # 종목 통화
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())       # 트리거가 갱신
    stock: Mapped[Stock] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint("target_price > 0"),)


class Portfolio(Base):
    __tablename__ = "portfolios"
    portfolio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    seed_krw: Mapped[Decimal] = mapped_column(Numeric(20, 0))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    items: Mapped[list[PortfolioItem]] = relationship(back_populates="portfolio", order_by="PortfolioItem.item_id",
                                                      passive_deletes=True)
    __table_args__ = (UniqueConstraint("user_id", "name"), CheckConstraint("seed_krw > 0"))


class PortfolioItem(Base):
    """ref_*는 담은 순간의 가격·환율 복사본(의도적 비정규화) — 평가손익을 가격/환율 효과로 나누는 기준."""
    __tablename__ = "portfolio_items"
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.portfolio_id", ondelete="CASCADE"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer)
    ref_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    ref_fx_rate: Mapped[Decimal] = mapped_column(Numeric(12, 4), server_default="1")
    ref_date: Mapped[date] = mapped_column(Date)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    # 생성 컬럼: 쓰기 불가, DB가 계산
    cost_krw: Mapped[Decimal] = mapped_column(Numeric(24, 2), Computed("quantity * ref_price * ref_fx_rate", persisted=True),
                                              nullable=True)
    portfolio: Mapped[Portfolio] = relationship(back_populates="items")
    stock: Mapped[Stock] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("portfolio_id", "stock_id"), CheckConstraint("quantity > 0"),
                      CheckConstraint("ref_price > 0"), CheckConstraint("ref_fx_rate > 0"))


# ── [S3-D] 재무·공시 ──
class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    fin_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"))
    period_end: Mapped[date] = mapped_column(Date)
    period_type: Mapped[str] = mapped_column(String(4))
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    operating_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    net_income: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_assets: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_equity: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    total_debt: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    data_source: Mapped[str] = mapped_column(String(20))
    accounting_std: Mapped[str | None] = mapped_column(String(20))
    currency: Mapped[str | None] = mapped_column(String(3))          # 공시 표시통화 — 금액은 환산 후(D-026)
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # 환산 환율(원화 공시면 NULL)
    __table_args__ = (UniqueConstraint("stock_id", "period_end", "period_type"),)


class Disclosure(Base):
    __tablename__ = "disclosures"
    disclosure_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"))
    rcept_no: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    report_type: Mapped[str | None] = mapped_column(String(100))
    filed_at: Mapped[datetime] = mapped_column()
    url: Mapped[str | None] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(20))


# ── [S4-D] 매력도 설정·파생 결과 ──
FACTOR_CHECK = "factor IN ('value','quality','growth','safety','momentum')"


class ScoringPreset(Base):
    __tablename__ = "scoring_presets"
    preset_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")


class ScoringWeight(Base):
    __tablename__ = "scoring_weights"
    preset_id: Mapped[int] = mapped_column(ForeignKey("scoring_presets.preset_id", ondelete="CASCADE"),
                                           primary_key=True)
    factor: Mapped[str] = mapped_column(String(12), primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    __table_args__ = (CheckConstraint(FACTOR_CHECK), CheckConstraint("weight >= 0 AND weight <= 1"))


class StockMetricValue(Base):
    __tablename__ = "stock_metric_values"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(24), primary_key=True)
    factor: Mapped[str] = mapped_column(String(12))
    raw_value: Mapped[Decimal | None] = mapped_column(Numeric)
    z_raw: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    z_adj: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    __table_args__ = (CheckConstraint(FACTOR_CHECK),)


class StockScore(Base):
    __tablename__ = "stock_scores"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    preset_id: Mapped[int] = mapped_column(ForeignKey("scoring_presets.preset_id"), primary_key=True)
    value_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    growth_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    safety_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    momentum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    composite: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    factor_coverage: Mapped[int] = mapped_column(SmallInteger)
    data_quality: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    __table_args__ = (CheckConstraint("score BETWEEN 0 AND 100"), CheckConstraint("factor_coverage BETWEEN 0 AND 5"))


# ── [S5-D] 데이터 유효기간·밸류에이션 기초값 ──
class DataFreshness(Base):
    __tablename__ = "data_freshness"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column()
    valid_until: Mapped[datetime] = mapped_column()
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(Text)


class FundamentalBase(Base):
    __tablename__ = "fundamental_bases"
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger)
    shares_as_of: Mapped[date | None] = mapped_column(Date)
    dps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    dps_period_end: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


# ── [S6-D] 홈 위젯 ──
class SectorPerformanceDaily(Base):
    """섹터 히트맵 — 섹터별 전일 대비 등락률(캐시 성격). 가중치는 app/services/sectors.py 상수."""
    __tablename__ = "sector_performance_daily"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market: Mapped[str] = mapped_column(CHAR(2))
    sector_code: Mapped[str] = mapped_column(String(16))
    sector_name: Mapped[str] = mapped_column(String(40))
    trade_date: Mapped[date] = mapped_column(Date)
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("market", "sector_code", "trade_date"), CheckConstraint("market IN ('KR','US')"))


class MarketSentimentDaily(Base):
    """시장 심리 지수(StockMind 간이 계산) — 계산식은 app/services/sentiment.py, 버전은 formula_version."""
    __tablename__ = "market_sentiment_daily"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market: Mapped[str] = mapped_column(CHAR(2))
    trade_date: Mapped[date] = mapped_column(Date)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    label: Mapped[str] = mapped_column(String(10))
    price_position: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    ma_gap_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    rsi_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    vix_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    formula_version: Mapped[int] = mapped_column(SmallInteger)
    computed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("market", "trade_date"), CheckConstraint("market IN ('KR','US')"),
                      CheckConstraint("score BETWEEN 0 AND 100"))


class IngestCursor(Base):
    """공시 목록 증분 수집 기준점 — 소스별 마지막으로 처리한 접수번호(app/ingest/jobs.py load_dart_feed)."""
    __tablename__ = "ingest_cursor"
    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_rcept_no: Mapped[str] = mapped_column(CHAR(14))
    last_rcept_dt: Mapped[date] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (CheckConstraint("last_rcept_no ~ '^[0-9]{14}$'"),)


# ── 2차 로그인 ──
class UserPreference(Base):
    """사용자별 설정(테마·투자 성향·지표 선택 등) — 키 목록은 app/services/auth.py PREF_KEYS."""
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    prefs: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (CheckConstraint("jsonb_typeof(prefs) = 'object'"),)
