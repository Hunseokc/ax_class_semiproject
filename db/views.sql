-- =====================================================================
-- 파생 지표 VIEW — 수익률·변동성 등 파생값은 저장하지 않고 VIEW로 계산한다.
-- 비율 값은 모두 소수(0.05 = 5%)로 반환한다. 표시 단위 변환은 API/프론트에서 한다.
-- 데이터가 부족하면 NULL을 반환한다(거짓 값을 만들지 않음).
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
--   (오래된 SNAPSHOT보다 더 최근 DAILY가 있으면 DAILY를 쓴다 — ASSUMPTIONS A-24)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_fx_latest AS
SELECT f.fx_id, f.rate_at, f.usd_krw, f.granularity, f.source
FROM fx_rates f
ORDER BY f.rate_at DESC, (f.granularity = 'SNAPSHOT') DESC
LIMIT 1;

-- ---------------------------------------------------------------------
-- v_stock_metrics: 종목별 최신 지표 1행
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_stock_metrics AS
WITH latest AS (                      -- 기준: 종목별 최신 거래일
    SELECT lp.stock_id, lp.market, lp.country, lp.currency,
           lp.trade_date AS as_of, lp.close, lp.change_rate, lp.volume
    FROM v_latest_price lp
),
recent AS (                           -- 최신일부터 거꾸로 거래일 번호(rn=1이 최신)
    SELECT d.stock_id, d.trade_date, d.close, d.volume,
           ROW_NUMBER() OVER (PARTITION BY d.stock_id ORDER BY d.trade_date DESC) AS rn
    FROM daily_prices d
),
daily_ret AS (                        -- 최근 253개 종가 → 252개 일수익률
    SELECT r.stock_id, r.rn, r.trade_date, r.close,
           r.close / NULLIF(LAG(r.close) OVER (PARTITION BY r.stock_id ORDER BY r.trade_date), 0) - 1 AS ret
    FROM recent r
    WHERE r.rn <= 253
),
risk AS (                             -- 연환산 변동성: 252개 일수익률이 모두 있을 때만
    SELECT dr.stock_id,
           CASE WHEN COUNT(dr.ret) = 252
                THEN STDDEV_SAMP(dr.ret) * SQRT(252::numeric) END AS volatility_1y
    FROM daily_ret dr
    GROUP BY dr.stock_id
),
drawdown AS (                         -- 최근 252거래일 누적 고점 대비 낙폭
    SELECT r.stock_id, r.rn,
           r.close / MAX(r.close) OVER (PARTITION BY r.stock_id ORDER BY r.trade_date
                                        ROWS UNBOUNDED PRECEDING) - 1 AS dd
    FROM recent r
    WHERE r.rn <= 252
),
mdd AS (
    SELECT dd.stock_id,
           CASE WHEN COUNT(*) = 252 THEN MIN(dd.dd) END AS max_drawdown_1y
    FROM drawdown dd
    GROUP BY dd.stock_id
),
ma AS (                               -- 이동평균: 해당 기간 거래일 수가 다 찼을 때만
    SELECT r.stock_id,
           CASE WHEN COUNT(*) FILTER (WHERE r.rn <= 20)  = 20  THEN AVG(r.close) FILTER (WHERE r.rn <= 20)  END AS ma20,
           CASE WHEN COUNT(*) FILTER (WHERE r.rn <= 60)  = 60  THEN AVG(r.close) FILTER (WHERE r.rn <= 60)  END AS ma60,
           CASE WHEN COUNT(*) FILTER (WHERE r.rn <= 120) = 120 THEN AVG(r.close) FILTER (WHERE r.rn <= 120) END AS ma120,
           -- 거래량 기준: 최신일을 제외한 직전 20거래일 평균
           CASE WHEN COUNT(*) FILTER (WHERE r.rn BETWEEN 2 AND 21) = 20
                THEN AVG(r.volume) FILTER (WHERE r.rn BETWEEN 2 AND 21) END AS avg_volume_20d
    FROM recent r
    WHERE r.rn <= 120
    GROUP BY r.stock_id
),
range_52w AS (                        -- 52주(기준일로부터 1년) 고가·저가 (일중 고가·저가 기준)
    SELECT l.stock_id,
           MAX(d.high) AS high_52w,
           MIN(d.low)  AS low_52w
    FROM latest l
    JOIN daily_prices d
      ON d.stock_id = l.stock_id
     AND d.trade_date >  (l.as_of - INTERVAL '1 year')::date
     AND d.trade_date <= l.as_of
    GROUP BY l.stock_id
),
fy AS (                               -- FY 재무 + 직전 FY (결산일 간격이 약 1년일 때만 직전 FY로 인정)
    SELECT f.stock_id, f.period_end, f.revenue, f.operating_income, f.net_income,
           f.total_equity, f.total_debt, f.accounting_std,
           LAG(f.period_end)       OVER w AS prev_end,
           LAG(f.revenue)          OVER w AS prev_revenue,
           LAG(f.operating_income) OVER w AS prev_operating_income,
           ROW_NUMBER() OVER (PARTITION BY f.stock_id ORDER BY f.period_end DESC) AS rn
    FROM financial_statements f
    WHERE f.period_type = 'FY'
    WINDOW w AS (PARTITION BY f.stock_id ORDER BY f.period_end)
),
fin AS (
    SELECT fy.stock_id, fy.period_end AS fin_period_end, fy.accounting_std,
           fy.operating_income / NULLIF(fy.revenue, 0)       AS operating_margin,
           CASE WHEN fy.total_equity > 0 THEN fy.net_income / fy.total_equity END AS roe,
           fy.total_debt / NULLIF(fy.total_equity, 0)        AS debt_ratio,
           CASE WHEN fy.prev_end BETWEEN fy.period_end - 400 AND fy.period_end - 330
                THEN (fy.revenue - fy.prev_revenue) / NULLIF(ABS(fy.prev_revenue), 0) END AS revenue_yoy,
           CASE WHEN fy.prev_end BETWEEN fy.period_end - 400 AND fy.period_end - 330
                THEN (fy.operating_income - fy.prev_operating_income)
                     / NULLIF(ABS(fy.prev_operating_income), 0) END AS operating_income_yoy
    FROM fy
    WHERE fy.rn = 1
)
SELECT l.stock_id, l.market, l.country, l.currency, l.as_of, l.close, l.change_rate,
       -- 기간 수익률: 기준일에서 기간을 뺀 날짜 이전 가장 가까운 거래일 종가 대비
       ROUND(l.close / NULLIF(p1w.close, 0) - 1, 6) AS return_1w,
       ROUND(l.close / NULLIF(p1m.close, 0) - 1, 6) AS return_1m,
       ROUND(l.close / NULLIF(p3m.close, 0) - 1, 6) AS return_3m,
       ROUND(l.close / NULLIF(p6m.close, 0) - 1, 6) AS return_6m,
       ROUND(l.close / NULLIF(p1y.close, 0) - 1, 6) AS return_1y,
       ROUND(rk.volatility_1y, 6)                    AS volatility_1y,
       ROUND(md.max_drawdown_1y, 6)                  AS max_drawdown_1y,
       ROUND(ma.ma20, 4)  AS ma20,
       ROUND(ma.ma60, 4)  AS ma60,
       ROUND(ma.ma120, 4) AS ma120,
       ROUND(l.close / NULLIF(ma.ma120, 0) - 1, 6)   AS ma120_gap,
       -- 52주 범위는 1년치 데이터가 있을 때만(1년 전 기준 종가 존재 = p1y)
       CASE WHEN p1y.close IS NOT NULL THEN r52.high_52w END AS high_52w,
       CASE WHEN p1y.close IS NOT NULL THEN r52.low_52w  END AS low_52w,
       CASE WHEN p1y.close IS NOT NULL
            THEN ROUND((l.close - r52.low_52w) / NULLIF(r52.high_52w - r52.low_52w, 0), 6) END AS position_52w,
       l.volume,
       ROUND(ma.avg_volume_20d, 0)                   AS avg_volume_20d,
       ROUND(l.volume / NULLIF(ma.avg_volume_20d, 0), 6) AS volume_ratio_20d,
       -- 최신 밸류에이션
       v.as_of        AS valuation_as_of,
       v.per, v.pbr, v.eps, v.bps,
       v.market_cap,
       ROUND(v.market_cap * CASE WHEN l.currency = 'USD' THEN fx.usd_krw ELSE 1 END, 0) AS market_cap_krw,
       fx.usd_krw     AS fx_usd_krw,
       fx.rate_at     AS fx_rate_at,
       -- 최신 FY 재무
       fn.fin_period_end, fn.accounting_std,
       ROUND(fn.operating_margin, 6)     AS operating_margin,
       ROUND(fn.roe, 6)                  AS roe,
       ROUND(fn.debt_ratio, 6)           AS debt_ratio,
       ROUND(fn.revenue_yoy, 6)          AS revenue_yoy,
       ROUND(fn.operating_income_yoy, 6) AS operating_income_yoy
