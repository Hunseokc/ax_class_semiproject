-- 매력도 3단계: 프리셋별 팩터 점수·종합 점수·0~100 변환 (stock_metric_values의 z_adj 사용)
-- 파라미터: as_of
--   팩터 점수 F = 그 팩터의 유효 지표 z_adj 평균 (지표 1개 이상)
--   종합 = Σ(w × F) / Σ w  (유효 팩터만 — 가중치 재정규화). 유효 팩터 < 3이면 NULL
--   Final = 100 × Φ(Z_c),  Z_c = 종합을 국가·프리셋 안에서 평균·표본표준편차로 다시 표준화한 값
--   Φ(z) = 0.5 × (1 + erf(z / √2))  — PostgreSQL 16 내장 erf 사용. Min-Max는 쓰지 않는다(docs/09 5절)
WITH f AS (
    SELECT mv.stock_id, mv.factor, AVG(mv.z_adj) AS score
    FROM stock_metric_values mv
    WHERE mv.as_of = :as_of AND mv.z_adj IS NOT NULL
    GROUP BY mv.stock_id, mv.factor
),
st AS (                               -- 지표 행이 있는 종목 = 점수 대상
    SELECT mv.stock_id, mk.country, COUNT(DISTINCT f.factor) AS coverage
    FROM (SELECT DISTINCT stock_id FROM stock_metric_values WHERE as_of = :as_of) mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN f     ON f.stock_id = mv.stock_id
    GROUP BY mv.stock_id, mk.country
),
wide AS (
    SELECT st.stock_id, st.country, st.coverage, p.preset_id,
           MAX(f.score) FILTER (WHERE f.factor = 'value')    AS value_score,
           MAX(f.score) FILTER (WHERE f.factor = 'quality')  AS quality_score,
           MAX(f.score) FILTER (WHERE f.factor = 'growth')   AS growth_score,
           MAX(f.score) FILTER (WHERE f.factor = 'safety')   AS safety_score,
           MAX(f.score) FILTER (WHERE f.factor = 'momentum') AS momentum_score,
           SUM(w.weight * f.score) / NULLIF(SUM(w.weight) FILTER (WHERE f.score IS NOT NULL), 0) AS weighted
    FROM st
    CROSS JOIN scoring_presets p
    LEFT JOIN f               ON f.stock_id = st.stock_id
    LEFT JOIN scoring_weights w ON w.preset_id = p.preset_id AND w.factor = f.factor
    GROUP BY st.stock_id, st.country, st.coverage, p.preset_id
),
comp AS (
    SELECT wide.*, CASE WHEN wide.coverage >= 3 THEN wide.weighted END AS composite
    FROM wide
),
zc AS (                               -- 국가·프리셋 안에서 종합 점수를 다시 표준화 (NULL은 통계에서 제외)
    SELECT comp.*,
           AVG(comp.composite)         OVER (PARTITION BY comp.preset_id, comp.country) AS c_mean,
           STDDEV_SAMP(comp.composite) OVER (PARTITION BY comp.preset_id, comp.country) AS c_sd
    FROM comp
)
SELECT zc.stock_id, zc.preset_id, zc.country, zc.coverage AS factor_coverage,
       ROUND(zc.value_score, 4)    AS value_score,
       ROUND(zc.quality_score, 4)  AS quality_score,
       ROUND(zc.growth_score, 4)   AS growth_score,
       ROUND(zc.safety_score, 4)   AS safety_score,
       ROUND(zc.momentum_score, 4) AS momentum_score,
       ROUND(zc.composite, 4)      AS composite,
       CASE WHEN zc.composite IS NOT NULL THEN
         ROUND(CAST(100 * 0.5 * (1 + erf(CAST(CASE WHEN zc.c_sd > 0 THEN (zc.composite - zc.c_mean) / zc.c_sd ELSE 0 END
                                             AS double precision) / sqrt(2::double precision))) AS numeric), 2)
       END AS score
FROM zc
ORDER BY zc.preset_id, zc.stock_id
