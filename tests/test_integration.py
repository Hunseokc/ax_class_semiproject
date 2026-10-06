"""통합: 화면 라우트·정적 파일 서빙, 화면 흐름 순서대로 API를 이어 호출하는 사용자 시나리오, 프론트 import 경로."""
import re
from pathlib import Path

import pytest

from app.core.config import ROOT_DIR

API = "/api/v1"


@pytest.mark.parametrize("path", ["/", "/stocks", "/stocks/KOSPI/005930", "/portfolio"])
def test_pages_are_served(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert 'id="sidebar"' in r.text and "/static/js/pages/" in r.text


@pytest.mark.parametrize("path", ["/static/css/tokens.css", "/static/js/api.js", "/static/js/pages/portfolio.js"])
def test_static_files_are_served(client, path):
    assert client.get(path).status_code == 200


def test_frontend_imports_resolve():
    """ES 모듈의 상대 import 경로가 실제 파일을 가리키는지 (빌드 단계가 없으므로 정적으로 확인)."""
    web = ROOT_DIR / "web"
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
    """홈 → 주식 리스트(★·담기) → 종목 상세 → 모의 포트폴리오 → 정리."""
    # 홈: 지수·환율·관심종목(빈 상태)·거래량 상위
    assert client.get(f"{API}/market/indices").json()["indices"]
    assert client.get(f"{API}/market/fx").json()["fx_stale"] is False
    assert client.get(f"{API}/watchlist").json()["count"] == 0
    assert client.get(f"{API}/stocks?country=KR&sort=volume&limit=5").json()["items"][0]["ticker"] == "000660"

    # 주식 리스트: 그룹 필터 목록, ★ 추가 → is_watched 반영 → 홈 카드에 표시
    assert {g["name"] for g in client.get(f"{API}/peer-groups").json()["groups"]} == {"반도체", "빅테크"}
    assert client.post(f"{API}/watchlist", json={"market": "NASDAQ", "ticker": "NVDA"}).status_code == 201
    nvda = next(x for x in client.get(f"{API}/stocks").json()["items"] if x["ticker"] == "NVDA")
    assert nvda["is_watched"] is True
    assert [c["ticker"] for c in client.get(f"{API}/watchlist").json()["items"]] == ["NVDA"]

    # 종목 상세: 상세·캔들·분석·경쟁 비교·차트·재무·공시가 모두 응답
    base = f"{API}/stocks/NASDAQ/NVDA"
    assert client.get(base).json()["is_watched"] is True
    for sub in ("/candles?range=1m", "/analysis", "/peers", "/peers/chart?range=1m", "/financials", "/disclosures"):
        assert client.get(base + sub).status_code == 200, sub

    # 모의 포트폴리오: 생성 → KRW·USD 담기 → 요약 → 수정 → 시드 축소 거부 → 삭제
    pid = client.post(f"{API}/portfolios", json={"name": "여정", "seed_krw": 5_000_000}).json()["portfolio_id"]
    krw_item = client.post(f"{API}/portfolios/{pid}/items", json={"market": "KOSPI", "ticker": "005930", "mode": "amount", "value": 1_000_000}).json()
    usd_item = client.post(f"{API}/portfolios/{pid}/items", json={"market": "NASDAQ", "ticker": "NVDA", "mode": "weight", "value": 20}).json()
    assert (krw_item["quantity"], usd_item["quantity"]) == (14, 6)          # 1,000,000/70,000 · 1,000,000/(110×1,300)
    s = client.get(f"{API}/portfolios/{pid}/summary").json()
    assert s["used_krw"] == 14 * 70_000 + 6 * 110 * 1300
    assert {m["country"] for m in s["market_weights"]} == {"KR", "US"}
    r = client.put(f"{API}/portfolios/{pid}/items/{usd_item['item_id']}", json={"mode": "quantity", "value": 3})
    assert r.status_code == 200 and r.json()["cost_krw"] == 3 * 110 * 1300
    assert client.put(f"{API}/portfolios/{pid}", json={"name": "여정", "seed_krw": 100_000}).status_code == 409
    assert client.delete(f"{API}/portfolios/{pid}/items/{krw_item['item_id']}").status_code == 204
    assert client.delete(f"{API}/portfolios/{pid}").status_code == 204
    assert client.delete(f"{API}/watchlist/NASDAQ/NVDA").status_code == 204
    assert client.get(f"{API}/watchlist").json()["count"] == 0
