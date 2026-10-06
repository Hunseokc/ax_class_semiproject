-- 경쟁 그룹 기준일=100 가격 추이: 구간 첫 거래일 종가를 100으로 환산
-- 구간 끝 = 그룹 구성원 중 가장 최근 거래일, 시작 = 끝 − months 파라미터 개월
WITH members AS (
    SELECT gm.stock_id FROM peer_group_members gm WHERE gm.group_id = :group_id
),
bounds AS (
    SELECT MAX(d.trade_date) AS end_date
    FROM daily_prices d JOIN members m ON m.stock_id = d.stock_id
),
px AS (
    SELECT d.stock_id, d.trade_date, d.close,
           FIRST_VALUE(d.close) OVER (PARTITION BY d.stock_id ORDER BY d.trade_date) AS base_close
    FROM daily_prices d
    JOIN members m ON m.stock_id = d.stock_id
    CROSS JOIN bounds b
    WHERE d.trade_date > b.end_date - make_interval(months => :months)
)
SELECT px.stock_id, s.ticker, s.name, mk.code AS market, px.trade_date,
       ROUND(px.close / NULLIF(px.base_close, 0) * 100, 4) AS indexed
FROM px
JOIN stocks s   ON s.stock_id = px.stock_id
JOIN markets mk ON mk.market_id = s.market_id
ORDER BY px.trade_date, px.stock_id
