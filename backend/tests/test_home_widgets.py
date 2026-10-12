"""대시보드 홈 위젯: 시장 심리 지수(compute_sentiment·저장·백필·버전), 섹터 히트맵(수집·호출 최소화·조회)."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.providers.base import Bar
from app.services import sentiment as S
from app.services.fx import FxService
from app.services.refresh import RETRY_AFTER, RefreshService
from app.services.sectors import SECTORS, load_sectors, read_sectors
from tests.conftest import scalar
from tests.fakes import CallLog, make_providers

API = "/api/v1"
# 월요일 14:00 KST — 국내는 장중(마지막 마감 10/08, 10/09 한글날), 미국은 마지막 마감 10/09(금)
NOW = datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ compute_sentiment (순수 함수)
@pytest.mark.parametrize("score, label", [(0, "극단적 공포"), (19.99, "극단적 공포"), (20, "공포"), (39.99, "공포"),
                                          (40, "중립"), (60, "탐욕"), (79.99, "탐욕"), (80, "극단적 탐욕"), (100, "극단적 탐욕"),
                                          (None, "데이터 부족")])
def test_label_boundaries(score, label):
    assert S.label_for(score) == label


def test_components_and_average():
    closes = [100.0] * 251 + [110.0]                       # 252개: 52주 최고에서 끝남
    r = S.compute_sentiment(closes)
    assert r["price_position"] == 100                       # (110 − 100) / (110 − 100)
    ma = (100 * 124 + 110) / 125
    assert r["ma_gap_score"] == round(50 + (110 / ma - 1) * 100 * 5, 2)          # 괴리 +9.9% × 5 + 50 = 99.56
    assert r["rsi_score"] == 100                            # 상승만 → RSI 100
    assert r["vix_score"] is None and r["label"] == "극단적 탐욕"
    assert r["score"] == round((100 + r["ma_gap_score"] + 100) / 3, 2)             # VIX 없는 국내: 3개 평균
    assert S.compute_sentiment([100.0] * 251 + [130.0])["ma_gap_score"] == 100    # 괴리 +29.8% → 상한 100


def test_clamp_lower_bound_and_vix():
    closes = [100.0] * 251 + [80.0]
    r = S.compute_sentiment(closes, vix_closes=[50.0])
    assert r["price_position"] == 0 and r["ma_gap_score"] == 0 and r["rsi_score"] == 0
    assert r["vix_score"] == 0                              # VIX 35 이상 → 0
    assert S.compute_sentiment(closes, vix_closes=[5.0])["vix_score"] == 100     # VIX 12 이하 → 100
    assert S.compute_sentiment(closes, vix_closes=[23.5])["vix_score"] == 50


def test_insufficient_data():
    assert S.compute_sentiment([])["label"] == "데이터 부족"
    r = S.compute_sentiment([100.0 + i for i in range(30)])  # RSI만 계산 가능(구성요소 1개)
    assert r["rsi_score"] is not None and r["price_position"] is None and r["ma_gap_score"] is None
    assert r["score"] is None and r["label"] == "데이터 부족"
    r = S.compute_sentiment([100.0 + i for i in range(30)], vix_closes=[20.0])   # RSI + VIX = 2개 → 계산
    assert r["score"] == round((r["rsi_score"] + r["vix_score"]) / 2, 2)
    assert S.compute_sentiment([100.0] * 260)["price_position"] is None          # 고가=저가 → 위치 계산 불가


# ------------------------------------------------------------------ 저장·백필·버전
def _load_index(engine, code: str, closes: list[float], end: date) -> list[date]:
    days, d = [], end
    while len(days) < len(closes):
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    days.reverse()
    with engine.begin() as conn:
        iid = conn.execute(text("SELECT index_id FROM indices WHERE code = :c"), {"c": code}).scalar()
        if iid is None:
            iid = conn.execute(text("""INSERT INTO indices (code, name, market_id, source_symbol, display_order)
                                       VALUES (:c, :c, 2, :c, 9) RETURNING index_id"""), {"c": code}).scalar()
        conn.execute(text("DELETE FROM index_daily_prices WHERE index_id = :i"), {"i": iid})
        conn.execute(text("INSERT INTO index_daily_prices (index_id, trade_date, close) VALUES (:i, :d, :c)"),
                     [{"i": iid, "d": d, "c": c} for d, c in zip(days, closes)])
    return days


def test_ensure_sentiment_backfills_and_upserts_without_duplicates(engine):
    days = _load_index(engine, "KOSPI", [2000 + i for i in range(300)], date(2026, 10, 8))
    pts = S.ensure_sentiment(engine, "KR", NOW)
    assert {k: v["trade_date"] for k, v in pts.items()} == {"current": days[-1], "previous": days[-2], "week_ago": days[-6]}
    assert scalar(engine, "SELECT count(*) FROM market_sentiment_daily") == 3                  # 백필 2행 포함
    S.ensure_sentiment(engine, "KR", NOW)
    assert scalar(engine, "SELECT count(*) FROM market_sentiment_daily") == 3                  # 다시 불러도 중복 없음
    # 백필 값 = 그 날까지 자른 시계열로 계산한 값
    expected = S.compute_sentiment([2000 + i for i in range(295)])["score"]
    assert float(scalar(engine, "SELECT score FROM market_sentiment_daily WHERE trade_date = :d", d=days[-6])) == expected


def test_stored_rows_are_reused_unless_formula_version_differs(engine):
    days = _load_index(engine, "KOSPI", [2000 + i for i in range(300)], date(2026, 10, 8))
    S.ensure_sentiment(engine, "KR", NOW)
    with engine.begin() as conn:                                        # 저장값이 그대로 쓰이는지 표시를 남김
        conn.execute(text("UPDATE market_sentiment_daily SET score = 11, label = '극단적 공포' WHERE trade_date = :d"), {"d": days[-1]})
        conn.execute(text("UPDATE market_sentiment_daily SET score = 12, formula_version = 0 WHERE trade_date = :d"), {"d": days[-2]})
    pts = S.ensure_sentiment(engine, "KR", NOW)
    assert pts["current"]["score"] == 11                                # 같은 버전 → 재계산하지 않음
    assert pts["previous"]["score"] != 12 and pts["previous"]["formula_version"] == S.FORMULA_VERSION
    assert scalar(engine, "SELECT formula_version FROM market_sentiment_daily WHERE trade_date = :d", d=days[-2]) == S.FORMULA_VERSION


def test_us_sentiment_uses_vix_only_when_recent(engine):
    days = _load_index(engine, "SPX", [5000 + i for i in range(300)], date(2026, 10, 9))
    _load_index(engine, "VIX", [15.0] * 20, date(2026, 9, 1))           # 기준일보다 한 달 오래됨 → 쓰지 않음
    assert S.ensure_sentiment(engine, "US", NOW)["current"]["vix_score"] is None
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM market_sentiment_daily"))
    _load_index(engine, "VIX", [15.0] * 20, days[-1])
    assert S.ensure_sentiment(engine, "US", NOW)["current"]["vix_score"] == round((35 - 15) / 23 * 100, 2)


def test_get_sentiment_falls_back_to_last_stored_row(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM index_daily_prices"))
    r = S.get_sentiment(engine, "KR", NOW)
    assert r["score"] is None and r["label"] == "데이터 부족" and r["previous"] is None    # 저장 행도 없음
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO market_sentiment_daily (market, trade_date, score, label, formula_version)
                             VALUES ('KR', '2026-10-01', 55, '중립', 1)"""))
    r = S.get_sentiment(engine, "KR", NOW)
    assert r["score"] == 55 and r["as_of"] == date(2026, 10, 1) and r["label"] == "중립"


