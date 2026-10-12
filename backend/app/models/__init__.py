"""SQLAlchemy ORM 모델 — db/schema.sql과 1:1 매핑 (DDL의 원본은 schema.sql).

Stage 1 테이블만 정의한다. 이후 단계 테이블은 D가 단계 시작 시 schema.sql과 함께 추가한다.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (CHAR, BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric,
                        SmallInteger, String, Text, UniqueConstraint)
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
