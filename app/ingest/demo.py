"""데모 데이터: demo 사용자의 관심종목 8건과 모의 포트폴리오 2개(KRW·USD 혼합).

포트폴리오는 PortfolioService를 거쳐 만든다 → 담기 기준가·환율 저장, 시드 초과 검증이 실제 경로와 같다.
이미 같은 이름의 포트폴리오가 있으면 건너뛴다(재실행 안전). 시세가 없는 종목(샘플 데이터 등)은 건너뛰고 보고한다.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import Engine, select, text

from app.core.config import get_settings
from app.core.db import session_factory
from app.ingest.jobs import seed_demo_watchlist
from app.models import Portfolio, User
from app.providers.factory import Providers
from app.services.fx import FxService
from app.core.errors import Unprocessable
from app.services.portfolio import PortfolioService

log = logging.getLogger(__name__)

DEMO_PORTFOLIOS = [
    ("반도체·빅테크 성장형", 30_000_000, [
        ("KOSPI", "005930", "amount", 5_000_000, "국내 반도체 대표"),
        ("KOSPI", "000660", "weight", 15, None),
        ("NASDAQ", "NVDA", "weight", 15, None),
        ("NASDAQ", "AVGO", "amount", 3_000_000, None),
        ("NASDAQ", "MSFT", "weight", 12, None),
        ("NASDAQ", "AAPL", "quantity", 5, None),
    ]),
    ("국내 산업재 균형형", 20_000_000, [
        ("KOSPI", "005380", "weight", 15, "자동차"),
        ("KOSPI", "012450", "amount", 3_000_000, "방산"),
        ("KOSPI", "005490", "amount", 2_000_000, "철강"),
        ("KOSPI", "207940", "quantity", 1, "바이오"),
        ("NASDAQ", "TSLA", "weight", 10, None),
    ]),
]


def seed_demo(engine: Engine, providers: Providers) -> dict:
    out = {"watchlist": seed_demo_watchlist(engine), "portfolios": [], "items": 0, "skipped": []}
    fx = FxService(engine, providers.fx, get_settings().refresh_ttl_hours)
    with session_factory(engine)() as db:
        uid = db.execute(select(User.user_id).where(User.nickname == "demo")).scalar_one()
        svc = PortfolioService(db, fx)
        for name, seed, items in DEMO_PORTFOLIOS:
            if db.execute(select(Portfolio).where(Portfolio.user_id == uid, Portfolio.name == name)).scalar():
                log.info("이미 있음: %s", name)
                continue
            priced = set(db.execute(text("""SELECT m.code, s.ticker FROM v_latest_price lp JOIN stocks s USING (stock_id)
                                            JOIN markets m ON m.market_id = s.market_id""")).all())
            if not any((mk, tk) in priced for mk, tk, *_ in items):
                out["skipped"].append(f"{name}(시세 있는 종목 없음)")
                continue
            pf = svc.create(uid, name, Decimal(seed))
            for market, ticker, mode, value, memo in items:
                try:
                    svc.add_item(pf.portfolio_id, market, ticker, mode, Decimal(value), memo)
                    out["items"] += 1
                except Unprocessable as e:          # 샘플 데이터처럼 시세가 없는 종목은 건너뛴다
                    if e.code != "NO_PRICE":
                        raise
                    out["skipped"].append(f"{ticker}(시세 없음)")
            out["portfolios"].append(name)
    return out
