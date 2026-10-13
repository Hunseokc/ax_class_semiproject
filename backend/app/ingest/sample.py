"""소량 샘플 CSV 가져오기 (재현용, sample_data/에 커밋).

샘플: 4개 종목(삼성전자·SK하이닉스·AAPL·NVDA = 반도체 그룹) × 최근 6개월 + 지수·환율 6개월.
CSV는 ID 대신 (market, ticker)·지수 code로 기록해 다른 DB에서도 그대로 가져올 수 있다.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy import Engine, text

from app.core.config import ROOT_DIR
from app.ingest.store import upsert

log = logging.getLogger(__name__)
SAMPLE_DIR = ROOT_DIR / "sample_data"


def _read(path: Path) -> list[dict]:
    # 빈 칸은 None으로: 숫자 컬럼에 빈 문자열이 들어가면 DB가 거부한다
    with path.open(encoding="utf-8") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def import_sample(engine: Engine, src: Path = SAMPLE_DIR) -> dict[str, int]:
    """master(--offline) 적재 후 실행한다. 외부 호출 없음. 재실행해도 행 수가 변하지 않는다."""
    counts = {}
    with engine.begin() as conn:
        sid = {(m, t): i for i, m, t in conn.execute(text(
            "SELECT s.stock_id, m.code, s.ticker FROM stocks s JOIN markets m USING (market_id)")).all()}
        iid = dict(conn.execute(text("SELECT code, index_id FROM indices")).all())

        def with_sid(rows):
            for r in rows:
                r["stock_id"] = sid[(r.pop("market"), r.pop("ticker"))]
            return rows

        for r in _read(src / "stocks.csv"):
            conn.execute(text("UPDATE stocks SET name_en = :name_en, corp_code = :corp_code, cik = :cik "
                              "WHERE stock_id = :stock_id"), with_sid([r])[0])
        specs = [("daily_prices.csv", "daily_prices", ["stock_id", "trade_date"], with_sid),
                 ("valuation_snapshots.csv", "valuation_snapshots", ["stock_id", "as_of"], with_sid),
                 ("fx_rates.csv", "fx_rates", ["granularity", "rate_at"], lambda rows: rows)]
        for fname, table, conflict, fix in specs:
            counts[table] = upsert(conn, table, fix(_read(src / fname)), conflict)
        idx = _read(src / "index_daily_prices.csv")
        for r in idx:
            r["index_id"] = iid[r.pop("code")]
        counts["index_daily_prices"] = upsert(conn, "index_daily_prices", idx, ["index_id", "trade_date"])
    log.info("샘플 적재: %s", counts)
    return counts
