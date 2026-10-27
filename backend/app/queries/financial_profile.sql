-- 금융 묶음 하위 업종 비교(D-028, 개발산출물/09 12절): 같은 국가·같은 주 테마(은행·카드 / 보험 / 증권·자산운용)
-- 비교 표본 종목의 P/B·ROE(3년 평균)·P/E. 종합 매력도 대신 'ROE 대비 P/B' 위치를 참고 정보로 보인다
-- 파라미터: country, stock_id(상장 목록 종목을 열었으면 그 종목도 넣는다 — 아니면 NULL)
--   P/B = 종가 / BPS(BPS > 0), P/E = 종가 / EPS(EPS > 0) — 적자·자본 음수면 비운다
--   ROE = 지배주주 순이익 / 지배 자본(자본 > 0)의 최근 3개 FY 평균(최신 FY 결산일부터 1,000일 안)
WITH m AS (
    SELECT s.stock_id, s.ticker, s.name, mk.code AS market, t.group_id, t.theme, vm.close, vm.bps, vm.eps
    FROM stocks s
    JOIN markets mk         ON mk.market_id = s.market_id
    JOIN v_stock_theme t    ON t.stock_id = s.stock_id AND t.family = 'financial'
    JOIN v_stock_metrics vm ON vm.stock_id = s.stock_id
    WHERE mk.country = :country AND s.is_active
      AND (s.coverage <> 'listed' OR s.stock_id = CAST(:stock_id AS int))
),
fy AS (
    SELECT f.stock_id, f.period_end, f.net_income, f.total_equity,
           MAX(f.period_end) OVER (PARTITION BY f.stock_id) AS last_end
    FROM financial_statements f
    WHERE f.period_type = 'FY' AND f.stock_id IN (SELECT m.stock_id FROM m)
),
roe AS (
    SELECT fy.stock_id, AVG(fy.net_income / fy.total_equity) AS roe3, COUNT(*) AS years
    FROM fy
    WHERE fy.period_end > fy.last_end - 1000 AND fy.total_equity > 0 AND fy.net_income IS NOT NULL
    GROUP BY fy.stock_id
)
SELECT m.stock_id, m.ticker, m.name, m.market, m.group_id, m.theme,
       CASE WHEN m.bps > 0 THEN m.close / m.bps END AS pb,
       CASE WHEN m.eps > 0 THEN m.close / m.eps END AS pe,
       r.roe3, COALESCE(r.years, 0) AS roe_years
FROM m
LEFT JOIN roe r ON r.stock_id = m.stock_id
ORDER BY m.theme, m.name
