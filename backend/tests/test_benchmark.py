"""매력도 비교군: 공식 업종 섹터별 시가총액 상위 선정, 섹터 그룹 = 주 그룹, 빠지면 상장 목록으로 복귀,
대량 일봉(국내 날짜별 전 종목·미국 묶음)과 수정주가 이벤트 감지, 유효기간 기반 재무, 요청 시 상세 수집,
갱신 범위 분리, 데이터 정리, DART 호출 제한, 스케줄러 판단, 잠금, 마이그레이션."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.ingest import benchmark, jobs
from app.ingest.benchmark import load_benchmark, prune_benchmark, run_benchmark, select_benchmark
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock
from app.providers.base import Classification
from app.providers.http import WindowLimiter
from app.services import hydration
from app.services.hydration import Hydrator, hydrate
from app.services.scheduler import SEOUL, Scheduler, benchmark_due, daily_boundary
from app.services.scoring import compute_scores
from tests.fakes import FakeKrBulk, FakeReference, FakeUsBatch, make_providers

API = "/api/v1"
TODAY = date.today()
CIK = {"AAA": "0000000011", "BBB": "0000000012", "CCC": "0000000013", "DDD": "0000000014", "EEE": "0000000015",
       "AAPL": "0000320193", "NVDA": "0001045810"}
# 국내: 반도체·전자 노출 2 + 후보 3, 은행 1(제외 업종) / 미국: 반도체·전자 노출 2 + 후보 4, IT·인터넷 1
CLASSES = [Classification("005930", "전기·전자", Decimal(400)), Classification("000660", "전기·전자", Decimal(100)),
           Classification("100001", "전기·전자", Decimal(900)), Classification("100002", "전기·전자", Decimal(800)),
           Classification("100003", "전기·전자", Decimal(700)), Classification("100004", "은행", Decimal(5000))]
SHARES = {CIK["AAA"]: 50, CIK["BBB"]: 40, CIK["CCC"]: 30, CIK["DDD"]: 20, CIK["EEE"]: 10, CIK["AAPL"]: 1000, CIK["NVDA"]: 900}
SIC = {CIK["AAA"]: 3674, CIK["BBB"]: 3674, CIK["CCC"]: 3674, CIK["DDD"]: 3674, CIK["EEE"]: 7372,
       CIK["AAPL"]: 3571, CIK["NVDA"]: 3674}


def seed_listed(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (market_id, ticker, name, coverage) VALUES (1, :t, :n, 'listed')"),
                     [{"t": t, "n": f"국내{t}"} for t in ("100001", "100002", "100003", "100004")])
        conn.execute(text("INSERT INTO stocks (market_id, ticker, name, name_en, cik, coverage) VALUES (2, :t, :t, :t, :c, 'listed')"),
                     [{"t": t, "c": CIK[t]} for t in ("AAA", "BBB", "CCC", "DDD", "EEE")])
        conn.execute(text("UPDATE stocks SET cik = :c WHERE ticker = :t"), [{"t": t, "c": CIK[t]} for t in ("AAPL", "NVDA")])
        conn.execute(text("UPDATE stocks SET corp_code = 'C' || ticker WHERE ticker IN ('005930', '000660')"))


@pytest.fixture
def pv(engine):
    seed_listed(engine)
    p = make_providers(with_fundamentals=True)
    p.kr_bulk = FakeKrBulk(list(CLASSES))
    p.us_batch_price = FakeUsBatch()
    p.us_reference = FakeReference(dict(SHARES), dict(SIC))
    return p


def stocks_by_ticker(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT s.ticker, s.coverage, s.is_active, s.corp_code, s.cik, s.stock_id, s.sector,
                                           s.industry, s.sic,
                                           (SELECT g.name FROM peer_group_members gm JOIN peer_groups g USING (group_id)
                                             WHERE gm.stock_id = s.stock_id AND gm.is_primary) AS primary_group
                                    FROM stocks s""")).mappings()
        return {r["ticker"]: dict(r) for r in rows}


def select(engine, pv, **kw):
    return select_benchmark(engine, pv, today=TODAY, per_sector=4, **kw)


