"""매력도 비교군: 선정(시가총액 상위·국가별 섹터당 최대 N), 평시 필수 데이터만 갱신, 요청 시 상세 수집,
갱신 범위 분리, 데이터 정리, DART 호출 제한, 스케줄러 판단, 잠금, 마이그레이션."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingest import benchmark, jobs
from app.ingest.benchmark import load_benchmark, prune_benchmark, run_benchmark, select_benchmark
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock
from app.providers.http import WindowLimiter
from app.services import hydration
from app.services.hydration import Hydrator, hydrate
from app.services.scheduler import SEOUL, Scheduler, benchmark_due, daily_boundary
from app.services.scoring import compute_scores
from tests.fakes import make_providers

API = "/api/v1"
TODAY = date.today()
CAND = ([{"group": "반도체", "country": "KR", "market": "KOSPI", "ticker": t, "name": f"국내{t}"}
         for t in ("100001", "100002", "100003", "100004")]
        + [{"group": "반도체", "country": "US", "market": "NASDAQ", "ticker": t, "name": f"US {t}"}
           for t in ("AAA", "BBB", "CCC", "DDD")]
        + [{"group": "빅테크", "country": "US", "market": "NASDAQ", "ticker": "EEE", "name": "US EEE"}])
CAPS = {"100001": 900, "100002": 800, "100003": 700, "AAA": 50, "BBB": 40, "CCC": 30, "DDD": 20, "EEE": 10}


@pytest.fixture
def pv():
    return make_providers(caps=CAPS, with_fundamentals=True)


def stocks_by_ticker(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT s.ticker, s.coverage, s.is_active, s.corp_code, s.cik, s.stock_id,
                                           (SELECT gm.is_primary FROM peer_group_members gm WHERE gm.stock_id = s.stock_id
                                            ORDER BY gm.is_primary DESC LIMIT 1) AS is_primary
                                    FROM stocks s""")).mappings()
        return {r["ticker"]: dict(r) for r in rows}


def select(engine, pv, caps=None, **kw):
    if caps is not None:
        pv.kr_valuation.caps = caps
    return select_benchmark(engine, pv, today=TODAY, candidates=CAND, per_sector=4, **kw)


# ------------------------------------------------------------------ 선정
def test_select_picks_top_market_cap_per_country_and_sector(engine, pv):
    out = select(engine, pv)
    # KR 반도체: 노출 2(삼성·SK) + 상위 2 / US 반도체: 노출 1(NVDA) + 상위 3 / US 빅테크: 노출 1(AAPL) + 후보 1개뿐
    assert out["by_group"] == {"반도체·KR": "노출 2 + 비교군 2", "반도체·US": "노출 1 + 비교군 3", "빅테크·US": "노출 1 + 비교군 1"}
    assert set(out["selected"]) == {"100001", "100002", "AAA", "BBB", "CCC", "EEE"}
    assert out["no_market_cap"] == ["100004"]
    s = stocks_by_ticker(engine)
    assert all(s[t]["coverage"] == "benchmark" and s[t]["is_active"] and s[t]["is_primary"] for t in out["selected"])
    assert "100003" not in s and "DDD" not in s                     # 순위 밖 후보는 저장하지 않는다
    assert s["100001"]["corp_code"] == "C100001" and s["AAA"]["cik"]  # DART 고유번호·SEC CIK 매핑
    assert s["005930"]["coverage"] == "featured"


def test_reselect_deactivates_dropped_unless_watched(engine, pv):
    select(engine, pv)
    s = stocks_by_ticker(engine)
    with engine.begin() as conn:                                      # 100002는 관심종목에 담겨 있다
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, :s)"), {"s": s["100002"]["stock_id"]})
    out = select(engine, pv, caps={**CAPS, "100003": 2000, "100004": 1500, "CCC": 1})
    s = stocks_by_ticker(engine)
    assert set(out["selected"]) >= {"100003", "100004"} and set(out["dropped"]) == {"100001", "CCC"}
    assert not s["100001"]["is_active"] and s["100002"]["is_active"]  # 관심종목은 비교군에서 빠져도 계속 활성
    assert s["CCC"]["is_active"] is False


