-- =====================================================================
-- 매력도 비교군(benchmark) 계층 — 멱등. 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 003_benchmark  →  python -m app.ingest benchmark --reselect
-- =====================================================================

ALTER TABLE stocks ADD COLUMN IF NOT EXISTS coverage VARCHAR(10) NOT NULL DEFAULT 'featured';
ALTER TABLE stocks DROP CONSTRAINT IF EXISTS stocks_coverage_check;
-- 'listed'는 005에서 추가된 값이다. 005 뒤에 이 파일을 다시 실행해도 제약이 좁아지지 않도록 함께 허용한다
ALTER TABLE stocks ADD CONSTRAINT stocks_coverage_check CHECK (coverage IN ('featured','benchmark','listed'));
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS detail_synced_at TIMESTAMPTZ;

ALTER TABLE ingestion_logs DROP CONSTRAINT IF EXISTS ingestion_logs_job_type_check;
ALTER TABLE ingestion_logs ADD CONSTRAINT ingestion_logs_job_type_check CHECK (job_type IN
  ('PRICES','INDICES','FX','VALUATION','FINANCIALS','DISCLOSURES','SCORES','MASTER','BENCHMARK','HYDRATE'));