# ------------------------------------------------------------------ 선정
def test_select_by_official_sector_and_market_cap(engine, pv):
    out = select(engine, pv)
    # 섹터당 4: 국내 반도체·전자 = 노출 2 + 시총 상위 2, 은행은 제외 업종 / 미국 반도체·전자 = 노출 2 + 상위 2, IT·인터넷 = 1
    assert out["by_sector"] == {"반도체·전자·KR": "노출 2 + 비교군 2", "반도체·전자·US": "노출 2 + 비교군 2",
                                "IT·인터넷·US": "노출 0 + 비교군 1"}
    assert set(out["selected"]) == {"100001", "100002", "AAA", "BBB", "EEE"}
    s = stocks_by_ticker(engine)
    assert all(s[t]["coverage"] == "benchmark" for t in out["selected"])
    assert s["100003"]["coverage"] == "listed" and s["100003"]["industry"] == "전기·전자"   # 순위 밖도 업종은 기록
    assert s["100004"]["sector"] is None and s["100004"]["coverage"] == "listed"          # 금융 업종은 표본에서 제외
    assert s["AAA"]["sic"] == 3674 and s["EEE"]["sector"] == "IT·인터넷"
    # 섹터 그룹이 주 그룹(섹터 중립화), 테마 그룹(반도체 등)은 주 그룹이 아니다
    assert {t: s[t]["primary_group"] for t in ("005930", "NVDA", "100001", "AAA", "EEE")} == {
        "005930": "반도체·전자", "NVDA": "반도체·전자", "100001": "반도체·전자", "AAA": "반도체·전자", "EEE": "IT·인터넷"}
    with engine.connect() as conn:
        kinds = dict(conn.execute(text("SELECT name, kind FROM peer_groups")).all())
    assert kinds["반도체"] == "theme" and kinds["반도체·전자"] == "sector"
    assert [c[0] for c in pv.us_reference.calls].count("frame") == 1                  # 시장 전체 발행주식수 1회
    assert {c[1] for c in pv.us_reference.calls if c[0] == "sic"} == set(CIK.values())
    n_sic = len(pv.us_reference.calls)
    select(engine, pv)
    assert len(pv.us_reference.calls) == n_sic + 1                                    # SIC는 1년 안에 다시 묻지 않는다(frame만)


def test_reselect_returns_dropped_to_listed(engine, pv):
    select(engine, pv)
    s = stocks_by_ticker(engine)
    with engine.begin() as conn:                                      # 100002는 관심종목에 담겨 있다
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, :s)"), {"s": s["100002"]["stock_id"]})
    pv.kr_bulk.classifications = [c if c.ticker != "100003" else Classification("100003", "전기·전자", Decimal(2000))
                                  for c in CLASSES]
    out = select(engine, pv)
    s = stocks_by_ticker(engine)
    assert "100003" in out["selected"] and out["dropped"] == ["100002"]
    assert s["100002"]["coverage"] == "listed" and s["100002"]["is_active"]          # 지우지 않고 상장 목록으로(검색 가능)
    assert s["100002"]["primary_group"] is None                                       # 섹터 그룹에서도 빠짐


# ------------------------------------------------------------------ 평시 데이터
def bench_ids(engine) -> dict[str, int]:
    return {t: r["stock_id"] for t, r in stocks_by_ticker(engine).items() if r["coverage"] == "benchmark"}


def test_daily_load_uses_bulk_and_freshness(engine, pv):
    select(engine, pv)
    n_batch = pv.us_batch_price.count                                # 선정 때 시가총액용 종가를 받은 묶음 호출 제외
    load_benchmark(engine, pv, today=TODAY)
    # 이력 없는 국내 종목은 종목별 수정주가 백필, 미국은 묶음 다운로드
    assert {c[0]: c[1] for c in pv.kr_price.calls} == {"100001": TODAY - timedelta(days=400), "100002": TODAY - timedelta(days=400)}
    batch = pv.us_batch_price.calls[n_batch:]
    assert len(batch) == 1 and set(batch[0][0]) == {"AAA", "BBB", "EEE"}
    assert [c[0] for c in pv.kr_bulk.calls].count("vals") == 1                       # 국내 밸류에이션: 전 종목 1일치
    # 재무: 비교군 3개년 + 노출 종목 5개년, 처음이라 모두
    fin = pv.kr_financial.calls + pv.us_financial.calls
    assert sorted(t for t, y in fin if y == 3) == ["100001", "100002", "AAA", "BBB", "EEE"]
    assert sorted(t for t, y in fin if y == 5) == ["000660", "005930", "AAPL", "NVDA"]
    assert pv.kr_disclosure.count == 0 and pv.us_disclosure.count == 0              # 공시는 평시에 받지 않는다
    # 다음 날: 재무는 유효기간 안이라 받지 않고, 일봉은 대량 증분만(종목별 호출 없음)
    n_fin, n_price = len(fin), pv.kr_price.count
    out = load_benchmark(engine, pv, today=TODAY)
    assert len(pv.kr_financial.calls + pv.us_financial.calls) == n_fin and out["financials"] == {}
    assert pv.kr_price.count == n_price and "FAILED" not in out["prices"].values()


