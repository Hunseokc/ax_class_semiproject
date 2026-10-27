-- 매력도 3단계(모델 v2): 프리셋별 팩터 점수·종합 점수·같은 시장 백분위 (stock_metric_values의 z_adj 사용)
-- 파라미터: as_of, w_metrics·w_values(팩터 안 지표 가중치 — 없으면 1), h_stocks·h_counts(종목별 이어지는 FY 수),
--           required(필수 팩터), min_factors(유효 팩터 최소 수)
--   팩터 F = 그 팩터 유효 지표 z_adj의 가중 평균 (안정성 = 변동성 2 · 부채/자산 1)
--   재무 FY가 3개 미만이면 저평가 F × (FY 수 / 3) — 이력이 짧아 보수 규칙(3년 평균·함정 신호)을 못 쓴 만큼 중립 쪽으로(D-010)
--   국가·점수 묶음(family) 안에서 팩터마다 F를 평균 0·표본표준편차 1로 다시 표준화(Fs)
--   종합 = Σ(w × Fs), 빠진 팩터는 0(중립). 필수 팩터(저평가·수익성)가 없거나 유효 팩터 < min_factors면 NULL
--   점수 = 같은 국가·묶음·프리셋 안 백분위 100 × (n − 순위) / n — "상위 p%"(= 100 × 순위 / n)와 정확히 맞물린다(D-003).
--     80 이상 = 상위 20%. 표본이 1개면 50
--   family = 주 테마의 scoring(financial 금융끼리 / general) — score_rank_normal.sql과 같은 묶음
--   금융 묶음은 팩터 점수만 남기고 종합·백분위를 내지 않는다(D-028 — 은행·보험·증권의 회계 구조가 달라 한 줄 순위를 만들지 않음,
--     화면은 같은 하위 업종 안 P/B·ROE 비교 — services/financial_profile.py)
WITH mw AS (
    SELECT * FROM unnest(CAST(:w_metrics AS text[]), CAST(:w_values AS numeric[])) AS x(metric, w)
),
hist AS (
    SELECT * FROM unnest(CAST(:h_stocks AS int[]), CAST(:h_counts AS int[])) AS x(stock_id, fy_count)
),
f0 AS (
    SELECT mv.stock_id, mv.factor, SUM(COALESCE(mw.w, 1) * mv.z_adj) / SUM(COALESCE(mw.w, 1)) AS score
    FROM stock_metric_values mv
    LEFT JOIN mw ON mw.metric = mv.metric
    WHERE mv.as_of = :as_of AND mv.z_adj IS NOT NULL
    GROUP BY mv.stock_id, mv.factor
),
st AS (                               -- 지표 행이 있는 종목 = 점수 대상
    SELECT mv.stock_id, mk.country, COALESCE(t.family, 'general') AS family
    FROM (SELECT DISTINCT stock_id FROM stock_metric_values WHERE as_of = :as_of) mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = mv.stock_id
),
f1 AS (
    SELECT f0.stock_id, f0.factor, st.country, st.family,
           CASE WHEN f0.factor = 'value' AND COALESCE(h.fy_count, 0) < 3
                THEN f0.score * COALESCE(h.fy_count, 0) / 3.0 ELSE f0.score END AS score
    FROM f0
    JOIN st ON st.stock_id = f0.stock_id
    LEFT JOIN hist h ON h.stock_id = f0.stock_id
),
fz AS (                               -- 국가·묶음 안 팩터 재표준화
    SELECT f1.stock_id, f1.factor,
           CASE WHEN STDDEV_SAMP(f1.score) OVER w > 0
                THEN (f1.score - AVG(f1.score) OVER w) / STDDEV_SAMP(f1.score) OVER w ELSE 0 END AS score
    FROM f1
    WINDOW w AS (PARTITION BY f1.country, f1.family, f1.factor)
),
wide AS (
    SELECT st.stock_id, st.country, st.family, p.preset_id, COUNT(fz.factor) AS coverage,
           MAX(fz.score) FILTER (WHERE fz.factor = 'value')    AS value_score,
           MAX(fz.score) FILTER (WHERE fz.factor = 'quality')  AS quality_score,
           MAX(fz.score) FILTER (WHERE fz.factor = 'growth')   AS growth_score,
           MAX(fz.score) FILTER (WHERE fz.factor = 'safety')   AS safety_score,
           MAX(fz.score) FILTER (WHERE fz.factor = 'momentum') AS momentum_score,
           COALESCE(SUM(w.weight * fz.score), 0) AS weighted,
           COUNT(*) FILTER (WHERE fz.factor = ANY(CAST(:required AS text[])))
               = cardinality(CAST(:required AS text[])) AS has_required
    FROM st
    CROSS JOIN scoring_presets p
    LEFT JOIN fz              ON fz.stock_id = st.stock_id
    LEFT JOIN scoring_weights w ON w.preset_id = p.preset_id AND w.factor = fz.factor
    GROUP BY st.stock_id, st.country, st.family, p.preset_id
),
comp AS (
    SELECT wide.*, CASE WHEN wide.family <> 'financial' AND wide.has_required AND wide.coverage >= :min_factors
                        THEN wide.weighted END AS composite
    FROM wide
),
ranked AS (                           -- 국가·묶음·프리셋 안 순위 (NULL은 제외)
    SELECT comp.*,
           RANK()   OVER (PARTITION BY comp.preset_id, comp.country, comp.family ORDER BY comp.composite DESC) AS pos,
           COUNT(*) OVER (PARTITION BY comp.preset_id, comp.country, comp.family)                            AS n
    FROM comp
    WHERE comp.composite IS NOT NULL
)
SELECT c.stock_id, c.preset_id, c.country, c.family, CAST(c.coverage AS int) AS factor_coverage,
       ROUND(c.value_score, 4)    AS value_score,
       ROUND(c.quality_score, 4)  AS quality_score,
       ROUND(c.growth_score, 4)   AS growth_score,
       ROUND(c.safety_score, 4)   AS safety_score,
       ROUND(c.momentum_score, 4) AS momentum_score,
       ROUND(c.composite, 4)      AS composite,
       CASE WHEN r.n = 1 THEN 50 WHEN r.n > 1 THEN ROUND(100.0 * (r.n - r.pos) / r.n, 2) END AS score,
       c.has_required
FROM comp c
LEFT JOIN ranked r ON r.stock_id = c.stock_id AND r.preset_id = c.preset_id
ORDER BY c.preset_id, c.stock_id
