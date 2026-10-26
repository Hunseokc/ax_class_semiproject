-- 매력도 2단계-2: 섹터 중립화(축소 추정) → stock_metric_values.z_adj
-- 파라미터: as_of, k (config/scoring.yaml shrinkage_k)
--   z_adj = clamp(z − n / (n + k) × (같은 국가·같은 주 테마 안 z 평균), −3, 3)
--   주 테마 = peer_group_members.is_primary (config/universe.yaml themes — 업종 코드·직접 지정으로 정한다)
--   n = 같은 국가의 주 테마 구성원 중 그 지표의 z가 있는 종목 수. 그룹 평균에는 자기 자신도 포함된다
--   z는 국가 안에서 표준화한 값이라, 다른 국가 구성원의 z와 섞어 평균 내지 않는다
--   주 테마가 없거나 n = 1이면 z_adj = z
--   중립화 뒤에도 [−3, 3]으로 자른다 — 그룹 평균이 크게 음수인 그룹(적자 종목이 섞인 그룹)에서 3을 넘는 값이 나오지 않게
--   안정성(safety) 지표는 중립화하지 않는다(z_adj = z) — 업종 특성으로 출렁이는 것도 그대로 반영 (개발산출물/09 4절)
WITH g AS (
    SELECT mv.stock_id, mv.metric, mv.factor, mv.z_raw, gm.group_id, mk.country
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN peer_group_members gm ON gm.stock_id = mv.stock_id AND gm.is_primary
    WHERE mv.as_of = :as_of AND mv.z_raw IS NOT NULL
),
s AS (
    SELECT g.*,
           COUNT(*)      OVER (PARTITION BY g.group_id, g.country, g.metric) AS n,
           AVG(g.z_raw)  OVER (PARTITION BY g.group_id, g.country, g.metric) AS group_mean
    FROM g
)
UPDATE stock_metric_values t
SET z_adj = CASE WHEN s.factor = 'safety' OR s.group_id IS NULL OR s.n = 1 THEN s.z_raw
                 ELSE LEAST(3, GREATEST(-3, s.z_raw - CAST(s.n AS numeric) / (s.n + :k) * s.group_mean)) END
FROM s
WHERE t.as_of = :as_of AND t.stock_id = s.stock_id AND t.metric = s.metric
