"""yfinance 기반 시세·지수·환율·미국 밸류에이션·재무 보완."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.providers.base import Bar, Financial, FxPoint, IndexRef, StockRef, Valuation
from app.providers.convert import positive_or_none, to_dec, to_int
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(0.7)
SEOUL = ZoneInfo("Asia/Seoul")
FX_SYMBOL = "KRW=X"


def _yf():
    import yfinance as yf
    return yf


def _history(symbol: str, start: date, end: date, tz: str, has_volume: bool = True) -> list[Bar]:
    yf = _yf()
    # yfinance end는 배타적 → 하루 더한다
    df = call_with_retry(
        lambda: yf.Ticker(symbol).history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                                          auto_adjust=True, raise_errors=True),
        throttle=_throttle, what=f"yfinance history {symbol}")
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
        )]

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
