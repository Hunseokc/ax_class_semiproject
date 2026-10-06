"""소량 샘플 CSV 내보내기/가져오기 (재현용, sample_data/에 커밋).

샘플: 4개 종목(삼성전자·SK하이닉스·AAPL·NVDA = 반도체 그룹) × 최근 6개월 + 지수·환율 6개월 + 해당 종목 FY 재무.
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
SAMPLE_STOCKS = [("KOSPI", "005930"), ("KOSPI", "000660"), ("NASDAQ", "AAPL"), ("NASDAQ", "NVDA")]
MONTHS = 6

_STOCK_FILTER = "(m.code, s.ticker) IN (" + ", ".join(f"('{m}', '{t}')" for m, t in SAMPLE_STOCKS) + ")"

EXPORTS = {
    "stocks.csv": f"""
        SELECT m.code AS market, s.ticker, s.name_en, s.corp_code, s.cik
        FROM stocks s JOIN markets m USING (market_id) WHERE {_STOCK_FILTER} ORDER BY 1, 2""",
    "daily_prices.csv": f"""
        SELECT m.code AS market, s.ticker, d.trade_date, d.open, d.high, d.low, d.close, d.volume
        FROM daily_prices d JOIN stocks s USING (stock_id) JOIN markets m USING (market_id)
        WHERE {_STOCK_FILTER}
          AND d.trade_date > (SELECT MAX(trade_date) FROM daily_prices x WHERE x.stock_id = d.stock_id) - INTERVAL '{MONTHS} months'
        ORDER BY 1, 2, 3""",
    "valuation_snapshots.csv": f"""
        SELECT m.code AS market, s.ticker, v.as_of, v.per, v.pbr, v.eps, v.bps, v.market_cap, v.shares_outstanding, v.source
        FROM valuation_snapshots v JOIN stocks s USING (stock_id) JOIN markets m USING (market_id)
        WHERE {_STOCK_FILTER} AND v.as_of > CURRENT_DATE - INTERVAL '{MONTHS} months'
        ORDER BY 1, 2, 3""",
    "financial_statements.csv": f"""
        SELECT m.code AS market, s.ticker, f.period_end, f.period_type, f.revenue, f.operating_income, f.net_income,
               f.total_assets, f.total_equity, f.total_debt, f.data_source, f.accounting_std
        FROM financial_statements f JOIN stocks s USING (stock_id) JOIN markets m USING (market_id)
        WHERE {_STOCK_FILTER} ORDER BY 1, 2, 3""",
    "disclosures.csv": f"""
        SELECT m.code AS market, s.ticker, d.rcept_no, d.title, d.report_type, d.filed_at, d.url, d.data_source
        FROM disclosures d JOIN stocks s USING (stock_id) JOIN markets m USING (market_id)
        WHERE {_STOCK_FILTER} AND d.filed_at > now() - INTERVAL '{MONTHS} months'
        ORDER BY 1, 2, d.filed_at""",
    "index_daily_prices.csv": f"""
        SELECT i.code, p.trade_date, p.open, p.high, p.low, p.close
        FROM index_daily_prices p JOIN indices i USING (index_id)
        WHERE p.trade_date > (SELECT MAX(trade_date) FROM index_daily_prices) - INTERVAL '{MONTHS} months'
        ORDER BY 1, 2""",
    "fx_rates.csv": f"""
        SELECT rate_at, usd_krw, granularity, source FROM fx_rates
        WHERE granularity = 'DAILY'
          AND rate_at > (SELECT MAX(rate_at) FROM fx_rates WHERE granularity = 'DAILY') - INTERVAL '{MONTHS} months'
        ORDER BY 1""",
}


def export_sample(engine: Engine, out_dir: Path = SAMPLE_DIR) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    with engine.connect() as conn:
        for name, sql in EXPORTS.items():
            result = conn.execute(text(sql))
            rows = result.all()
            with (out_dir / name).open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(result.keys())
                w.writerows(rows)
            counts[name] = len(rows)
    return counts


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def import_sample(engine: Engine, src: Path = SAMPLE_DIR) -> dict[str, int]:
    """master(--offline) 적재 후 실행한다. 외부 호출 없음."""
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
                 ("financial_statements.csv", "financial_statements", ["stock_id", "period_end", "period_type"], with_sid),
                 ("disclosures.csv", "disclosures", ["rcept_no"], with_sid),
                 ("fx_rates.csv", "fx_rates", ["granularity", "rate_at"], lambda rows: rows)]
        for fname, table, conflict, fix in specs:
            counts[table] = upsert(conn, table, fix(_read(src / fname)), conflict)
        idx = _read(src / "index_daily_prices.csv")
        for r in idx:
            r["index_id"] = iid[r.pop("code")]
        counts["index_daily_prices"] = upsert(conn, "index_daily_prices", idx, ["index_id", "trade_date"])
    return counts
