"""yfinance 기반 시세·지수·환율·미국 밸류에이션·재무 보완."""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from time import sleep
from zoneinfo import ZoneInfo

from app.providers.base import Bar, Financial, FxPoint, IndexRef, ProviderError, StockRef, Valuation
from app.providers.convert import positive_or_none, to_dec, to_int
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(0.7)
SEOUL = ZoneInfo("Asia/Seoul")
FX_SYMBOL = "KRW=X"
BATCH = 100                      # 묶음 다운로드 한 번의 종목 수
CAP_RETRY_PASS_WAIT = 60         # 시가총액 실패 종목을 다시 부르기 전 쉬는 초


def _yf():
    import yfinance as yf
    return yf


# yf.download는 실패(차단·429 등)를 예외 대신 'yfinance' 로거 ERROR로만 알린다. 그 로거는 logging.py에서 꺼 두었으므로
# 다운로드하는 동안만 호출한 스레드의 ERROR 메시지를 모은다(화면 출력은 계속 끈다).
_capture_lock = threading.Lock()


class _ErrorCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.thread = threading.get_ident()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self.thread:
            msg = record.getMessage().strip()
            if msg:
                self.messages.append(msg)


@contextmanager
def _capture_yf_errors() -> Iterator[list[str]]:
    lg = logging.getLogger("yfinance")
    with _capture_lock:
        h = _ErrorCapture()
        level, propagate = lg.level, lg.propagate
        lg.addHandler(h)
        lg.setLevel(logging.ERROR)
        lg.propagate = False
        try:
            yield h.messages
        finally:
            lg.removeHandler(h)
            lg.setLevel(level)
            lg.propagate = propagate


SHORT_RANGE = timedelta(days=7)   # 이 이하 증분 구간의 '데이터 없음'은 휴장일로 본다


def _history(symbol: str, start: date, end: date, tz: str, has_volume: bool = True) -> list[Bar]:
    yf = _yf()

    def fetch():
        try:
            # yfinance end는 배타적 → 하루 더한다
            return yf.Ticker(symbol).history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                             auto_adjust=True, raise_errors=True)
        except Exception as e:
            # 짧은 구간이 공휴일뿐이면 yfinance는 YFPricesMissingError를 낸다 → 재시도 없이 빈 결과.
            # 증분은 마지막 저장일 다음 날부터 다시 요청하므로 일시적 누락이어도 다음 갱신에서 채워진다.
            # 긴 구간의 '데이터 없음'은 상장폐지·심볼 오류일 수 있어 실패로 둔다.
            if type(e).__name__ == "YFPricesMissingError" and end - start <= SHORT_RANGE:
                log.info("yfinance history %s: %s~%s 거래 없음(휴장)", symbol, start, end)
                return None
            raise

    df = call_with_retry(fetch, throttle=_throttle, what=f"yfinance history {symbol}")
    if df is None:
        return []
    out = []
    for ts, r in df.iterrows():
        local = ts.tz_convert(tz) if ts.tzinfo else ts
        out.append(Bar(
            trade_date=local.date(),
            open=to_dec(r.get("Open"), 4), high=to_dec(r.get("High"), 4),
            low=to_dec(r.get("Low"), 4), close=to_dec(r.get("Close"), 4),
            volume=to_int(r.get("Volume")) if has_volume else None,
        ))
    return out


