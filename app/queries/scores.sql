-- 매력도 점수 계산 (유니버스 내 상대평가, 같은 country 안에서 PERCENT_RANK)
-- 파라미터: as_of, w_val, w_gro, w_pro, w_mom (가중치), version (weights_version)
-- 팩터 점수 = 하위 지표 PERCENT_RANK 평균 × 100 (계산 가능한 하위 지표만)
-- 최종 점수 = 계산 가능한 팩터만 가중평균(가중치 재정규화). 전부 불가면 NULL
-- 하위 지표 순위는 값이 있는 종목끼리만 매긴다 (PARTITION BY country, 값 IS NULL)
-- 같은 country에서 값이 있는 종목이 2개 미만이면 순위를 매기지 않는다(NULL)
WITH inputs AS (
    SELECT m.stock_id, m.country,
           CASE WHEN m.per > 0 THEN m.per END AS per,          -- 음수·0·NULL PER/PBR 제외
           CASE WHEN m.pbr > 0 THEN m.pbr END AS pbr,
           m.revenue_yoy, m.operating_income_yoy,
           m.operating_margin, m.roe,
           m.return_3m, m.ma120_gap
    FROM v_stock_metrics m
),
ranked AS (
    SELECT i.*,
           -- 낮을수록 좋음 → 내림차순 정렬해 가장 낮은 값이 1
           CASE WHEN COUNT(per) OVER w_country >= 2 AND per IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, per IS NULL ORDER BY per DESC) AS numeric) END AS r_per,
           CASE WHEN COUNT(pbr) OVER w_country >= 2 AND pbr IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, pbr IS NULL ORDER BY pbr DESC) AS numeric) END AS r_pbr,
           -- 높을수록 좋음 → 오름차순 정렬해 가장 높은 값이 1
           CASE WHEN COUNT(revenue_yoy) OVER w_country >= 2 AND revenue_yoy IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, revenue_yoy IS NULL ORDER BY revenue_yoy) AS numeric) END AS r_rev_yoy,
           CASE WHEN COUNT(operating_income_yoy) OVER w_country >= 2 AND operating_income_yoy IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, operating_income_yoy IS NULL ORDER BY operating_income_yoy) AS numeric) END AS r_op_yoy,
           CASE WHEN COUNT(operating_margin) OVER w_country >= 2 AND operating_margin IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, operating_margin IS NULL ORDER BY operating_margin) AS numeric) END AS r_opm,
           CASE WHEN COUNT(roe) OVER w_country >= 2 AND roe IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, roe IS NULL ORDER BY roe) AS numeric) END AS r_roe,
           CASE WHEN COUNT(return_3m) OVER w_country >= 2 AND return_3m IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, return_3m IS NULL ORDER BY return_3m) AS numeric) END AS r_ret3m,
           CASE WHEN COUNT(ma120_gap) OVER w_country >= 2 AND ma120_gap IS NOT NULL
                THEN CAST(PERCENT_RANK() OVER (PARTITION BY country, ma120_gap IS NULL ORDER BY ma120_gap) AS numeric) END AS r_gap
    FROM inputs i
    WINDOW w_country AS (PARTITION BY country)
),
factors AS (
    -- 하위 지표 평균: NULL은 빼고 평균, 둘 다 NULL이면 팩터 NULL
    SELECT r.*,
           (SELECT AVG(x) * 100 FROM (VALUES (r.r_per), (r.r_pbr)) v(x))         AS valuation_score,
           (SELECT AVG(x) * 100 FROM (VALUES (r.r_rev_yoy), (r.r_op_yoy)) v(x))   AS growth_score,
           (SELECT AVG(x) * 100 FROM (VALUES (r.r_opm), (r.r_roe)) v(x))          AS profitability_score,
           (SELECT AVG(x) * 100 FROM (VALUES (r.r_ret3m), (r.r_gap)) v(x))        AS momentum_score
    FROM ranked r
)
SELECT f.stock_id,
       CAST(:as_of AS date) AS as_of,
       ROUND(
         (COALESCE(f.valuation_score * :w_val, 0) + COALESCE(f.growth_score * :w_gro, 0)
          + COALESCE(f.profitability_score * :w_pro, 0) + COALESCE(f.momentum_score * :w_mom, 0))
         / NULLIF(CASE WHEN f.valuation_score     IS NOT NULL THEN :w_val ELSE 0 END
                + CASE WHEN f.growth_score        IS NOT NULL THEN :w_gro ELSE 0 END
                + CASE WHEN f.profitability_score IS NOT NULL THEN :w_pro ELSE 0 END
                + CASE WHEN f.momentum_score      IS NOT NULL THEN :w_mom ELSE 0 END, 0), 2) AS score,
       ROUND(f.valuation_score, 2)     AS valuation_score,
       ROUND(f.growth_score, 2)        AS growth_score,
       ROUND(f.profitability_score, 2) AS profitability_score,
       ROUND(f.momentum_score, 2)      AS momentum_score,
       jsonb_build_object(
         'unavailable', jsonb_strip_nulls(jsonb_build_object(
             'valuation',     CASE WHEN f.valuation_score IS NULL THEN 'PER·PBR 모두 없음(적자·미제공) 또는 비교 표본 부족' END,
             'growth',        CASE WHEN f.growth_score IS NULL THEN '매출·영업이익 YoY 계산 불가(직전 FY 없음·분모 0) 또는 비교 표본 부족' END,
             'profitability', CASE WHEN f.profitability_score IS NULL THEN '영업이익률·ROE 계산 불가(재무 없음·자본 ≤ 0) 또는 비교 표본 부족' END,
             'momentum',      CASE WHEN f.momentum_score IS NULL THEN '3개월 수익률·120일선 괴리율 계산 불가(시세 기간 부족)' END)),
         'missing_inputs', to_jsonb(array_remove(ARRAY[
             CASE WHEN f.r_per IS NULL THEN 'per' END, CASE WHEN f.r_pbr IS NULL THEN 'pbr' END,
             CASE WHEN f.r_rev_yoy IS NULL THEN 'revenue_yoy' END, CASE WHEN f.r_op_yoy IS NULL THEN 'operating_income_yoy' END,
             CASE WHEN f.r_opm IS NULL THEN 'operating_margin' END, CASE WHEN f.r_roe IS NULL THEN 'roe' END,
             CASE WHEN f.r_ret3m IS NULL THEN 'return_3m' END, CASE WHEN f.r_gap IS NULL THEN 'ma120_gap' END], NULL)),
         'partition', f.country
       ) AS data_quality,
       CAST(:version AS text) AS weights_version
FROM factors f
ORDER BY f.stock_id