def test_sentiment_api(client, engine):
    _load_index(engine, "KOSPI", [2000 + i for i in range(300)], date(2026, 10, 8))
    body = client.get(f"{API}/home/sentiment", params={"country": "KR"}).json()
    assert body["index_code"] == "KOSPI" and body["label"] == "극단적 탐욕" and body["components"]["vix_score"] is None
    assert body["previous"]["score"] is not None and body["week_ago"]["score"] is not None
    assert client.get(f"{API}/home/sentiment", params={"country": "JP"}).status_code == 422


# ------------------------------------------------------------------ 섹터 히트맵
class FakeSectorBatch(CallLog):
    """섹터 ETF 묶음 다운로드: 10/08 100 → 10/09 101(+1%), 미국 기준 마감 전인 10/12 봉도 돌려준다."""
    source = "FAKE"

    def __init__(self, missing=()):
        super().__init__()
        self.missing = set(missing)

    def get_daily_prices_batch(self, stocks, start, end):
        self.record(tuple(s.ticker for s in stocks), start, end)
        bars = [Bar(date(2026, 10, 8), None, None, None, Decimal(100), 0), Bar(date(2026, 10, 9), None, None, None, Decimal(101), 0),
                Bar(date(2026, 10, 12), None, None, None, Decimal(150), 0)]
        return {s.ticker: bars for s in stocks if s.ticker not in self.missing}


