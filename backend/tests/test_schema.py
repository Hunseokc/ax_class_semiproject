"""DB 설계(Stage 1 테이블 10개): ORM ↔ schema.sql 일치, 제약조건(CHECK/UNIQUE/FK/CASCADE) 방어.

이후 단계 테이블이 추가되면 담당 단계에서 테이블 수와 제약 케이스를 늘린다.
"""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models import Base

STAGE1_TABLES = {"markets", "stocks", "peer_groups", "peer_group_members", "daily_prices", "valuation_snapshots",
                 "indices", "index_daily_prices", "fx_rates", "ingestion_logs"}


def test_orm_matches_schema(engine):
    insp, dialect = inspect(engine), postgresql.dialect()
    diffs = []
    for t in Base.metadata.sorted_tables:
        db_cols = {c["name"]: c for c in insp.get_columns(t.name)}
        for c in t.columns:
            d = db_cols.pop(c.name, None)
            if d is None:
                diffs.append(f"{t.name}.{c.name} DB에 없음")
                continue
            if str(d["type"].compile(dialect=dialect)) != str(c.type.compile(dialect=dialect)):
                diffs.append(f"{t.name}.{c.name} 타입 {d['type']} vs {c.type}")
            if d["nullable"] != c.nullable and not c.primary_key:
                diffs.append(f"{t.name}.{c.name} NULL 허용 불일치")
        diffs += [f"{t.name}.{x} ORM에 없음" for x in db_cols]
    assert diffs == []


def test_tables_are_stage1_only(engine):
    assert set(Base.metadata.tables) == STAGE1_TABLES
    assert set(inspect(engine).get_table_names()) == STAGE1_TABLES


@pytest.mark.parametrize("label, sql", [
    ("고가 < 저가", "INSERT INTO daily_prices VALUES (1, '2030-01-01', 10, 9, 11, 10, 1)"),
    ("음수 거래량", "INSERT INTO daily_prices VALUES (1, '2030-01-02', 10, 11, 9, 10, -1)"),
    ("가격 0", "INSERT INTO daily_prices VALUES (1, '2030-01-03', 0, 0, 0, 0, 1)"),
    ("일봉 중복(PK)", "INSERT INTO daily_prices SELECT * FROM daily_prices LIMIT 1"),
    ("없는 종목 FK", "INSERT INTO daily_prices VALUES (999, '2030-01-04', 10, 11, 9, 10, 1)"),
    ("잘못된 국가", "INSERT INTO markets (code, country, currency, timezone) VALUES ('X', 'JP', 'KRW', 'x')"),
    ("잘못된 통화", "INSERT INTO markets (code, country, currency, timezone) VALUES ('Y', 'KR', 'JPY', 'x')"),
    ("잘못된 granularity", "INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now(), 1, 'HOURLY')"),
    ("환율 0", "INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now(), 0, 'DAILY')"),
    ("환율 중복", "INSERT INTO fx_rates (rate_at, usd_krw, granularity) SELECT rate_at, usd_krw, granularity FROM fx_rates LIMIT 1"),
    ("지수 종가 0", "INSERT INTO index_daily_prices (index_id, trade_date, close) VALUES (1, '2030-01-01', 0)"),
    ("음수 시가총액", "INSERT INTO valuation_snapshots (stock_id, as_of, market_cap, source) VALUES (1, '2030-01-01', -1, 'PYKRX')"),
    ("잘못된 밸류 source", "INSERT INTO valuation_snapshots (stock_id, as_of, source) VALUES (1, '2030-01-01', 'X')"),
    ("같은 시장 같은 티커", "INSERT INTO stocks (market_id, ticker, name) VALUES (1, '005930', '중복')"),
    ("같은 이름 그룹", "INSERT INTO peer_groups (name) VALUES ('반도체')"),
    ("잘못된 job_type", "INSERT INTO ingestion_logs (source, job_type, status, started_at) VALUES ('INTERNAL', 'X', 'SUCCESS', now())"),
    ("종료 < 시작", "INSERT INTO ingestion_logs (source, job_type, status, started_at, finished_at) "
                  "VALUES ('INTERNAL', 'PRICES', 'SUCCESS', now(), now() - interval '1 hour')"),
])
def test_constraints_reject_bad_rows(engine, label, sql):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(sql))


def test_delete_cascades(engine):
    """종목 삭제 → 일봉·밸류·그룹 소속 CASCADE, 로그의 stock_id는 SET NULL. 그룹 삭제 → 소속 CASCADE."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO ingestion_logs (source, job_type, stock_id, status, started_at) "
                          "VALUES ('PYKRX', 'PRICES', 1, 'SUCCESS', now())"))
        conn.execute(text("DELETE FROM stocks WHERE stock_id = 1"))
        left = conn.execute(text("""SELECT (SELECT count(*) FROM daily_prices WHERE stock_id = 1),
                                           (SELECT count(*) FROM valuation_snapshots WHERE stock_id = 1),
                                           (SELECT count(*) FROM peer_group_members WHERE stock_id = 1),
                                           (SELECT stock_id FROM ingestion_logs)""")).one()
        assert tuple(left) == (0, 0, 0, None)
        conn.execute(text("DELETE FROM peer_groups WHERE group_id = 1"))
        assert conn.execute(text("SELECT count(*) FROM peer_group_members WHERE group_id = 1")).scalar() == 0
