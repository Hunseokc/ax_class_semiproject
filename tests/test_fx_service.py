"""환율 서비스: TTL·실패 시 마지막 값·동시 요청 중복 호출 방지."""
import threading
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.errors import ServiceUnavailable
from app.services.fx import FxService
from tests.conftest import scalar
from tests.fakes import FakeFx


def age_snapshots(engine, hours: int = 5) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE fx_rates SET rate_at = rate_at - make_interval(hours => :h) WHERE granularity = 'SNAPSHOT'"),
                     {"h": hours})


def test_within_ttl_no_external_call(engine):
    fx = FakeFx()
    q = FxService(engine, fx, 4).get_current_rate()
    assert fx.current.count == 0
    assert q.usd_krw == Decimal(1300) and q.stale is False and q.granularity == "SNAPSHOT"


def test_ttl_expired_calls_once_and_stores_snapshot(engine):
    age_snapshots(engine)
    fx = FakeFx(rate="1350")
    svc = FxService(engine, fx, 4)
    q1, q2 = svc.get_current_rate(), svc.get_current_rate()
    assert fx.current.count == 1                    # 두 번째 요청은 새 SNAPSHOT(TTL 이내)을 읽음
    assert q1.usd_krw == q2.usd_krw == Decimal(1350) and q1.stale is False
    assert scalar(engine, "SELECT count(*) FROM fx_rates WHERE granularity = 'SNAPSHOT'") == 2
    assert scalar(engine, "SELECT status FROM ingestion_logs WHERE job_type = 'FX'") == "SUCCESS"


def test_failure_returns_last_value_with_stale(engine):
    age_snapshots(engine)
    fx = FakeFx(fail=True)
    svc = FxService(engine, fx, 4)
    q = svc.get_current_rate()
    assert q.stale is True and q.usd_krw == Decimal(1300)
    assert scalar(engine, "SELECT status FROM ingestion_logs WHERE job_type = 'FX'") == "FAILED"
    svc.get_current_rate()                          # 실패 직후 재요청 → 쿨다운으로 외부 호출 안 함
    assert fx.current.count == 1


def test_failure_without_any_stored_rate_is_error(engine):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM fx_rates"))
    with pytest.raises(ServiceUnavailable):
        FxService(engine, FakeFx(fail=True), 4).get_current_rate()
    # 503으로 끝나도 실패 기록은 남는다
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'FX' AND status = 'FAILED'") == 1


def test_concurrent_requests_call_external_once(engine):
    age_snapshots(engine)
    fx = FakeFx(rate="1360", delay=0.3)
    svc = FxService(engine, fx, 4)
    barrier, results = threading.Barrier(6), []

    def worker():
        barrier.wait()
        results.append(svc.get_current_rate())

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert fx.current.count == 1
    assert {r.usd_krw for r in results} == {Decimal(1360)}
