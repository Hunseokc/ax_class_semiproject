-- 종목 수치 분석: v_stock_metrics 1행 + 선택한 프리셋의 최신 매력도
--   국가 내 순위·백분위는 같은 as_of·프리셋에서 점수가 있는 같은 country 종목끼리 (RANK·PERCENT_RANK)
WITH sc AS (
    SELECT st.*
    FROM stock_scores st
    WHERE st.stock_id = :stock_id AND st.preset_id = :preset_id
    ORDER BY st.as_of DESC
    LIMIT 1
),
ranked AS (
    SELECT st.stock_id,
           RANK()         OVER (ORDER BY st.score DESC) AS rank_position,
           COUNT(*)       OVER ()                       AS rank_total,
           PERCENT_RANK() OVER (ORDER BY st.score)      AS percentile
    FROM stock_scores st
    JOIN stocks s   ON s.stock_id = st.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE st.preset_id = :preset_id AND st.as_of = (SELECT as_of FROM sc) AND st.score IS NOT NULL
      AND mk.country = (SELECT m2.country FROM stocks s2 JOIN markets m2 ON m2.market_id = s2.market_id
                        WHERE s2.stock_id = :stock_id)
)
SELECT vm.*,
       sc.as_of AS score_as_of, sc.score, sc.composite, sc.factor_coverage, sc.data_quality,
       sc.value_score, sc.quality_score, sc.growth_score, sc.safety_score, sc.momentum_score,
       r.rank_position, r.rank_total, ROUND(CAST(r.percentile * 100 AS numeric), 1) AS percentile
FROM v_stock_metrics vm
LEFT JOIN sc ON true
LEFT JOIN ranked r ON r.stock_id = vm.stock_id
WHERE vm.stock_id = :stock_id
