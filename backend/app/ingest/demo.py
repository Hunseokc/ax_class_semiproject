"""데모 데이터: demo 사용자의 관심종목 8건과 모의 포트폴리오 2개(KRW·USD 혼합).

포트폴리오는 PortfolioService를 거쳐 만든다 → 담기 기준가·환율 저장, 시드 초과 검증이 실제 경로와 같다.
이미 같은 이름의 포트폴리오가 있으면 건너뛴다(재실행 안전). 시세가 없는 종목(샘플 데이터 등)은 건너뛰고 보고한다.
Stage 4 껍데기: 매력도 시드 점수(seed_demo_scores)도 함께 넣는다.
"""
from __future__ import annotations

import logging
from datetime import datetime
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
from app.services.scoring import METRICS, SEOUL

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
    out = {"watchlist": seed_demo_watchlist(engine), "portfolios": [], "items": 0, "skipped": [],
           "scores": seed_demo_scores(engine)}
    fx = FxService(engine, providers.fx, get_settings().refresh_ttl_hours)
    with session_factory(engine)() as db:
        uid = db.execute(select(User.user_id).where(User.nickname == "demo")).scalar_one()
        svc = PortfolioService(db, fx, uid)
        for name, seed, items in DEMO_PORTFOLIOS:
            if db.execute(select(Portfolio).where(Portfolio.user_id == uid, Portfolio.name == name)).scalar():
                log.info("이미 있음: %s", name)
                continue
            priced = set(db.execute(text("""SELECT m.code, s.ticker FROM v_latest_price lp JOIN stocks s USING (stock_id)
                                            JOIN markets m ON m.market_id = s.market_id""")).all())
            if not any((mk, tk) in priced for mk, tk, *_ in items):
                out["skipped"].append(f"{name}(시세 있는 종목 없음)")
                continue
            pf = svc.create(name, Decimal(seed))
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


# ── [S4-D] 매력도 시드 점수 ──
# TODO(껍데기): D — C의 compute_scores(services/scoring.py)가 머지되면 이 함수와 seed_demo의 "scores" 줄을 지운다.
#   그때부터는 `python -m app.ingest scores`가 실제 점수를 만든다. 지금은 B·A가 쓸 stock_metric_values·stock_scores 행을
#   오늘(서울) as_of로 넣는다: 시세가 있는 종목 × 지표 9개의 Z는 stock_id로 정한 -2.0~2.0 고정값(원값 NULL),
#   팩터 점수 = 지표 Z 평균, 종합 = 프리셋 가중합(프리셋마다 점수가 달라짐), 점수 = 50 + 20 × 종합(0~100로 자름).
def seed_demo_scores(engine: Engine) -> int:
    as_of = datetime.now(SEOUL).date()
    metrics = [{"metric": k, "factor": m.factor, "n": i} for i, (k, m) in enumerate(METRICS.items(), start=1)]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM stock_scores WHERE as_of = :d"), {"d": as_of})
        conn.execute(text("DELETE FROM stock_metric_values WHERE as_of = :d"), {"d": as_of})
        conn.execute(text("""
            INSERT INTO stock_metric_values (stock_id, as_of, metric, factor, raw_value, z_raw, z_adj)
            SELECT lp.stock_id, :d, :metric, :factor, NULL, z.z, z.z
            FROM v_latest_price lp
            JOIN stocks s ON s.stock_id = lp.stock_id AND s.is_active
            CROSS JOIN LATERAL (SELECT ROUND(((lp.stock_id * 7 + :n * 13) % 41 - 20) / 10.0, 4) AS z) z"""),
            [{**m, "d": as_of} for m in metrics])
        return conn.execute(text("""
            WITH f AS (
                SELECT stock_id, factor, AVG(z_adj) AS sc FROM stock_metric_values WHERE as_of = :d GROUP BY stock_id, factor
            ), p AS (
                SELECT f.stock_id, w.preset_id,
                       MAX(f.sc) FILTER (WHERE f.factor = 'value')    AS value_score,
                       MAX(f.sc) FILTER (WHERE f.factor = 'quality')  AS quality_score,
                       MAX(f.sc) FILTER (WHERE f.factor = 'growth')   AS growth_score,
                       MAX(f.sc) FILTER (WHERE f.factor = 'safety')   AS safety_score,
                       MAX(f.sc) FILTER (WHERE f.factor = 'momentum') AS momentum_score,
                       SUM(w.weight * f.sc) AS composite
                FROM f JOIN scoring_weights w ON w.factor = f.factor
                GROUP BY f.stock_id, w.preset_id
            )
            INSERT INTO stock_scores (stock_id, as_of, preset_id, value_score, quality_score, growth_score, safety_score,
                                      momentum_score, composite, score, factor_coverage, data_quality)
            SELECT p.stock_id, :d, p.preset_id, p.value_score, p.quality_score, p.growth_score, p.safety_score,
                   p.momentum_score, p.composite, LEAST(100, GREATEST(0, ROUND(50 + 20 * p.composite, 2))), 5,
                   jsonb_build_object('partition', m.country, 'notes', jsonb_build_array('seed-demo 시드 값(껍데기)'))
            FROM p
            JOIN stocks s  ON s.stock_id = p.stock_id
            JOIN markets m ON m.market_id = s.market_id"""), {"d": as_of}).rowcount
