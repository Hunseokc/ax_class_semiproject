"""config/universe.yaml 읽기(불변 데이터클래스)와 DB 마스터 → Provider 참조 객체 변환."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import yaml
from sqlalchemy import Connection, text

from app.core.config import CONFIG_DIR
from app.providers.base import IndexRef, StockRef


@dataclass(frozen=True)
class MarketSpec:
    code: str
    country: str
    currency: str
    timezone: str


@dataclass(frozen=True)
class IndexSpec:
    code: str
    name: str
    market: str
    display_order: int
    pykrx: str | None = None
    yf_symbol: str | None = None
    category: str = "index"         # index / commodity(원자재 선물 — 대시보드 '원자재' 묶음, 원자재 연동 테마의 가격 위치)
    unit: str | None = None         # 원자재 가격 단위($/톤 등). 지수는 없음

    @property
    def source_symbol(self) -> str:
        """indices.source_symbol(NOT NULL): 국내 지수는 pykrx 코드, 그 밖은 yfinance 심볼."""
        return self.pykrx or self.yf_symbol


@dataclass(frozen=True)
class StockSpec:
    market: str
    ticker: str
    name: str
    yf_symbol: str


@dataclass(frozen=True)
class Universe:
    markets: tuple[MarketSpec, ...]
    indices: tuple[IndexSpec, ...]
    stocks: tuple[StockSpec, ...]
    fx_yf_symbol: str
    benchmark: dict                 # [S4-D] 비교군 설정 (per_sector·price_days·fin_years·reselect_days …)
    sectors: list                   # 업종 섹터 이름 (stocks.sector — 주 테마의 sector)
    themes: list                    # 테마 [{name, sector, ksic, sic, tickers, scoring, commodity …}] (app/ingest/sectors.py)
    secondary_themes: dict          # 티커 → 보조 테마 이름 목록
    ingest: dict                    # 수집 적재 공통 (flush_every)
    background: dict                # 백그라운드 재무 적재 하루 예산 (app/ingest/background.py)
    corporate_actions: list = field(default_factory=list)   # 최신 FY 결산 뒤 분할·대규모 매각(R4-8 — score_metrics.sql)


@lru_cache
def load_universe() -> Universe:
    with open(CONFIG_DIR / "universe.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # **dict 언패킹: YAML에 모르는 키가 있으면 TypeError로 바로 드러난다
    return Universe(
        markets=tuple(MarketSpec(**m) for m in raw["markets"]),
        indices=tuple(IndexSpec(**i) for i in raw["indices"]),
        stocks=tuple(StockSpec(**s) for s in raw["stocks"]),
        fx_yf_symbol=raw["fx"]["usd_krw"]["yf_symbol"],
        benchmark=raw["benchmark"],
        sectors=raw["sectors"],
        themes=raw["themes"],
        secondary_themes={str(k): v for k, v in (raw.get("secondary_themes") or {}).items()},
        ingest=raw.get("ingest") or {},
        background=raw.get("background") or {},
        corporate_actions=raw.get("corporate_actions") or [],
    )


def yf_symbol(market: str, ticker: str) -> str:
    """yfinance 심볼: 코스피 .KS, 코스닥 .KQ, 미국은 티커 그대로."""
    return {"KOSPI": f"{ticker}.KS", "KOSDAQ": f"{ticker}.KQ"}.get(market, ticker)


# ── [S4-D] 갱신 범위 ──
# 자주 갱신(4시간)할 종목 = 노출 종목 + 관심종목·포트폴리오에 담긴 종목
FREQUENT_SQL = """(s.coverage = 'featured'
    OR EXISTS (SELECT 1 FROM watchlist_items w WHERE w.stock_id = s.stock_id)
    OR EXISTS (SELECT 1 FROM portfolio_items pi WHERE pi.stock_id = s.stock_id))"""
SCOPES = {"all": "true", "frequent": FREQUENT_SQL,
          "benchmark": f"s.coverage = 'benchmark' AND NOT {FREQUENT_SQL}"}


def stock_refs(conn: Connection, tickers: list[str] | None = None, *, scope: str = "frequent",
               stock_ids: list[int] | None = None) -> list[StockRef]:
    """수집 대상(활성 종목). scope: frequent(4시간 갱신) / benchmark(그 밖의 비교군, 1일 갱신) / all.
    tickers·stock_ids를 주면 scope와 관계없이 그 종목만(stock_ids는 비활성 종목도 포함).
    yfinance 심볼은 universe.yaml 값을 쓰고, 없으면 시장 규칙(.KS/.KQ)으로 만든다."""
    if stock_ids:
        where, params = "s.stock_id = ANY(:ids)", {"ids": stock_ids}
    elif tickers:
        where, params = "s.is_active AND s.ticker = ANY(:tickers)", {"tickers": tickers}
    else:
        where, params = f"s.is_active AND {SCOPES[scope]}", {}
    yf = {(s.market, s.ticker): s.yf_symbol for s in load_universe().stocks}
    rows = conn.execute(text(f"""
        SELECT s.stock_id, m.code, m.country, s.ticker, m.timezone, s.corp_code, s.cik
        FROM stocks s JOIN markets m ON m.market_id = s.market_id
        WHERE {where} ORDER BY s.stock_id"""), params).all()
    return [StockRef(stock_id=r[0], market=r[1], country=r[2], ticker=r[3],
                     yf_symbol=yf.get((r[1], r[3])) or yf_symbol(r[1], r[3]),
                     timezone=r[4], corp_code=r[5], cik=r[6]) for r in rows]


def index_refs(conn: Connection) -> list[IndexRef]:
    meta = {i.code: i for i in load_universe().indices}
    rows = conn.execute(text("""
        SELECT i.index_id, i.code, m.country, m.timezone
        FROM indices i JOIN markets m ON m.market_id = i.market_id ORDER BY i.display_order""")).all()
    return [IndexRef(index_id=r[0], code=r[1], country=r[2], timezone=r[3],
                     pykrx_code=meta[r[1]].pykrx, yf_symbol=meta[r[1]].yf_symbol) for r in rows]
