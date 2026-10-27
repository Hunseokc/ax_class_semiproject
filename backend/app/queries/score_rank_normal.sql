-- 매력도 2단계-1(모델 v2.2): 지표별 국가(country)·점수 묶음(family) 안 순위 → 순위 정규 점수(RN)의 확률 p = (r − 0.5) / n
-- 파라미터: as_of
--   family = 주 테마의 scoring(v_stock_theme): financial(금융끼리) / general(그 밖, 주 테마가 없어도 general)
--     금융은 PER·PBR이 구조적으로 낮아 일반 기업과 섞으면 저평가가 늘 상위가 된다 (개발산출물/09 3절)
--   r = 원값 오름차순 순위, 같은 값은 평균 순위(RANK + (같은 값 수 − 1) / 2), n = 그 지표 값이 있는 종목 수
--   z = Φ⁻¹(p)와 방향(−는 부호 반대)·감점 전용 지표의 0 이하 자르기는 scoring.normalize가 한다(PostgreSQL에 역정규 함수가 없다, D-019)
--   z_raw가 이미 채워진 행은 통계에서 빼고 건드리지 않는다
WITH v AS (
    SELECT mv.stock_id, mv.metric, mv.raw_value, mk.country, COALESCE(t.family, 'general') AS family
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_theme t ON t.stock_id = mv.stock_id
    WHERE mv.as_of = :as_of AND mv.raw_value IS NOT NULL AND mv.z_raw IS NULL
)
SELECT v.stock_id, v.metric,
       (RANK() OVER w + (COUNT(*) OVER (PARTITION BY v.country, v.family, v.metric, v.raw_value) - 1) / 2.0 - 0.5)
           / COUNT(*) OVER (PARTITION BY v.country, v.family, v.metric) AS p
FROM v
WINDOW w AS (PARTITION BY v.country, v.family, v.metric ORDER BY v.raw_value)
