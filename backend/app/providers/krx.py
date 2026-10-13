"""pykrx 기반 국내 시세·지수.

pykrx 1.2.x는 지수 등 일부 조회에 KRX 로그인이 필요하다(ASSUMPTIONS A-01).
로그인 정보는 import 전에 환경변수로 내보내야 하므로 모듈 import를 지연한다.
밸류에이션·날짜별 전 종목 조회·업종 분류·상장 목록은 Stage 3에서 추가한다.
"""
from __future__ import annotations

from datetime import date

from app.core.config import export_krx_credentials
from app.providers.base import Bar, IndexRef, StockRef
from app.providers.convert import to_dec, to_int
from app.providers.http import Throttle, call_with_retry

_throttle = Throttle(0.7)


def _stock():
    export_krx_credentials()
    from pykrx import stock
    return stock


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _bars(df, has_volume: bool) -> list[Bar]:
    out = []
    for ts, r in df.iterrows():
        out.append(Bar(
            trade_date=ts.date(),
            open=to_dec(r.get("시가")), high=to_dec(r.get("고가")),
            low=to_dec(r.get("저가")), close=to_dec(r.get("종가")),
            volume=to_int(r.get("거래량")) if has_volume else None,
        ))
    return out


class KrxProvider:
    """PriceProvider + IndexProvider (KR)."""
    source = "PYKRX"

    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]:
        s = _stock()
        df = call_with_retry(
            lambda: s.get_market_ohlcv(_ymd(start), _ymd(end), stock.ticker, adjusted=True),
            throttle=_throttle, what=f"pykrx ohlcv {stock.ticker}")
        return _bars(df, has_volume=True)

    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]:
        s = _stock()
        df = call_with_retry(
            lambda: s.get_index_ohlcv(_ymd(start), _ymd(end), index.pykrx_code),
            throttle=_throttle, what=f"pykrx index {index.code}")
        return _bars(df, has_volume=False)
