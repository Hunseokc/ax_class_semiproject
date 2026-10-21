-- 대시보드 '매력도 순위' TOP N: 이미 계산·저장된 매력도(stock_scores)의 종목별 최신 점수를 읽기만 한다
-- 대상 = 노출 종목 + 매력도 비교군 + 사용자의 관심종목 (거래량 급증과 같은 집합). 점수가 없는 종목은 제외
-- 주의: text()는 주석 안의 콜론+이름도 바인드 파라미터로 읽으므로 주석에 쓰지 않는다
WITH targets AS (
    SELECT s.stock_id
    FROM stocks s
    JOIN markets m ON m.market_id = s.market_id
    WHERE s.is_active AND m.country = CAST(:country AS text)
      AND (s.coverage IN ('featured', 'benchmark')
           OR EXISTS (SELECT 1 FROM watchlist_items w WHERE w.stock_id = s.stock_id AND w.user_id = :user_id))
),
latest AS (
    SELECT t.stock_id, sc.score, sc.as_of
    FROM targets t
    CROSS JOIN LATERAL (SELECT st.score, st.as_of FROM stock_scores st
                        WHERE st.stock_id = t.stock_id
                          AND st.preset_id = (SELECT preset_id FROM scoring_presets WHERE code = :preset)
                        ORDER BY st.as_of DESC LIMIT 1) sc
    WHERE sc.score IS NOT NULL
)
SELECT RANK() OVER (ORDER BY l.score DESC) AS rank,
       s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency,
       l.score AS value, l.as_of,
       (w.stock_id IS NOT NULL) AS is_watched
FROM latest l
JOIN stocks s  ON s.stock_id = l.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN watchlist_items w ON w.stock_id = s.stock_id AND w.user_id = :user_id
ORDER BY l.score DESC, s.stock_id
LIMIT :limit
