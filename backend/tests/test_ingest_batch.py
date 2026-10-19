"""재무·공시 수집의 회사 단위 잠금 + 묶음 저장 통합 — 상세 요청이 비교군 묶음 전체를 기다리지 않는다 (추가기능 API 정의서 4절)."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.ingest import jobs
from app.services import freshness
from tests.conftest import scalar
from tests.fakes import FakeDisclosure, FakeFinancial, make_providers


def _providers(delay: float = 0.0):
    return replace(make_providers(), kr_financial=FakeFinancial("DART", delay), us_financial=FakeFinancial("SEC"),
                   kr_disclosure=FakeDisclosure("DART"), us_disclosure=FakeDisclosure("SEC"))


def _add_kr_stocks(engine, n: int) -> list[int]:
    ids = list(range(101, 101 + n))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO stocks (stock_id, market_id, ticker, name, corp_code) VALUES (:i, 1, :t, :t, :c)"),
                     [{"i": i, "t": f"9{i:05d}", "c": f"C{i}"} for i in ids])
    return ids


def test_financials_statuses_and_freshness_after_batch(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET corp_code = 'C' || ticker WHERE stock_id = 1"))
        conn.execute(text("UPDATE stocks SET cik = '0000320193' WHERE stock_id = 3"))
    st = jobs.load_financials(engine, _providers(), years=2, stock_ids=[1, 2, 3])   # 2는 corp_code 없음
    assert st == {"005930": "SUCCESS", "000660": "FAILED", "AAPL": "SUCCESS"}
    with engine.connect() as conn:
        fr = dict(conn.execute(text("SELECT stock_id, status FROM data_freshness WHERE kind = 'financials'")).all())
        err = conn.execute(text("SELECT error FROM data_freshness WHERE stock_id = 2")).scalar()
    assert fr == {1: "SUCCESS", 2: "FAILED", 3: "SUCCESS"}
    assert "미매핑" in err                                                  # 고정 문구가 아니라 실제 사유
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'FINANCIALS'") == 3


def test_small_flush_every_writes_in_several_transactions(engine):
    ids = _add_kr_stocks(engine, 5)
    st = jobs.load_financials(engine, _providers(), years=2, stock_ids=ids, flush_every=2)
    assert set(st.values()) == {"SUCCESS"} and len(st) == 5
    assert scalar(engine, "SELECT count(*) FROM financial_statements") == 10


def test_disclosure_annual_report_expires_financials_in_same_batch(engine):
    with engine.begin() as conn:                                            # 사업보고서보다 먼저 받아 둔 재무
        freshness.mark(conn, "financials", 1, True, now=datetime.now(timezone.utc) - timedelta(days=60))
        conn.execute(text("UPDATE data_freshness SET valid_until = now() + interval '30 days' WHERE stock_id = 1"))
    st = jobs.load_disclosures(engine, _providers(), days=90, stock_ids=[1])
    assert st == {"005930": "SUCCESS"}
    with engine.connect() as conn:
        assert freshness.due(conn, "financials", [1]) == [1]
    assert "재무 유효기간 만료" in scalar(engine, "SELECT error FROM ingestion_logs WHERE job_type = 'DISCLOSURES'")


def test_detail_request_waits_only_one_company(engine):
    ids = _add_kr_stocks(engine, 7)
    batch, detail = ids[:6], ids[6]
    pv = _providers(delay=0.3)
    t = threading.Thread(target=jobs.load_financials, args=(engine, pv), kwargs={"years": 2, "stock_ids": batch})
    t.start()
    time.sleep(0.1)
    started = time.monotonic()
    assert jobs.load_financials(engine, pv, years=2, stock_ids=[detail]) == {f"9{detail:05d}": "SUCCESS"}
    took = time.monotonic() - started
    t.join()
    assert took < 1.0, took                                                 # 묶음 전체(약 1.8초)를 기다리지 않는다
    assert scalar(engine, "SELECT count(*) FROM data_freshness WHERE status = 'SUCCESS'") == 7


def test_kr_and_us_do_not_share_lock(engine):
    ids = _add_kr_stocks(engine, 4)
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET cik = '0000320193' WHERE stock_id = 3"))
    pv = _providers(delay=0.5)
    t = threading.Thread(target=jobs.load_financials, args=(engine, pv), kwargs={"years": 2, "stock_ids": ids})
    t.start()
    time.sleep(0.1)
    started = time.monotonic()
    assert jobs.load_financials(engine, pv, years=2, stock_ids=[3]) == {"AAPL": "SUCCESS"}
    took = time.monotonic() - started
    t.join()
    assert took < 0.4, took                                                 # KR 잠금을 기다리지 않음
    note = scalar(engine, "SELECT error FROM ingestion_logs WHERE stock_id = 3")
    assert note is None or "잠금 대기" not in note
