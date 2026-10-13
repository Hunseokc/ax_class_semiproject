"""yfinance 기반 시세·지수·환율.

미국 밸류에이션·재무 보완·묶음 다운로드는 Stage 3에서 추가한다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.providers.base import Bar, FxPoint, IndexRef, StockRef
from app.providers.convert import to_dec, to_int
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(0.7)
SEOUL = ZoneInfo("Asia/Seoul")
FX_SYMBOL = "KRW=X"


def _yf():
    import yfinance as yf
    return yf


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
    """PriceProvider + IndexProvider + FxProvider."""
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
