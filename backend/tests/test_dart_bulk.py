"""OpenDART 재무정보 일괄다운로드 첫 적재(dart_bulk) — 헤더 이름으로 열 찾기, 연결 우선, 재실행해도 같은 행 수 (추가기능 API 정의서 6-6).

픽스처 txt는 2025 사업보고서 파일과 같은 헤더(손익 파일의 이름 없는 빈 열 포함)·cp949·탭 구분으로 만든다.
"""
from __future__ import annotations

import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.ingest.dart_bulk import load_bulk, parse_file, to_financials
from app.ingest.jobs import to_krw
from app.providers.base import Financial, ProviderError
from app.providers.dart import DartClient
from tests.conftest import scalar

BS_HEADER = ["재무제표종류", "종목코드", "회사명", "시장구분", "업종", "업종명", "결산월", "결산기준일", "보고서종류", "통화",
             "항목코드", "항목명", "당기", "전기", "전전기", ""]
PL_HEADER = ["재무제표종류", "종목코드", "회사명", "시장구분", "업종", "업종명", "결산월", "결산기준일", "보고서종류", "통화",
             "항목코드", "항목명", "", "당기", "", "", "전기", "전전기", ""]


def _bs(kind, code, end, aid, nm, amount, cur="KRW"):
    return [kind, f"[{code}]", "회사", "유가증권시장상장법인", "264", "업종", "12", end, "사업보고서", cur, aid, nm, amount, "1", "1", ""]


def _pl(kind, code, end, aid, nm, amount, cur="KRW"):
    return [kind, f"[{code}]", "회사", "유가증권시장상장법인", "264", "업종", "12", end, "사업보고서", cur, aid, nm, "", amount, "", "", "1", "1", ""]


def _write(path, header, rows):
    path.write_bytes("\n".join("\t".join(r) for r in [header, *rows]).encode("cp949"))
    return path


