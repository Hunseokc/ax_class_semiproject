-- =====================================================================
-- 매력도 다중 팩터 모델(v2) — 이미 적재된 DB를 데이터 유지한 채 바꾼다.
-- 새로 만드는 DB는 schema.sql에 반영되어 있으므로 실행하지 않는다.
-- 실행: python -m app.ingest migrate 001_scoring_v2  →  python -m app.ingest scores
-- 이전 stock_scores(PERCENT_RANK 방식)는 재생성 가능한 파생 테이블이라 삭제 후 다시 계산한다.
-- =====================================================================

ALTER TABLE peer_group_members ADD COLUMN IF NOT EXISTS is_primary BOOLEAN NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pgm_primary ON peer_group_members (stock_id) WHERE is_primary;

-- 주 그룹 초기값: 종목마다 group_id가 가장 작은 그룹 (이후 master 적재가 universe.yaml 순서로 다시 맞춘다)
UPDATE peer_group_members gm SET is_primary = true
WHERE NOT EXISTS (SELECT 1 FROM peer_group_members x WHERE x.stock_id = gm.stock_id AND x.is_primary)
  AND gm.group_id = (SELECT MIN(x.group_id) FROM peer_group_members x WHERE x.stock_id = gm.stock_id);

CREATE TABLE IF NOT EXISTS scoring_presets (
  preset_id   SMALLSERIAL PRIMARY KEY,
  code        VARCHAR(20) NOT NULL UNIQUE,
  name        VARCHAR(50) NOT NULL,
  description TEXT,
  sort_order  SMALLINT    NOT NULL DEFAULT 0
);
ALTER TABLE scoring_presets ADD COLUMN IF NOT EXISTS sort_order SMALLINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS scoring_weights (
  preset_id SMALLINT     NOT NULL REFERENCES scoring_presets ON DELETE CASCADE,
  factor    VARCHAR(12)  NOT NULL CHECK (factor IN ('value','quality','growth','safety','momentum')),
  weight    NUMERIC(4,3) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  PRIMARY KEY (preset_id, factor)
);

CREATE TABLE IF NOT EXISTS stock_metric_values (
  stock_id  INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  as_of     DATE         NOT NULL,
  metric    VARCHAR(24)  NOT NULL,
  factor    VARCHAR(12)  NOT NULL CHECK (factor IN ('value','quality','growth','safety','momentum')),
  raw_value NUMERIC,
  z_raw     NUMERIC(8,4),
  z_adj     NUMERIC(8,4),
  PRIMARY KEY (stock_id, as_of, metric)
);

DROP TABLE IF EXISTS stock_scores;
CREATE TABLE stock_scores (
  stock_id        INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  as_of           DATE         NOT NULL,
  preset_id       SMALLINT     NOT NULL REFERENCES scoring_presets,
  value_score     NUMERIC(8,4),
  quality_score   NUMERIC(8,4),
  growth_score    NUMERIC(8,4),
  safety_score    NUMERIC(8,4),
  momentum_score  NUMERIC(8,4),
  composite       NUMERIC(8,4),
  score           NUMERIC(5,2) CHECK (score BETWEEN 0 AND 100),
  factor_coverage SMALLINT     NOT NULL CHECK (factor_coverage BETWEEN 0 AND 5),
  data_quality    JSONB        NOT NULL DEFAULT '{}',
  PRIMARY KEY (stock_id, as_of, preset_id)
);
