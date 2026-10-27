-- 소속 테마의 위치(D-020): 같은 as_of·국가·점수 묶음에서 주 테마마다 '중립화 전 팩터 F'의 평균을 내 테마 사이 순위를 매긴다
-- 파라미터: as_of, country, family, w_metrics·w_values(팩터 안 지표 가중치 — 없으면 1)
--   F = 그 팩터 유효 지표 z_raw의 가중 평균, 재무 FY 3개 미만이면 저평가 F × (FY 수 / 3) — score_aggregate.sql f1과 같은 규칙
--   중립화한 z_adj·Fs로 평균 내면 테마 평균을 이미 2/3 뺀 값이라 순위가 어긋난다(라운드 2 R2-3)
--   재표준화(Fs)는 같은 표본에 같은 선형 변환이라 순위가 같아 하지 않는다
--   대상 = 종합 점수가 있는 종목(프리셋과 무관 — 필수 팩터·유효 팩터 수는 프리셋마다 같다), 테마 = 그 팩터 값이 있는 구성원 2개 이상
WITH mw AS (
    SELECT * FROM unnest(CAST(:w_metrics AS text[]), CAST(:w_values AS numeric[])) AS x(metric, w)
),
scored AS (
    SELECT DISTINCT st.stock_id, gm.group_id, g.name AS group_name,
           COALESCE(CAST(st.data_quality->>'fy_history' AS int), 0) AS fy_count
    FROM stock_scores st
    JOIN stocks s   ON s.stock_id = st.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = st.stock_id
    JOIN peer_group_members gm ON gm.stock_id = st.stock_id AND gm.is_primary
    JOIN peer_groups g ON g.group_id = gm.group_id
    WHERE st.as_of = :as_of AND mk.country = :country AND COALESCE(t.family, 'general') = :family
      AND st.composite IS NOT NULL
),
f AS (
    SELECT sc.group_id, sc.group_name, mv.factor,
           SUM(COALESCE(mw.w, 1) * mv.z_raw) / SUM(COALESCE(mw.w, 1))
             * CASE WHEN mv.factor = 'value' AND sc.fy_count < 3 THEN sc.fy_count / 3.0 ELSE 1 END AS score
    FROM scored sc
    JOIN stock_metric_values mv ON mv.stock_id = sc.stock_id AND mv.as_of = :as_of AND mv.z_raw IS NOT NULL
    LEFT JOIN mw ON mw.metric = mv.metric
    GROUP BY sc.stock_id, sc.group_id, sc.group_name, sc.fy_count, mv.factor
),
theme AS (
    SELECT f.group_id, f.group_name, f.factor, AVG(f.score) AS score
    FROM f
    GROUP BY f.group_id, f.group_name, f.factor
    HAVING COUNT(*) >= 2
)
SELECT th.group_id, th.group_name, th.factor, th.score,
       RANK()   OVER (PARTITION BY th.factor ORDER BY th.score DESC) AS position,
       COUNT(*) OVER (PARTITION BY th.factor)                        AS total
FROM theme th
