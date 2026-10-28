"""미국 listed 종목 재무 일괄 첫 적재 — SEC frames(app/providers/sec_bulk.py)로 회사별 호출 없이 (D8).

frames 값은 회사별 companyfacts와 97% 같다(2026-10-19 노출·비교군 76개 × 3개년 대조). 나머지는 frames가 서식과 상관없이
최근 제출값을 골라 위임장(DEF 14A) 반올림 값이 들어가거나, 52/53주 회계연도 경계에서 한 해가 빠지는 경우다.
그래서 **임시 값**으로만 넣는다: 재무 유효기간을 PROVISIONAL_TTL(7일)로 짧게 두고, 그 뒤 상세 화면을 열면
회사별 API(sec.py — 정확한 10-K 값 + yfinance 보완)로 다시 받는다. 노출 종목·비교군은 지금처럼 회사별 API만 쓴다.
행 notes에 path=SEC_FRAMES를 남긴다 — 비교군에 뽑히면 그날 API로 다시 받는다(D-039, benchmark.select_benchmark).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, text

from app.ingest.jobs import fix_zero_equity
from app.ingest.store import job_log, upsert
from app.providers.sec_bulk import SecFrames, get_annual_financials_bulk
from app.services import freshness

log = logging.getLogger(__name__)

FIN_FIELDS = ("revenue", "operating_income", "net_income", "total_assets", "total_equity", "total_debt")
PROVISIONAL_TTL = timedelta(days=7)
LOG_SOURCE = "SEC_BULK"              # 하루 호출 예산(source='SEC' 행)에 세지 않는다
CHUNK = 500


def load_us_bulk(engine: Engine, *, years: int = 3, frames: SecFrames | None = None,
                 now: datetime | None = None) -> dict:
    """재무 기록이 없는 활성 미국 listed 종목(CIK 있음)에 frames 재무를 넣는다. 반환: {"targets", "companies", "rows", "calls"}"""
    now = now or datetime.now(timezone.utc)
    out = {"targets": 0, "companies": 0, "rows": 0, "calls": 0}
    with job_log(engine, source=LOG_SOURCE, job_type="FINANCIALS", label="frames") as res:
        with engine.connect() as conn:
            targets = dict(conn.execute(text("""
                SELECT s.cik, s.stock_id FROM stocks s JOIN markets m ON m.market_id = s.market_id
                WHERE m.country = 'US' AND s.is_active AND s.coverage = 'listed' AND s.cik IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM data_freshness f WHERE f.stock_id = s.stock_id AND f.kind = 'financials')""")).all())
        out["targets"] = len(targets)
        if targets:
            frames = frames or SecFrames()
            fins = get_annual_financials_bulk(set(targets), years, frames=frames)
            out["calls"] = frames.calls
            items = [(targets[cik], fs) for cik, fs in fins.items()]
            for i in range(0, len(items), CHUNK):
                with engine.begin() as conn:
                    for sid, fs in items[i:i + CHUNK]:
                        for f in fs:
                            fix_zero_equity(f)
                        out["rows"] += upsert(conn, "financial_statements", [
                            {"stock_id": sid, "period_end": f.period_end, "period_type": "FY",
                             **{k: getattr(f, k) for k in FIN_FIELDS}, "data_source": "SEC", "accounting_std": "US-GAAP",
                             "notes": "; ".join(["path=SEC_FRAMES", *f.notes])}
                            for f in fs], ["stock_id", "period_end", "period_type"])
                        freshness.mark_provisional(conn, "financials", sid, PROVISIONAL_TTL, now=now)
            out["companies"] = len(items)
        res.rows = out["rows"]
        res.notes.append(f"대상 {out['targets']} · 회사 {out['companies']} · frames {out['calls']}회 · 임시 값(유효 {PROVISIONAL_TTL.days}일)")
    return out
