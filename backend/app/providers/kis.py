"""한국투자증권(KIS) Open API 기반 국내 일봉·지수·밸류에이션 — pykrx(KRX 로그인)가 막혔을 때의 교체 경로.

PRICE_SOURCE_KR=kis면 kr_price·kr_index·kr_valuation을 맡는다. KIS에는 날짜별 전 종목 조회가 없어
대량 조회(kr_bulk)·상장 목록(kr_listing)은 두지 않는다 → 비교군도 종목별 수집 경로를 탄다(yfinance 모드와 같은 경로).
- 접근 토큰: 24시간 유효, 발급은 1분에 1회 → 프로세스 안에서 재사용하고 /srv/data에도 남겨 재시작 때 다시 쓴다
- 일봉: 1회 최대 100행 → 기간이 길면 끝 날짜를 앞당겨 이어 받는다
- 밸류에이션: KIS는 현재 EPS·BPS·상장주식수만 준다 → 기간 안 각 거래일 종가로 PER·PBR·시가총액을 계산한다(배당 dps는 미제공)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import requests

from app.core.config import ROOT_DIR, get_settings
from app.providers.base import Bar, IndexRef, ProviderError, StockRef, Valuation
from app.providers.convert import to_dec, to_int
from app.providers.http import Throttle, call_with_retry

log = logging.getLogger(__name__)
_throttle = Throttle(1.05)         # 모의투자 한도(초당 1건) 기준 — 앱키가 모의투자로 발급되어 가장 낮은 한도에 맞춘다
PAGE = 100                         # 기간별 시세 1회 최대 행 수
TOKEN_FILE = ROOT_DIR / "data" / "kis_token.json"
# KIS 업종 코드 (universe.yaml의 pykrx 코드와 다르다)
INDEX_CODES = {"KOSPI": "0001", "KOSDAQ": "1001", "KOSPI200": "2001"}
EXPIRED = {"EGW00121", "EGW00123"}  # 유효하지 않은 토큰 / 만료된 토큰


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _day(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


class _Token:
    def __init__(self, path: Path = TOKEN_FILE):
        self.path = path
        self._tok: str | None = None
        self._exp = 0.0
        self._lock = threading.Lock()

    def get(self, s) -> str:
        with self._lock:
            if self._tok and time.time() < self._exp - 600:
                return self._tok
            if self._load(s.kis_api_key):
                return self._tok
            for attempt in range(2):
                r = requests.post(f"{s.kis_base_url}/oauth2/tokenP", timeout=15, json={
                    "grant_type": "client_credentials", "appkey": s.kis_api_key, "appsecret": s.kis_api_secret})
                d = r.json()
                if "access_token" in d:
                    self._tok, self._exp = d["access_token"], time.time() + int(d.get("expires_in", 86400))
                    self._save(s.kis_api_key)
                    log.info("KIS 접근 토큰 발급 (만료 %s)", d.get("access_token_token_expired"))
                    return self._tok
                if attempt == 0 and d.get("error_code") == "EGW00133":     # 1분 1회 발급 제한
                    time.sleep(61)
                    continue
                raise ProviderError(f"KIS 토큰 발급 실패: {d.get('error_code')} {d.get('error_description')}")
            raise ProviderError("KIS 토큰 발급 실패")

    def reset(self) -> None:
        with self._lock:
            self._tok, self._exp = None, 0.0
            self.path.unlink(missing_ok=True)

    def _load(self, key: str) -> bool:
        try:
            c = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return False
        if c.get("key") != key[-6:] or time.time() >= c.get("exp", 0) - 600:
            return False
        self._tok, self._exp = c["tok"], c["exp"]
        return True

    def _save(self, key: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"tok": self._tok, "exp": self._exp, "key": key[-6:]}))
        except OSError as e:
            log.warning("KIS 토큰 파일 저장 실패: %s", e)


_token = _Token()


class KisProvider:
    """PriceProvider + IndexProvider + ValuationProvider (KR)."""
    source = "KIS"

    def __init__(self):
        s = get_settings()
        if not (s.kis_api_key and s.kis_api_secret):
            raise ProviderError("KIS_API_KEY·KIS_API_SECRET이 없습니다")
        self.s = s

    def _get(self, path: str, tr_id: str, params: dict, what: str) -> dict:
        def call():
            h = {"authorization": f"Bearer {_token.get(self.s)}", "appkey": self.s.kis_api_key,
                 "appsecret": self.s.kis_api_secret, "tr_id": tr_id, "custtype": "P",
                 "content-type": "application/json; charset=utf-8"}
            r = requests.get(self.s.kis_base_url + path, headers=h, params=params, timeout=15)
            try:
                d = r.json()
            except ValueError:
                raise ProviderError(f"HTTP {r.status_code} JSON 아님: {r.text[:200]!r}") from None
            if d.get("rt_cd") != "0":
                if d.get("msg_cd") in EXPIRED:
                    _token.reset()                      # 다음 재시도에서 새로 발급
                raise ProviderError(f"{d.get('msg_cd')} {d.get('msg1')}")
            return d
        return call_with_retry(call, throttle=_throttle, what=what)

    def _paged(self, path: str, tr_id: str, base: dict, start: date, end: date, what: str) -> list[dict]:
        """기간별 시세를 끝 날짜부터 100행씩 거슬러 받는다(응답은 최신순)."""
        out: list[dict] = []
        hi = end
        while hi >= start:
            d = self._get(path, tr_id, {**base, "FID_INPUT_DATE_1": _ymd(start), "FID_INPUT_DATE_2": _ymd(hi)}, what)
            rows = [r for r in (d.get("output2") or []) if r.get("stck_bsop_date")]
            out += rows
            if len(rows) < PAGE:
                break
            hi = _day(min(r["stck_bsop_date"] for r in rows)) - timedelta(days=1)
        return out

    # ------------------------------------------------------------ 일봉
    def _stock_rows(self, stock: StockRef, start: date, end: date) -> list[dict]:
        return self._paged("/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", "FHKST03010100",
                           {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock.ticker,
                            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"},     # 0 = 수정주가
                           start, end, f"kis ohlcv {stock.ticker}")

    def get_daily_prices(self, stock: StockRef, start: date, end: date) -> list[Bar]:
        bars = [Bar(trade_date=_day(r["stck_bsop_date"]), open=to_dec(r.get("stck_oprc")), high=to_dec(r.get("stck_hgpr")),
                    low=to_dec(r.get("stck_lwpr")), close=to_dec(r.get("stck_clpr")), volume=to_int(r.get("acml_vol")))
                for r in self._stock_rows(stock, start, end)]
        return sorted(bars, key=lambda b: b.trade_date)

    def get_index_prices(self, index: IndexRef, start: date, end: date) -> list[Bar]:
        code = INDEX_CODES.get(index.code)
        if code is None:
            raise ProviderError(f"KIS 지수 코드 없음: {index.code}")
        rows = self._paged("/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice", "FHKUP03500100",
                           {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": code, "FID_PERIOD_DIV_CODE": "D"},
                           start, end, f"kis index {index.code}")
        bars = [Bar(trade_date=_day(r["stck_bsop_date"]), open=to_dec(r.get("bstp_nmix_oprc")),
                    high=to_dec(r.get("bstp_nmix_hgpr")), low=to_dec(r.get("bstp_nmix_lwpr")),
                    close=to_dec(r.get("bstp_nmix_prpr"))) for r in rows]
        return sorted(bars, key=lambda b: b.trade_date)

    # ------------------------------------------------------------ 밸류에이션
    def get_valuations(self, stock: StockRef, start: date, end: date) -> list[Valuation]:
        cur = self._get("/uapi/domestic-stock/v1/quotations/inquire-price", "FHKST01010100",
                        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock.ticker},
                        f"kis price {stock.ticker}").get("output") or {}
        eps, bps, shares = to_dec(cur.get("eps")), to_dec(cur.get("bps")), to_int(cur.get("lstn_stcn"))
        out = []
        for b in self.get_daily_prices(stock, start, end):
            if not b.close:
                continue
            out.append(Valuation(
                as_of=b.trade_date,
                # KRX와 같이 적자·자본잠식(EPS·BPS ≤ 0)은 산출 불가 → NULL
                per=_ratio(b.close, eps), pbr=_ratio(b.close, bps),
                eps=eps if eps else None, bps=bps if bps else None,
                market_cap=b.close * shares if shares else None,
                shares_outstanding=shares or None,
            ))
        return out


def _ratio(price: Decimal, per_share: Decimal | None) -> Decimal | None:
    if not per_share or per_share <= 0:
        return None
    return (price / per_share).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
