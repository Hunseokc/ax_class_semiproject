-- =====================================================================
-- 주식 분석 대시보드 — 테이블 생성 SQL (PostgreSQL 16)
-- 실행 순서: schema.sql → indexes.sql → views.sql
-- 금액·가격은 모두 NUMERIC (float 사용 안 함)
--
-- Stage 1 테이블 10개 + Stage 2 테이블 4개. 이후 단계 테이블·컬럼은 D가 단계 시작 시 추가해 "계약"으로 배포한다.
--   Stage 2: users, watchlist_items(memo·target_price는 Stage 5), portfolios, portfolio_items (+ updated_at 트리거)
--   Stage 3: financial_statements, disclosures
--   Stage 4+: 매력도·비교군·섹터 관련 테이블/컬럼
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
  UNIQUE (market_id, ticker)
);

-- 경쟁 그룹
CREATE TABLE peer_groups (
  group_id    SERIAL PRIMARY KEY,
  name        VARCHAR(64) NOT NULL UNIQUE,
  description TEXT
);

-- 종목 ↔ 경쟁 그룹 N:M 교차 테이블 (국내·해외 종목 혼합 가능)
CREATE TABLE peer_group_members (
  group_id   INT NOT NULL REFERENCES peer_groups ON DELETE CASCADE,
  stock_id   INT NOT NULL REFERENCES stocks      ON DELETE CASCADE,
  PRIMARY KEY (group_id, stock_id)
);

-- ---------------------------------------------------------------------
-- 2. 종목별 시계열
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
-- 4. 운영 로그
-- ---------------------------------------------------------------------

-- 수집·갱신 작업 로그. 갱신 TTL 판단(작업별 마지막 성공 시각)에도 사용
-- job_type은 Stage 1 작업만 허용한다. 이후 단계에서 FINANCIALS·DISCLOSURES·SCORES 등을 추가한다.
CREATE TABLE ingestion_logs (
  log_id      SERIAL PRIMARY KEY,
  source      VARCHAR(20) NOT NULL,                              -- PYKRX / YFINANCE / DART / SEC / INTERNAL
  job_type    VARCHAR(30) NOT NULL CHECK (job_type IN ('PRICES','INDICES','FX','VALUATION','MASTER')),
  stock_id    INT         REFERENCES stocks ON DELETE SET NULL,  -- 종목 단위 작업일 때만
  status      VARCHAR(10) NOT NULL CHECK (status IN ('SUCCESS','FAILED','SKIPPED')),
  rows_loaded INT         NOT NULL DEFAULT 0 CHECK (rows_loaded >= 0),
  error       TEXT,                                              -- 실패 사유 / 격리 행 사유
  started_at  TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- =====================================================================
-- Stage 2 — 사용자 기능 (D가 단계 시작 시 배포한 계약)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 5. 사용자·관심종목·모의 포트폴리오
-- ---------------------------------------------------------------------

-- updated_at 자동 갱신: UPDATE가 일어나면 앱이 챙기지 않아도 DB가 현재 시각을 넣는다
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 사용자: 인증 없음. 기본 사용자 1명(demo)은 load_master가 시드한다(get_current_user_id = 설정 DEFAULT_USER_ID). 2차에서 로그인으로 대체
CREATE TABLE users (
  user_id    SERIAL PRIMARY KEY,
  nickname   VARCHAR(50) NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 관심종목: 사용자 ↔ 종목 N:M 교차 테이블 + 정렬 순서. 메모·목표가는 Stage 5에서 컬럼 추가
CREATE TABLE watchlist_items (
  user_id    INT         NOT NULL REFERENCES users  ON DELETE CASCADE,
  stock_id   INT         NOT NULL REFERENCES stocks ON DELETE CASCADE,
  sort_order INT         NOT NULL DEFAULT 0,                       -- 작을수록 먼저 (PATCH /watchlist/order가 다시 매김)
  added_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, stock_id)                                  -- 같은 종목 중복 담기 금지 → 409 DUPLICATE_WATCHLIST
);

-- 모의 포트폴리오: "시드 안에서 담아보는 계산기 겸 장바구니" (거래 원장 아님)
CREATE TABLE portfolios (
  portfolio_id SERIAL PRIMARY KEY,
  user_id      INT           NOT NULL REFERENCES users ON DELETE CASCADE,
  name         VARCHAR(100)  NOT NULL,
  seed_krw     NUMERIC(20,0) NOT NULL CHECK (seed_krw > 0),        -- 투자 시드(원)
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  UNIQUE (user_id, name)                                           -- 같은 사용자의 포트폴리오 이름 중복 → 409
);
CREATE TRIGGER trg_portfolios_updated_at BEFORE UPDATE ON portfolios
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 포트폴리오 항목. ref_*는 "담은 순간"의 가격·환율 복사본이다 (의도적 비정규화).
--   현재가·현재 환율은 시간이 지나면 바뀌므로, 매입 기준(원가)을 daily_prices·fx_rates에서 다시 찾으면
--   값이 달라진다 → 담을 때 복사해 두어야 평가손익을 "가격 효과 / 환율 효과"로 분리할 수 있다.
CREATE TABLE portfolio_items (
  item_id      SERIAL PRIMARY KEY,
  portfolio_id INT           NOT NULL REFERENCES portfolios ON DELETE CASCADE,
  stock_id     INT           NOT NULL REFERENCES stocks ON DELETE RESTRICT,  -- 담긴 종목은 삭제 불가
  quantity     INT           NOT NULL CHECK (quantity > 0),        -- 정수 주식 수
  ref_price    NUMERIC(18,4) NOT NULL CHECK (ref_price > 0),       -- 담은 시점 종가 (종목 통화)
  ref_fx_rate  NUMERIC(12,4) NOT NULL DEFAULT 1 CHECK (ref_fx_rate > 0),  -- 담은 시점 환율 (KRW 종목은 1)
  ref_date     DATE          NOT NULL,                             -- 위 가격·환율의 기준일
  memo         TEXT,
  created_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ   NOT NULL DEFAULT now(),
  cost_krw     NUMERIC(24,2) GENERATED ALWAYS AS (quantity * ref_price * ref_fx_rate) STORED,  -- 원가(원)
  UNIQUE (portfolio_id, stock_id)                                  -- 같은 종목은 한 줄 (수량 수정으로 늘린다)
);
-- "원가 합계 ≤ 시드"는 행 간 제약이라 CHECK로 걸 수 없다 → 서비스에서 트랜잭션 + 포트폴리오 행 잠금(SELECT ... FOR UPDATE)으로 보장한다.
CREATE TRIGGER trg_portfolio_items_updated_at BEFORE UPDATE ON portfolio_items
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
