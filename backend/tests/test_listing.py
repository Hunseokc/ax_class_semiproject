"""상장 종목 목록(listed): 보통주 필터, 목록 동기화(기존 종목 보호·이전 상장·상장폐지·이상 목록 보호),
일괄 수집·점수 유니버스에서 제외, 상단 검색 API, 요청 시 상세 수집, 참고 매력도, 배당수익률, 주 그룹 평균."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.ingest.listing import sync_listing
from app.ingest.universe import stock_refs
from app.providers.base import Listing
from app.providers.krx import is_common_kr
from app.providers.sec import is_common_us
from app.services.hydration import Hydrator, hydrate
from app.services.reference_score import robust_z
from app.services.scoring import compute_scores
from tests.conftest import D
from tests.fakes import FakeListing, make_providers
from tests.test_analysis import _path, _replace_prices

API = "/api/v1"
TODAY = date.today()
KR_LIST = [Listing("KOSPI", "005930", "삼성전자(목록 이름)"), Listing("KOSPI", "035720", "카카오"),
           Listing("KOSDAQ", "247540", "에코프로비엠"), Listing("KOSPI", "035420", "NAVER")]
US_LIST = [Listing("NASDAQ", "AAPL", "Apple Inc.", "Apple Inc.", "0000320193"),
           Listing("NYSE", "KO", "COCA COLA CO", "COCA COLA CO", "0000021344"),
           Listing("NYSE", "BRK-B", "BERKSHIRE HATHAWAY INC", "BERKSHIRE HATHAWAY INC", "0001067983")]


@pytest.fixture
def pv():
    p = make_providers(with_fundamentals=True)
    p.kr_listing = FakeListing("PYKRX", list(KR_LIST))
    p.us_listing = FakeListing("SEC", list(US_LIST))
    return p


@pytest.fixture(autouse=True)
def markets(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO markets (market_id, code, country, currency, timezone) VALUES
            (3, 'KOSDAQ', 'KR', 'KRW', 'Asia/Seoul'), (4, 'NYSE', 'US', 'USD', 'America/New_York')"""))


def rows(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        return {r["ticker"]: dict(r) for r in conn.execute(text("""
            SELECT s.stock_id, s.ticker, s.name, s.coverage, s.is_active, s.cik, s.corp_code, m.code AS market
            FROM stocks s JOIN markets m ON m.market_id = s.market_id""")).mappings()}


# ------------------------------------------------------------------ 보통주 필터
def test_common_stock_filters():
    assert is_common_kr("005930", "삼성전자") and is_common_kr("0126Z0", "새종목")
    assert not is_common_kr("005935", "삼성전자우") and not is_common_kr("00104K", "CJ4우(전환)")
    assert not is_common_kr("442310", "하나28호스팩")
    assert is_common_us("AAPL", "Apple Inc.") and is_common_us("BRK-B", "BERKSHIRE") and is_common_us("GOOGL", "Alphabet")
    assert not is_common_us("BAC-PB", "BANK OF AMERICA") and not is_common_us("ETI-P", "ENTERGY TEXAS")  # 우선주
    assert not is_common_us("KCAC-UN", "Kensington") and not is_common_us("ABCDW", "Some Corp")         # 유닛·워런트
    assert not is_common_us("SPY", "SPDR S&P 500 ETF TRUST") and not is_common_us("PDI", "PIMCO Dynamic Income Fund")
    assert not is_common_us("GTER", "Globa Terra Acquisition Corp")                                       # 스팩


# ------------------------------------------------------------------ 동기화
def test_sync_adds_listed_and_keeps_existing_stocks(engine, pv):
    out = sync_listing(engine, pv, today=TODAY)
    assert out["KR"]["added"] == 3 and out["US"]["added"] == 2
    r = rows(engine)
    assert r["005930"]["coverage"] == "featured" and r["005930"]["name"] == "삼성전자"     # 노출 종목은 그대로
    assert r["AAPL"]["coverage"] == "featured"
    assert (r["035720"]["coverage"], r["035720"]["market"]) == ("listed", "KOSPI")
    assert r["247540"]["market"] == "KOSDAQ" and r["KO"]["market"] == "NYSE" and r["KO"]["cik"] == "0000021344"
    assert r["035720"]["corp_code"] == "C035720"                                          # DART 고유번호 일괄 매핑
    assert sync_listing(engine, pv, today=TODAY)["KR"] == {"added": 0, "updated": 3, "moved": 0, "deactivated": 0,
                                                           "corp_code": 0}


def test_sync_moves_market_and_deactivates_delisted(engine, pv):
    sync_listing(engine, pv, today=TODAY)
    before = rows(engine)["247540"]["stock_id"]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, :s, 1)"), {"s": before})
    pv.kr_listing.items = [Listing("KOSPI", "247540", "에코프로비엠"), Listing("KOSPI", "035720", "카카오"),
                           Listing("KOSPI", "035420", "NAVER")]                         # 코스닥 → 코스피 이전 상장
    out = sync_listing(engine, pv, today=TODAY)
    r = rows(engine)
    assert out["KR"]["moved"] == 1 and r["247540"]["market"] == "KOSPI" and r["247540"]["stock_id"] == before
    assert out["KR"]["deactivated"] == 0
    pv.kr_listing.items = [Listing("KOSPI", "247540", "에코프로비엠"), Listing("KOSPI", "035720", "카카오")]
    assert sync_listing(engine, pv, today=TODAY)["KR"]["deactivated"] == 1               # NAVER 상장폐지 가정
    r = rows(engine)
    assert not r["035420"]["is_active"] and r["005930"]["is_active"]                      # 노출 종목은 대상 아님


