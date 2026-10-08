-- =====================================================================
-- 주식 분석 대시보드 — 테이블 생성 SQL (PostgreSQL 16)
-- 실행 순서: schema.sql → indexes.sql → views.sql
-- 금액·가격은 모두 NUMERIC (float 사용 안 함)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. 시장·종목·경쟁 그룹 (마스터)
-- ---------------------------------------------------------------------

-- 시장: 통화·국가·시간대는 시장 단위 속성 → stocks에 반복하지 않는다 (3NF)
CREATE TABLE markets (
  market_id SMALLSERIAL PRIMARY KEY,
  code      VARCHAR(10) NOT NULL UNIQUE,                         -- KOSPI / KOSDAQ / NASDAQ / NYSE
  country   CHAR(2)     NOT NULL CHECK (country IN ('KR','US')),
  currency  CHAR(3)     NOT NULL CHECK (currency IN ('KRW','USD')),
  timezone  VARCHAR(40) NOT NULL                                 -- Asia/Seoul / America/New_York
);

-- 종목: 같은 티커라도 시장이 다르면 다른 종목 → (market_id, ticker) 자연키
CREATE TABLE stocks (
  stock_id  SERIAL PRIMARY KEY,
  market_id SMALLINT     NOT NULL REFERENCES markets,
  ticker    VARCHAR(16)  NOT NULL,
  name      VARCHAR(128) NOT NULL,
  name_en   VARCHAR(128),
  corp_code VARCHAR(16),                                         -- OpenDART 고유번호 (KR)
  cik       VARCHAR(10),                                         -- SEC CIK 10자리 (US)
  is_active BOOLEAN      NOT NULL DEFAULT true,                  -- false: 수집·점수 계산 대상에서 제외(데이터는 보존)
  -- featured: 화면에 노출하는 종목(4시간 갱신) / benchmark: 매력도 비교군(1일 갱신, 필수 데이터만 저장)
  coverage  VARCHAR(10)  NOT NULL DEFAULT 'featured' CHECK (coverage IN ('featured','benchmark')),
  detail_synced_at TIMESTAMPTZ,                                  -- benchmark 종목의 상세(공시·2년 일봉·5개년 재무)를 마지막으로 받은 시각
  UNIQUE (market_id, ticker)
);

-- 경쟁 그룹
CREATE TABLE peer_groups (
  group_id    SERIAL PRIMARY KEY,
  name        VARCHAR(64) NOT NULL UNIQUE,
  description TEXT
);

-- 종목 ↔ 경쟁 그룹 N:M 교차 테이블 (국내·해외 종목 혼합 가능)
-- is_primary: 매력도 섹터 중립화에 쓰는 주 그룹. 종목당 최대 1개(부분 UNIQUE 인덱스)
CREATE TABLE peer_group_members (
  group_id   INT     NOT NULL REFERENCES peer_groups ON DELETE CASCADE,
  stock_id   INT     NOT NULL REFERENCES stocks      ON DELETE CASCADE,
  is_primary BOOLEAN NOT NULL DEFAULT false,
  PRIMARY KEY (group_id, stock_id)
);
CREATE UNIQUE INDEX ux_pgm_primary ON peer_group_members (stock_id) WHERE is_primary;

-- ---------------------------------------------------------------------
-- 2. 종목별 시계열·재무·공시 (Stock 1─N)
-- ---------------------------------------------------------------------

-- 일봉: 시장 현지 날짜 기준, 수정주가
CREATE TABLE daily_prices (
  stock_id   INT           NOT NULL REFERENCES stocks ON DELETE CASCADE,
  trade_date DATE          NOT NULL,                             -- 시장 현지 날짜
  open       NUMERIC(18,4) NOT NULL,
  high       NUMERIC(18,4) NOT NULL,
  low        NUMERIC(18,4) NOT NULL,
  close      NUMERIC(18,4) NOT NULL,                             -- 수정주가
  volume     BIGINT        NOT NULL CHECK (volume >= 0),
  PRIMARY KEY (stock_id, trade_date),
  CHECK (high >= low),
  CHECK (low > 0)                                                -- 0·음수 가격은 이상 행으로 격리
);

