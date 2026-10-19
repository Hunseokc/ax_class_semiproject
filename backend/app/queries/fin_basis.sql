-- 매력도 비교 표본의 최신 FY 결산 연도별 종목 수 — 실적 시즌에 새 연도·지난 연도 재무가 섞인 정도 (docs/09)
-- 파라미터: country (KR·US), as_of (stock_metric_values.as_of = 점수 기준일)
-- 표본: 그 기준일에 지표가 계산된 그 국가 종목(노출 + 비교군, listed 제외). FY는 as_of 이하 결산일 중 최신
-- FY가 하나도 없는 종목은 세지 않는다
WITH u AS (
    SELECT DISTINCT mv.stock_id
    FROM stock_metric_values mv
    JOIN stocks s   ON s.stock_id = mv.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE mv.as_of = :as_of AND mk.country = :country AND s.coverage <> 'listed'
),
fy AS (
    SELECT u.stock_id, MAX(f.period_end) AS period_end
    FROM u
    JOIN financial_statements f ON f.stock_id = u.stock_id AND f.period_type = 'FY' AND f.period_end <= :as_of
    GROUP BY u.stock_id
)
SELECT CAST(EXTRACT(YEAR FROM fy.period_end) AS int) AS fiscal_year, COUNT(*) AS stocks
FROM fy
GROUP BY 1
ORDER BY 1 DESC
