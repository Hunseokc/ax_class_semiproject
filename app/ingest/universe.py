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


def yf_symbol(market: str, ticker: str) -> str:
    """yfinance 심볼: 코스피 .KS, 코스닥 .KQ, 미국은 티커 그대로."""
    return {"KOSPI": f"{ticker}.KS", "KOSDAQ": f"{ticker}.KQ"}.get(market, ticker)


# 자주 갱신(4시간)할 종목 = 노출 종목 + 관심종목·포트폴리오에 담긴 종목
FREQUENT_SQL = """(s.coverage = 'featured'
    OR EXISTS (SELECT 1 FROM watchlist_items w WHERE w.stock_id = s.stock_id)
    OR EXISTS (SELECT 1 FROM portfolio_items pi WHERE pi.stock_id = s.stock_id))"""
SCOPES = {"all": "true", "frequent": FREQUENT_SQL, "benchmark": f"NOT {FREQUENT_SQL}"}


def stock_refs(conn: Connection, tickers: list[str] | None = None, *, scope: str = "frequent",
               stock_ids: list[int] | None = None) -> list[StockRef]:
    """수집 대상(활성 종목). scope: frequent(4시간 갱신) / benchmark(그 밖의 비교군, 1일 갱신) / all.
    tickers·stock_ids를 주면 scope와 관계없이 그 종목만(stock_ids는 비활성 종목도 포함)."""
    if stock_ids:
        where, params = "s.stock_id = ANY(:ids)", {"ids": stock_ids}
    elif tickers:
        where, params = "s.is_active AND s.ticker = ANY(:tickers)", {"tickers": tickers}
    else:
        where, params = f"s.is_active AND {SCOPES[scope]}", {}
    yf = {(s["market"], s["ticker"]): s["yf_symbol"] for s in load_universe()["stocks"]}
    rows = conn.execute(text(f"""
        SELECT s.stock_id, m.code, m.country, s.ticker, m.timezone, s.corp_code, s.cik
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE {where} ORDER BY s.stock_id"""), params).all()
    return [StockRef(stock_id=r[0], market=r[1], country=r[2], ticker=r[3],
                     yf_symbol=yf.get((r[1], r[3])) or yf_symbol(r[1], r[3]),
                     timezone=r[4], corp_code=r[5], cik=r[6]) for r in rows]


def index_refs(conn: Connection) -> list[IndexRef]:
    meta = {i["code"]: i for i in load_universe()["indices"]}
    rows = conn.execute(text("""
        SELECT i.index_id, i.code, m.country, m.timezone
        FROM indices i JOIN markets m ON m.market_id = i.market_id ORDER BY i.display_order""")).all()
    return [IndexRef(index_id=r[0], code=r[1], country=r[2], timezone=r[3],
                     pykrx_code=meta[r[1]].get("pykrx"), yf_symbol=meta[r[1]].get("yf_symbol")) for r in rows]