-- 밸류에이션 스냅샷: KR은 pykrx 일별, US는 적재 시점 1행, 폴백은 DART 기반 파생값
CREATE TABLE valuation_snapshots (
  stock_id           INT           NOT NULL REFERENCES stocks ON DELETE CASCADE,
  as_of              DATE          NOT NULL,
  per                NUMERIC(18,4),                              -- 적자·미제공은 NULL
  pbr                NUMERIC(18,4),
  eps                NUMERIC(18,4),
  bps                NUMERIC(18,4),
  market_cap         NUMERIC(26,0) CHECK (market_cap >= 0),      -- 종목 통화 기준
  shares_outstanding BIGINT        CHECK (shares_outstanding >= 0),
  source             VARCHAR(20)   NOT NULL CHECK (source IN ('PYKRX','YFINANCE','DERIVED')),
  PRIMARY KEY (stock_id, as_of)
);

-- 재무제표: 연간(FY) 필수, 분기는 선택. 금액은 종목 통화 기준
CREATE TABLE financial_statements (
  fin_id           SERIAL PRIMARY KEY,
  stock_id         INT           NOT NULL REFERENCES stocks ON DELETE CASCADE,
  period_end       DATE          NOT NULL,                       -- 결산일
  period_type      VARCHAR(4)    NOT NULL CHECK (period_type IN ('FY','Q1','Q2','Q3','Q4')),
  revenue          NUMERIC(24,2),
  operating_income NUMERIC(24,2),
  net_income       NUMERIC(24,2),                                -- 지배기업 소유주 귀속 우선
  total_assets     NUMERIC(24,2),
  total_equity     NUMERIC(24,2),                                -- 지배기업 소유주 귀속 우선
  total_debt       NUMERIC(24,2),                                -- 부채총계 (KR Liabilities / US Liabilities)
  data_source      VARCHAR(20)   NOT NULL CHECK (data_source IN ('DART','SEC','YFINANCE')),
  accounting_std   VARCHAR(20),                                  -- K-IFRS / US-GAAP
  UNIQUE (stock_id, period_end, period_type)
);

-- 공시: DART 접수번호 / SEC accession number
CREATE TABLE disclosures (
  disclosure_id SERIAL PRIMARY KEY,
  stock_id      INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  rcept_no      VARCHAR(64)  NOT NULL UNIQUE,
  title         TEXT         NOT NULL,
  report_type   VARCHAR(100),
  filed_at      TIMESTAMPTZ  NOT NULL,
  url           TEXT,
  data_source   VARCHAR(20)  NOT NULL CHECK (data_source IN ('DART','SEC'))
);

-- ---------------------------------------------------------------------
-- 3. 시장 배경 정보: 지수·환율
-- ---------------------------------------------------------------------

CREATE TABLE indices (
  index_id      SMALLSERIAL PRIMARY KEY,
  code          VARCHAR(16) NOT NULL UNIQUE,                     -- KOSPI / KOSDAQ / SPX / IXIC / DJI
  name          VARCHAR(64) NOT NULL,
  market_id     SMALLINT    REFERENCES markets,
  source_symbol VARCHAR(32) NOT NULL,                            -- 라이브러리 조회용 심볼 (1001, ^GSPC …)
  display_order SMALLINT    NOT NULL DEFAULT 0
);

CREATE TABLE index_daily_prices (
  index_id   SMALLINT      NOT NULL REFERENCES indices ON DELETE CASCADE,
  trade_date DATE          NOT NULL,
  open       NUMERIC(18,4),
  high       NUMERIC(18,4),
  low        NUMERIC(18,4),
  close      NUMERIC(18,4) NOT NULL CHECK (close > 0),
  PRIMARY KEY (index_id, trade_date)
);

-- USD/KRW 환율. SNAPSHOT: 조회 시각 / DAILY: 해당 일자 00:00 Asia/Seoul
CREATE TABLE fx_rates (
  fx_id       SERIAL PRIMARY KEY,
  rate_at     TIMESTAMPTZ   NOT NULL,
  usd_krw     NUMERIC(12,4) NOT NULL CHECK (usd_krw > 0),
  granularity VARCHAR(8)    NOT NULL CHECK (granularity IN ('SNAPSHOT','DAILY')),
  source      VARCHAR(20)   NOT NULL DEFAULT 'YFINANCE',
  UNIQUE (granularity, rate_at)
);