def test_sync_skips_deactivation_when_list_looks_broken(engine, pv):
    sync_listing(engine, pv, today=TODAY)
    pv.kr_listing.items = [Listing("KOSPI", "035720", "카카오")]                         # 직전 활성 3 → 1 (절반 미만)
    assert sync_listing(engine, pv, today=TODAY)["KR"]["deactivated"] == 0
    pv.us_listing.items = []
    out = sync_listing(engine, pv, today=TODAY)                                          # 빈 목록은 실패로 기록
    assert "US" not in out
    with engine.connect() as conn:
        assert conn.execute(text("""SELECT status FROM ingestion_logs WHERE error LIKE '%빈 목록%'
                                    ORDER BY log_id DESC LIMIT 1""")).scalar() == "FAILED"


# ------------------------------------------------------------------ 일괄 수집·유니버스 제외
def test_listed_excluded_from_bulk_scopes_and_score_universe(engine, pv):
    sync_listing(engine, pv, today=TODAY)
    with engine.connect() as conn:
        for scope in ("frequent", "benchmark", "all"):
            assert not {r.ticker for r in stock_refs(conn, scope=scope)} & {"035720", "KO", "BRK-B"}, scope
    kakao = rows(engine)["035720"]["stock_id"]
    _replace_prices(engine, kakao, _path(300, 0.3, 0.05), D)
    compute_scores(engine, as_of=TODAY)
    with engine.begin() as conn:
        scored = set(conn.execute(text("SELECT DISTINCT stock_id FROM stock_scores")).scalars())
        assert kakao not in scored and 1 in scored
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, :s, 1)"), {"s": kakao})
        assert "035720" in {r.ticker for r in stock_refs(conn, scope="frequent")}        # 관심종목에 담으면 4시간 갱신


# ------------------------------------------------------------------ 검색 API
def test_search_ranks_matches_and_covers_listed(client, engine, pv):
    sync_listing(engine, pv, today=TODAY)
    items = client.get(f"{API}/stocks/search?q=삼성").json()["items"]
    assert [(x["ticker"], x["coverage"]) for x in items] == [("005930", "featured")]
    items = client.get(f"{API}/stocks/search?q=035").json()["items"]
    assert [x["ticker"] for x in items] == ["035720", "035420"]                         # 티커 앞부분 일치, 짧은 이름 먼저
    assert client.get(f"{API}/stocks/search?q=ko").json()["items"][0]["ticker"] == "KO"  # 티커 완전 일치 우선
    assert client.get(f"{API}/stocks/search?q=berkshire").json()["items"][0]["ticker"] == "BRK-B"
    assert client.get(f"{API}/stocks/search?q=%25").json()["items"] == []               # LIKE 특수문자는 글자 그대로
    assert len(client.get(f"{API}/stocks/search?q=0&limit=2").json()["items"]) == 2
    assert client.get(f"{API}/stocks/search?q=").status_code == 422
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET is_active = false WHERE ticker = 'KO'"))
    assert client.get(f"{API}/stocks/search?q=coca").json()["items"] == []               # 상장폐지(비활성) 제외
    assert client.get(f"{API}/stocks?q=카카오").json()["items"] == []                    # 리스트에는 시세 없는 listed 없음


