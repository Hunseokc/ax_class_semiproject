"""통합: 화면 라우트·정적 파일 서빙, 화면 흐름 순서대로 API를 이어 호출하는 사용자 시나리오, 프론트 import 경로."""
import re

import pytest
from sqlalchemy import text

from app.core.config import FRONTEND_DIR
from app.ingest import jobs, sample
from tests.conftest import TABLES

API = "/api/v1"


# 모의 포트폴리오(/portfolio)는 Stage 2에서 화면 스크립트가 생기면 이 목록에 추가한다
@pytest.mark.parametrize("path", ["/", "/stocks", "/stocks/KOSPI/005930"])
def test_pages_are_served(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="sidebar"' in r.text and "/static/js/pages/" in r.text


@pytest.mark.parametrize("path", ["/static/css/tokens.css", "/static/js/api.js", "/static/js/pages/stock.js"])
def test_static_files_are_served(client, path):
    assert client.get(path).status_code == 200


def test_frontend_imports_resolve():
    """ES 모듈의 상대 import 경로가 실제 파일을 가리키는지 (빌드 단계가 없으므로 정적으로 확인)."""
    web = FRONTEND_DIR
    missing = []
    for f in (web / "js").rglob("*.js"):
        for spec in re.findall(r'from\s+"(\.{1,2}/[^"]+)"', f.read_text(encoding="utf-8")):
            if not (f.parent / spec).resolve().exists():
                missing.append(f"{f.relative_to(web)} → {spec}")
    for html in web.glob("*.html"):
        for src in re.findall(r'(?:src|href)="/static/([^"]+)"', html.read_text(encoding="utf-8")):
            if not (web / src).exists():
                missing.append(f"{html.name} → {src}")
    assert missing == []


def test_user_journey_across_screens(client):
    """홈 → 주식 리스트 → 종목 상세."""
    # 홈: 지수·환율
    assert client.get(f"{API}/market/indices").json()["indices"]
    assert client.get(f"{API}/market/fx").json()["fx_stale"] is False

    # 주식 리스트: 거래량 순위, 그룹 필터 목록, 전체 탭(시총 정렬)
    assert client.get(f"{API}/stocks?country=KR&sort=volume&limit=5").json()["items"][0]["ticker"] == "000660"
    assert {g["name"] for g in client.get(f"{API}/peer-groups").json()["groups"]} == {"반도체", "빅테크"}
    assert "NVDA" in {x["ticker"] for x in client.get(f"{API}/stocks").json()["items"]}

    # 종목 상세: 상세·캔들
    base = f"{API}/stocks/NASDAQ/NVDA"
    assert client.get(base).json()["ticker"] == "NVDA"
    for sub in ("/candles?range=1m",):
        assert client.get(base + sub).status_code == 200, sub


def test_sample_import_serves_main_apis(engine, client):
    """수집 대체 경로: 빈 DB → master --offline → import-sample 만으로 화면 3개가 쓰는 API가 모두 200."""
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    jobs.load_master(engine, offline=True)
    counts = sample.import_sample(engine)
    assert all(n > 0 for n in counts.values()), counts

    stock = client.get(f"{API}/stocks?country=KR&sort=volume&limit=1").json()["items"][0]
    base = f"{API}/stocks/{stock['market']}/{stock['ticker']}"
    for url in (f"{API}/market/indices", f"{API}/market/fx", f"{API}/peer-groups", f"{API}/stocks",
                base, f"{base}/candles?range=1y"):
        assert client.get(url).status_code == 200, url
    assert client.get(f"{base}/candles?range=1y").json()["candles"]