-- ---------------------------------------------------------------------
-- 4. 사용자·관심종목·모의 포트폴리오
-- ---------------------------------------------------------------------

-- 인증 없음. 기본 사용자 1명(demo)을 시드한다. 2차에서 로그인으로 대체
CREATE TABLE users (
  user_id    SERIAL PRIMARY KEY,
  nickname   VARCHAR(50) NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 사용자 ↔ 종목 N:M 교차 테이블
CREATE TABLE watchlist_items (
  user_id      INT           NOT NULL REFERENCES users  ON DELETE CASCADE,
  stock_id     INT           NOT NULL REFERENCES stocks ON DELETE CASCADE,
  sort_order   INT           NOT NULL DEFAULT 0,
  added_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
  memo         VARCHAR(200),                                                  -- 사용자 메모 (migration 004)
  target_price NUMERIC(20,4) CHECK (target_price > 0),                        -- 목표가(종목 통화)
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),                          -- 트리거가 갱신
  PRIMARY KEY (user_id, stock_id)
);

CREATE TABLE portfolios (
  portfolio_id SERIAL PRIMARY KEY,
  user_id      INT           NOT NULL REFERENCES users ON DELETE CASCADE,
  name         VARCHAR(100)  NOT NULL,
  seed_krw     NUMERIC(20,0) NOT NULL CHECK (seed_krw > 0),     -- 투자 시드(원)
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)
);

-- 장바구니 1종목 = 1행 (체결 기록 아님)
-- [의도적 비정규화 1] ref_price·ref_fx_rate·ref_date는 "담은 시점"의 불변 사실이다.
--   시세·환율 테이블이 갱신·보정되어도 담은 시점의 원가가 바뀌면 안 되므로 복사해 저장한다.
CREATE TABLE portfolio_items (
  item_id      SERIAL PRIMARY KEY,
  portfolio_id INT           NOT NULL REFERENCES portfolios ON DELETE CASCADE,
  stock_id     INT           NOT NULL REFERENCES stocks     ON DELETE RESTRICT,  -- 담긴 종목은 삭제 불가
  quantity     INT           NOT NULL CHECK (quantity > 0),
  ref_price    NUMERIC(18,4) NOT NULL CHECK (ref_price > 0),                     -- 담은 시점 종가(종목 통화)
  ref_fx_rate  NUMERIC(12,4) NOT NULL DEFAULT 1 CHECK (ref_fx_rate > 0),         -- 담은 시점 환율 (KRW 종목은 1)
  ref_date     DATE          NOT NULL,                                           -- ref_price의 거래일
  memo         TEXT,
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  cost_krw     NUMERIC(24,2) GENERATED ALWAYS AS (quantity * ref_price * ref_fx_rate) STORED,  -- 원가(원)
  UNIQUE (portfolio_id, stock_id)
);
-- "원가 합계 ≤ 시드"는 행 간 제약이라 CHECK로 걸 수 없다.
-- 서비스 계층에서 트랜잭션 + 포트폴리오 행 잠금(SELECT ... FOR UPDATE)으로 보장하고 테스트한다.

-- ---------------------------------------------------------------------
-- 5. 파생 결과·운영 로그
-- ---------------------------------------------------------------------

-- 매력도 가중치 프리셋 (config/scoring.yaml에서 적재). "프리셋별 가중치 합 = 1"은 행 간 제약이라
--   CHECK로 걸 수 없다 → 적재 시 검증(app/services/scoring.py)하고 테스트로 보장한다.
CREATE TABLE scoring_presets (
  preset_id   SMALLSERIAL PRIMARY KEY,
  code        VARCHAR(20) NOT NULL UNIQUE,                       -- aggressive / growth / balanced / value
  name        VARCHAR(50) NOT NULL,
  description TEXT,
  sort_order  SMALLINT    NOT NULL DEFAULT 0                     -- 화면 표시 순서 (위험 → 성장 → 균형 → 가치)
);

