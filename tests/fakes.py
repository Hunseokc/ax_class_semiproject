"""테스트용 fake provider. 외부 호출 대신 고정 데이터를 돌려주고 호출 횟수·인자를 기록한다."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.providers.base import Bar, FxPoint, IndexRef, StockRef, Valuation
from app.providers.factory import Providers

SAFE_LAG = timedelta(days=2)    # 어느 시장 기준으로도 '오늘(미확정 봉)'이 되지 않도록 이틀 전까지만 돌려준다


def _days(start: date, end: date) -> list[date]:
    end = min(end, date.today() - SAFE_LAG)
    out, d = [], start
    while d <= end:
        out.append(d)
        d += timedelta(days=1)
    return out


class CallLog:
    def __init__(self):
        self.calls: list[tuple] = []
        self._lock = threading.Lock()

    def record(self, *args) -> None:
        with self._lock:
            self.calls.append(args)

    @property
    def count(self) -> int:
        return len(self.calls)


class FakePrice(CallLog):
    source = "FAKE"

    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]:
        self.record(stock.ticker, start, end)
        return [Bar(d, Decimal(100), Decimal(110), Decimal(90), Decimal(105), 1000) for d in _days(start, end)]


class FakeIndex(CallLog):
    source = "FAKE"

    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]:
        self.record(index.code, start, end)
        return [Bar(d, None, None, None, Decimal(2500)) for d in _days(start, end)]


class FakeFx:
    source = "FAKE"

    def __init__(self, rate: str = "1350", fail: bool = False, delay: float = 0.0):
        self.rate, self.fail, self.delay = Decimal(rate), fail, delay
        self.current = CallLog()
        self.daily = CallLog()

    def get_current_rate(self) -> FxPoint:
        self.current.record()
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("fake fx failure")
        return FxPoint(datetime.now(timezone.utc), self.rate)

    def get_daily_rates(self, start: date, end: date) -> list[FxPoint]:
        self.daily.record(start, end)
        return [FxPoint(datetime.combine(d, datetime.min.time(), timezone.utc), self.rate) for d in _days(start, end)]


class FakeValuation(CallLog):
    source = "YFINANCE"          # valuation_snapshots.source CHECK 허용값

    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]:
        self.record(stock.ticker, start, end)
        return [Valuation(as_of=min(end, date.today() - SAFE_LAG), per=Decimal(10), pbr=Decimal(1), market_cap=Decimal(10**12),
                          shares_outstanding=10**9)]


def make_providers(fx: FakeFx | None = None) -> Providers:
    price, index, val = FakePrice(), FakeIndex(), FakeValuation()
    fx = fx or FakeFx()
    return Providers(kr_price=price, us_price=price, kr_index=index, us_index=index, fx=fx,
                     kr_valuation=val, us_valuation=val, kr_financial=None, us_financial=None,
                     us_financial_supplement=None, kr_disclosure=None, us_disclosure=None)
