-- 지표별 TOP N 랭킹 (노출 종목 기준, ASSUMPTIONS A-115)
-- 지표값은 v_stock_metrics 재사용. 지표 선택은 CASE로(컬럼명을 문자열로 끼워 넣지 않음)
-- RANK(): 같은 값이면 같은 순위, 다음 순위는 건너뜀(1, 2, 2, 4). NULL 지표는 순위에서 제외
-- 주의: text()는 주석 안의 콜론+이름도 바인드 파라미터로 읽으므로 주석에 쓰지 않는다
WITH base AS (
    SELECT v.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency, v.as_of,
           CASE CAST(:metric AS text)
                WHEN 'return_1m'      THEN v.return_1m
                WHEN 'return_3m'      THEN v.return_3m
                WHEN 'return_1y'      THEN v.return_1y
                WHEN 'volume'         THEN v.volume::numeric
                WHEN 'market_cap_krw' THEN v.market_cap_krw
           END AS value
    FROM v_stock_metrics v
    JOIN stocks s  ON s.stock_id = v.stock_id
    JOIN markets m ON m.market_id = s.market_id
    WHERE s.coverage = 'featured' AND s.is_active
      AND (CAST(:country AS text) IS NULL OR m.country = CAST(:country AS text))
),
ranked AS (
    SELECT b.*,
           RANK() OVER (ORDER BY CASE WHEN CAST(:order_dir AS text) = 'asc'  THEN b.value END ASC,
                                 CASE WHEN CAST(:order_dir AS text) = 'desc' THEN b.value END DESC) AS rank,
           COUNT(*) OVER () AS total            -- 지표값이 있는 종목 수
    FROM base b
    WHERE b.value IS NOT NULL
)
SELECT r.rank, r.stock_id, r.market, r.country, r.currency, r.ticker, r.name, r.value, r.as_of, r.total
FROM ranked r
ORDER BY r.rank, r.ticker
LIMIT :limit
