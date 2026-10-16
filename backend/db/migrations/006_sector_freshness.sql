-- =====================================================================
-- 비교군 확대(공식 업종 섹터) + 데이터 유효기간 + 미국 밸류에이션 기초값 — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 006_sector_freshness  →  python -m app.ingest benchmark --reselect
-- =====================================================================

ALTER TABLE peer_groups ADD COLUMN IF NOT EXISTS kind VARCHAR(10) NOT NULL DEFAULT 'theme';
ALTER TABLE peer_groups DROP CONSTRAINT IF EXISTS peer_groups_kind_check;
ALTER TABLE peer_groups ADD CONSTRAINT peer_groups_kind_check CHECK (kind IN ('theme','sector'));

ALTER TABLE stocks ADD COLUMN IF NOT EXISTS industry VARCHAR(64);
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS sic SMALLINT;
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS sector VARCHAR(32);
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS industry_checked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS data_freshness (
  stock_id    INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  kind        VARCHAR(16)  NOT NULL CHECK (kind IN ('financials','disclosures','price_history')),
  fetched_at  TIMESTAMPTZ  NOT NULL,
  valid_until TIMESTAMPTZ  NOT NULL,
  status      VARCHAR(10)  NOT NULL CHECK (status IN ('SUCCESS','FAILED')),
  error       TEXT,
  PRIMARY KEY (stock_id, kind),
  CHECK (valid_until >= fetched_at)
);

CREATE TABLE IF NOT EXISTS fundamental_bases (
  stock_id           INT           PRIMARY KEY REFERENCES stocks ON DELETE CASCADE,
  shares_outstanding BIGINT        CHECK (shares_outstanding > 0),
  shares_as_of       DATE,
  dps                NUMERIC(18,4) CHECK (dps >= 0),
  dps_period_end     DATE,
  source             VARCHAR(20)   NOT NULL,
  updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now()
);

-- 장 마감·KRX 공표 전에 받아 값이 모두 비어 있는 국내 밸류에이션 행 정리(다음 수집에서 다시 받는다, A-07)
DELETE FROM valuation_snapshots
WHERE source = 'PYKRX' AND per IS NULL AND pbr IS NULL AND eps IS NULL AND bps IS NULL AND market_cap IS NULL;
