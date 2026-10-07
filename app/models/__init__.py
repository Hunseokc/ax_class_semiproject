"""SQLAlchemy ORM 모델 — db/schema.sql과 1:1 매핑 (DDL의 원본은 schema.sql)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CHAR, BigInteger, Boolean, CheckConstraint, Computed, Date, DateTime, ForeignKey, Integer, Numeric,
                        SmallInteger, String, Text, UniqueConstraint, func)
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
    market: Mapped[Market] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("market_id", "ticker"),)


class PeerGroup(Base):
    __tablename__ = "peer_groups"
    group_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


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


# ------------------------------------------------------------------ 지수·환율
class Index(Base):
    __tablename__ = "indices"
    index_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.market_id"))
    source_symbol: Mapped[str] = mapped_column(String(32))
    display_order: Mapped[int] = mapped_column(SmallInteger, server_default="0")


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


# ------------------------------------------------------------------ 사용자
class User(Base):
    __tablename__ = "users"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nickname: Mapped[str] = mapped_column(String(50), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.stock_id", ondelete="CASCADE"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())
    stock: Mapped[Stock] = relationship(lazy="joined")


class Portfolio(Base):
    __tablename__ = "portfolios"
    portfolio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    seed_krw: Mapped[Decimal] = mapped_column(Numeric(20, 0))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())     # 트리거가 갱신
    items: Mapped[list[PortfolioItem]] = relationship(back_populates="portfolio", order_by="PortfolioItem.item_id",
                                                      passive_deletes=True)
    __table_args__ = (UniqueConstraint("user_id", "name"), CheckConstraint("seed_krw > 0"))


class PortfolioItem(Base):
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


# ------------------------------------------------------------------ 파생·운영
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