class FailingIndex(CallLog):
    source = "FAKE"

    def get_index_prices(self, index, start, end):
        self.record(index.code)
        raise RuntimeError("KRX 응답 없음")

    @property
    def sector_calls(self) -> int:                         # 지수 갱신(INDICES)의 KOSPI 호출은 빼고 센다
        return sum(1 for (code,) in self.calls if code in {s.code for s in SECTORS["KR"]})


def _providers(**kw):
    p = make_providers()
    p.us_batch_price = kw.get("batch", FakeSectorBatch())
    if "kr_index" in kw:
        p.kr_index = kw["kr_index"]
    return p


def test_load_us_sectors_one_batch_call_and_skips_unclosed_bar(engine):
    p = _providers()
    status, counts, _ = load_sectors(engine, p, "US", NOW)
    assert status == "SUCCESS" and p.us_batch_price.count == 1                     # 11개를 한 번에
    assert len(p.us_batch_price.calls[0][0]) == len(SECTORS["US"])
    assert scalar(engine, "SELECT count(*) FROM sector_performance_daily") == 11    # 10/09 한 날짜만(10/12 미확정 봉 제외)
    assert float(scalar(engine, "SELECT change_pct FROM sector_performance_daily WHERE sector_code = 'XLK'")) == 1.0


def test_sectors_not_refetched_until_next_session(engine):
    p = _providers()
    load_sectors(engine, p, "US", NOW)
    status, _, detail = load_sectors(engine, p, "US", NOW + timedelta(hours=10))     # 다음 마감(10/12 장 마감) 전
    assert status == "SUCCESS" and "다음 거래일" in detail and p.us_batch_price.count == 1
    load_sectors(engine, p, "US", datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc))  # 10/12 뉴욕 마감 뒤
    assert p.us_batch_price.count == 2


def test_missing_sector_is_partial_and_shown_as_dash(engine, client):
    p = _providers(batch=FakeSectorBatch(missing={"XLB"}))
    status, counts, detail = load_sectors(engine, p, "US", NOW)
    assert status == "PARTIAL" and counts["missing"] == 1 and "소재" in detail
    body = client.get(f"{API}/home/sectors", params={"country": "US"}).json()
    by = {s["code"]: s for s in body["sectors"]}
    assert body["available"] and body["as_of"] == "2026-10-09" and by["XLB"]["change_pct"] is None and by["XLK"]["change_pct"] == 1
    assert sum(s["weight"] for s in body["sectors"]) == pytest.approx(sum(s.weight for s in SECTORS["US"]))


def test_kr_sector_failure_stops_after_first_call(engine, client):
    p = _providers(kr_index=FailingIndex())
    status, _, detail = load_sectors(engine, p, "KR", NOW)
    assert status == "FAILED" and "KRX" in detail and p.kr_index.sector_calls == 1   # 나머지 10개는 시도하지 않음
    body = client.get(f"{API}/home/sectors", params={"country": "KR"}).json()
    assert body["available"] is False and all(s["change_pct"] is None for s in body["sectors"])


def test_old_sector_rows_are_pruned(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO sector_performance_daily (market, sector_code, sector_name, trade_date, change_pct)
                             VALUES ('US', 'XLK', '정보기술', '2026-08-01', 1)"""))
    load_sectors(engine, _providers(), "US", NOW)
    assert scalar(engine, "SELECT count(*) FROM sector_performance_daily WHERE trade_date < '2026-09-01'") == 0


def test_refresh_runs_sector_jobs_with_ttl_and_retry(engine):
    p = _providers(kr_index=FailingIndex())
    clock = [NOW]
    svc = RefreshService(engine, p, FxService(engine, p.fx, 4), 4, clock=lambda: clock[0], sector_loader=load_sectors)
    first = {j.job_type: j.status for j in svc.refresh().jobs}
    assert first["SECTORS_US"] == "SUCCESS" and first["SECTORS_KR"] == "FAILED"
    clock[0] = NOW + timedelta(minutes=10)                               # TTL·재시도 간격 안 → 외부 호출 없음
    second = {j.job_type: j.status for j in svc.refresh().jobs}
    assert second["SECTORS_US"] == "SKIPPED" and second["SECTORS_KR"] == "SKIPPED"
    assert p.us_batch_price.count == 1 and p.kr_index.sector_calls == 1
    clock[0] = NOW + RETRY_AFTER + timedelta(minutes=1)                 # 실패한 국내만 30분 뒤 재시도
    third = {j.job_type: j.status for j in svc.refresh().jobs}
    assert third["SECTORS_US"] == "SKIPPED" and p.kr_index.sector_calls == 2


def test_read_sectors_without_data(engine):
    from sqlalchemy.orm import Session
    with Session(engine) as db:
        r = read_sectors(db, "US")
    assert r["available"] is False and r["as_of"] is None and len(r["sectors"]) == 11
