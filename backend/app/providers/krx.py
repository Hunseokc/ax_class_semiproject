"""pykrx 기반 국내 시세·지수·밸류에이션.

pykrx 1.2.x는 시총·펀더멘털·지수 조회에 KRX 로그인이 필요하다(ASSUMPTIONS A-01).
로그인 정보는 import 전에 환경변수로 내보내야 하므로 모듈 import를 지연한다.
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, timedelta

from app.core.config import export_krx_credentials
from app.providers.base import Bar, Classification, IndexRef, Listing, StockRef, Valuation
from app.providers.convert import positive_or_none, to_dec, to_int
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(0.7)
SPAC = re.compile(r"스팩")
DIAG_INTERVAL = 600      # 로그인 실패 진단은 10분에 1회까지(재시도마다 KRX 호출이 늘지 않게)
_last_diag = 0.0
# pykrx 1.2.9 website/comm/auth.py의 로그인 절차와 같은 주소 (pykrx 하위 모듈을 import하면 로그인이 한 번 더 일어나 직접 둔다)
KRX_LOGIN_PAGE = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001.cmd"
KRX_LOGIN_JSP = "https://data.krx.co.kr/contents/MDC/COMS/client/view/login.jsp?site=mdc"
KRX_LOGIN_URL = "https://data.krx.co.kr/contents/MDC/COMS/client/MDCCOMS001D1.cmd"
KRX_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def _stock():
    export_krx_credentials()
    try:
        from pykrx import stock    # import 시점에 KRX 로그인 — 응답이 JSON이 아니면 여기서 예외
    except Exception:
        _diagnose_login()
        raise
    return stock


def _diagnose_login() -> None:
    """pykrx 로그인 실패 원인 기록: 나가는 IP + pykrx와 같은 로그인 절차의 실제 응답(앞부분)."""
    global _last_diag
    if time.monotonic() - _last_diag < DIAG_INTERVAL:
        return
    _last_diag = time.monotonic()
    import requests

    try:
        ip = requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception as e:  # noqa: BLE001
        ip = f"확인 실패({type(e).__name__})"
    try:
        s = requests.Session()
        s.get(KRX_LOGIN_PAGE, headers={"User-Agent": KRX_UA}, timeout=15)
        s.get(KRX_LOGIN_JSP, headers={"User-Agent": KRX_UA, "Referer": KRX_LOGIN_PAGE}, timeout=15)
        r = s.post(KRX_LOGIN_URL, timeout=15, headers={"User-Agent": KRX_UA, "Referer": KRX_LOGIN_PAGE},
                   data={"mbrNm": "", "telNo": "", "di": "", "certType": "",
                         "mbrId": os.environ.get("KRX_ID", ""), "pw": os.environ.get("KRX_PW", "")})
        body = re.sub(r"\s+", " ", r.text)[:500]
        log.error("KRX 로그인 진단: egress_ip=%s status=%s type=%s url=%s redirects=%s body=%r",
                  ip, r.status_code, r.headers.get("content-type"), r.url,
                  [h.status_code for h in r.history], body)
    except Exception as e:  # noqa: BLE001
        log.error("KRX 로그인 진단: egress_ip=%s 요청 실패 %s: %s", ip, type(e).__name__, e)


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def is_common_kr(ticker: str, name: str) -> bool:
    """보통주: 단축코드 끝자리 0(우선주는 5·7·9·K 등). 스팩(기업인수목적회사)은 제외."""
    return len(ticker) == 6 and ticker.endswith("0") and not SPAC.search(name)


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
    """PriceProvider + IndexProvider + ValuationProvider (KR)."""
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

    def get_listed_stocks(self, as_of: date) -> list[Listing]:
        """코스피·코스닥 보통주 목록. 종목명은 pykrx가 한 번 받아 둔 티커 표에서 찾는다."""
        s = _stock()
        out = []
        for market in ("KOSPI", "KOSDAQ"):
            tickers = call_with_retry(lambda: s.get_market_ticker_list(_ymd(as_of), market=market),
                                      throttle=_throttle, what=f"pykrx ticker list {market}")
            for t in tickers:
                name = s.get_market_ticker_name(t)
                if isinstance(name, str) and name and is_common_kr(t, name):
                    out.append(Listing(market=market, ticker=t, name=name))
        return out

    # ------------------------------------------------------------ 날짜별 전 종목 (호출 1회)
    def get_bars_by_date(self, day: date) -> dict[str, Bar]:
        """그날 전 종목 일봉(수정 전 가격) + 등락률. 휴장일은 빈 dict. 거래정지(시가 0·거래량 0)는 빼고 돌려준다."""
        s = _stock()
        df = call_with_retry(lambda: s.get_market_ohlcv(_ymd(day), market="ALL"),
                             throttle=_throttle, what=f"pykrx ohlcv all {day}")
        out = {}
        for t, r in df.iterrows():
            if not to_dec(r.get("시가")) or not to_int(r.get("거래량")):
                continue
            out[str(t)] = Bar(trade_date=day, open=to_dec(r.get("시가")), high=to_dec(r.get("고가")),
                              low=to_dec(r.get("저가")), close=to_dec(r.get("종가")), volume=to_int(r.get("거래량")),
                              change_rate=to_dec(r.get("등락률")))
        return out

    def get_valuations_by_date(self, day: date) -> dict[str, Valuation]:
        s = _stock()
        fund = call_with_retry(lambda: s.get_market_fundamental(_ymd(day), market="ALL"),
                               throttle=_throttle, what=f"pykrx fundamental all {day}")
        cap = call_with_retry(lambda: s.get_market_cap(_ymd(day), market="ALL"),
                              throttle=_throttle, what=f"pykrx market_cap all {day}")
        caps = {str(t): r for t, r in cap.iterrows()}
        out = {}
        for t, r in fund.iterrows():
            c = caps.get(str(t))
            eps, bps = to_dec(r.get("EPS")), to_dec(r.get("BPS"))
            out[str(t)] = Valuation(
                as_of=day, per=positive_or_none(to_dec(r.get("PER"))), pbr=positive_or_none(to_dec(r.get("PBR"))),
                eps=eps if eps not in (None, 0) else None, bps=bps if bps not in (None, 0) else None,
                market_cap=to_dec(c.get("시가총액")) if c is not None else None,
                shares_outstanding=to_int(c.get("상장주식수")) if c is not None else None,
                dps=to_dec(r.get("DPS")))                       # 무배당은 0 (PER 등과 달리 유효한 값)
        return out

    # ── [S5-D] 업종 분류 ──
    def get_sector_classifications(self, as_of: date) -> list[Classification]:
        """코스피·코스닥 전 종목의 KRX 업종명과 시가총액(as_of 이전 가장 가까운 거래일)."""
        s = _stock()
        for back in range(8):
            d = as_of - timedelta(days=back)
            out = []
            for market in ("KOSPI", "KOSDAQ"):
                df = call_with_retry(lambda: s.get_market_sector_classifications(_ymd(d), market),
                                     throttle=_throttle, what=f"pykrx sector {market} {d}")
                out += [Classification(ticker=str(t), industry=str(r.get("업종명")), market_cap=to_dec(r.get("시가총액")))
                        for t, r in df.iterrows() if r.get("업종명")]
            if out:
                return out
        return []

    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]:
        s = _stock()
        fund = call_with_retry(
            lambda: s.get_market_fundamental(_ymd(start), _ymd(end), stock.ticker),
            throttle=_throttle, what=f"pykrx fundamental {stock.ticker}")
        cap = call_with_retry(
            lambda: s.get_market_cap(_ymd(start), _ymd(end), stock.ticker),
            throttle=_throttle, what=f"pykrx market_cap {stock.ticker}")
        caps = {ts.date(): r for ts, r in cap.iterrows()}
        out = []
        for ts, r in fund.iterrows():
            c = caps.get(ts.date())
            eps, bps = to_dec(r.get("EPS")), to_dec(r.get("BPS"))
            out.append(Valuation(
                as_of=ts.date(),
                # KRX는 산출 불가(적자 등)를 0으로 표기 → NULL
                per=positive_or_none(to_dec(r.get("PER"))),
                pbr=positive_or_none(to_dec(r.get("PBR"))),
                eps=eps if eps not in (None, 0) else None,
                bps=bps if bps not in (None, 0) else None,
                market_cap=to_dec(c.get("시가총액")) if c is not None else None,
                shares_outstanding=to_int(c.get("상장주식수")) if c is not None else None,
                dps=to_dec(r.get("DPS")),                       # 무배당은 0 (PER 등과 달리 유효한 값)
            ))
        return out
