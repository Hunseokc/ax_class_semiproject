-- =====================================================================
-- 보조 인덱스 (PK·UNIQUE가 자동 생성하는 인덱스는 제외) — Stage 1·2 테이블분
-- 각 인덱스가 받치는 조회 패턴을 주석으로 적는다.
-- =====================================================================

-- 종목 검색(이름 정렬·접두 검색). 부분 일치(ILIKE '%q%')는 B-tree로 받칠 수 없음 → 25행 규모라 순차 스캔 허용
CREATE INDEX ix_stocks_name ON stocks (name);

-- 특정 날짜의 전 종목 시세(시장별 최신 거래일, 거래량 순위 등). PK는 stock_id 선두라 날짜 단독 조건에 못 씀
CREATE INDEX ix_daily_prices_trade_date ON daily_prices (trade_date);

-- (만들지 않음) valuation_snapshots (stock_id, as_of DESC): PK (stock_id, as_of)의 역방향 스캔이 같은 조회를 받친다 → 중복 인덱스

-- 날짜 기준 전 지수 조회(대시보드 홈)
CREATE INDEX ix_index_prices_trade_date ON index_daily_prices (trade_date);

-- 최신 SNAPSHOT/DAILY 환율 1건 (FxService TTL 판단, v_fx_latest)
CREATE INDEX ix_fx_granularity_rate_at ON fx_rates (granularity, rate_at DESC);

-- 작업 종류별 마지막 성공 시각(갱신 TTL 판단)
CREATE INDEX ix_ingestion_logs_job_finished ON ingestion_logs (job_type, finished_at DESC);

-- 종목 → 소속 경쟁 그룹 조회. PK (group_id, stock_id)는 stock_id 단독 조건에 못 씀
CREATE INDEX ix_peer_members_stock ON peer_group_members (stock_id);

-- ── Stage 2 ──
-- 종목 → 이 종목을 관심종목으로 담은 사용자 조회. PK (user_id, stock_id)는 stock_id 단독 조건에 못 씀
CREATE INDEX ix_watchlist_stock ON watchlist_items (stock_id);

-- 종목 → 이 종목이 담긴 포트폴리오 항목 조회(종목 삭제 전 확인 등). UNIQUE (portfolio_id, stock_id)는 stock_id 단독 조건에 못 씀
CREATE INDEX ix_portfolio_items_stock ON portfolio_items (stock_id);

-- 사용자별 포트폴리오 목록은 UNIQUE (user_id, name)이 받친다 → 별도 인덱스 만들지 않음

-- 이후 단계에서 추가: ix_fin_stock_type_end·ix_disclosures_stock_filed(Stage 3)
