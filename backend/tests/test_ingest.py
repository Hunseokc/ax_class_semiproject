"""수집·전처리: 이상 행 격리, 샘플 재적재 시 행 수 불변."""
import csv
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.ingest import jobs, sample
from app.ingest.preprocess import Bar, FxPoint, clean_bars, clean_fx
from app.ingest.universe import StockSpec, load_universe
from tests.conftest import TABLES, scalar


def bar(d, o=10, h=11, l=9, c=10, v=100):
    return Bar(d, Decimal(o), Decimal(h), Decimal(l), Decimal(c) if c is not None else None, v)


def test_clean_bars_quarantines_with_reason():
    d0 = date(2026, 1, 5)
    bars = [bar(d0), bar(d0, c=12),                      # 중복 → 마지막 값 유지
            bar(d0 + timedelta(1), h=8),                  # 고가 < 저가
            bar(d0 + timedelta(2), o=0, h=0, l=0, c=0),   # 거래정지
            bar(d0 + timedelta(3), c=None),               # 종가 결측
            bar(d0 + timedelta(4), v=-1)]                 # 음수 거래량
    ok, bad = clean_bars(bars, "Asia/Seoul", require_volume=True, now=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert [(b.trade_date, b.close) for b in ok] == [(d0, 12)]
    assert sorted(q.reason for q in bad) == sorted(["고가 < 저가", "가격 0 이하(거래정지 등)", "종가 결측", "음수 거래량"])


def test_clean_bars_drops_unfinished_session():
    now = datetime(2026, 3, 3, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))      # 장중
    ok, bad = clean_bars([bar(date(2026, 3, 2)), bar(date(2026, 3, 3))], "Asia/Seoul", require_volume=True, now=now)
    assert [b.trade_date for b in ok] == [date(2026, 3, 2)]
    assert bad[0].reason == "장 마감 전 미확정 봉"


def test_clean_fx_quarantines_spike():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 문자열로 만든다: Decimal(13.01)은 float 오차가 섞여 Decimal("13.01")과 다른 값이 된다
    pts = [FxPoint(base + timedelta(days=i), Decimal(v))
           for i, v in enumerate(["1300", "1302", "1301", "13.01", "1303", "1304"])]
    ok, bad = clean_fx(pts)
    assert [p.usd_krw for p in ok] == [Decimal(v) for v in ("1300", "1302", "1301", "1303", "1304")]
    assert [q.row["usd_krw"] for q in bad] == [Decimal("13.01")]
    assert "초과 이탈" in bad[0].reason


def test_master_failure_is_logged_and_raised(engine, monkeypatch):
    """마스터 적재가 실패하면 FAILED 로그를 남기고 예외를 전파한다(CLI가 성공으로 끝나지 않는다)."""
    u = load_universe()
    broken = replace(u, indices=(replace(u.indices[0], market="NOPE"),))      # 없는 시장 코드
    monkeypatch.setattr(jobs, "load_universe", lambda: broken)
    with pytest.raises(KeyError):
        jobs.load_master(engine, offline=True)
    assert scalar(engine, "SELECT status FROM ingestion_logs WHERE job_type = 'MASTER'") == "FAILED"
    assert scalar(engine, "SELECT count(*) FROM stocks") == 4                 # 롤백: 픽스처 4종목 그대로


def test_master_rejects_ticker_listed_in_two_markets(engine, monkeypatch):
    """peer_groups.members는 티커만 적으므로, 같은 티커가 두 시장에 있으면 적재 전에 멈춘다."""
    u = load_universe()
    dup = replace(u, stocks=u.stocks + (StockSpec("NASDAQ", "005930", "Dup", "005930"),))
    monkeypatch.setattr(jobs, "load_universe", lambda: dup)
    with pytest.raises(ValueError, match="중복"):
        jobs.load_master(engine, offline=True)
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs") == 0         # DB를 건드리기 전에 실패


def _csv_rows(name: str) -> int:
    with (sample.SAMPLE_DIR / name).open(encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _counts(engine) -> dict[str, int]:
    # ingestion_logs는 실행할 때마다 1행씩 쌓이는 것이 정상이라 비교에서 뺀다
    return {t: scalar(engine, f"SELECT count(*) FROM {t}") for t in TABLES if t != "ingestion_logs"}


def test_sample_reload_is_idempotent(engine):
    # conftest의 고정 픽스처를 비우고, 실제 마스터 + 샘플만으로 시작한다
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))

    def run():
        jobs.load_master(engine, offline=True)
        sample.import_sample(engine)

    run()
    first = _counts(engine)
    run()
    assert _counts(engine) == first                                       # 두 번 실행해도 행 수 동일

    u = load_universe()
    assert first["markets"] == len(u.markets)
    assert first["stocks"] == len(u.stocks)
    assert first["indices"] == len(u.indices)
    assert first["peer_groups"] == len(u.peer_groups)
    assert first["peer_group_members"] == sum(len(g.members) for g in u.peer_groups)
    assert first["daily_prices"] == _csv_rows("daily_prices.csv")
    assert first["valuation_snapshots"] == _csv_rows("valuation_snapshots.csv")
    assert first["index_daily_prices"] == _csv_rows("index_daily_prices.csv")
    assert first["fx_rates"] == _csv_rows("fx_rates.csv")
    assert all(n > 0 for n in first.values())                             # 모든 Stage 1 테이블에 행이 있다
    assert scalar(engine, "SELECT count(*) FROM ingestion_logs WHERE job_type = 'MASTER' AND status = 'SUCCESS'") == 2
