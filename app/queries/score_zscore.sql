-- 매력도 2단계-1: 지표별 국가(country) 내 로버스트 Z → stock_metric_values.z_raw
-- 파라미터: as_of, negatives(방향이 −인 지표 목록)
--   Z = (x − 중앙값) / (1.4826 × MAD),  MAD = median(|x − 중앙값|)
--   유효 표본 < 5 또는 MAD = 0 → 평균·표본표준편차 Z, 표준편차도 0(또는 표본 1개)이면 Z = 0
--   방향 −는 부호를 뒤집고, 모든 Z를 [−3, 3]으로 자른다
--   z_raw가 이미 채워진 행(자본 ≤ 0 부채비율 = −3 고정)은 통계에서 빼고 건드리지 않는다
WITH v AS (
    SELECT mv.stock_id, mv.metric, mv.raw_value, mk.country
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE mv.as_of = :as_of AND mv.raw_value IS NOT NULL AND mv.z_raw IS NULL
),
med AS (                              -- 국가·지표별 중앙값과 평균·표준편차
    SELECT v.country, v.metric, COUNT(*) AS n,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY v.raw_value) AS m,
           AVG(v.raw_value)         AS mean,
           STDDEV_SAMP(v.raw_value) AS sd
    FROM v
    GROUP BY v.country, v.metric
),
mad AS (                              -- MAD = 중앙값으로부터의 절대 편차의 중앙값
    SELECT v.country, v.metric,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(v.raw_value - med.m)) AS mad
    FROM v
    JOIN med ON med.country = v.country AND med.metric = v.metric
    GROUP BY v.country, v.metric
),
z AS (
    SELECT v.stock_id, v.metric,
           CASE WHEN med.n >= 5 AND mad.mad > 0 THEN (v.raw_value - med.m) / (1.4826 * mad.mad)
                WHEN med.sd > 0                 THEN CAST((v.raw_value - med.mean) / med.sd AS double precision)
                ELSE 0 END AS z
    FROM v
    JOIN med ON med.country = v.country AND med.metric = v.metric
    JOIN mad ON mad.country = v.country AND mad.metric = v.metric
)
UPDATE stock_metric_values t
SET z_raw = LEAST(3, GREATEST(-3, CASE WHEN t.metric = ANY(CAST(:negatives AS text[])) THEN -z.z ELSE z.z END))
FROM z
WHERE t.as_of = :as_of AND t.stock_id = z.stock_id AND t.metric = z.metric
