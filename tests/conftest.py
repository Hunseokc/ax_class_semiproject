"""pytest 공통: 테스트 DB(TEST_DATABASE_URL) 스키마를 세션마다 새로 만들고, 테스트마다 비운 뒤 고정 픽스처를 넣는다.

고정 픽스처 (today 기준 상대 날짜, 기준일 D = today - 4일):
  시장  KOSPI(KR/KRW), NASDAQ(US/USD)
  종목  1 삼성전자 005930  종가 68,000 → 69,000 → 70,000   거래량 1,000   시총 400조원
        2 SK하이닉스 000660 종가 150,000 (3일)              거래량 3,000   시총 100조원
        3 AAPL                종가 195 → 198 → 200          거래량 500     시총 3조 달러
        4 NVDA                종가 100 → 105 → 110          거래량 800     시총 1조 달러
  그룹  반도체(1,2,4), 빅테크(3) — 모두 주 그룹
  프리셋 init_db가 config/scoring.yaml로 적재(테스트마다 비우지 않음)
  환율  DAILY 1,300 (3일), SNAPSHOT 1,300 (지금 → TTL 이내)
  지수  KOSPI 3일
  사용자 demo(1), other(2)
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import deps
from app.core.config import get_settings
from app.ingest.jobs import init_db
from app.main import app
from tests.fakes import FakeFx, make_providers

TABLES = ["portfolio_items", "portfolios", "watchlist_items", "users", "stock_scores", "stock_metric_values",
          "ingestion_logs", "fx_rates",
          "index_daily_prices", "indices", "disclosures", "financial_statements", "valuation_snapshots",
          "daily_prices", "peer_group_members", "peer_groups", "stocks", "markets"]

TODAY = date.today()
D = TODAY - timedelta(days=4)            # 픽스처 마지막 거래일
DAYS = [D - timedelta(days=2), D - timedelta(days=1), D]


@pytest.fixture(scope="session")
def engine():
    url = get_settings().test_database_url
    assert "test" in url, "테스트는 반드시 테스트 DB에서 실행한다"
    eng = create_engine(url, pool_size=10, max_overflow=10)
    init_db(eng, reset=True)
    yield eng
    eng.dispose()


def load_fixture(conn) -> None:
    conn.execute(text("""
        INSERT INTO markets (market_id, code, country, currency, timezone) VALUES
          (1, 'KOSPI', 'KR', 'KRW', 'Asia/Seoul'), (2, 'NASDAQ', 'US', 'USD', 'America/New_York');
        INSERT INTO stocks (stock_id, market_id, ticker, name, name_en) VALUES
          (1, 1, '005930', '삼성전자', 'Samsung Electronics'), (2, 1, '000660', 'SK하이닉스', 'SK hynix'),
          (3, 2, 'AAPL', 'Apple', 'Apple'), (4, 2, 'NVDA', 'NVIDIA', 'NVIDIA');
        INSERT INTO peer_groups (group_id, name) VALUES (1, '반도체'), (2, '빅테크');
        INSERT INTO peer_group_members VALUES (1, 1, true), (1, 2, true), (1, 4, true), (2, 3, true);
        INSERT INTO users (user_id, nickname) VALUES (1, 'demo'), (2, 'other');
        INSERT INTO indices (index_id, code, name, market_id, source_symbol, display_order)
          VALUES (1, 'KOSPI', 'KOSPI', 1, '1001', 1);
        SELECT setval('stocks_stock_id_seq', 4), setval('peer_groups_group_id_seq', 2),
               setval('users_user_id_seq', 2), setval('indices_index_id_seq', 1), setval('markets_market_id_seq', 2);
    """))
    closes = {1: [68000, 69000, 70000], 2: [150000] * 3, 3: [195, 198, 200], 4: [100, 105, 110]}
    volumes = {1: 1000, 2: 3000, 3: 500, 4: 800}
    rows = [{"s": s, "d": d, "c": c, "v": volumes[s]} for s, cs in closes.items() for d, c in zip(DAYS, cs)]
    conn.execute(text("INSERT INTO daily_prices VALUES (:s, :d, :c, :c, :c, :c, :v)"), rows)
    conn.execute(text("""
        INSERT INTO valuation_snapshots (stock_id, as_of, per, pbr, market_cap, source) VALUES
          (1, :d, 12, 1.2, 400000000000000, 'PYKRX'), (2, :d, 8, 1.5, 100000000000000, 'PYKRX'),
          (3, :d, 30, 40, 3000000000000, 'YFINANCE'), (4, :d, 50, 30, 1000000000000, 'YFINANCE')"""), {"d": D})
    conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (CAST(:d AS date) + time '00:00', 1300, 'DAILY')"),
                 [{"d": d} for d in DAYS])
    conn.execute(text("INSERT INTO fx_rates (rate_at, usd_krw, granularity) VALUES (now(), 1300, 'SNAPSHOT')"))
    conn.execute(text("INSERT INTO index_daily_prices (index_id, trade_date, close) VALUES (1, :d, :c)"),
                 [{"d": d, "c": 2500 + i * 10} for i, d in enumerate(DAYS)])


@pytest.fixture(autouse=True)
def db_fixture(engine):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        load_fixture(conn)
    yield


@pytest.fixture
def fake_fx() -> FakeFx:
    return FakeFx()


@pytest.fixture
def providers(fake_fx):
    return make_providers(fake_fx)


@pytest.fixture
def client(engine, providers):
    app.dependency_overrides[deps.get_engine_dep] = lambda: engine
    app.dependency_overrides[deps.get_providers] = lambda: providers
    app.dependency_overrides[deps.get_scorer] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def as_user(client):
    """이후 요청을 지정한 사용자로 보낸다 (2차에서 JWT가 정할 사용자를 대신함)."""
    def _set(user_id: int) -> None:
        app.dependency_overrides[deps.get_current_user_id] = lambda: user_id
    return _set


def scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()
