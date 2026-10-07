-- 매력도 1단계: 종목별 지표 원값 (기준: 종목별 최신 거래일 종가·최신 밸류에이션·최신 FY 재무)
-- 지표 정의·NULL 사유는 docs/09 1절. 한 종목당 9행(값이 없으면 raw_value NULL)
-- z_fixed: 정규화 없이 Z를 고정하는 경우(자본 ≤ 0인 부채비율 → −3). note: 대체 계산·고정 사유
WITH base AS (
    SELECT vm.stock_id, vm.close, vm.eps, vm.bps, vm.volatility_1y, vm.market_cap, vs.shares_outstanding
    FROM v_stock_metrics vm
    LEFT JOIN LATERAL (SELECT x.shares_outstanding FROM valuation_snapshots x
                       WHERE x.stock_id = vm.stock_id ORDER BY x.as_of DESC LIMIT 1) vs ON true
),
fy AS (
    SELECT f.stock_id, f.period_end, f.revenue, f.operating_income, f.net_income, f.total_equity, f.total_debt,
           LAG(f.period_end) OVER w AS prev_end,
           LAG(f.revenue)    OVER w AS prev_revenue,
           LAG(f.net_income) OVER w AS prev_net_income,
           ROW_NUMBER() OVER (PARTITION BY f.stock_id ORDER BY f.period_end DESC) AS rn
    FROM financial_statements f
    WHERE f.period_type = 'FY'
    WINDOW w AS (PARTITION BY f.stock_id ORDER BY f.period_end)
),
fin AS (                              -- 최신 FY + 직전 FY(결산일 간격이 약 1년일 때만 인정, v_stock_metrics와 같은 규칙)
    SELECT fy.*, COALESCE(fy.prev_end BETWEEN fy.period_end - 400 AND fy.period_end - 330, false) AS has_prev
    FROM fy
    WHERE fy.rn = 1
),
px AS (                               -- 최신 거래일부터 거꾸로 번호(rn = 1이 t)
    SELECT d.stock_id, d.close, ROW_NUMBER() OVER (PARTITION BY d.stock_id ORDER BY d.trade_date DESC) AS rn
    FROM daily_prices d
),
mom AS (                              -- t−21, t−126, t−252 거래일 종가
    SELECT px.stock_id,
           MAX(px.close) FILTER (WHERE px.rn = 22)  AS c_21,
           MAX(px.close) FILTER (WHERE px.rn = 127) AS c_126,
           MAX(px.close) FILTER (WHERE px.rn = 253) AS c_252
    FROM px
    WHERE px.rn IN (22, 127, 253)
    GROUP BY px.stock_id
),
inp AS (
    SELECT b.stock_id, b.close, b.bps, b.volatility_1y, f.revenue, f.operating_income, f.net_income,
           f.total_equity, f.total_debt, f.has_prev, f.prev_revenue, f.prev_net_income,
           m.c_21, m.c_126, m.c_252,
           -- EPS 환산용 주식수: 상장주식수, 없으면 시가총액 / 종가
           COALESCE(CAST(b.shares_outstanding AS numeric), b.market_cap / NULLIF(b.close, 0)) AS shares,
           b.eps AS eps_provider
    FROM base b
    LEFT JOIN fin f ON f.stock_id = b.stock_id
    LEFT JOIN mom m ON m.stock_id = b.stock_id
),
calc AS (
    SELECT i.*,
           -- KRX는 적자 기업 EPS를 주지 않으므로 FY 순이익 / 주식수로 대체 → 적자는 음수 E/P(하위)
           COALESCE(i.eps_provider, i.net_income / NULLIF(i.shares, 0)) AS eps,
           (i.eps_provider IS NULL AND i.net_income IS NOT NULL AND i.shares > 0) AS eps_derived
    FROM inp i
)
SELECT c.stock_id, v.metric, v.factor, v.raw_value, v.z_fixed, v.note
FROM calc c
CROSS JOIN LATERAL (VALUES
    ('earnings_yield',   'value',    c.eps / NULLIF(c.close, 0), CAST(NULL AS numeric),
        CASE WHEN c.eps_derived THEN 'EPS 미제공 → FY 순이익 / 주식수로 대체' END),
    ('book_yield',       'value',    c.bps / NULLIF(c.close, 0), NULL, NULL),
    ('roe',              'quality',  CASE WHEN c.total_equity > 0 THEN c.net_income / c.total_equity END, NULL, NULL),
    ('operating_margin', 'quality',  c.operating_income / NULLIF(c.revenue, 0), NULL, NULL),
    ('revenue_yoy',      'growth',   CASE WHEN c.has_prev AND c.prev_revenue > 0 THEN c.revenue / c.prev_revenue - 1 END,
        NULL, NULL),
    -- (EPS_t − EPS_{t−1}) / 종가. 두 해 EPS 모두 FY 순이익 / 최신 주식수(주식수 변동은 반영하지 않음)
    ('eps_change_yield', 'growth',   CASE WHEN c.has_prev AND c.shares > 0
                                          THEN (c.net_income - c.prev_net_income) / c.shares / NULLIF(c.close, 0) END,
        NULL, NULL),
    ('debt_ratio',       'safety',   CASE WHEN c.total_equity > 0 THEN c.total_debt / c.total_equity END,
        CASE WHEN c.total_equity <= 0 THEN CAST(-3 AS numeric) END,
        CASE WHEN c.total_equity <= 0 THEN '자본 ≤ 0 → Z = −3 고정' END),
    ('volatility',       'safety',   c.volatility_1y, NULL, NULL),
    ('momentum',         'momentum', CASE WHEN c.c_252 IS NOT NULL THEN c.c_21 / c.c_252 - 1
                                          WHEN c.c_126 IS NOT NULL THEN c.c_21 / c.c_126 - 1 END,
        NULL,
        CASE WHEN c.c_252 IS NULL AND c.c_126 IS NOT NULL THEN '일봉 253개 미만 → 6-1개월 수익률로 대체' END)
) AS v(metric, factor, raw_value, z_fixed, note)
ORDER BY c.stock_id, v.metric
