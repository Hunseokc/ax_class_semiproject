"""회사 단위 잠금(LockSession)·묶음 저장(BatchWriter)·하루 재무 예산(due limit) — 추가기능 API 정의서 4절."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.ingest.store import (DART_LOCK_KEY, SEC_LOCK_KEY, BatchWriter, LockSession, Unit, provider_lock_key)
from app.services import freshness
from tests.conftest import scalar


def _try_lock(engine, key: int) -> bool:
    """다른 연결에서 잠금을 잡아 보고 바로 푼다. 잡히면 True(아무도 안 잡고 있음)."""
    with engine.connect() as conn:
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
        if got:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        conn.commit()
    return got


def _unit(stock_id: int, **kw) -> Unit:
    return Unit(source="DART", job_type="DISCLOSURES", stock_id=stock_id, label=f"T{stock_id}", country="KR",
                kind="disclosures", started_at=datetime.now(timezone.utc), **kw)


def _add_stocks(engine, n: int) -> list[int]:
    ids = list(range(101, 101 + n))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name) VALUES (:i, 1, :t, :t)"),
                     [{"i": i, "t": f"9{i:05d}"} for i in ids])
    return ids


def test_provider_lock_key_splits_by_country():
    assert provider_lock_key("KR") == DART_LOCK_KEY == 7_301_010
    assert provider_lock_key("US") == SEC_LOCK_KEY == 7_301_012
    with pytest.raises(ValueError):
        provider_lock_key("JP")


def test_lock_session_reuses_one_connection_and_releases(engine):
    with LockSession(engine) as locks:
        with locks.hold(DART_LOCK_KEY) as waited:
            assert waited >= 0 and not _try_lock(engine, DART_LOCK_KEY)     # 잡고 있는 동안은 다른 연결이 못 잡음
            assert _try_lock(engine, SEC_LOCK_KEY)                          # 다른 나라 키는 따로
        assert _try_lock(engine, DART_LOCK_KEY)                             # hold를 나오면 바로 풀림
        conn = locks.conn
        with locks.hold(DART_LOCK_KEY):
            assert locks.conn is conn                                       # 같은 연결을 다시 씀
    with pytest.raises(RuntimeError):
        with locks.hold(DART_LOCK_KEY):
            pass


def test_batch_writer_flushes_every_n(engine):
    ids = _add_stocks(engine, 25)
    writer = BatchWriter(engine, 20)
    for i in ids:
        writer.add(_unit(i, writes=[("disclosures", [{"stock_id": i, "rcept_no": f"r{i}", "title": "공시",
                                                       "report_type": "기타", "filed_at": datetime.now(timezone.utc),
                                                       "url": None, "data_source": "DART"}], ["rcept_no"])], rows=1))
    assert writer.flushes == 1                                              # 20개째에서 한 번
    writer.flush()
    assert writer.flushes == 2 and writer.flush() == [] and writer.flushes == 2
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'DISCLOSURES'") == 25
    assert scalar(engine, "SELECT count(*) FROM disclosures") == 25
    assert scalar(engine, "SELECT count(*) FROM data_freshness WHERE status = 'SUCCESS'") == 25
    assert [u.status for u in writer.done] == ["SUCCESS"] * 25


def test_failed_unit_marks_freshness_failed_and_logs(engine):
    writer = BatchWriter(engine, 20)
    writer.add(_unit(1, error="ProviderError: 가짜 실패",
                     writes=[("disclosures", [{"stock_id": 1, "rcept_no": "x"}], ["rcept_no"])]))
    writer.flush()
    assert scalar(engine, "SELECT count(*) FROM disclosures") == 0          # 실패한 회사의 행은 쓰지 않음
    assert scalar(engine, "SELECT status FROM data_freshness WHERE stock_id = 1") == "FAILED"
    assert scalar(engine, "SELECT error FROM ingestion_logs WHERE stock_id = 1 AND status = 'FAILED'") == "ProviderError: 가짜 실패"


def test_flush_db_error_fails_batch_but_keeps_logs(engine):
    writer = BatchWriter(engine, 20)
    writer.add(_unit(1, writes=[("disclosures", [{"stock_id": 1, "rcept_no": "ok", "title": "공시", "report_type": "기타",
                                                 "filed_at": datetime.now(timezone.utc), "url": None,
                                                 "data_source": "DART"}], ["rcept_no"])]))
    writer.add(_unit(2, writes=[("no_such_table", [{"a": 1}], ["a"])]))
    batch = writer.flush()
    assert [u.status for u in batch] == ["FAILED", "FAILED"]
    assert all(u.error.startswith("묶음 저장 실패: ") for u in batch)
    assert scalar(engine, "SELECT count(*) FROM disclosures") == 0          # 묶음 전체가 롤백
    assert scalar(engine, "SELECT count(*) FROM data_freshness WHERE status = 'SUCCESS'") == 0
    assert scalar(engine, "SELECT count(*) FROM data_freshness WHERE status = 'FAILED'") == 2
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE status = 'FAILED'") == 2


def test_on_flush_gets_only_successful_units(engine):
    seen = []
    writer = BatchWriter(engine, 20, on_flush=lambda units: seen.extend(u.stock_id for u in units))
    writer.add(_unit(1))
    writer.add(_unit(2, error="실패"))
    writer.flush()
    assert seen == [1]


def test_due_limit_orders_missing_then_oldest(engine):
    ids = _add_stocks(engine, 5)                                            # 101, 102: 기록 없음
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for sid, days_ago in ((103, 1), (104, 5), (105, 3)):                # 지난 정도: 104 > 105 > 103
            freshness.mark(conn, "financials", sid, False, now=now - timedelta(days=days_ago + 1))
        assert freshness.due(conn, "financials", ids, now=now, limit=3) == [101, 102, 104]
        assert freshness.due(conn, "financials", list(reversed(ids)), now=now) == list(reversed(ids))
        assert freshness.due(conn, "financials", ids, now=now, limit=0) == []
