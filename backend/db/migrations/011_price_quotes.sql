-- =====================================================================
-- 현재가 스냅샷 price_quotes (관심종목·상세 화면 표시 전용, KIS) + ingestion_logs job_type 'QUOTES'. 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 011_price_quotes
-- =====================================================================

CREATE TABLE IF NOT EXISTS price_quotes (
  stock_id    INT           PRIMARY KEY REFERENCES stocks ON DELETE CASCADE,
  price       NUMERIC(18,4) NOT NULL CHECK (price > 0),
  prev_close  NUMERIC(18,4) CHECK (prev_close > 0),
  change      NUMERIC(18,4),
  change_rate NUMERIC(10,6),
  quoted_at   TIMESTAMPTZ   NOT NULL,
  source      VARCHAR(20)   NOT NULL DEFAULT 'KIS'
);

ALTER TABLE ingestion_logs DROP CONSTRAINT IF EXISTS ingestion_logs_job_type_check;
ALTER TABLE ingestion_logs ADD CONSTRAINT ingestion_logs_job_type_check CHECK (job_type IN
  ('PRICES','INDICES','FX','VALUATION','FINANCIALS','DISCLOSURES','SCORES','MASTER','BENCHMARK','HYDRATE',
   'SECTORS_US','SECTORS_KR','QUOTES'));
