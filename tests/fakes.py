"""테스트용 fake provider. 외부 호출 대신 고정 데이터를 돌려주고 호출 횟수·인자를 기록한다."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.providers.base import Bar, Disclosure, Financial, FxPoint, IndexRef, StockRef, Valuation
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

    def __init__(self, caps: dict[str, int] | None = None):
        super().__init__()
        self.caps = caps or {}

    def get_market_caps(self, stocks: list[StockRef], as_of: date) -> dict[str, Decimal]:
        self.record("caps", tuple(s.ticker for s in stocks))
        return {s.ticker: Decimal(self.caps[s.ticker]) for s in stocks if s.ticker in self.caps}

    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]:
        self.record(stock.ticker, start, end)
        return [Valuation(as_of=min(end, date.today() - SAFE_LAG), per=Decimal(10), pbr=Decimal(1), market_cap=Decimal(10**12),
                          shares_outstanding=10**9)]


class FakeFinancial(CallLog):
    """직전 연도·그 전 연도 FY 2개. 고유번호(corp_codes)·CIK(ciks) 매핑도 흉내 낸다."""

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        self.record(stock.ticker, years)
        y = date.today().year - 1
        return [Financial(date(yy, 12, 31), "FY", revenue=Decimal(100 + i * 10), operating_income=Decimal(10),
                          net_income=Decimal(8 + i), total_assets=Decimal(300), total_equity=Decimal(100),
                          total_debt=Decimal(50), data_source=self.source) for i, yy in enumerate((y - 1, y))]

    def corp_codes(self, codes: set[str]) -> dict[str, str]:
        return {c: f"C{c}" for c in codes}

    def ciks(self, tickers: set[str]) -> dict[str, str]:
        return {t: f"{abs(hash(t)) % 10**10:010d}" for t in tickers}


class FakeDisclosure(CallLog):
    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]:
        self.record(stock.ticker, start, end)
        return [Disclosure(rcept_no=f"{stock.ticker}-1", title="사업보고서", report_type="정기공시",
                           filed_at=datetime.now(timezone.utc), url=None)]


def make_providers(fx: FakeFx | None = None, *, caps: dict[str, int] | None = None, with_fundamentals: bool = False) -> Providers:
    price, index, val = FakePrice(), FakeIndex(), FakeValuation(caps)
    fx = fx or FakeFx()
    fin = {"kr_financial": None, "us_financial": None, "kr_disclosure": None, "us_disclosure": None}
    if with_fundamentals:
        fin = {"kr_financial": FakeFinancial("DART"), "us_financial": FakeFinancial("SEC"),
               "kr_disclosure": FakeDisclosure("DART"), "us_disclosure": FakeDisclosure("SEC")}
    return Providers(kr_price=price, us_price=price, kr_index=index, us_index=index, fx=fx,
                     kr_valuation=val, us_valuation=val, us_financial_supplement=None, **fin)
