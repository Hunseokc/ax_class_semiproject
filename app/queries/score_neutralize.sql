-- 매력도 2단계-2: 섹터 중립화(축소 추정) → stock_metric_values.z_adj
-- 파라미터: as_of, k (config/scoring.yaml shrinkage_k)
--   z_adj = z − n / (n + k) × (주 그룹 안 z 평균)
--   n = 주 그룹에서 그 지표의 z가 있는 종목 수. 그룹 평균에는 자기 자신도 포함된다
--   주 그룹은 국내·해외 종목이 섞일 수 있고, z는 이미 국가 안에서 표준화된 값이다
--   주 그룹이 없거나 n = 1이면 z_adj = z. z_adj는 다시 자르지 않는다
WITH g AS (
    SELECT mv.stock_id, mv.metric, mv.z_raw, gm.group_id
    FROM stock_metric_values mv
    LEFT JOIN peer_group_members gm ON gm.stock_id = mv.stock_id AND gm.is_primary
    WHERE mv.as_of = :as_of AND mv.z_raw IS NOT NULL
),
s AS (
    SELECT g.*,
           COUNT(*)      OVER (PARTITION BY g.group_id, g.metric) AS n,
           AVG(g.z_raw)  OVER (PARTITION BY g.group_id, g.metric) AS group_mean
    FROM g
)
UPDATE stock_metric_values t
SET z_adj = CASE WHEN s.group_id IS NULL OR s.n = 1 THEN s.z_raw
                 ELSE s.z_raw - CAST(s.n AS numeric) / (s.n + :k) * s.group_mean END
FROM s
WHERE t.as_of = :as_of AND t.stock_id = s.stock_id AND t.metric = s.metric
