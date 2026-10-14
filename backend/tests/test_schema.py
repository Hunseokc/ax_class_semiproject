"""DB 설계(Stage 1 테이블 10개 + Stage 2 테이블 4개): ORM ↔ schema.sql 일치, 제약조건(CHECK/UNIQUE/FK/CASCADE) 방어.

이후 단계 테이블이 추가되면 담당 단계에서 테이블 수와 제약 케이스를 늘린다.
"""
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.models import Base

STAGE1_TABLES = {"markets", "stocks", "peer_groups", "peer_group_members", "daily_prices", "valuation_snapshots",
                 "indices", "index_daily_prices", "fx_rates", "ingestion_logs"}
STAGE2_TABLES = {"users", "watchlist_items", "portfolios", "portfolio_items"}


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


def test_tables_are_stage1_and_2_only(engine):
    assert set(Base.metadata.tables) == STAGE1_TABLES | STAGE2_TABLES
    assert set(inspect(engine).get_table_names()) == STAGE1_TABLES | STAGE2_TABLES


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
    # ── Stage 2 ──
    ("닉네임 중복", "INSERT INTO users (nickname) VALUES ('demo')"),
    ("관심종목 중복(PK)", "INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 1), (1, 1)"),
    ("없는 사용자 관심종목 FK", "INSERT INTO watchlist_items (user_id, stock_id) VALUES (999, 1)"),
    ("시드 0", "INSERT INTO portfolios (user_id, name, seed_krw) VALUES (1, 'P', 0)"),
    ("포트폴리오 이름 중복", "INSERT INTO portfolios (user_id, name, seed_krw) VALUES (1, 'P', 100), (1, 'P', 100)"),
    ("수량 0", "INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'P', 100);"
              "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date) VALUES (1, 1, 0, 1, 1, '2030-01-01')"),
    ("담은 가격 0", "INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'P', 100);"
                 "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date) VALUES (1, 1, 1, 0, 1, '2030-01-01')"),
    ("항목 종목 중복", "INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'P', 100);"
                  "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date) "
                  "VALUES (1, 1, 1, 1, 1, '2030-01-01'), (1, 1, 2, 1, 1, '2030-01-01')"),
    ("담긴 종목 삭제(RESTRICT)", "INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'P', 100);"
                            "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_date) VALUES (1, 1, 1, 1, '2030-01-01');"
                            "DELETE FROM stocks WHERE stock_id = 1"),
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


def test_user_delete_cascades_and_updated_at_trigger(engine):
    """사용자 삭제 → 관심종목·포트폴리오·항목 CASCADE. cost_krw 생성 컬럼 계산. UPDATE 시 updated_at 트리거가 시각을 갱신한다."""
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 1)"))
        conn.execute(text("INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'P', 1000000)"))
        conn.execute(text("INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date) "
                          "VALUES (1, 3, 2, 195, 1300, '2030-01-01')"))
        # cost_krw는 생성 컬럼: 2주 × 195달러 × 1300원 = 507,000원
        assert conn.execute(text("SELECT cost_krw FROM portfolio_items")).scalar() == Decimal("507000.00")
        conn.execute(text("UPDATE portfolios SET created_at = created_at - interval '1 day', "
                          "updated_at = updated_at - interval '1 day' WHERE portfolio_id = 1"))
        conn.execute(text("UPDATE portfolios SET name = 'Q' WHERE portfolio_id = 1"))
        assert conn.execute(text("SELECT updated_at > created_at + interval '12 hours' FROM portfolios")).scalar()
        conn.execute(text("DELETE FROM users WHERE user_id = 1"))
        left = conn.execute(text("""SELECT (SELECT count(*) FROM watchlist_items), (SELECT count(*) FROM portfolios),
                                           (SELECT count(*) FROM portfolio_items)""")).one()
        assert tuple(left) == (0, 0, 0)
