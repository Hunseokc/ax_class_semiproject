-- =====================================================================
-- 파생 지표 VIEW — 파생값은 저장하지 않고 VIEW로 계산한다.
-- 비율 값은 모두 소수(0.05 = 5%)로 반환한다. 표시 단위 변환은 API/프론트에서 한다.
-- 데이터가 부족하면 NULL을 반환한다(거짓 값을 만들지 않음).
-- 실행 순서: schema.sql → indexes.sql → views.sql  (CREATE OR REPLACE라 재실행해도 안전)
-- Stage 1 범위: v_latest_price, v_fx_latest. Stage 4: v_stock_metrics(B).
-- =====================================================================

-- ---------------------------------------------------------------------
-- v_latest_price: 종목별 최신 종가, 전일 종가, 등락률, 최신 거래량
--   종목마다 PK 역방향 스캔으로 최근 2행만 읽고 LAG로 전일 종가를 구한다.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_latest_price AS
SELECT s.stock_id,
       m.code     AS market,
       m.country,
       m.currency,
       lp.trade_date,
       lp.close,
       lp.prev_close,
       lp.close - lp.prev_close                          AS change,
       ROUND(lp.close / NULLIF(lp.prev_close, 0) - 1, 6) AS change_rate,
       lp.volume
FROM stocks s
JOIN markets m ON m.market_id = s.market_id
CROSS JOIN LATERAL (
    SELECT t.trade_date, t.close, t.volume,
           LAG(t.close) OVER (ORDER BY t.trade_date) AS prev_close
    FROM (SELECT d.trade_date, d.close, d.volume
          FROM daily_prices d
          WHERE d.stock_id = s.stock_id
          ORDER BY d.trade_date DESC
          LIMIT 2) t
    ORDER BY t.trade_date DESC
    LIMIT 1
) lp;

-- ---------------------------------------------------------------------
-- v_fx_latest: 최신 USD/KRW 1행
--   가장 최근 rate_at을 고르고, 같은 시각이면 SNAPSHOT을 우선한다.
--   (오래된 SNAPSHOT보다 더 최근 DAILY가 있으면 DAILY를 쓴다)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fx_latest AS
SELECT f.fx_id, f.rate_at, f.usd_krw, f.granularity, f.source
FROM fx_rates f
ORDER BY f.rate_at DESC, (f.granularity = 'SNAPSHOT') DESC
LIMIT 1;

-- ── [S4-B] v_stock_metrics ──
-- ---------------------------------------------------------------------
-- v_stock_metrics: 종목별 최신 지표 1행
-- TODO(껍데기): B — 원본 views.sql의 v_stock_metrics(CTE·윈도우 함수)로 교체.
--   지금은 컬럼 이름·순서·타입만 docs/05 9-4 계약과 같고, 최신 종가·밸류에이션·환율처럼 바로 꺼낼 수 있는 값만 채운다.
--   수익률·변동성·MDD·이동평균·52주·거래량 비율·재무 지표는 NULL. (타입까지 같아야 B의 CREATE OR REPLACE VIEW가 기존 DB에서도 된다)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock_metrics AS
SELECT l.stock_id, l.market, l.country, l.currency, l.trade_date AS as_of, l.close, l.change_rate,
       NULL::numeric AS return_1w,
       NULL::numeric AS return_1m,
       NULL::numeric AS return_3m,
       NULL::numeric AS return_6m,
       NULL::numeric AS return_1y,
       NULL::numeric AS volatility_1y,
       NULL::numeric AS max_drawdown_1y,
       NULL::numeric AS ma20,
       NULL::numeric AS ma60,
       NULL::numeric AS ma120,
       NULL::numeric AS ma120_gap,
       NULL::numeric AS high_52w,
       NULL::numeric AS low_52w,
       NULL::numeric AS position_52w,
       l.volume,
       NULL::numeric AS avg_volume_20d,
       NULL::numeric AS volume_ratio_20d,
       -- 최신 밸류에이션
       v.as_of        AS valuation_as_of,
       v.per, v.pbr, v.eps, v.bps,
       v.market_cap,
       ROUND(v.market_cap * CASE WHEN l.currency = 'USD' THEN fx.usd_krw ELSE 1 END, 0) AS market_cap_krw,
       fx.usd_krw     AS fx_usd_krw,
       fx.rate_at     AS fx_rate_at,
       -- 최신 FY 재무
       NULL::date        AS fin_period_end,
       NULL::varchar(20) AS accounting_std,
       NULL::numeric     AS operating_margin,
       NULL::numeric     AS roe,
       NULL::numeric     AS debt_ratio,
       NULL::numeric     AS revenue_yoy,
       NULL::numeric     AS operating_income_yoy
FROM v_latest_price l
LEFT JOIN LATERAL (SELECT vs.as_of, vs.per, vs.pbr, vs.eps, vs.bps, vs.market_cap
                   FROM valuation_snapshots vs
                   WHERE vs.stock_id = l.stock_id
                   ORDER BY vs.as_of DESC LIMIT 1) v ON true
LEFT JOIN v_fx_latest fx ON true;
