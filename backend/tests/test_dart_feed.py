"""공시 목록 증분(load_dart_feed) — 새 사업보고서를 낸 DB 종목만 재무 만료, 기준점은 성공한 뒤에만 이동 (추가기능 API 정의서 6-4).

실제 list.json은 접수번호 순으로 정렬되지 않는다([첨부추가] 등이 앞에 섞임). 그래서 기준점에서 멈추지 않고 기간 안 전체 페이지를 받는다.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.ingest import jobs
from app.providers.dart import FiledReport
from app.services import freshness
from tests.conftest import scalar
from tests.fakes import FakeDartFeed, FakeFinancial, make_providers

TODAY = date(2026, 3, 20)
SAMSUNG = "00126380"


def _r(no: str, corp: str = SAMSUNG, nm: str = "사업보고서 (2025.12)") -> FiledReport:
    return FiledReport(rcept_no=no, rcept_dt=date(int(no[:4]), int(no[4:6]), int(no[6:8])), corp_code=corp,
                       stock_code=None, report_nm=nm)


def _setup(engine, cursor: tuple[str, date] | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET corp_code = :c WHERE stock_id = 1"), {"c": SAMSUNG})
        freshness.mark(conn, "financials", 1, True, now=datetime.now(timezone.utc) - timedelta(days=1))
        if cursor:
            conn.execute(text("INSERT INTO ingest_cursor (source, last_rcept_no, last_rcept_dt) VALUES ('DART_A001', :n, :d)"),
                         {"n": cursor[0], "d": cursor[1]})


def _cursor(engine):
    return scalar(engine, "SELECT last_rcept_no FROM ingest_cursor WHERE source = 'DART_A001'")


def _run(engine, feed: FakeDartFeed) -> dict:
    return jobs.load_dart_feed(engine, make_providers(kr_feed=feed), today=TODAY)


def test_feed_expires_only_db_stocks_and_moves_cursor(engine):
    _setup(engine)
    feed = FakeDartFeed([([_r("20260318000100"), _r("20260319000200", corp="99999999"),
                           _r("20260319000300", nm="반기보고서 (2025.12)")], 1)])
    out = _run(engine, feed)
    assert out == {"status": "SUCCESS", "pages": 1, "filings": 2, "matched": 1, "expired": 1, "cursor": "20260319000300"}
    assert scalar(engine, "SELECT rcept_no FROM disclosures") == "20260318000100"
    with engine.connect() as conn:
        assert freshness.due(conn, "financials", [1]) == [1]                # 다음 재무 작업 대상
    assert _cursor(engine) == "20260319000300"


def test_feed_reads_every_page_even_when_order_is_mixed(engine):
    _setup(engine, ("20260317000500", date(2026, 3, 17)))
    feed = FakeDartFeed([([_r("20260316000001", nm="[첨부추가]사업보고서 (2025.12)")], 2),   # 1페이지는 기준점 이하만
                         ([_r("20260318000100")], 2)])
    out = _run(engine, feed)
    assert feed.count == 2 and out["matched"] == 1 and _cursor(engine) == "20260318000100"


def test_feed_skips_attachment_only_filings(engine):
    _setup(engine, ("20260317000500", date(2026, 3, 17)))
    feed = FakeDartFeed([([_r("20260318000700", nm="[첨부추가]사업보고서 (2025.12)"),
                           _r("20260318000800", nm="[기재정정]사업보고서 (2025.12)")], 1)])
    out = _run(engine, feed)
    assert out["filings"] == 1 and out["matched"] == 1                     # 정정은 만료, 첨부만 바뀐 공시는 아님
    assert scalar(engine, "SELECT title FROM disclosures") == "[기재정정]사업보고서 (2025.12)"
    assert _cursor(engine) == "20260318000800"


def test_feed_failure_keeps_cursor(engine):
    _setup(engine, ("20260317000500", date(2026, 3, 17)))
    feed = FakeDartFeed([([_r("20260318000100")], 2), ([], 2)], fail_on=2)
    out = _run(engine, feed)
    assert out["status"] == "FAILED" and out["cursor"] == "20260317000500"
    assert _cursor(engine) == "20260317000500"
    assert scalar(engine, "SELECT count(*) FROM disclosures") == 0
    with engine.connect() as conn:
        assert freshness.due(conn, "financials", [1]) == []                 # 실패하면 아무것도 만료하지 않는다
    assert "가짜 목록 실패" in scalar(engine, "SELECT error FROM ingestion_logs WHERE status = 'FAILED'")


def test_feed_splits_long_gap_into_90_day_windows(engine):
    start = TODAY - timedelta(days=200)
    _setup(engine, (f"{start:%Y%m%d}000001", start))
    feed = FakeDartFeed([([], 0)] * 3)
    _run(engine, feed)
    windows = [(c[0], c[1]) for c in feed.calls]
    assert len(windows) == 3 and windows[0][0] == start - timedelta(days=2) and windows[-1][1] == TODAY
    assert all((e - s).days <= 89 for s, e in windows)
    assert all(windows[i][1] + timedelta(days=1) == windows[i + 1][0] for i in range(2))   # 오래된 구간부터, 빈틈 없이


def test_feed_first_run_starts_7_days_back(engine):
    _setup(engine)
    feed = FakeDartFeed([([], 0)])
    out = _run(engine, feed)
    assert feed.calls[0][0] == TODAY - timedelta(days=7)
    assert out["cursor"] == "20260313000000" and _cursor(engine) == "20260313000000"


def test_feed_skipped_without_provider(engine):
    assert jobs.load_dart_feed(engine, make_providers(), today=TODAY)["status"] == "SKIPPED"


class _EmptyFinancial(FakeFinancial):
    def get_annual_financials(self, stock, years):
        self.record(stock.ticker, years)
        return []


def test_empty_financials_are_failed(engine):
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET corp_code = :c WHERE stock_id = 1"), {"c": SAMSUNG})
    pv = replace(make_providers(), kr_financial=_EmptyFinancial("DART"))
    assert jobs.load_financials(engine, pv, stock_ids=[1]) == {"005930": "FAILED"}
    assert scalar(engine, "SELECT status FROM data_freshness WHERE stock_id = 1") == "FAILED"
    assert "재무 빈 응답" in scalar(engine, "SELECT error FROM data_freshness WHERE stock_id = 1")
