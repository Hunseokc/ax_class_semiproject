"""매력도 비교군: 갱신 범위 분리, 요청 시 상세 수집(유효기간이 지난 것만), 스케줄러 판단, 잠금, 마이그레이션.

선정: 업종 코드(fake KSIC·SIC) → 주 테마 → 국가·테마별 시가총액(fake caps·cap_rank) 상위.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingest import background, benchmark, jobs
from app.ingest.benchmark import run_benchmark
from app.ingest.store import BENCHMARK_LOCK_KEY, advisory_lock
from app.services import hydration
from app.services.hydration import Hydrator, hydrate
from app.services.scheduler import SEOUL, Scheduler, benchmark_due, daily_boundary
from tests.fakes import make_providers

API = "/api/v1"
TODAY = date.today()


@pytest.fixture
def pv():
    return make_providers(with_fundamentals=True)


def add_benchmark(engine) -> dict[str, int]:
    """비교군 종목 2개(국내 100001, 미국 AAA)를 반도체 그룹에 넣는다. 반환: {티커: stock_id}."""
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO stocks (market_id, ticker, name, corp_code, cik, coverage) VALUES
              (1, '100001', '국내100001', 'C100001', NULL, 'benchmark'),
              (2, 'AAA', 'US AAA', NULL, '0000000011', 'benchmark');
            INSERT INTO peer_group_members (group_id, stock_id)
              SELECT 1, stock_id FROM stocks WHERE ticker IN ('100001', 'AAA')"""))
        return dict(conn.execute(text("SELECT ticker, stock_id FROM stocks WHERE coverage = 'benchmark'")).all())


# ------------------------------------------------------------------ 갱신 범위
def test_frequent_refresh_excludes_benchmark_unless_watched(engine, pv):
    ids = add_benchmark(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, :s)"), {"s": ids["AAA"]})
    jobs.load_prices(engine, pv, today=TODAY)                          # 4시간 갱신과 같은 기본 범위
    assert {c[0] for c in pv.kr_price.calls} == {"005930", "000660", "AAPL", "NVDA", "AAA"}