@pytest.fixture
def files(tmp_path):
    """005930: 연결·별도 둘 다(연결이 이김), 000660: 별도만, 999999: DB에 없는 회사."""
    bs = _write(tmp_path / "2025_사업보고서_01_재무상태표.txt", BS_HEADER, [
        _bs("재무상태표, 유동/비유동법 - 연결", "005930", "2025-12-31", "ifrs-full_Assets", "자산총계", "566,942,110,000,000"),
        _bs("재무상태표, 유동/비유동법 - 연결", "005930", "2025-12-31", "ifrs-full_Equity", "자본총계", "436,320,337,000,000"),
        _bs("재무상태표, 유동/비유동법 - 연결", "005930", "2025-12-31", "ifrs-full_EquityAttributableToOwnersOfParent",
            "지배기업의 소유주에게 귀속되는 자본", "424,313,255,000,000"),
        _bs("재무상태표, 유동/비유동법 - 연결", "005930", "2025-12-31", "ifrs-full_Liabilities", "부채총계", "130,621,773,000,000"),
        _bs("재무상태표, 유동/비유동법 - 별도", "005930", "2025-12-31", "ifrs-full_Assets", "자산총계", "358,902,051,000,000"),
        _bs("재무상태표, 유동/비유동법 - 별도", "000660", "2025-12-31", "ifrs-full_Assets", "자산총계", "100"),
        _bs("재무상태표, 유동/비유동법 - 별도", "999999", "2025-12-31", "ifrs-full_Assets", "자산총계", "1"),
    ])
    pl = _write(tmp_path / "2025_사업보고서_03_포괄손익계산서.txt", PL_HEADER, [
        _pl("단일 포괄손익계산서, 기능별 분류, 세후 - 연결", "005930", "2025-12-31", "ifrs-full_Revenue", "매출액", "333,605,938,000,000"),
        _pl("단일 포괄손익계산서, 기능별 분류, 세후 - 연결", "005930", "2025-12-31", "dart_OperatingIncomeLoss", "영업이익", "43,601,051,000,000"),
        _pl("단일 포괄손익계산서, 기능별 분류, 세후 - 연결", "005930", "2025-12-31", "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "지배기업의 소유주에게 귀속되는 당기순이익", "44,260,956,000,000"),
        _pl("단일 포괄손익계산서, 기능별 분류, 세후 - 별도", "000660", "2025-12-31", "ifrs-full_Revenue", "매출액", "-"),
    ])
    z = tmp_path / "2025_4Q_PL.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(pl, pl.name.encode("cp949").decode("cp437"))   # OpenDART zip처럼 파일 이름이 cp949
    return [bs, z]


def test_parse_requires_columns(tmp_path):
    bad = _write(tmp_path / "bad.txt", [h for h in BS_HEADER if h != "항목코드"], [])
    with pytest.raises(ValueError, match="항목코드"):
        parse_file(bad)


def test_parse_finds_columns_by_name_and_reads_zip(files):
    rows = parse_file(files[1])                                          # 손익: 빈 열 때문에 '당기'가 14번째 열
    rev = next(r for r in rows if r.account_id == "ifrs-full_Revenue" and r.stock_code == "005930")
    assert rev.amount == Decimal("333605938000000") and rev.statement == "CIS" and rev.consolidated
    assert next(r for r in rows if r.stock_code == "000660").amount is None   # "-"는 값 없음


def test_consolidated_preferred_over_separate(files):
    fins = to_financials(parse_file(files[0]) + parse_file(files[1]))
    s = fins["005930"][0]
    assert (s.period_end, s.total_assets, s.total_equity, s.revenue, s.net_income) == (
        date(2025, 12, 31), Decimal("566942110000000.00"), Decimal("424313255000000.00"),   # 자본 = 지배기업 귀속(API와 같은 규칙)
        Decimal("333605938000000.00"), Decimal("44260956000000.00"))
    assert s.notes == [] and fins["000660"][0].notes == ["fs_div=OFS"]       # 별도만 있으면 별도 + 표시


def test_load_bulk_is_idempotent_and_seeds_cursor(engine, files):
    for _ in range(2):
        out = load_bulk(engine, files, as_of=date(2026, 10, 8))
        assert out == {"files": 2, "companies": 2, "rows": 2, "skipped": 1}
    assert scalar(engine, "SELECT count(*) FROM financial_statements") == 2
    assert scalar(engine, "SELECT count(*) FROM data_freshness WHERE kind = 'financials' AND status = 'SUCCESS'") == 2
    assert scalar(engine, "SELECT last_rcept_no FROM ingest_cursor WHERE source = 'DART_A001'") == "20261008000000"
    assert scalar(engine, "SELECT source FROM ingestion_logs WHERE job_type = 'FINANCIALS'") == "DART_BULK"


def test_load_bulk_does_not_move_newer_cursor_back(engine, files):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO ingest_cursor (source, last_rcept_no, last_rcept_dt) VALUES ('DART_A001', '20261015000123', '2026-10-15')"))
    load_bulk(engine, files, as_of=date(2026, 10, 8))
    assert scalar(engine, "SELECT last_rcept_no FROM ingest_cursor") == "20261015000123"


# ------------------------------------------------------------------ 표시통화 (D-026)
def test_to_krw_converts_foreign_statements_at_period_end_rate():
    """원화가 아닌 표시통화(두산밥캣 USD)는 결산일 환율로 원화 환산하고 원래 통화·환율을 남긴다. USD 밖 통화·환율 없음은 넣지 않는다."""
    f = Financial(period_end=date(2025, 12, 31), period_type="FY", revenue=Decimal("10"), net_income=Decimal("-2"), currency="USD")
    out = to_krw([f], lambda d: Decimal("1400.5"))[0]
    assert (out.revenue, out.net_income, out.total_assets) == (Decimal("14005.00"), Decimal("-2801.00"), None)
    assert (out.currency, out.fx_rate) == ("USD", Decimal("1400.5")) and "USD→KRW 1400.5(결산일)" in out.notes
    kr = to_krw([Financial(period_end=date(2025, 12, 31), period_type="FY", revenue=Decimal("10"))], lambda d: None)[0]
    assert (kr.revenue, kr.currency, kr.fx_rate) == (Decimal("10"), "KRW", None)       # 원화 공시는 그대로(환율 조회 안 함)
    with pytest.raises(ProviderError, match="CNY"):
        to_krw([Financial(period_end=date(2025, 12, 31), period_type="FY", currency="CNY")], lambda d: Decimal(1))
    with pytest.raises(ProviderError, match="환율 없음"):
        to_krw([f], lambda d: None)
    assert DartClient._currency([{"currency": ""}, {"currency": "usd"}]) == "USD" and DartClient._currency([]) is None


def test_load_bulk_converts_usd_statements_with_stored_fx(engine, tmp_path):
    """일괄 파일의 '통화' 열이 USD면 DB의 결산일 USD/KRW로 환산한다. 그날 환율이 없는 회사는 넣지 않고 건너뛴다."""
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES ('2025-12-30 15:00+09', 1440, 'DAILY')"""))
    bs = _write(tmp_path / "bs.txt", BS_HEADER, [
        _bs("재무상태표, 유동/비유동법 - 연결", "005930", "2025-12-31", "ifrs-full_Assets", "자산총계", "1,000", cur="USD"),
        _bs("재무상태표, 유동/비유동법 - 연결", "000660", "2024-12-31", "ifrs-full_Assets", "자산총계", "1,000", cur="USD"),
    ])
    assert parse_file(bs)[0].currency == "USD"
    out = load_bulk(engine, [bs], as_of=date(2026, 10, 8))
    assert out["companies"] == 1 and out["skipped"] == 1                               # 000660: 2024-12-31 환율 없음
    with engine.connect() as conn:
        row = conn.execute(text("SELECT total_assets, currency, fx_rate FROM financial_statements")).one()
    assert tuple(row) == (Decimal("1440000.00"), "USD", Decimal("1440.0000"))
