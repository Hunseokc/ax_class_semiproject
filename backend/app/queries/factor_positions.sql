-- 같은 as_of·프리셋·국가·점수 묶음(family) 종목의 팩터 점수(재표준화 Fs)와 같은 시장 백분위, 주 테마 (D-003)
--   백분위 = 100 × (n − 순위) / n — 종합 점수(score_aggregate.sql)와 같은 정의. 80 이상 = 그 팩터 상위 20%
--   상세 화면의 레이더·요소 카드(이 종목·주 테마 평균)와 '소속 테마의 위치'(테마 평균 팩터의 순위)에 쓴다
WITH base AS (
    SELECT st.stock_id, g.group_id, g.name AS group_name, v.factor, v.score
    FROM stock_scores st
    JOIN stocks s   ON s.stock_id = st.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = st.stock_id
    LEFT JOIN peer_group_members gm ON gm.stock_id = st.stock_id AND gm.is_primary
    LEFT JOIN peer_groups g ON g.group_id = gm.group_id
    CROSS JOIN LATERAL (VALUES ('value', st.value_score), ('quality', st.quality_score), ('growth', st.growth_score),
                               ('safety', st.safety_score), ('momentum', st.momentum_score)) AS v(factor, score)
    WHERE st.as_of = :as_of AND st.preset_id = :preset_id AND mk.country = :country
      AND COALESCE(t.family, 'general') = :family AND st.composite IS NOT NULL AND v.score IS NOT NULL
)
SELECT b.stock_id, b.group_id, b.group_name, b.factor, b.score,
       ROUND(100.0 * (COUNT(*) OVER w - RANK() OVER (w ORDER BY b.score DESC)) / COUNT(*) OVER w, 2) AS percentile
FROM base b
WINDOW w AS (PARTITION BY b.factor)