# ------------------------------------------------------------------ 평시 데이터
def test_daily_load_fetches_only_essentials(engine, pv):
    select(engine, pv)
    load_benchmark(engine, pv, today=TODAY)
    bench = {"100001", "100002", "AAA", "BBB", "CCC", "EEE"}
    price_calls = {c[0]: c[1] for c in pv.kr_price.calls}
    assert set(price_calls) == bench                                   # 노출 종목은 비교군 갱신 대상이 아니다
    assert all(start == TODAY - timedelta(days=400) for start in price_calls.values())
    val_calls = {c[0]: (c[1], c[2]) for c in pv.kr_valuation.calls if c[0] != "caps"}
    assert set(val_calls) == bench                                     # 최신값만: 국내 최근 10일, 미국 스냅샷 1행
    assert all(val_calls[t][0] == TODAY - timedelta(days=10) for t in ("100001", "100002"))
    assert all(val_calls[t][0] == val_calls[t][1] for t in ("AAA", "BBB", "CCC", "EEE"))
    fin_calls = pv.kr_financial.calls + pv.us_financial.calls
    assert sorted(t for t, _ in fin_calls) == sorted(bench) and {y for _, y in fin_calls} == {3}
    assert pv.kr_disclosure.count == 0 and pv.us_disclosure.count == 0    # 공시는 평시에 받지 않는다
    # 다음 날: 최신 FY가 있으니 재무를 다시 받지 않고, 일봉은 증분만
    n_fin = len(fin_calls)
    load_benchmark(engine, pv, today=TODAY)
    assert len(pv.kr_financial.calls + pv.us_financial.calls) == n_fin


def test_financials_rechecked_only_when_stale(engine, pv):
    select(engine, pv)
    ids = [stocks_by_ticker(engine)["100001"]["stock_id"]]
    assert benchmark.financials_due(engine, ids, TODAY) == ids          # FY 없음
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO financial_statements (stock_id, period_end, period_type, data_source)
                             VALUES (:s, :d, 'FY', 'DART')"""), {"s": ids[0], "d": TODAY - timedelta(days=500)})
        conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, stock_id, status, started_at, finished_at)
                             VALUES ('DART', 'FINANCIALS', :s, 'SUCCESS', now(), now())"""), {"s": ids[0]})
    assert benchmark.financials_due(engine, ids, TODAY) == []            # 오래됐지만 방금 확인함 → 7일 대기
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert benchmark.financials_due(engine, ids, TODAY, now=later) == ids


def test_frequent_refresh_excludes_benchmark_unless_watched(engine, pv):
    select(engine, pv)
    s = stocks_by_ticker(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, :s)"), {"s": s["AAA"]["stock_id"]})
    jobs.load_prices(engine, pv, today=TODAY)                          # 4시간 갱신과 같은 기본 범위
    assert {c[0] for c in pv.kr_price.calls} == {"005930", "000660", "AAPL", "NVDA", "AAA"}


def test_scores_include_active_benchmark_only(engine, pv):
    select(engine, pv)
    load_benchmark(engine, pv, today=TODAY)
    compute_scores(engine, as_of=TODAY)
    with engine.begin() as conn:
        scored = set(conn.execute(text("""SELECT DISTINCT s.ticker FROM stock_scores st JOIN stocks s USING (stock_id)
                                          WHERE st.as_of = :d"""), {"d": TODAY}).scalars())
        conn.execute(text("UPDATE stocks SET is_active = false WHERE ticker = 'BBB'"))
    assert {"100001", "AAA", "BBB", "005930"} <= scored
    compute_scores(engine, as_of=TODAY)
    with engine.connect() as conn:
        assert "BBB" not in set(conn.execute(text("""SELECT s.ticker FROM stock_scores st JOIN stocks s USING (stock_id)
                                                     WHERE st.as_of = :d"""), {"d": TODAY}).scalars())


def test_prune_keeps_only_essential_data(engine, pv):
    select(engine, pv)
    s = stocks_by_ticker(engine)
    old, recent = s["100001"]["stock_id"], s["100002"]["stock_id"]
    with engine.begin() as conn:
        for sid in (old, recent):
            conn.execute(text("INSERT INTO daily_prices VALUES (:s, :d, 10, 11, 9, 10, 1)"), {"s": sid, "d": TODAY - timedelta(days=600)})
            conn.execute(text("""INSERT INTO disclosures (stock_id, rcept_no, title, filed_at, data_source)
                                 VALUES (:s, :r, 't', now(), 'DART')"""), {"s": sid, "r": f"r{sid}"})
        conn.execute(text("UPDATE stocks SET detail_synced_at = now() WHERE stock_id = :s"), {"s": recent})
    assert prune_benchmark(engine, TODAY) == 2                         # 상세를 안 본 종목: 오래된 일봉·공시 삭제
    with engine.connect() as conn:
        left = dict(conn.execute(text("SELECT stock_id, count(*) FROM disclosures GROUP BY stock_id")).all())
    assert old not in left and left[recent] == 1                       # 최근 상세를 연 종목은 유지


