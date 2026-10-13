-- =====================================================================
-- 파생 지표 VIEW — 파생값은 저장하지 않고 VIEW로 계산한다.
-- 비율 값은 모두 소수(0.05 = 5%)로 반환한다. 표시 단위 변환은 API/프론트에서 한다.
-- 데이터가 부족하면 NULL을 반환한다(거짓 값을 만들지 않음).
-- 실행 순서: schema.sql → indexes.sql → views.sql  (CREATE OR REPLACE라 재실행해도 안전)
-- Stage 1 범위: v_latest_price, v_fx_latest. v_stock_metrics는 Stage 4에서 추가한다.
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
