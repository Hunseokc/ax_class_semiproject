"""config/universe.yaml 읽기 — YAML을 불변 데이터클래스로 바꿔 돌려준다."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml

from app.core.config import CONFIG_DIR


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
class PeerGroupSpec:
    name: str
    members: tuple[str, ...]        # 티커 목록 (노출 종목 사이에 티커가 겹치지 않는다)


@dataclass(frozen=True)
class Universe:
    markets: tuple[MarketSpec, ...]
    indices: tuple[IndexSpec, ...]
    stocks: tuple[StockSpec, ...]
    peer_groups: tuple[PeerGroupSpec, ...]
    fx_yf_symbol: str


@lru_cache
def load_universe() -> Universe:
    with open(CONFIG_DIR / "universe.yaml", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # **dict 언패킹: YAML에 모르는 키가 있으면 TypeError로 바로 드러난다
    return Universe(
        markets=tuple(MarketSpec(**m) for m in raw["markets"]),
        indices=tuple(IndexSpec(**i) for i in raw["indices"]),
        stocks=tuple(StockSpec(**s) for s in raw["stocks"]),
        peer_groups=tuple(PeerGroupSpec(name=g["name"], members=tuple(g["members"]))
                          for g in raw["peer_groups"]),
        fx_yf_symbol=raw["fx"]["usd_krw"]["yf_symbol"],
    )


def yf_symbol(market: str, ticker: str) -> str:
    """yfinance 심볼: 코스피 .KS, 코스닥 .KQ, 미국은 티커 그대로."""
    return {"KOSPI": f"{ticker}.KS", "KOSDAQ": f"{ticker}.KQ"}.get(market, ticker)