# ------------------------------------------------------------------ 요청 시 상세 수집
def test_hydrate_fetches_only_expired_data(engine, pv):
    sid = add_benchmark(engine)["100001"]
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
    # 최근 7일 일봉을 지워 증분 구간에 확정된 평일이 꼭 들어가게 한다. 그대로 두면 주말·한국 월요일 장 마감 전에는
    # 받을 구간이 주말뿐이라 코드가 의도대로 호출을 건너뛰어, 마지막 호출이 처음 백필로 남는다
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM daily_prices WHERE stock_id = :s AND trade_date > :d"), {"s": sid, "d": TODAY - timedelta(days=7)})
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
    ids = add_benchmark(engine)
    sid = ids["AAA"]
    ex = CapturingExecutor()
    h = Hydrator(lambda: engine, lambda: pv, ttl_hours=24, executor=ex)
    assert h.request(sid, "benchmark", None) == "loading"
    assert h.request(sid, "benchmark", None) == "loading" and len(ex.jobs) == 1   # 같은 종목은 한 번만
    fn, args = ex.jobs[0]
    fn(*args)
    assert h.request(sid, "benchmark", h._synced_at(sid)) == "ready"
    other = ids["100001"]
    monkeypatch.setattr(hydration, "hydrate", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    h.request(other, "benchmark", None)
    fn, args = ex.jobs[-1]
    fn(*args)
    assert h.request(other, "benchmark", None) == "failed" and len(ex.jobs) == 2   # 실패 후 10분은 재시도 안 함


def test_adding_benchmark_to_watchlist_requests_details(client, engine, hydrator):
    ids = add_benchmark(engine)
    assert client.post(f"{API}/watchlist", json={"market": "NASDAQ", "ticker": "AAA"}).status_code == 201
    assert hydrator.requests == [ids["AAA"]]
    client.post(f"{API}/watchlist", json={"market": "NASDAQ", "ticker": "NVDA"})   # 노출 종목은 요청하지 않는다
    assert hydrator.requests == [ids["AAA"]]


# ------------------------------------------------------------------ 실행·스케줄
def test_run_benchmark_skips_when_locked(engine, pv):
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

    def fake_background(engine_, providers, now=None):
        ran.append("background")
        with engine_.begin() as conn:
            conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, status, error, started_at, finished_at)
                                 VALUES ('INTERNAL', 'BENCHMARK', 'SUCCESS', '백그라운드: test', now(), now())"""))
        return {}

    monkeypatch.setattr(benchmark, "run_benchmark", fake_run)
    monkeypatch.setattr(background, "run_background", fake_background)
    sch = Scheduler(engine, lambda: RefreshService(engine, p, FxService(engine, p.fx, 4), 4), lambda: p, None)
    assert sch.tick() == ["refresh", "benchmark", "background", "guests"]
    assert sch.tick() == []                                            # 4시간 TTL·오늘 07:00·08:00 이후 이미 실행
    assert ran == ["benchmark", "background"]


def test_scheduler_backs_off_failing_jobs(engine, monkeypatch):
    """실패해서 성공 기록이 없어도 5분마다 다시 돌지 않는다(갱신 30분·비교군 60분 간격)."""
    from app.services.fx import FxService
    from app.services.refresh import RefreshService
    p = make_providers()
    calls = []
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *a: calls.append(1) or {})   # 성공 기록 없음 = 실패
    monkeypatch.setattr(background, "run_background", lambda *a, **kw: {})
    sch = Scheduler(engine, lambda: RefreshService(engine, p, FxService(engine, p.fx, 4), 4), lambda: p, None)
    t0 = datetime.now(timezone.utc)
    assert "benchmark" in sch.tick(t0)
    assert "benchmark" not in sch.tick(t0 + timedelta(minutes=5))
    assert "benchmark" in sch.tick(t0 + timedelta(minutes=61)) and len(calls) == 2


def test_refresh_runs_scores_only_with_scorer(engine):
    from app.services.fx import FxService
    from app.services.refresh import RefreshService
    p = make_providers()
    jobs_ = {j.job_type: j for j in RefreshService(engine, p, FxService(engine, p.fx, 4), 4).refresh().jobs}
    assert jobs_["SCORES"].status == "SKIPPED" and jobs_["SCORES"].detail == "점수 계산기 미연결"
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ingestion_logs"))
    jobs_ = {j.job_type: j for j in RefreshService(engine, p, FxService(engine, p.fx, 4), 4,
                                                    scorer=lambda e: 7).refresh().jobs}
    assert jobs_["SCORES"].status == "SUCCESS" and jobs_["SCORES"].counts == {"rows": 7}


def test_migration_003_is_idempotent(engine):
    for _ in range(2):
        jobs.migrate(engine, "003_benchmark")
    with engine.connect() as conn:
        cols = set(conn.execute(text("""SELECT column_name FROM information_schema.columns
                                        WHERE table_name = 'stocks'""")).scalars())
        check = conn.execute(text("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                                     WHERE conname = 'ingestion_logs_job_type_check'""")).scalar()
    assert {"coverage", "detail_synced_at"} <= cols and "BENCHMARK" in check and "HYDRATE" in check


# ------------------------------------------------------------------ 테마 분류 → 비교군 선정 (config/universe.yaml themes)
def _listed(conn, rows):
    """상장 목록 종목 추가: (시장 id, 티커, corp_code, cik, cap_rank)."""
    conn.execute(text("""INSERT INTO stocks (market_id, ticker, name, corp_code, cik, cap_rank, coverage)
                         VALUES (:m, :t, :t, :corp, :cik, :rank, 'listed')"""),
                 [{"m": m, "t": t, "corp": corp, "cik": cik, "rank": rank} for m, t, corp, cik, rank in rows])


