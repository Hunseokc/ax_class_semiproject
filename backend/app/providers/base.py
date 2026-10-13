"""외부 데이터 소스 인터페이스.

수집 로직은 이 인터페이스에만 의존하고, 구현(pykrx·yfinance)은 factory에서 고른다.
테스트는 fake 구현을 주입한다. 반환값은 전처리 전 원본에 가까운 레코드이며 금액은 Decimal이다.

Stage 1은 일봉·지수·환율만 둔다. 밸류에이션·재무·공시·대량 조회 인터페이스는 Stage 3에서 추가한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

# Bar·FxPoint는 Stage 1에서 전처리(C)가 먼저 정의했다 → 같은 클래스를 그대로 다시 내보낸다(re-export).
# Stage 3에서 이 파일로 옮기고 preprocess가 여기서 import하도록 바꾼다.
from app.ingest.preprocess import Bar, FxPoint

__all__ = ["Bar", "FxPoint", "StockRef", "IndexRef", "PriceProvider", "IndexProvider", "FxProvider",
           "ProviderError"]


# ------------------------------------------------------------------ 레코드
@dataclass(frozen=True)
class StockRef:
    """수집 대상 종목 식별 정보 (universe.yaml + DB 매핑)."""
    stock_id: int
    market: str          # markets.code
    country: str         # KR / US
    ticker: str
    yf_symbol: str
    timezone: str
    corp_code: str | None = None
    cik: str | None = None


@dataclass(frozen=True)
class IndexRef:
    index_id: int
    code: str
    country: str
    timezone: str
    pykrx_code: str | None
    yf_symbol: str | None


# ------------------------------------------------------------------ 인터페이스
class PriceProvider(Protocol):
    source: str
    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]: ...


class IndexProvider(Protocol):
    source: str
    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]: ...


class FxProvider(Protocol):
    source: str
    def get_daily_rates(self, start: date, end: date) -> list[FxPoint]: ...
    def get_current_rate(self) -> FxPoint: ...


class ProviderError(Exception):
    """외부 소스 호출 실패 (재시도 후에도 실패)."""