class YahooProvider:
    """PriceProvider + IndexProvider + FxProvider + ValuationProvider(US)."""
    source = "YFINANCE"

    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]:
        return _history(stock.yf_symbol, start, end, stock.timezone)

    def get_daily_prices_batch(self, stocks: list[StockRef], start: date, end: date) -> dict[str, list[Bar]]:
        """여러 종목 수정주가 일봉을 한 번에 받는다(BATCH 종목씩 묶음). 받지 못한 종목은 결과에서 빠진다."""
        yf = _yf()
        out: dict[str, list[Bar]] = {}
        for i in range(0, len(stocks), BATCH):
            chunk = stocks[i:i + BATCH]
            symbols = [s.yf_symbol for s in chunk]

            def fetch():
                with _capture_yf_errors() as errors:
                    df = yf.download(symbols, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                     auto_adjust=True, progress=False, threads=True, group_by="ticker")
                # 묶음 전체가 비면 차단·장애로 보고 실패로 올린다 → 재시도 후 ingestion_logs에 FAILED + 원인
                if df is None or df.empty:
                    raise ProviderError(" ".join(errors)[:400] or "빈 응답")
                if errors:
                    log.warning("yfinance download 일부 실패: %s", " ".join(errors)[:500])
                return df

            df = call_with_retry(fetch, throttle=_throttle, what=f"yfinance download {len(symbols)}종목")
            for st in chunk:
                try:
                    sub = df[st.yf_symbol] if len(symbols) > 1 else df
                except KeyError:
                    continue
                bars = []
                for ts, r in sub.dropna(how="all").iterrows():
                    local = ts.tz_convert(st.timezone) if ts.tzinfo else ts
                    bars.append(Bar(trade_date=local.date(), open=to_dec(r.get("Open"), 4), high=to_dec(r.get("High"), 4),
                                    low=to_dec(r.get("Low"), 4), close=to_dec(r.get("Close"), 4),
                                    volume=to_int(r.get("Volume"))))
                if bars:
                    out[st.ticker] = bars
        return out

    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]:
        return _history(index.yf_symbol, start, end, index.timezone, has_volume=False)

    # --- 환율
    def get_daily_rates(self, start: date, end: date) -> list[FxPoint]:
        yf = _yf()
        df = call_with_retry(
            lambda: yf.Ticker(FX_SYMBOL).history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                                 raise_errors=True),
            throttle=_throttle, what="yfinance fx daily")
        # 인덱스 tz는 Europe/London. 그 날짜를 00:00 Asia/Seoul로 저장 (ASSUMPTIONS A-08)
        return [FxPoint(rate_at=datetime.combine(ts.date(), time(0), SEOUL), usd_krw=to_dec(r.get("Close"), 4))
                for ts, r in df.iterrows()]

    def get_current_rate(self) -> FxPoint:
        yf = _yf()
        price = call_with_retry(lambda: yf.Ticker(FX_SYMBOL).fast_info["lastPrice"],
                                throttle=_throttle, what="yfinance fx current",
                                retry_if=lambda p: p is None or p != p)
        return FxPoint(rate_at=datetime.now(timezone.utc), usd_krw=to_dec(price, 4))

    # --- 밸류에이션 (적재 시점 스냅샷)
    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]:
        yf = _yf()
        info = call_with_retry(lambda: yf.Ticker(stock.yf_symbol).info, throttle=_throttle,
                               what=f"yfinance info {stock.yf_symbol}", retry_if=lambda i: not i)
        return [Valuation(
            as_of=end,
            per=positive_or_none(to_dec(info.get("trailingPE"), 4)),
            pbr=positive_or_none(to_dec(info.get("priceToBook"), 4)),
            eps=to_dec(info.get("trailingEps"), 4),
            bps=to_dec(info.get("bookValue"), 4),
            market_cap=to_dec(info.get("marketCap"), 0),
            shares_outstanding=to_int(info.get("sharesOutstanding")),
            # 연간 주당배당금. 무배당 종목은 dividendRate가 없고 trailingAnnualDividendRate가 0이다
            dps=to_dec(info.get("dividendRate") if info.get("dividendRate") is not None
                       else info.get("trailingAnnualDividendRate"), 4),
        )]

    # --- 시가총액 (미국 순위·ADR 비율, 수정 4 R4-3·R4-4)
    def get_market_caps(self, stocks: list[StockRef]) -> dict[str, Decimal]:
        """티커 → yfinance 시가총액(달러, 상장 단위 기준 — ADR도 ADS 기준). 받지 못한 종목은 빠진다.
        종목마다 요청 1번(약 0.5초)이라 순위를 매기는 30일마다 후보만 부른다.
        Yahoo가 401(Invalid Crumb)이면 yfinance는 예외 대신 {'trailingPegRatio': None}을 돌려준다 — 정상 응답에는 늘 있는
        quoteType이 없으면 실패로 보고 재시도하고, 그래도 실패한 종목은 잠시 쉰 뒤 한 번 더 부른다(차단이 몇 분 이어짐)."""
        yf = _yf()
        out: dict[str, Decimal] = {}
        todo = list(stocks)
        for wait in (0, CAP_RETRY_PASS_WAIT):
            if not todo:
                break
            if wait:
                log.warning("시가총액 %d종목 실패 — %ds 뒤 한 번 더", len(todo), wait)
                sleep(wait)
            failed = []
            for st in todo:
                try:
                    info = call_with_retry(lambda: yf.Ticker(st.yf_symbol).info, throttle=_throttle,
                                           what=f"yfinance info {st.yf_symbol}", retry_if=lambda i: "quoteType" not in i)
                except ProviderError:
                    failed.append(st)
                    continue
                cap = to_dec(info.get("marketCap"), 0)
                if cap and cap > 0 and (info.get("currency") or "USD") == "USD":
                    out[st.ticker] = cap
            todo = failed
        if todo:
            log.warning("시가총액 끝내 실패 %d종목: %s", len(todo), ", ".join(st.ticker for st in todo[:30]))
        return out

    # --- 재무 보완 (연간 4개 기간)
    def get_annual_financials(self, stock: StockRef, years: int) -> list[Financial]:
        yf = _yf()
        t = yf.Ticker(stock.yf_symbol)
        inc = call_with_retry(lambda: t.income_stmt, throttle=_throttle, what=f"yfinance income {stock.yf_symbol}")
        bs = call_with_retry(lambda: t.balance_sheet, throttle=_throttle, what=f"yfinance balance {stock.yf_symbol}")

        def pick(df, col, *rows):
            for r in rows:
                if r in df.index and col in df.columns:
                    v = to_dec(df.at[r, col], 2)
                    if v is not None:
                        return v
            return None

        out = []
        for col in list(inc.columns)[:years]:
            out.append(Financial(
                period_end=col.date(), period_type="FY",
                revenue=pick(inc, col, "Total Revenue", "Operating Revenue"),
                operating_income=pick(inc, col, "Operating Income"),
                net_income=pick(inc, col, "Net Income Common Stockholders", "Net Income"),
                total_assets=pick(bs, col, "Total Assets"),
                total_equity=pick(bs, col, "Stockholders Equity", "Common Stock Equity"),
                total_debt=pick(bs, col, "Total Liabilities Net Minority Interest"),
                data_source="YFINANCE", accounting_std="US-GAAP" if stock.country == "US" else "K-IFRS",
            ))
        return out
