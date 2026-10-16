"""상장 종목 목록(listed): 보통주 필터, 목록 동기화(기존 종목 보호·이전 상장·상장폐지·이상 목록 보호), 상단 검색 API.

Stage 6-B에서 뺀 것(연결 예정 — PR 목록): 일괄 수집·점수 유니버스에서 제외, 요청 시 상세 수집, 참고 매력도, 배당수익률, 주 그룹 평균."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.ingest.listing import sync_listing
from app.providers.base import Listing
from app.providers.krx import is_common_kr
from app.providers.sec import is_common_us
from tests.fakes import FakeListing, make_providers

API = "/api/v1"
TODAY = date.today()
KR_LIST = [Listing("KOSPI", "005930", "삼성전자(목록 이름)"), Listing("KOSPI", "035720", "카카오"),
           Listing("KOSDAQ", "247540", "에코프로비엠"), Listing("KOSPI", "035420", "NAVER")]
US_LIST = [Listing("NASDAQ", "AAPL", "Apple Inc.", "Apple Inc.", "0000320193"),
           Listing("NYSE", "KO", "COCA COLA CO", "COCA COLA CO", "0000021344"),
           Listing("NYSE", "BRK-B", "BERKSHIRE HATHAWAY INC", "BERKSHIRE HATHAWAY INC", "0001067983")]


@pytest.fixture
def pv():
    p = make_providers(with_fundamentals=True)
    p.kr_listing = FakeListing("PYKRX", list(KR_LIST))
    p.us_listing = FakeListing("SEC", list(US_LIST))
    return p


@pytest.fixture(autouse=True)
def markets(engine):
    with engine.begin() as conn:
        conn.execute(text("""INSERT INTO markets (market_id, code, country, currency, timezone) VALUES
            (3, 'KOSDAQ', 'KR', 'KRW', 'Asia/Seoul'), (4, 'NYSE', 'US', 'USD', 'America/New_York')"""))


def rows(engine) -> dict[str, dict]:
    with engine.connect() as conn:
        return {r["ticker"]: dict(r) for r in conn.execute(text("""
            SELECT s.stock_id, s.ticker, s.name, s.coverage, s.is_active, s.cik, s.corp_code, m.code AS market
            FROM stocks s JOIN markets m ON m.market_id = s.market_id""")).mappings()}


# ------------------------------------------------------------------ 보통주 필터
def test_common_stock_filters():
    assert is_common_kr("005930", "삼성전자") and is_common_kr("0126Z0", "새종목")
    assert not is_common_kr("005935", "삼성전자우") and not is_common_kr("00104K", "CJ4우(전환)")
    assert not is_common_kr("442310", "하나28호스팩")
    assert is_common_us("AAPL", "Apple Inc.") and is_common_us("BRK-B", "BERKSHIRE") and is_common_us("GOOGL", "Alphabet")
    assert not is_common_us("BAC-PB", "BANK OF AMERICA") and not is_common_us("ETI-P", "ENTERGY TEXAS")  # 우선주
    assert not is_common_us("KCAC-UN", "Kensington") and not is_common_us("ABCDW", "Some Corp")         # 유닛·워런트
    assert not is_common_us("SPY", "SPDR S&P 500 ETF TRUST") and not is_common_us("PDI", "PIMCO Dynamic Income Fund")
    assert not is_common_us("GTER", "Globa Terra Acquisition Corp")                                       # 스팩


# ------------------------------------------------------------------ 동기화
def test_sync_adds_listed_and_keeps_existing_stocks(engine, pv):
    out = sync_listing(engine, pv, today=TODAY)
    assert out["KR"]["added"] == 3 and out["US"]["added"] == 2
    r = rows(engine)
    assert r["005930"]["coverage"] == "featured" and r["005930"]["name"] == "삼성전자"     # 노출 종목은 그대로
    assert r["AAPL"]["coverage"] == "featured"
    assert (r["035720"]["coverage"], r["035720"]["market"]) == ("listed", "KOSPI")
    assert r["247540"]["market"] == "KOSDAQ" and r["KO"]["market"] == "NYSE" and r["KO"]["cik"] == "0000021344"
    assert r["035720"]["corp_code"] == "C035720"                                          # DART 고유번호 일괄 매핑
    assert sync_listing(engine, pv, today=TODAY)["KR"] == {"added": 0, "updated": 3, "moved": 0, "deactivated": 0,
                                                           "corp_code": 0}


def test_sync_moves_market_and_deactivates_delisted(engine, pv):
    sync_listing(engine, pv, today=TODAY)
    before = rows(engine)["247540"]["stock_id"]
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO watchlist_items (user_id, stock_id, sort_order) VALUES (1, :s, 1)"), {"s": before})
    pv.kr_listing.items = [Listing("KOSPI", "247540", "에코프로비엠"), Listing("KOSPI", "035720", "카카오"),
                           Listing("KOSPI", "035420", "NAVER")]                         # 코스닥 → 코스피 이전 상장
    out = sync_listing(engine, pv, today=TODAY)
    r = rows(engine)
    assert out["KR"]["moved"] == 1 and r["247540"]["market"] == "KOSPI" and r["247540"]["stock_id"] == before
    assert out["KR"]["deactivated"] == 0
    pv.kr_listing.items = [Listing("KOSPI", "247540", "에코프로비엠"), Listing("KOSPI", "035720", "카카오")]
    assert sync_listing(engine, pv, today=TODAY)["KR"]["deactivated"] == 1               # NAVER 상장폐지 가정
    r = rows(engine)
    assert not r["035420"]["is_active"] and r["005930"]["is_active"]                      # 노출 종목은 대상 아님


def test_sync_skips_deactivation_when_list_looks_broken(engine, pv):
    sync_listing(engine, pv, today=TODAY)
    pv.kr_listing.items = [Listing("KOSPI", "035720", "카카오")]                         # 직전 활성 3 → 1 (절반 미만)
    assert sync_listing(engine, pv, today=TODAY)["KR"]["deactivated"] == 0
    pv.us_listing.items = []
    out = sync_listing(engine, pv, today=TODAY)                                          # 빈 목록은 실패로 기록
    assert "US" not in out
    with engine.connect() as conn:
        assert conn.execute(text("""SELECT status FROM ingestion_logs WHERE error LIKE '%빈 목록%'
                                    ORDER BY log_id DESC LIMIT 1""")).scalar() == "FAILED"


# ------------------------------------------------------------------ 검색 API
def test_search_ranks_matches_and_covers_listed(client, engine, pv):
    sync_listing(engine, pv, today=TODAY)
    items = client.get(f"{API}/stocks/search?q=삼성").json()["items"]
    assert [(x["ticker"], x["coverage"]) for x in items] == [("005930", "featured")]
    items = client.get(f"{API}/stocks/search?q=035").json()["items"]
    assert [x["ticker"] for x in items] == ["035720", "035420"]                         # 티커 앞부분 일치, 짧은 이름 먼저
    assert client.get(f"{API}/stocks/search?q=ko").json()["items"][0]["ticker"] == "KO"  # 티커 완전 일치 우선
    assert client.get(f"{API}/stocks/search?q=berkshire").json()["items"][0]["ticker"] == "BRK-B"
    assert client.get(f"{API}/stocks/search?q=%25").json()["items"] == []               # LIKE 특수문자는 글자 그대로
    assert len(client.get(f"{API}/stocks/search?q=0&limit=2").json()["items"]) == 2
    assert client.get(f"{API}/stocks/search?q=").status_code == 422
    with engine.begin() as conn:
        conn.execute(text("UPDATE stocks SET is_active = false WHERE ticker = 'KO'"))
    assert client.get(f"{API}/stocks/search?q=coca").json()["items"] == []               # 상장폐지(비활성) 제외
