"""현재가 (관심종목 카드·종목 상세 헤더 표시 전용) — 국내·미국 모두 KIS.

- 종목 상세: GET /stocks/{market}/{ticker}/quote가 열 때 바로 받는다. 같은 종목은 MAX_AGE(1분) 안이면 저장값을 쓴다
  (KIS 초당 1건 한도 보호). 받기에 실패하면 마지막 저장값을 stale로, 그것도 없으면 None → 화면은 일봉 종가를 그대로 둔다
- 관심종목: 갱신 작업 QUOTES(app/services/refresh.py, 1시간)가 누군가의 관심종목에 담긴 종목을 모두 받아 둔다
- 분석·점수·차트·포트폴리오 평가는 daily_prices(일봉)를 그대로 쓴다. 이 값은 price_quotes 표에만 저장한다
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Connection, Engine, text

from app.ingest.store import job_log
from app.ingest.universe import stock_refs
from app.providers.base import QuoteProvider, StockRef
from app.services.fx import utcnow

log = logging.getLogger(__name__)

MAX_AGE = timedelta(minutes=1)


def stored_quote(conn: Connection, stock_id: int) -> dict | None:
    row = conn.execute(text("""SELECT price, prev_close, change, change_rate, quoted_at, source
                               FROM price_quotes WHERE stock_id = :id"""), {"id": stock_id}).mappings().first()
    return dict(row) if row else None


def fetch_and_store(engine: Engine, provider: QuoteProvider, ref: StockRef, now: datetime) -> dict:
    q = provider.get_quote(ref)
    row = {"price": q.price, "prev_close": q.prev_close, "change": q.change, "change_rate": q.change_rate,
           "quoted_at": now, "source": provider.source}
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO price_quotes (stock_id, price, prev_close, change, change_rate, quoted_at, source)
            VALUES (:stock_id, :price, :prev_close, :change, :change_rate, :quoted_at, :source)
            ON CONFLICT (stock_id) DO UPDATE SET price = EXCLUDED.price, prev_close = EXCLUDED.prev_close,
              change = EXCLUDED.change, change_rate = EXCLUDED.change_rate, quoted_at = EXCLUDED.quoted_at,
              source = EXCLUDED.source"""), {"stock_id": ref.stock_id, **row})
    return row


class QuoteService:
    def __init__(self, engine: Engine, provider: QuoteProvider | None,
                 clock: Callable[[], datetime] = utcnow, max_age: timedelta = MAX_AGE):
        self.engine = engine
        self.provider = provider
        self.clock = clock
        self.max_age = max_age

    def get(self, stock_id: int) -> dict | None:
        """종목 1개 현재가. {price, prev_close, change, change_rate, quoted_at, source, stale} 또는 None."""
        now = self.clock()
        with self.engine.connect() as conn:
            row = stored_quote(conn, stock_id)
            refs = stock_refs(conn, stock_ids=[stock_id]) if self.provider else []
        if row and now - row["quoted_at"] < self.max_age:
            return {**row, "stale": False}
        if not refs:
            return {**row, "stale": True} if row else None
        try:
            return {**fetch_and_store(self.engine, self.provider, refs[0], now), "stale": False}
        except Exception:  # noqa: BLE001 — 현재가 실패는 화면이 일봉 종가로 대신한다
            log.exception("현재가 조회 실패: stock_id=%s", stock_id)
            return {**row, "stale": True} if row else None


def refresh_watchlist_quotes(engine: Engine, provider: QuoteProvider, now: datetime | None = None) -> dict[str, str]:
    """관심종목에 담긴 종목(사용자 무관, 중복 없이) 현재가를 받아 둔다. 종목별 결과는 ingestion_logs QUOTES."""
    now = now or utcnow()
    with engine.connect() as conn:
        ids = conn.execute(text("""SELECT DISTINCT w.stock_id FROM watchlist_items w
                                   JOIN stocks s ON s.stock_id = w.stock_id WHERE s.is_active""")).scalars().all()
        refs = stock_refs(conn, stock_ids=list(ids)) if ids else []
    statuses = {}
    for ref in refs:
        with job_log(engine, source=provider.source, job_type="QUOTES", stock_id=ref.stock_id, label=ref.ticker) as res:
            fetch_and_store(engine, provider, ref, now)
            res.rows = 1
        statuses[ref.ticker] = res.status
    return statuses