def test_select_benchmark_by_theme_and_market_cap(engine):
    from dataclasses import replace
    from decimal import Decimal

    from app.ingest.sectors import sync_themes
    from tests.fakes import FakeKrBulk, FakeKrReference, FakeReference
    with engine.begin() as conn:
        sync_themes(conn)                                    # master 적재가 하는 일(테마 → peer_groups)
        _listed(conn, [(1, "100001", "C1", None, None), (1, "100002", "C2", None, None),
                       (1, "100003", "C3", None, None), (1, "100004", "C4", None, None),
                       (2, "AAA", None, "11", 2), (2, "BBB", None, "12", 1), (2, "CCC", None, "13", None),
                       (2, "BBBX", None, "12", 3)])                     # BBB와 같은 회사(CIK) — 다른 주식 종류
    kref = FakeKrReference({"C1": "2611", "C2": "26112", "C3": "64121", "C4": "68"})   # 반도체·반도체·은행·리츠
    uref = FakeReference(sic={"11": 3674, "12": 3674, "13": 3674})
    caps = {"100001": Decimal(10), "100002": Decimal(20), "100003": Decimal(5), "100004": Decimal(50)}
    bulk = FakeKrBulk(tickers=set(caps) | {"005930", "000660"}, caps=caps)   # 그날 일봉에 없으면 거래정지(R4-7)
    pv = replace(make_providers(), kr_reference=kref, us_reference=uref, kr_bulk=bulk)

    out = benchmark.select_benchmark(engine, pv, per_sector=3)
    with engine.connect() as conn:
        rows = {r.ticker: r for r in conn.execute(text("""
            SELECT s.ticker, s.coverage, s.sector, s.ksic, s.sic, t.theme FROM stocks s
            LEFT JOIN v_stock_theme t ON t.stock_id = s.stock_id"""))}
    # 반도체·KR: 노출 2(삼성전자·SK하이닉스) + 시가총액 상위 1 / 은행·KR 1 / 리츠(점수 없음)는 고르지 않는다
    assert out["by_group"]["반도체·KR"] == "노출 2 + 비교군 1" and rows["100002"].coverage == "benchmark"
    assert rows["100001"].coverage == "listed" and rows["100001"].theme == "반도체"     # 테마는 붙지만 비교군 밖
    assert (rows["100003"].coverage, rows["100003"].sector) == ("benchmark", "금융")
    assert (rows["100004"].coverage, rows["100004"].theme, rows["100004"].ksic) == ("listed", "리츠·부동산", "68")
    # 반도체·US: 노출 1(NVDA) + cap_rank 순 2. 순위 밖(CCC)은 SIC를 묻지 않는다
    assert out["by_group"]["반도체·US"] == "노출 1 + 비교군 2" and {rows["AAA"].coverage, rows["BBB"].coverage} == {"benchmark"}
    assert rows["BBBX"].coverage == "listed"                              # 회사당 1종목 — 순위가 높은 BBB만
    assert rows["CCC"].sic is None and rows["CCC"].theme is None and uref.count == 3 and kref.count == 4
    assert rows["AAPL"].theme == "빅테크" and rows["AAPL"].sector == "IT·인터넷"     # 노출 종목은 직접 지정

    # 다시 고르면: 업종 코드는 다시 묻지 않고(1년 주기), 빠진 비교군은 상장 목록 종목으로 돌아간다
    out = benchmark.select_benchmark(engine, pv, per_sector=2)
    with engine.connect() as conn:
        cov = dict(conn.execute(text("SELECT ticker, coverage FROM stocks WHERE ticker IN ('AAA', 'BBB', '100002')")).all())
    assert cov == {"AAA": "listed", "BBB": "benchmark", "100002": "listed"} and set(out["dropped"]) == {"AAA", "100002"}
    assert uref.count == 3 and kref.count == 4


def test_migration_012_is_idempotent(engine):
    for _ in range(2):
        jobs.migrate(engine, "012_themes")
    with engine.connect() as conn:
        cols = {(t, c) for t, c in conn.execute(text("""SELECT table_name, column_name FROM information_schema.columns
                                                        WHERE table_name IN ('stocks', 'peer_groups', 'indices')"""))}
    assert {("stocks", "ksic"), ("peer_groups", "sector"), ("peer_groups", "scoring"), ("peer_groups", "commodity_linked"),
            ("indices", "category"), ("indices", "unit")} <= cols
