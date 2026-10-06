"""config/universe.yaml 읽기와 DB 마스터 → Provider 참조 객체 변환."""
from __future__ import annotations

from functools import lru_cache

import yaml
from sqlalchemy import Connection, text

from app.core.config import CONFIG_DIR
from app.providers.base import IndexRef, StockRef


@lru_cache
def load_universe() -> dict:
    with open(CONFIG_DIR / "universe.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def stock_refs(conn: Connection, tickers: list[str] | None = None) -> list[StockRef]:
    yf = {(s["market"], s["ticker"]): s["yf_symbol"] for s in load_universe()["stocks"]}
    rows = conn.execute(text("""
        SELECT s.stock_id, m.code, m.country, s.ticker, m.timezone, s.corp_code, s.cik
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE s.is_active ORDER BY s.stock_id""")).all()
    refs = [StockRef(stock_id=r[0], market=r[1], country=r[2], ticker=r[3], yf_symbol=yf.get((r[1], r[3]), r[3]),
                     timezone=r[4], corp_code=r[5], cik=r[6]) for r in rows]
    return [r for r in refs if not tickers or r.ticker in tickers]


def index_refs(conn: Connection) -> list[IndexRef]:
    meta = {i["code"]: i for i in load_universe()["indices"]}
    rows = conn.execute(text("""
        SELECT i.index_id, i.code, m.country, m.timezone
        FROM indices i JOIN markets m ON m.market_id = i.market_id ORDER BY i.display_order""")).all()
    return [IndexRef(index_id=r[0], code=r[1], country=r[2], timezone=r[3],
                     pykrx_code=meta[r[1]].get("pykrx"), yf_symbol=meta[r[1]].get("yf_symbol")) for r in rows]