CREATE TABLE scoring_weights (
  preset_id SMALLINT     NOT NULL REFERENCES scoring_presets ON DELETE CASCADE,
  factor    VARCHAR(12)  NOT NULL CHECK (factor IN ('value','quality','growth','safety','momentum')),
  weight    NUMERIC(4,3) NOT NULL CHECK (weight >= 0 AND weight <= 1),
  PRIMARY KEY (preset_id, factor)
);

-- [의도적 비정규화 2] 매력도 계산 결과를 as_of별로 저장하는 재생성 가능한 파생 테이블 2개.
--   국가별 중앙값·MAD·그룹 평균을 화면 요청마다 다시 계산하지 않고, 점수의 근거(지표 원값·Z)를 설명하기 위해 저장한다.
--   같은 as_of는 DELETE 후 INSERT로 재생성한다(python -m app.ingest scores, POST /market/refresh).
-- 지표별 원값과 Z — 프리셋과 무관하므로 as_of당 한 번만 계산
CREATE TABLE stock_metric_values (
  stock_id  INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  as_of     DATE         NOT NULL,
  metric    VARCHAR(24)  NOT NULL,                                -- earnings_yield, book_yield, roe …
  factor    VARCHAR(12)  NOT NULL CHECK (factor IN ('value','quality','growth','safety','momentum')),
  raw_value NUMERIC,                                              -- 계산 불가면 NULL
  z_raw     NUMERIC(8,4),                                         -- 국가 내 로버스트 Z(방향 반영, ±3 클리핑)
  z_adj     NUMERIC(8,4),                                         -- 주 그룹 축소 추정으로 섹터 중립화한 Z
  PRIMARY KEY (stock_id, as_of, metric)
);

-- 프리셋별 팩터 점수·종합 점수
CREATE TABLE stock_scores (
  stock_id        INT          NOT NULL REFERENCES stocks ON DELETE CASCADE,
  as_of           DATE         NOT NULL,
  preset_id       SMALLINT     NOT NULL REFERENCES scoring_presets,
  value_score     NUMERIC(8,4),                                   -- 팩터 점수 = 유효 지표 z_adj 평균 (Z 단위)
  quality_score   NUMERIC(8,4),
  growth_score    NUMERIC(8,4),
  safety_score    NUMERIC(8,4),
  momentum_score  NUMERIC(8,4),
  composite       NUMERIC(8,4),                                   -- 유효 팩터 가중 평균(가중치 재정규화), 유효 팩터 < 3이면 NULL
  score           NUMERIC(5,2) CHECK (score BETWEEN 0 AND 100),   -- 100·Φ(국가 내 표준화한 composite)
  factor_coverage SMALLINT     NOT NULL CHECK (factor_coverage BETWEEN 0 AND 5),
  data_quality    JSONB        NOT NULL DEFAULT '{}',             -- 계산 불가 지표·팩터와 사유
  PRIMARY KEY (stock_id, as_of, preset_id)
);

-- 수집·갱신 작업 로그. 갱신 TTL 판단(작업별 마지막 성공 시각)에도 사용
CREATE TABLE ingestion_logs (
  log_id      SERIAL PRIMARY KEY,
  source      VARCHAR(20) NOT NULL,                              -- PYKRX / YFINANCE / DART / SEC / INTERNAL
  job_type    VARCHAR(30) NOT NULL CHECK (job_type IN
                ('PRICES','INDICES','FX','VALUATION','FINANCIALS','DISCLOSURES','SCORES','MASTER','BENCHMARK','HYDRATE')),
  stock_id    INT         REFERENCES stocks ON DELETE SET NULL,  -- 종목 단위 작업일 때만
  status      VARCHAR(10) NOT NULL CHECK (status IN ('SUCCESS','FAILED','SKIPPED')),
  rows_loaded INT         NOT NULL DEFAULT 0 CHECK (rows_loaded >= 0),
  error       TEXT,                                              -- 실패 사유 / 격리 행 사유
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- ---------------------------------------------------------------------
-- 6. updated_at 자동 갱신 트리거
-- ---------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_portfolios_updated_at
  BEFORE UPDATE ON portfolios FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_portfolio_items_updated_at
  BEFORE UPDATE ON portfolio_items FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_watchlist_items_updated_at
  BEFORE UPDATE ON watchlist_items FOR EACH ROW EXECUTE FUNCTION set_updated_at();
