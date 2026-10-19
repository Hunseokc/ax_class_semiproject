"""백그라운드 재무 적재 — 하루 예산·우선순위(거래대금 → 시가총액)·재무 기록 있는 종목 제외 (추가기능 API 정의서 7절)."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.ingest import background
from app.ingest.background import priority_queue, run_background, used_today
from app.providers.base import Bar, Valuation
from app.services import freshness
from tests.conftest import scalar
from tests.fakes import CallLog, FakeFinancial, make_providers


class _Bulk(CallLog):
    """티커 → (종가, 거래량, 시가총액)인 날짜별 전 종목 조회."""
    source = "FAKE"

    def __init__(self, data: dict[str, tuple[int, int, int]]):
        super().__init__()
        self.data = data

    def get_bars_by_date(self, day):
        self.record("bars", day)
        return {t: Bar(day, Decimal(c), Decimal(c), Decimal(c), Decimal(c), v) for t, (c, v, _) in self.data.items()}

    def get_valuations_by_date(self, day):
        self.record("vals", day)
        return {t: Valuation(as_of=day, market_cap=Decimal(m)) for t, (_, _, m) in self.data.items()}


def _listed(engine, n: int, start: int = 101) -> list[int]:
    ids = list(range(start, start + n))
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO stocks (stock_id, market_id, ticker, name, coverage, corp_code)
                             VALUES (:i, 1, :t, :t, 'listed', :c)"""), [{"i": i, "t": f"9{i:05d}", "c": f"C{i}"} for i in ids])
    return ids


def _logs(engine, source: str, n: int, when: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO ingestion_logs (source, job_type, status, started_at, finished_at)
                             VALUES (:s, 'FINANCIALS', 'SUCCESS', :t, :t)"""), [{"s": source, "t": when}] * n)


@pytest.fixture
def budget(monkeypatch):
    def set_(kr: int, us: int = 0):
        monkeypatch.setattr(background, "config", lambda: {"dart_calls_per_day": kr, "sec_calls_per_day": us})
    return set_


def test_used_today_counts_only_today_and_source(engine):
    now = datetime.now(timezone.utc)
    _logs(engine, "DART", 3, now)
    _logs(engine, "DART", 4, now - timedelta(days=2))                   # 어제 이전
    _logs(engine, "DART_BULK", 5, now)                                   # 일괄 적재는 세지 않음
    _logs(engine, "SEC", 2, now)
    with engine.connect() as conn:
        assert used_today(conn, "DART", now) == 3 and used_today(conn, "SEC", now) == 2


def test_queue_skips_stocks_with_freshness(engine):
    ids = _listed(engine, 4)
    with engine.begin() as conn:
        freshness.mark(conn, "financials", ids[0], True)                 # 이미 받은 종목
        conn.execute(text("UPDATE stocks SET is_active = false WHERE stock_id = :i"), {"i": ids[1]})
        conn.execute(text("UPDATE stocks SET corp_code = NULL WHERE stock_id = :i"), {"i": ids[2]})   # 재무를 받을 수 없음
        conn.execute(text("UPDATE stocks SET corp_code = 'C1' WHERE stock_id = 1"))                  # featured는 대상 아님
        assert priority_queue(conn, "KR", 10, {}) == [ids[3]]


def test_kr_queue_orders_by_trading_value_then_cap(engine):
    ids = _listed(engine, 4)
    t = {i: f"9{i:05d}" for i in ids}
    ranking = {t[ids[0]]: (Decimal(100), Decimal(1)), t[ids[1]]: (Decimal(500), Decimal(1)),
               t[ids[2]]: (Decimal(100), Decimal(9))}                    # ids[3]은 순위 없음 → 맨 뒤
    with engine.connect() as conn:
        assert priority_queue(conn, "KR", 10, ranking) == [ids[1], ids[2], ids[0], ids[3]]
        assert priority_queue(conn, "KR", 2, ranking) == [ids[1], ids[2]]


def test_budget_stops_background(engine, budget):
    budget(kr=5)
    ids = _listed(engine, 4)
    _logs(engine, "DART", 3, datetime.now(timezone.utc))                # 오늘 이미 3행 사용 → 남은 2
    pv = replace(make_providers(), kr_financial=FakeFinancial("DART"),
                 kr_bulk=_Bulk({f"9{i:05d}": (10, 100 * k, 1) for k, i in enumerate(ids, 1)}))
    out = run_background(engine, pv)
    assert out["KR"]["budget"] == 5 and out["KR"]["used"] == 3 and out["KR"]["queued"] == 2
    assert set(out["KR"]["statuses"]) == {f"9{ids[3]:05d}", f"9{ids[2]:05d}"}   # 거래대금 큰 두 종목
    assert out["US"]["queued"] == 0
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'BENCHMARK' AND error LIKE '백그라운드:%'") == 1


def test_no_budget_left_makes_no_external_calls(engine, budget):
    budget(kr=3)
    _listed(engine, 2)
    _logs(engine, "DART", 3, datetime.now(timezone.utc))
    bulk = _Bulk({})
    pv = replace(make_providers(), kr_financial=FakeFinancial("DART"), kr_bulk=bulk)
    assert run_background(engine, pv)["KR"]["queued"] == 0
    assert bulk.count == 0 and pv.kr_financial.count == 0