# ------------------------------------------------------------------ 요청 시 상세 수집
def test_hydrate_fetches_details_and_marks_synced(engine, pv):
    select(engine, pv)
    sid = stocks_by_ticker(engine)["100001"]["stock_id"]
    hydrate(engine, pv, sid)
    assert pv.kr_price.calls[-1][1] == TODAY - timedelta(days=730)      # 2년 일봉
    assert pv.kr_financial.calls[-1] == ("100001", 5)                  # 5개년 재무
    assert pv.kr_disclosure.calls[-1][0] == "100001"
    with engine.connect() as conn:
        synced = conn.execute(text("SELECT detail_synced_at FROM stocks WHERE stock_id = :s"), {"s": sid}).scalar()
        assert conn.execute(text("SELECT count(*) FROM disclosures WHERE stock_id = :s"), {"s": sid}).scalar() == 1
    h = Hydrator(lambda: engine, lambda: pv, ttl_hours=24)
    assert h.status(sid, "benchmark", synced) == "ready"
    assert h.status(sid, "benchmark", synced - timedelta(hours=25)) == "stale"
    assert h.status(1, "featured", None) == "ready"


class CapturingExecutor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))


def test_hydrator_queues_once_and_backs_off_on_failure(engine, pv, monkeypatch):
    select(engine, pv)
    sid = stocks_by_ticker(engine)["AAA"]["stock_id"]
    ex = CapturingExecutor()
    h = Hydrator(lambda: engine, lambda: pv, ttl_hours=24, executor=ex)
    assert h.request(sid, "benchmark", None) == "loading"
    assert h.request(sid, "benchmark", None) == "loading" and len(ex.jobs) == 1   # 같은 종목은 한 번만
    fn, args = ex.jobs[0]
    fn(*args)
    assert h.request(sid, "benchmark", h._synced_at(sid)) == "ready"
    other = stocks_by_ticker(engine)["BBB"]["stock_id"]
    monkeypatch.setattr(hydration, "hydrate", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    h.request(other, "benchmark", None)
    fn, args = ex.jobs[-1]
    fn(*args)
    assert h.request(other, "benchmark", None) == "failed" and len(ex.jobs) == 2   # 실패 후 10분은 재시도 안 함


def test_api_lists_benchmark_only_on_search_and_requests_details(client, engine, pv, hydrator):
    select(engine, pv)
    default = {x["ticker"] for x in client.get(f"{API}/stocks").json()["items"]}
    assert default == {"005930", "000660", "AAPL", "NVDA"}
    found = client.get(f"{API}/stocks?q=AAA").json()["items"]
    assert [(x["ticker"], x["coverage"]) for x in found] == [("AAA", "benchmark")]
    d = client.get(f"{API}/stocks/NASDAQ/AAA").json()
    sid = stocks_by_ticker(engine)["AAA"]["stock_id"]
    assert d["coverage"] == "benchmark" and d["detail_status"] == "loading" and hydrator.requests == [sid]
    assert client.get(f"{API}/stocks/KOSPI/005930").json()["detail_status"] == "ready" and hydrator.requests == [sid]
    client.post(f"{API}/watchlist", json={"market": "NASDAQ", "ticker": "BBB"})
    assert hydrator.requests[-1] == stocks_by_ticker(engine)["BBB"]["stock_id"]
    # 경쟁 비교 표는 노출 종목 + 대상 종목만(비교군은 점수 표본으로만)
    members = {m["ticker"] for g in client.get(f"{API}/stocks/NASDAQ/AAA/peers").json()["groups"] for m in g["members"]}
    assert members == {"005930", "000660", "NVDA", "AAA"}


# ------------------------------------------------------------------ 실행·스케줄·제한
def test_run_benchmark_selects_loads_scores_and_skips_when_locked(engine, pv, monkeypatch):
    monkeypatch.setattr(benchmark, "candidates_from_config", lambda: CAND)
    monkeypatch.setattr(benchmark, "config", lambda: {**benchmark.load_universe()["benchmark"], "per_sector": 4})
    out = run_benchmark(engine, pv, compute_scores, today=TODAY)
    assert out["stocks"] == 6 and out["scores"] > 0 and "select" in out
    assert run_benchmark(engine, pv, None, today=TODAY).get("select") is None     # 30일 안에는 다시 고르지 않음
    with advisory_lock(engine, BENCHMARK_LOCK_KEY):
        assert run_benchmark(engine, pv, None, today=TODAY) is None               # 다른 프로세스가 실행 중


def test_daily_boundary_and_due():
    at = time(7, 0)
    before = datetime(2026, 10, 7, 6, 59, tzinfo=SEOUL)
    after = datetime(2026, 10, 7, 7, 1, tzinfo=SEOUL)
    assert daily_boundary(before, at) == datetime(2026, 10, 6, 7, 0, tzinfo=SEOUL)
    assert daily_boundary(after, at) == datetime(2026, 10, 7, 7, 0, tzinfo=SEOUL)
    ran_yesterday_9am = datetime(2026, 10, 6, 9, 0, tzinfo=SEOUL)
    assert not benchmark_due(ran_yesterday_9am, before, at)
    assert benchmark_due(ran_yesterday_9am, after, at) and benchmark_due(None, before, at)


def test_scheduler_tick_runs_due_jobs_once(engine, monkeypatch):
    from app.services.fx import FxService
    from app.services.refresh import RefreshService
    p = make_providers()
    ran = []

    def fake_run(engine_, providers, scorer):
        ran.append("benchmark")
        with engine_.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, status, error, started_at, finished_at)
                                 VALUES ('INTERNAL', 'BENCHMARK', 'SUCCESS', '일일: test', now(), now())"""))
        return {}

    monkeypatch.setattr(benchmark, "run_benchmark", fake_run)
    sch = Scheduler(engine, lambda: RefreshService(engine, p, FxService(engine, p.fx, 4), 4), lambda: p, None)
    assert sch.tick() == ["refresh", "benchmark"]
    assert sch.tick() == []                                            # 4시간 TTL·오늘 07:00 이후 이미 실행
    assert ran == ["benchmark"]


def test_scheduler_backs_off_failing_jobs(engine, monkeypatch):
    """실패해서 성공 기록이 없어도 5분마다 다시 돌지 않는다(갱신 30분·비교군 60분 간격)."""
    from app.services.fx import FxService
    from app.services.refresh import RefreshService
    p = make_providers()
    calls = []
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *a: calls.append(1) or {})   # 성공 기록 없음 = 실패
    sch = Scheduler(engine, lambda: RefreshService(engine, p, FxService(engine, p.fx, 4), 4), lambda: p, None)
    t0 = datetime.now(timezone.utc)
    assert "benchmark" in sch.tick(t0)
    assert "benchmark" not in sch.tick(t0 + timedelta(minutes=5))
    assert "benchmark" in sch.tick(t0 + timedelta(minutes=61)) and len(calls) == 2


def test_window_limiter_caps_calls_per_minute():
    now = [0.0]
    waits = []

    def sleep(sec):
        waits.append(sec)
        now[0] += sec

    lim = WindowLimiter(90, 60.0, clock=lambda: now[0], sleep=sleep)
    for i in range(90):
        now[0] = i * 0.1                                               # 9초 동안 90회
        lim.wait()
    assert waits == []
    lim.wait()                                                         # 91번째 → 첫 호출이 60초 창을 벗어날 때까지
    assert waits == [pytest.approx(60.0 - 8.9)]
    assert len([t for t in lim._calls if t > now[0] - 60]) <= 90


def test_migration_003_is_idempotent(engine):
    for _ in range(2):
        jobs.migrate(engine, "003_benchmark")
    with engine.connect() as conn:
        cols = set(conn.execute(text("""SELECT column_name FROM information_schema.columns
                                        WHERE table_name = 'stocks'""")).scalars())
        check = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                                     WHERE conname = 'ingestion_logs_job_type_check'""")).scalar()
    assert {"coverage", "detail_synced_at"} <= cols and "BENCHMARK" in check and "HYDRATE" in check
