"""DB 설계: ORM ↔ schema.sql 일치, 제약조건(CHECK/UNIQUE/FK/생성 컬럼/트리거) 방어."""
from datetime import date

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.models import Base


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
    assert len(Base.metadata.tables) == 20
    assert diffs == []


def _insert_item(conn, **kw):
    params = dict(pid=1, sid=1, q=1, p=70000, fx=1)
    params.update(kw)
    conn.execute(text("""INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_fx_rate, ref_date)
                         VALUES (:pid, :sid, :q, :p, :fx, CURRENT_DATE)"""), params)


@pytest.fixture
def portfolio(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO portfolios (portfolio_id, user_id, name, seed_krw) VALUES (1, 1, 'p', 10000000)"))


def test_generated_cost_and_updated_at_trigger(engine, portfolio):
    with engine.begin() as conn:
        _insert_item(conn, q=42)
        _insert_item(conn, sid=3, q=11, p=200, fx=1300)
    with engine.connect() as conn:
        costs = dict(conn.execute(text("SELECT stock_id, cost_krw FROM portfolio_items")).all())
    assert costs == {1: 2_940_000, 3: 2_860_000}
    with engine.begin() as conn:
        row = conn.execute(text("""UPDATE portfolio_items SET quantity = 43 WHERE stock_id = 1
                                   RETURNING cost_krw, updated_at > created_at""")).one()
    assert row[0] == 3_010_000 and row[1] is True


@pytest.mark.parametrize("label, sql, error", [
    ("수량 0", "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_date) VALUES (1, 2, 0, 1, now())", IntegrityError),
    ("음수 수량", "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_date) VALUES (1, 2, -1, 1, now())", IntegrityError),
    ("기준가 0", "INSERT INTO portfolio_items (portfolio_id, stock_id, quantity, ref_price, ref_date) VALUES (1, 2, 1, 0, now())", IntegrityError),
    ("시드 0", "INSERT INTO portfolios (user_id, name, seed_krw) VALUES (1, 'z', 0)", IntegrityError),
    ("고가 < 저가", "INSERT INTO daily_prices VALUES (1, '2030-01-01', 10, 9, 11, 10, 1)", IntegrityError),
    ("음수 거래량", "INSERT INTO daily_prices VALUES (1, '2030-01-02', 10, 11, 9, 10, -1)", IntegrityError),
    ("가격 0", "INSERT INTO daily_prices VALUES (1, '2030-01-03', 0, 0, 0, 0, 1)", IntegrityError),
    ("일봉 중복(PK)", "INSERT INTO daily_prices SELECT * FROM daily_prices LIMIT 1", IntegrityError),
    ("없는 종목 FK", "INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 999)", IntegrityError),
    ("잘못된 국가", "INSERT INTO markets (code, country, currency, timezone) VALUES ('X', 'JP', 'KRW', 'x')", IntegrityError),
    ("잘못된 granularity", "INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now(), 1, 'HOURLY')", IntegrityError),
    ("환율 0", "INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now(), 0, 'DAILY')", IntegrityError),
    ("잘못된 period_type", "INSERT INTO financial_statements (stock_id, period_end, period_type, data_source) VALUES (1, '2020-12-31', 'H1', 'DART')", IntegrityError),
    ("점수 101", "INSERT INTO stock_scores (stock_id, as_of, preset_id, score, factor_coverage) VALUES (1, '2026-01-01', 1, 101, 5)", IntegrityError),
    ("유효 팩터 6개", "INSERT INTO stock_scores (stock_id, as_of, preset_id, factor_coverage) VALUES (1, '2026-01-01', 1, 6)", IntegrityError),
    ("가중치 1 초과", "WITH p AS (INSERT INTO scoring_presets (code, name) VALUES ('t', 't') RETURNING preset_id) "
                    "INSERT INTO scoring_weights SELECT preset_id, 'value', 1.5 FROM p", IntegrityError),
    ("없는 팩터", "INSERT INTO stock_metric_values (stock_id, as_of, metric, factor) VALUES (1, '2026-01-01', 'x', 'size')", IntegrityError),
    ("주 그룹 2개", "INSERT INTO peer_group_members VALUES (2, 1, true)", IntegrityError),
    ("같은 시장 같은 티커", "INSERT INTO stocks (market_id, ticker, name) VALUES (1, '005930', '중복')", IntegrityError),
    ("생성 컬럼 직접 쓰기", "UPDATE portfolio_items SET cost_krw = 1", ProgrammingError),
])
def test_constraints_reject_bad_rows(engine, portfolio, label, sql, error):
    with engine.begin() as conn:
        _insert_item(conn)
    with pytest.raises(error):
        with engine.begin() as conn:
            conn.execute(text(sql))


def test_delete_rules(engine, portfolio):
    with engine.begin() as conn:
        _insert_item(conn)
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id) VALUES (1, 1)"))
    # 담긴 종목은 삭제 불가 (RESTRICT)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM stocks WHERE stock_id = 1"))
    # 포트폴리오 삭제 → 항목 CASCADE, 사용자 삭제 → 관심종목 CASCADE
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM portfolios WHERE portfolio_id = 1"))
        conn.execute(text("DELETE FROM users WHERE user_id = 1"))
        left = conn.execute(text("SELECT (SELECT count(*) FROM portfolio_items), (SELECT count(*) FROM watchlist_items)")).one()
    assert tuple(left) == (0, 0)


def test_views_exist(engine):
    with engine.connect() as conn:
        views = {r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.views WHERE table_schema='public'"))}
        latest = conn.execute(text("SELECT close, prev_close, change_rate FROM v_latest_price WHERE stock_id = 1")).one()
    assert {"v_latest_price", "v_fx_latest", "v_stock_metrics"} <= views
    assert latest.close == 70000 and latest.prev_close == 69000
    assert float(latest.change_rate) == pytest.approx(70000 / 69000 - 1, abs=1e-6)