def test_kr_bulk_detects_adjusted_price_and_refetches(engine, pv):
    select(engine, pv)
    load_benchmark(engine, pv, today=TODAY)
    ids = bench_ids(engine)
    with engine.begin() as conn:                                     # 최근 일주일을 비워 날짜별 조회 구간을 만든다
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:ids) AND trade_date > :d"),
                     {"ids": [ids["100001"], ids["100002"]], "d": TODAY - timedelta(days=7)})
    pv.kr_bulk.override["100001"] = (Decimal("52.5"), Decimal(0))   # 1:2 분할 — 등락률 0인데 종가가 절반
    before = pv.kr_price.count
    end = TODAY - timedelta(days=1)                                  # 오늘 봉은 장 마감 전이면 격리되므로 어제까지
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    st = jobs.load_prices_bulk(engine, pv, [ids["100001"], ids["100002"]], history_days=400, today=TODAY,
                               end={"KR": end})
    bars_calls = [c for c in pv.kr_bulk.calls if c[0] == "bars"]
    assert bars_calls and all(c[1] > TODAY - timedelta(days=7) for c in bars_calls)  # 빈 구간 날짜만, 날짜당 1회
    refetch = pv.kr_price.calls[before:]
    assert [(c[0], c[1]) for c in refetch] == [("100001", TODAY - timedelta(days=400))]   # 분할 종목만 수정주가로 전체
    assert st["100001"] == "SUCCESS" and st["100002"] == "SUCCESS"
    with engine.connect() as conn:
        n = conn.execute(text("SELECT count(*) FROM daily_prices WHERE stock_id = :s AND trade_date > :d"),
                         {"s": ids["100002"], "d": TODAY - timedelta(days=7)}).scalar()
    assert n == sum(1 for c in bars_calls if c[1].weekday() < 5)                    # 날짜별 조회로 채움


def test_us_batch_overlap_detects_split_and_refetches(engine, pv):
    select(engine, pv)
    load_benchmark(engine, pv, today=TODAY)
    ids = bench_ids(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = ANY(:ids) AND trade_date > :d"),
                     {"ids": [ids["AAA"], ids["BBB"]], "d": TODAY - timedelta(days=7)})
    pv.us_batch_price.closes["AAA"] = Decimal("52.5")                # 마지막 저장일 값이 바뀜 = 분할로 과거 수정
    before = pv.us_price.count
    jobs.load_prices_bulk(engine, pv, [ids["AAA"], ids["BBB"]], history_days=400, today=TODAY, end={"US": TODAY})
    assert [(c[0], c[1]) for c in pv.us_price.calls[before:]] == [("AAA", TODAY - timedelta(days=400))]
    last = pv.us_batch_price.calls[-1]
    assert set(last[0]) == {"AAA", "BBB"} and last[1] <= TODAY - timedelta(days=7)    # 마지막 저장일부터 겹쳐 받음


def test_frequent_refresh_excludes_benchmark_unless_watched(engine, pv):
    select(engine, pv)
    s = stocks_by_ticker(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, :s)"), {"s": s["AAA"]["stock_id"]})
    jobs.load_prices(engine, pv, today=TODAY)                          # 4시간 갱신과 같은 기본 범위
    assert {c[0] for c in pv.kr_price.calls} == {"005930", "000660", "AAPL", "NVDA", "AAA"}