# ------------------------------------------------------------------ 요청 시 상세 수집
def test_listed_detail_requests_hydration_and_hydrate_fetches_in_order(client, engine, pv, hydrator):
    sync_listing(engine, pv, today=TODAY)
    kakao = rows(engine)["035720"]["stock_id"]
    d = client.get(f"{API}/stocks/KOSPI/035720").json()
    assert d["coverage"] == "listed" and d["detail_status"] == "loading" and d["close"] is None
    assert hydrator.requests == [kakao]
    assert client.get(f"{API}/stocks/KOSPI/035720/analysis").status_code == 404            # 시세 전에는 분석 없음
    hydrate(engine, pv, kakao)
    assert pv.kr_price.calls[-1][1] == TODAY - timedelta(days=730)                        # 2년 일봉
    assert pv.kr_valuation.calls[-1][0] == "035720" and pv.kr_financial.calls[-1] == ("035720", 5)
    with engine.connect() as conn:
        synced = conn.execute(text("SELECT detail_synced_at FROM stocks WHERE stock_id = :s"), {"s": kakao}).scalar()
        jobs = conn.execute(text("""SELECT job_type FROM ingestion_logs WHERE stock_id = :s AND job_type <> 'HYDRATE'
                                    ORDER BY log_id"""), {"s": kakao}).scalars().all()
    assert jobs == ["PRICES", "FINANCIALS", "VALUATION", "DISCLOSURES"]                  # 가격부터 채운다(미국 밸류에이션은 재무의 기초값이 필요)
    h = Hydrator(lambda: engine, lambda: pv, ttl_hours=24)
    assert h.status(kakao, "listed", synced) == "ready" and h.status(kakao, "listed", None) == "stale"


