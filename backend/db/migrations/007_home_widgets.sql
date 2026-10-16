-- =====================================================================
-- 대시보드 홈 위젯: 섹터 히트맵 · 시장 심리 지수 — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 007_home_widgets
-- =====================================================================

-- 섹터 등락률(캐시 성격 — 30일 지난 행은 갱신 작업이 정리). 가중치는 저장하지 않고 코드 상수(app/services/sectors.py)
CREATE TABLE IF NOT EXISTS sector_performance_daily (
  id          BIGSERIAL    PRIMARY KEY,
  market      CHAR(2)      NOT NULL CHECK (market IN ('KR','US')),
  sector_code VARCHAR(16)  NOT NULL,                        -- 미국 섹터 ETF 티커(XLK…) / KRX 섹터 지수 코드
  sector_name VARCHAR(40)  NOT NULL,
  trade_date  DATE         NOT NULL,
  change_pct  NUMERIC(8,4),                                 -- 전일 대비 %(1.23 = 1.23%)
  fetched_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
  UNIQUE (market, sector_code, trade_date)
);

-- 시장 심리 지수(StockMind 간이 계산, 0~100 높을수록 탐욕). 구성요소 점수도 0~100
CREATE TABLE IF NOT EXISTS market_sentiment_daily (
  id              BIGSERIAL     PRIMARY KEY,
  market          CHAR(2)       NOT NULL CHECK (market IN ('KR','US')),
  trade_date      DATE          NOT NULL,                   -- 기준 지수(KOSPI·S&P 500)의 거래일
  score           NUMERIC(5,2)  NOT NULL CHECK (score BETWEEN 0 AND 100),
  label           VARCHAR(10)   NOT NULL,
  price_position  NUMERIC(5,2)  CHECK (price_position BETWEEN 0 AND 100),
  ma_gap_score    NUMERIC(5,2)  CHECK (ma_gap_score BETWEEN 0 AND 100),
  rsi_score       NUMERIC(5,2)  CHECK (rsi_score BETWEEN 0 AND 100),
  vix_score       NUMERIC(5,2)  CHECK (vix_score BETWEEN 0 AND 100),   -- 미국만
  formula_version SMALLINT      NOT NULL,
  computed_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  UNIQUE (market, trade_date)
);

-- 섹터 갱신 작업 결과를 ingestion_logs에 남긴다
ALTER TABLE ingestion_logs DROP CONSTRAINT IF EXISTS ingestion_logs_job_type_check;
ALTER TABLE ingestion_logs ADD CONSTRAINT ingestion_logs_job_type_check CHECK (job_type IN
  ('PRICES','INDICES','FX','VALUATION','FINANCIALS','DISCLOSURES','SCORES','MASTER','BENCHMARK','HYDRATE',
   'SECTORS_US','SECTORS_KR'));