def test_scores_use_benchmark_universe(engine, pv):
    select(engine, pv)
    load_benchmark(engine, pv, today=TODAY)
    compute_scores(engine, as_of=TODAY)
    with engine.connect() as conn:
        scored = set(conn.execute(text("""SELECT DISTINCT s.ticker FROM stock_scores st JOIN stocks s USING (stock_id)
                                          WHERE st.as_of = :d"""), {"d": TODAY}).scalars())
    assert {"100001", "100002", "AAA", "BBB", "EEE", "005930", "NVDA"} <= scored
    assert not scored & {"100003", "100004", "CCC"}                    # 상장 목록(비교군 밖)은 점수 표본이 아니다


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
def test_hydrate_fetches_only_expired_data(engine, pv):
    select(engine, pv)
    sid = stocks_by_ticker(engine)["100001"]["stock_id"]
    hydrate(engine, pv, sid)
    assert pv.kr_price.calls[-1][1] == TODAY - timedelta(days=730)      # 2년 일봉 백필
    assert pv.kr_financial.calls[-1] == ("100001", 5)                  # 5개년 재무
    assert pv.kr_disclosure.calls[-1][0] == "100001"
    with engine.connect() as conn:
        synced = conn.execute(text("SELECT detail_synced_at FROM stocks WHERE stock_id = :s"), {"s": sid}).scalar()
        assert conn.execute(text("SELECT count(*) FROM disclosures WHERE stock_id = :s"), {"s": sid}).scalar() == 1
    h = Hydrator(lambda: engine, lambda: pv, ttl_hours=24)
    assert h.status(sid, "benchmark", synced) == "ready"
    assert h.status(sid, "benchmark", synced - timedelta(hours=25)) == "stale"
    assert h.status(1, "featured", None) == "ready"
    # 다시 열면: 재무·공시·밸류에이션은 유효기간 안 → 일봉 증분만(백필 없음)
    counts = (pv.kr_financial.count, pv.kr_disclosure.count, pv.kr_valuation.count)
    out = hydrate(engine, pv, sid)
    assert (pv.kr_financial.count, pv.kr_disclosure.count, pv.kr_valuation.count) == counts
    assert out["financials"] == out["disclosures"] == out["valuation"] == "FRESH"
    assert pv.kr_price.calls[-1][1] != TODAY - timedelta(days=730)      # 증분


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
    assert d["sector"] == "반도체·전자" and d["groups"] == []                 # 업종 섹터는 표시용 필드, 테마 그룹 없음
    nv = client.get(f"{API}/stocks/NASDAQ/NVDA").json()
    assert nv["detail_status"] == "ready" and [g["name"] for g in nv["groups"]] == ["반도체"]   # 섹터 그룹은 테마 목록에 없음
    client.post(f"{API}/watchlist", json={"market": "NASDAQ", "ticker": "BBB"})
    assert hydrator.requests[-1] == stocks_by_ticker(engine)["BBB"]["stock_id"]
    # 경쟁 비교 표는 테마 그룹의 노출 종목 + 대상 종목만(비교군은 점수 표본으로만)
    members = {m["ticker"] for g in client.get(f"{API}/stocks/NASDAQ/NVDA/peers").json()["groups"] for m in g["members"]}
    assert members == {"005930", "000660", "NVDA"}
    assert {g["name"] for g in client.get(f"{API}/peer-groups").json()["groups"]} == {"반도체", "빅테크"}


# ------------------------------------------------------------------ 실행·스케줄·제한
def test_run_benchmark_selects_loads_scores_and_skips_when_locked(engine, pv, monkeypatch):
    monkeypatch.setattr(benchmark, "config", lambda: {**benchmark.load_universe()["benchmark"], "per_sector": 4})
    out = run_benchmark(engine, pv, compute_scores, today=TODAY)
    assert out["stocks"] == 5 and out["scores"] > 0 and "select" in out
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
    jobs.migrate(engine, "005_listed_dividend")
    with engine.connect() as conn:
        cols = set(conn.execute(text("""SELECT column_name FROM information_schema.columns
                                        WHERE table_name = 'stocks'""")).scalars())
        check = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                                     WHERE conname = 'ingestion_logs_job_type_check'""")).scalar()
    assert {"coverage", "detail_synced_at"} <= cols and "BENCHMARK" in check and "HYDRATE" in check
    assert "SECTORS_US" in check                                       # 007이 넓힌 값이 003 재실행으로 사라지지 않음


def test_migration_005_is_idempotent_and_survives_003_rerun(engine):
    for name in ("005_listed_dividend", "005_listed_dividend", "003_benchmark"):
        jobs.migrate(engine, name)
    with engine.connect() as conn:
        check = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                                     WHERE conname = 'stocks_coverage_check'""")).scalar()
        view_cols = set(conn.execute(text("""SELECT column_name FROM information_schema.columns
                                             WHERE table_name = 'v_stock_metrics'""")).scalars())
    assert "listed" in check and {"dps", "dividend_yield"} <= view_cols
