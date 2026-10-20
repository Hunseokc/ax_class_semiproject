"""KIS provider: 100행 단위 이어 받기·토큰 재사용·만료 토큰 재발급·종가 기반 밸류에이션."""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.providers import http, kis
from app.providers.base import IndexRef, ProviderError, StockRef

REF = StockRef(1, "KOSPI", "KR", "005930", "005930.KS", "Asia/Seoul")
SETTINGS = SimpleNamespace(kis_api_key="key123456", kis_api_secret="secret", kis_base_url="https://kis.test")


class _Resp:
    def __init__(self, data):
        self.data, self.status_code, self.text = data, 200, ""

    def json(self):
        return self.data


def _row(d: date, close: int) -> dict:
    return {"stck_bsop_date": d.strftime("%Y%m%d"), "stck_oprc": str(close), "stck_hgpr": str(close),
            "stck_lwpr": str(close), "stck_clpr": str(close), "acml_vol": "1000"}


@pytest.fixture
def fake_kis(monkeypatch, tmp_path):
    """영업일마다 종가 = 일련번호인 가짜 KIS. 응답은 최신순·최대 100행."""
    calls = {"token": 0, "get": [], "expire_once": False}
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(400)]

    def post(url, **kw):
        calls["token"] += 1
        return _Resp({"access_token": f"tok{calls['token']}", "expires_in": 86400})

    def get(url, headers=None, params=None, **kw):
        calls["get"].append((url.rsplit("/", 1)[-1], headers["authorization"], dict(params)))
        if calls["expire_once"]:
            calls["expire_once"] = False
            return _Resp({"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token 입니다."})
        if url.endswith("inquire-price"):
            return _Resp({"rt_cd": "0", "output": {"eps": "100.00", "bps": "-5", "lstn_stcn": "1000"}})
        lo, hi = params["FID_INPUT_DATE_1"], params["FID_INPUT_DATE_2"]
        rows = [_row(d, i + 1) for i, d in enumerate(days) if lo <= d.strftime("%Y%m%d") <= hi]
        if url.endswith("indexchartprice"):
            rows = [{"stck_bsop_date": r["stck_bsop_date"], "bstp_nmix_prpr": r["stck_clpr"], "bstp_nmix_oprc": "1",
                     "bstp_nmix_hgpr": "2", "bstp_nmix_lwpr": "0.5"} for r in rows]
        return _Resp({"rt_cd": "0", "output2": list(reversed(rows))[:kis.PAGE]})

    monkeypatch.setattr(kis.requests, "post", post)
    monkeypatch.setattr(kis.requests, "get", get)
    monkeypatch.setattr(kis, "_token", kis._Token(tmp_path / "kis_token.json"))
    monkeypatch.setattr(kis, "_throttle", http.Throttle(0))
    monkeypatch.setattr(http, "BACKOFF_BASE", 0)
    monkeypatch.setattr(kis, "get_settings", lambda: SETTINGS)
    return calls


def test_daily_prices_page_back_by_100_rows(fake_kis):
    bars = kis.KisProvider().get_daily_prices(REF, date(2026, 1, 1), date(2026, 8, 31))
    assert len(bars) == 243 and bars[0].trade_date == date(2026, 1, 1) and bars[-1].trade_date == date(2026, 8, 31)
    assert [b.trade_date for b in bars] == sorted({b.trade_date for b in bars})      # 겹침·누락 없이 오름차순
    assert len(fake_kis["get"]) == 3 and fake_kis["token"] == 1                      # 100+100+43, 토큰은 1번만


def test_token_is_reused_from_file_and_renewed_when_expired(fake_kis):
    p = kis.KisProvider()
    p.get_daily_prices(REF, date(2026, 1, 1), date(2026, 1, 5))
    kis._token._tok = None                             # 재시작 흉내: 메모리만 비움 → 파일에서 읽는다
    p.get_daily_prices(REF, date(2026, 1, 1), date(2026, 1, 5))
    assert fake_kis["token"] == 1
    fake_kis["expire_once"] = True                     # 서버가 만료 응답 → 토큰 버리고 재발급 후 재시도
    assert len(p.get_daily_prices(REF, date(2026, 1, 1), date(2026, 1, 5))) == 5
    assert fake_kis["token"] == 2 and fake_kis["get"][-1][1] == "Bearer tok2"


def test_index_uses_kis_codes(fake_kis):
    p = kis.KisProvider()
    bars = p.get_index_prices(IndexRef(1, "KOSDAQ", "KR", "Asia/Seoul", "2001", "^KQ11"), date(2026, 1, 1), date(2026, 1, 3))
    assert fake_kis["get"][-1][2]["FID_INPUT_ISCD"] == "1001" and bars[-1].close == Decimal(3)
    with pytest.raises(ProviderError):
        p.get_index_prices(IndexRef(2, "SPX", "US", "America/New_York", None, "^GSPC"), date(2026, 1, 1), date(2026, 1, 3))


def test_valuations_from_close_and_current_per_share(fake_kis):
    vals = kis.KisProvider().get_valuations(REF, date(2026, 1, 2), date(2026, 1, 3))
    v = vals[-1]
    assert v.as_of == date(2026, 1, 3) and v.per == Decimal("0.03")          # 종가 3 / EPS 100
    assert v.pbr is None and v.bps == Decimal(-5)                             # BPS ≤ 0 → PBR 산출 불가(BPS 값은 pykrx처럼 유지)
    assert v.market_cap == Decimal(3000) and v.shares_outstanding == 1000 and v.dps is None


def test_missing_keys_fail_fast(monkeypatch):
    monkeypatch.setattr(kis, "get_settings", lambda: SimpleNamespace(kis_api_key="", kis_api_secret=""))
    with pytest.raises(ProviderError):
        kis.KisProvider()
