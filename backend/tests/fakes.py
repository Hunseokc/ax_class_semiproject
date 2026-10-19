"""테스트용 fake provider. 외부 호출 대신 고정 데이터를 돌려주고 호출 횟수·인자를 기록한다.

Stage 5-D: 업종 분류(FakeKrBulk classifications)·미국 기초값(FakeReference).
Stage 6-B: 상장 목록(FakeListing)·DART 고유번호 일괄 매핑(FakeFinancial.corp_codes).
이후 단계: 비교군 시가총액(caps·get_market_caps)·배당(dps)은 Stage 6-D.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.providers.base import (Bar, Classification, Disclosure, Financial, FxPoint, IndexRef, Listing, StockRef, Valuation,
                                ValuationBase)
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
                          shares_outstanding=10**9, dps=Decimal("1.5"))]


class FakeFinancial(CallLog):
    """직전 연도·그 전 연도 FY 2개."""

    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        self.record(stock.ticker, years)
        y = date.today().year - 1
        return [Financial(date(yy, 12, 31), "FY", revenue=Decimal(100 + i * 10), operating_income=Decimal(10),
                          net_income=Decimal(8 + i), total_assets=Decimal(300), total_equity=Decimal(100),
                          total_debt=Decimal(50), data_source=self.source) for i, yy in enumerate((y - 1, y))]

    # ── [S6-B] 고유번호 일괄 매핑(상장 목록 동기화) ──
    def corp_codes(self, codes: set[str]) -> dict[str, str]:
        return {c: f"C{c}" for c in codes}


class FakeDisclosure(CallLog):
    def __init__(self, source: str):
        super().__init__()
        self.source = source

    def get_disclosures(self, stock: StockRef, start: date, end: date) -> list[Disclosure]:
        self.record(stock.ticker, start, end)
        return [Disclosure(rcept_no=f"{stock.ticker}-1", title="사업보고서", report_type="정기공시",
                           filed_at=datetime.now(timezone.utc) - timedelta(days=30), url=None)]   # 재무를 받기 전에 낸 보고서


# ── [S6-B] 상장 목록 ──
class FakeListing(CallLog):
    """상장 보통주 목록. items를 바꿔 가며 동기화(추가·이전 상장·상장폐지)를 흉내 낸다."""

    def __init__(self, source: str, items: list[Listing]):
        super().__init__()
        self.source, self.items = source, items

    def get_listed_stocks(self, as_of: date) -> list[Listing]:
        self.record(as_of)
        return list(self.items)


class FakeKrBulk(CallLog):
    """국내 날짜별 전 종목 조회. 주말은 휴장(빈 결과). override = {티커: (종가, 등락률%)}로 수정주가 이벤트를 흉내 낸다."""
    source = "PYKRX"

    def __init__(self, classifications: list[Classification] | None = None, tickers: set[str] | None = None):
        super().__init__()
        self.classifications = classifications or []
        self.tickers = tickers if tickers is not None else {c.ticker for c in self.classifications}
        self.override: dict[str, tuple[Decimal, Decimal]] = {}

    def get_sector_classifications(self, as_of: date) -> list[Classification]:
        self.record("sector", as_of)
        return list(self.classifications)

    def get_bars_by_date(self, day: date) -> dict[str, Bar]:
        self.record("bars", day)
        if day.weekday() >= 5:
            return {}
        out = {}
        for t in self.tickers:
            close, rate = self.override.get(t, (Decimal(105), Decimal(0)))
            out[t] = Bar(day, close, close + 5, close - 5, close, 1000, change_rate=rate)
        return out

    def get_valuations_by_date(self, day: date) -> dict[str, Valuation]:
        self.record("vals", day)
        if day.weekday() >= 5:
            return {}
        return {t: Valuation(as_of=day, per=Decimal(10), pbr=Decimal(1), eps=Decimal(10), bps=Decimal(100),
                             shares_outstanding=10**6, dps=Decimal(0)) for t in self.tickers}   # 무배당 = 0


class FakeUsBatch(CallLog):
    """미국 묶음 다운로드. closes = {티커: 종가}(기본 105)."""
    source = "YFINANCE"

    def __init__(self):
        super().__init__()
        self.closes: dict[str, Decimal] = {}

    def get_daily_prices_batch(self, stocks: list[StockRef], start: date, end: date) -> dict[str, list[Bar]]:
        self.record(tuple(s.ticker for s in stocks), start, end)
        out = {}
        for s in stocks:
            c = self.closes.get(s.ticker, Decimal(105))
            out[s.ticker] = [Bar(d, c, c + 5, c - 5, c, 1000) for d in _days(start, end) if d.weekday() < 5]
        return out


class FakeReference(CallLog):
    """SEC 참조 데이터: 시장 전체 발행주식수(frames), SIC, 밸류에이션 기초값."""
    source = "SEC"

    def __init__(self, shares: dict[str, int] | None = None, sic: dict[str, int] | None = None,
                 bases: dict[str, ValuationBase] | None = None):
        super().__init__()
        self.shares, self.sic, self.bases = shares or {}, sic or {}, bases or {}

    def get_shares_frame(self, as_of: date) -> dict[str, int]:
        self.record("frame", as_of)
        return dict(self.shares)

    def get_sic(self, cik: str) -> tuple[int | None, str | None]:
        self.record("sic", cik)
        code = self.sic.get(cik)
        return code, (f"SIC {code}" if code else None)

    def get_valuation_base(self, stock: StockRef) -> ValuationBase:
        self.record("base", stock.ticker)
        return self.bases.get(stock.ticker, ValuationBase(shares_outstanding=None, shares_as_of=None))


def make_providers(fx: FakeFx | None = None, *, with_fundamentals: bool = False) -> Providers:
    price, index, val = FakePrice(), FakeIndex(), FakeValuation()
    fx = fx or FakeFx()
    fin = {"kr_financial": None, "us_financial": None, "kr_disclosure": None, "us_disclosure": None}
    if with_fundamentals:
        fin = {"kr_financial": FakeFinancial("DART"), "us_financial": FakeFinancial("SEC"),
               "kr_disclosure": FakeDisclosure("DART"), "us_disclosure": FakeDisclosure("SEC")}
    return Providers(kr_price=price, us_price=price, kr_index=index, us_index=index, fx=fx,
                     kr_valuation=val, us_valuation=val, us_financial_supplement=None, **fin)
