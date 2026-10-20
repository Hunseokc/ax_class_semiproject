-- =====================================================================
-- 국내 시세 소스 KIS(한국투자증권 Open API) 추가 — 밸류에이션 source에 'KIS' 허용. 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 010_kis_source
-- =====================================================================

ALTER TABLE valuation_snapshots DROP CONSTRAINT IF EXISTS valuation_snapshots_source_check;
ALTER TABLE valuation_snapshots ADD CONSTRAINT valuation_snapshots_source_check
  CHECK (source IN ('PYKRX','YFINANCE','DERIVED','KIS'));
