"""상장 종목 목록(listed) — 상단 검색에서 상장 보통주 전체를 찾기 위한 이름·티커 마스터.

- 출처: 국내 pykrx(코스피·코스닥 티커 목록 + 종목명, 단축코드 끝자리 0 = 보통주, 스팩 제외)
        미국 SEC company_tickers_exchange.json(NASDAQ·NYSE, 우선주·워런트·유닛·ETF·펀드·스팩 제외)
- 저장: stocks에 coverage = 'listed'로 이름·티커만. 이미 있는 노출 종목·비교군은 건드리지 않는다
  (같은 국가에 같은 티커가 다른 시장으로 있으면 새로 만들지 않는다)
- 목록에서 빠진 listed 종목(상장폐지 등)은 is_active = false. 관심종목·포트폴리오가 FK로 참조할 수 있어 지우지 않는다
- 목록이 직전 활성 수의 절반도 안 되면 소스 이상으로 보고 비활성화하지 않는다
- 상세 데이터(일봉·밸류에이션·재무·공시)는 종목을 열 때 받는다(app/services/hydration.py),
  매력도는 유니버스 분포에 대입한 참고 점수로만 보여 준다(app/services/reference_score.py)
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import Engine, text

from app.ingest.store import job_log, upsert
from app.providers.base import ProviderError
from app.providers.factory import Providers

log = logging.getLogger(__name__)
MIN_KEEP_RATIO = 0.5


def sync_listing(engine: Engine, providers: Providers, *, today: date | None = None) -> dict[str, dict]:
    """국가마다 상장 보통주 목록을 받아 stocks에 맞춘다. 반환: {국가: {added, updated, deactivated}}."""
    today = today or date.today()
    out = {}
    for country in ("KR", "US"):
        p = providers.listing(country)
        if p is None:
            log.info("상장 종목 목록 %s: provider 없음 — 건너뜀", country)
            continue
        with job_log(engine, source=p.source, job_type="MASTER", label=f"listing {country}") as res:
            listings = p.get_listed_stocks(today)
            if not listings:
                raise ProviderError("빈 목록")
            out[country] = _apply(engine, country, listings)
            if country == "KR":
                out[country]["corp_code"] = _map_corp_codes(engine, providers)
            res.rows = len(listings)
            res.notes.append(", ".join(f"{k} {v}" for k, v in out[country].items()))
    return out


def _map_corp_codes(engine: Engine, providers: Providers) -> int:
    """DART 고유번호를 한 번에 매핑한다(corpCode.xml 1회). 클릭할 때마다 받지 않도록 목록 동기화 때 처리."""
    dart = providers.kr_financial
    if not hasattr(dart, "corp_codes"):
        return 0
    with engine.connect() as conn:
        missing = dict(conn.execute(text("""
            SELECT s.ticker, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
            WHERE m.country = 'KR' AND s.coverage = 'listed' AND s.is_active AND s.corp_code IS NULL""")).all())
    if not missing:
        return 0
    codes = dart.corp_codes(set(missing))
    rows = [{"id": missing[t], "corp": c} for t, c in codes.items()]
    if rows:
        with engine.begin() as conn:
            conn.execute(text("UPDATE stocks SET corp_code = :corp WHERE stock_id = :id"), rows)
    return len(rows)


def _apply(engine: Engine, country: str, listings: list) -> dict:
    with engine.begin() as conn:
        market_id = dict(conn.execute(text("SELECT code, market_id FROM markets WHERE country = :c"), {"c": country}).all())
        existing = {r.ticker: r for r in conn.execute(text("""
            SELECT s.stock_id, s.ticker, s.market_id, s.coverage, s.is_active FROM stocks s
            JOIN markets m ON m.market_id = s.market_id WHERE m.country = :c"""), {"c": country})}
        # 시장을 옮긴 listed 종목(코스닥 → 코스피 이전 상장 등)은 같은 행의 시장만 바꾼다(관심종목 참조 유지)
        moved = [{"id": existing[x.ticker].stock_id, "m": market_id[x.market]} for x in listings
                 if x.market in market_id and x.ticker in existing and existing[x.ticker].coverage == "listed"
                 and existing[x.ticker].market_id != market_id[x.market]]
        if moved:
            conn.execute(text("UPDATE stocks SET market_id = :m WHERE stock_id = :id"), moved)
        rows = [{"market_id": market_id[x.market], "ticker": x.ticker, "name": x.name[:128],
                 "name_en": (x.name_en or None) and x.name_en[:128], "cik": x.cik, "coverage": "listed", "is_active": True}
                for x in listings if x.market in market_id
                and (x.ticker not in existing or existing[x.ticker].coverage == "listed")]
        added = sum(1 for r in rows if r["ticker"] not in existing)
        # 이름·CIK·활성 여부만 갱신(coverage는 listed 행에만 쓰므로 노출 종목·비교군으로 바뀌지 않는다)
        upsert(conn, "stocks", rows, ["market_id", "ticker"], update=["name", "name_en", "cik", "is_active"])
        active_before = sum(1 for r in existing.values() if r.coverage == "listed" and r.is_active)
        deactivated = 0
        if len(listings) >= active_before * MIN_KEEP_RATIO:
            deactivated = conn.execute(text("""
                UPDATE stocks s SET is_active = false
                FROM markets m
                WHERE m.market_id = s.market_id AND m.country = :c AND s.coverage = 'listed' AND s.is_active
                  AND NOT (s.ticker = ANY(:tickers))"""),
                {"c": country, "tickers": [x.ticker for x in listings]}).rowcount
        else:
            log.warning("상장 종목 목록 %s: %d건 < 직전 활성 %d건의 절반 — 비활성화 생략", country, len(listings), active_before)
    return {"added": added, "updated": len(rows) - added, "moved": len(moved), "deactivated": deactivated}
