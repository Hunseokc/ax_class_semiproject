-- =====================================================================
-- 상장 종목 전체 검색(listed 계층) + 주당배당금 — 멱등. 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 005_listed_dividend  →  python -m app.ingest listing
-- migrate는 이 파일 뒤에 views.sql을 다시 적용한다(v_stock_metrics에 dps·dividend_yield 추가).
-- =====================================================================

ALTER TABLE stocks DROP CONSTRAINT IF EXISTS stocks_coverage_check;
ALTER TABLE stocks ADD CONSTRAINT stocks_coverage_check CHECK (coverage IN ('featured','benchmark','listed'));

ALTER TABLE valuation_snapshots ADD COLUMN IF NOT EXISTS dps NUMERIC(18,4);
ALTER TABLE valuation_snapshots DROP CONSTRAINT IF EXISTS valuation_snapshots_dps_check;
ALTER TABLE valuation_snapshots ADD CONSTRAINT valuation_snapshots_dps_check CHECK (dps >= 0);