FROM latest l
LEFT JOIN LATERAL (SELECT d.close FROM daily_prices d
                   WHERE d.stock_id = l.stock_id AND d.trade_date <= l.as_of - 7
                   ORDER BY d.trade_date DESC LIMIT 1) p1w ON true
LEFT JOIN LATERAL (SELECT d.close FROM daily_prices d
                   WHERE d.stock_id = l.stock_id AND d.trade_date <= (l.as_of - INTERVAL '1 month')::date
                   ORDER BY d.trade_date DESC LIMIT 1) p1m ON true
LEFT JOIN LATERAL (SELECT d.close FROM daily_prices d
                   WHERE d.stock_id = l.stock_id AND d.trade_date <= (l.as_of - INTERVAL '3 months')::date
                   ORDER BY d.trade_date DESC LIMIT 1) p3m ON true
LEFT JOIN LATERAL (SELECT d.close FROM daily_prices d
                   WHERE d.stock_id = l.stock_id AND d.trade_date <= (l.as_of - INTERVAL '6 months')::date
                   ORDER BY d.trade_date DESC LIMIT 1) p6m ON true
LEFT JOIN LATERAL (SELECT d.close FROM daily_prices d
                   WHERE d.stock_id = l.stock_id AND d.trade_date <= (l.as_of - INTERVAL '1 year')::date
                   ORDER BY d.trade_date DESC LIMIT 1) p1y ON true
LEFT JOIN risk      rk  ON rk.stock_id  = l.stock_id
LEFT JOIN mdd       md  ON md.stock_id  = l.stock_id
LEFT JOIN ma            ON ma.stock_id  = l.stock_id
LEFT JOIN range_52w r52 ON r52.stock_id = l.stock_id
LEFT JOIN LATERAL (SELECT vs.as_of, vs.per, vs.pbr, vs.eps, vs.bps, vs.market_cap
                   FROM valuation_snapshots vs
                   WHERE vs.stock_id = l.stock_id
                   ORDER BY vs.as_of DESC LIMIT 1) v ON true
LEFT JOIN v_fx_latest fx ON true
LEFT JOIN fin fn ON fn.stock_id = l.stock_id;