# ------------------------------------------------------------------ 참고 매력도
def build_universe(engine, pv) -> int:
    """노출 4종목 + listed 1종목에 서로 다른 시세 경로(300거래일)와 FY 재무를 넣고 점수를 계산한다."""
    sync_listing(engine, pv, today=TODAY)
    kakao = rows(engine)["035720"]["stock_id"]
    for i, sid in enumerate([1, 2, 3, 4, kakao]):
        _replace_prices(engine, sid, _path(300, i * 0.7, 0.02 * (i - 2)), D)
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, revenue, operating_income,
                                 net_income, total_assets, total_equity, total_debt, data_source)
                             VALUES (:s, :e, 'FY', :r, :o, :n, 1000, :eq, :dt, 'DART')"""),
                     [{"s": sid, "e": date(y, 12, 31), "r": 100 + i * 20 + (y - 2023) * (5 + i), "o": 10 + i * 3,
                       "n": 8 + i * 2 + (y - 2023), "eq": 100 + i * 10, "dt": 50 + i * 15}
                      for i, sid in enumerate([1, 2, 3, 4, kakao]) for y in (2023, 2024)])
        conn.execute(text("""INSERT INTO valuation_snapshots (stock_id, as_of, eps, bps, market_cap, dps, source)
                             VALUES (:s, :d, 5, 60, 10000000000000, 1.4, 'PYKRX')"""), {"s": kakao, "d": D})
    compute_scores(engine, as_of=TODAY)
    return kakao


def test_reference_score_for_listed_without_touching_universe(client, engine, pv):
    kakao = build_universe(engine, pv)
    with engine.connect() as conn:
        before = conn.execute(text("SELECT stock_id, preset_id, score FROM stock_scores ORDER BY 1, 2")).all()
    a = client.get(f"{API}/stocks/KOSPI/035720/analysis").json()
    s = a["attractiveness"]
    assert s["reference"] is True and "참고 점수" in s["reference_note"] and s["as_of"] == TODAY.isoformat()
    assert 0 <= s["score"] <= 100 and s["factor_coverage"] == 5
    assert s["rank"]["country"] == "KR" and s["rank"]["total"] == 3                      # 국내 유니버스 2개 + 이 종목
    assert all(m["z_adj"] is None for m in s["metrics"])                                 # 섹터 중립화 없음
    assert s["peer_average"] is None
    composite = sum(f["contribution"] for f in s["factors"].values())
    assert composite == pytest.approx(s["composite"], abs=1e-3)
    with engine.connect() as conn:
        after = conn.execute(text("SELECT stock_id, preset_id, score FROM stock_scores ORDER BY 1, 2")).all()
    assert before == after and kakao not in {r[0] for r in after}                        # 유니버스 점수는 그대로
    # 배당수익률 = 주당배당금 / 최신 종가
    m = a["metrics"]
    last_close = float(_path(300, 4 * 0.7, 0.04)[-1])
    assert m["dps"] == 1.4 and m["dividend_yield"] == pytest.approx(1.4 / last_close, abs=1e-6)


def test_reference_score_leaves_metric_empty_without_universe_values(client, engine, pv):
    build_universe(engine, pv)
    with engine.begin() as conn:                         # 국내 유니버스의 B/P 값이 모두 없는 날(예: 장 시작 전 밸류에이션)
        conn.execute(text("""UPDATE stock_metric_values SET raw_value = NULL
                             WHERE metric = 'book_yield' AND stock_id IN (1, 2)"""))
    s = client.get(f"{API}/stocks/KOSPI/035720/analysis").json()["attractiveness"]
    by = next(m for m in s["metrics"] if m["metric"] == "book_yield")
    assert by["raw_value"] is not None and by["z_raw"] is None                       # 0으로 두지 않는다
    assert s["data_quality"]["missing_metrics"]["book_yield"] == "같은 시장 비교군에 이 지표 값이 없음"


def test_robust_z_matches_sql_for_universe_member(engine, pv):
    build_universe(engine, pv)
    with engine.connect() as conn:
        vals = conn.execute(text("""SELECT mv.raw_value, mv.z_raw FROM stock_metric_values mv
                                    JOIN stocks s USING (stock_id) JOIN markets m USING (market_id)
                                    WHERE mv.as_of = :d AND mv.metric = 'momentum' AND m.country = 'US'"""),
                            {"d": TODAY}).all()
    xs = [float(v.raw_value) for v in vals]
    assert len(xs) == 2
    for v in vals:
        assert robust_z(float(v.raw_value), xs) == pytest.approx(float(v.z_raw), abs=1e-4)
    assert robust_z(1.0, []) == 0 and robust_z(2.0, [1.0, 1.0]) == 0
    assert robust_z(3.0, [1.0, 2.0, 3.0]) == pytest.approx((3 - 2) / statistics.stdev([1, 2, 3]))
    six = [0.1, 0.12, 0.08, 0.11, 0.5, 0.09]                                             # 표본 5개 이상 → 로버스트 Z
    m = statistics.median(six)
    mad = statistics.median(abs(x - m) for x in six)
    assert robust_z(0.5, six) == pytest.approx((0.5 - m) / (1.4826 * mad))


def test_featured_analysis_has_peer_average_for_radar(client, engine, pv):
    build_universe(engine, pv)
    s = client.get(f"{API}/stocks/KOSPI/005930/analysis").json()["attractiveness"]
    assert s["reference"] is False
    pa = s["peer_average"]
    assert pa["group_name"] == "반도체" and pa["size"] == 2                               # 같은 국가 주 그룹(삼성·SK)
    with engine.connect() as conn:
        exp = conn.execute(text("""SELECT AVG(value_score) FROM stock_scores st JOIN scoring_presets p USING (preset_id)
                                   WHERE p.code = 'balanced' AND st.stock_id IN (1, 2) AND st.as_of = :d"""),
                           {"d": TODAY}).scalar()
    assert pa["factors"]["value"] == pytest.approx(float(exp), abs=1e-4)
    assert client.get(f"{API}/stocks/NASDAQ/AAPL/analysis").json()["attractiveness"]["peer_average"] is None  # 그룹에 혼자
