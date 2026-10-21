-- 대시보드 '거래량 급증' TOP N: 배수 = 당일 거래량 / 직전 20거래일 평균 거래량(당일 제외)
-- 대상 = 노출 종목 + 매력도 비교군(섹터별 표본) + 사용자의 관심종목 — 전 종목 스캔을 새로 하지 않는다
-- 직전 20거래일이 모두 있어야 계산(부족하면 제외). 당일 거래량 0, 평균 0은 제외
-- 주의: text()는 주석 안의 콜론+이름도 바인드 파라미터로 읽으므로 주석에 쓰지 않는다
WITH targets AS (
    SELECT s.stock_id
    FROM stocks s
    JOIN markets m ON m.market_id = s.market_id
    WHERE s.is_active AND m.country = CAST(:country AS text)
      AND (s.coverage IN ('featured', 'benchmark')
           OR EXISTS (SELECT 1 FROM watchlist_items w WHERE w.stock_id = s.stock_id AND w.user_id = :user_id))
),
recent AS (                           -- 종목별 최근 21거래일 (rn=1이 당일)
    SELECT t.stock_id, r.trade_date, r.volume, r.rn
    FROM targets t
    CROSS JOIN LATERAL (
        SELECT d.trade_date, d.volume, ROW_NUMBER() OVER (ORDER BY d.trade_date DESC) AS rn
        FROM (SELECT trade_date, volume FROM daily_prices
              WHERE stock_id = t.stock_id ORDER BY trade_date DESC LIMIT 21) d
    ) r
),
agg AS (
    SELECT stock_id,
           MAX(trade_date) FILTER (WHERE rn = 1)        AS as_of,
           MAX(volume)     FILTER (WHERE rn = 1)        AS volume,
           COUNT(volume)   FILTER (WHERE rn BETWEEN 2 AND 21) AS base_days,
           AVG(volume)     FILTER (WHERE rn BETWEEN 2 AND 21) AS avg_volume_20d
    FROM recent
    GROUP BY stock_id
),
surge AS (
    SELECT a.*, ROUND(a.volume / a.avg_volume_20d, 4) AS value
    FROM agg a
    WHERE a.base_days = 20 AND a.volume > 0 AND a.avg_volume_20d > 0
)
SELECT RANK() OVER (ORDER BY g.value DESC) AS rank,
       s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency,
       g.value, g.volume, ROUND(g.avg_volume_20d, 0) AS avg_volume_20d, g.as_of,
       (w.stock_id IS NOT NULL) AS is_watched
FROM surge g
JOIN stocks s  ON s.stock_id = g.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN watchlist_items w ON w.stock_id = s.stock_id AND w.user_id = :user_id
ORDER BY g.value DESC, s.stock_id
LIMIT :limit
