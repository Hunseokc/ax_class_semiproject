-- HAVING으로 제외된 시장 (표본 부족)
SELECT mk.code AS market, COUNT(*) AS stocks
-- TODO(연결): D의 stocks.coverage(003_benchmark)가 생기면 WHERE에 s.coverage = 'featured'(통계는 노출 종목 기준)를 복원한다. 지금은 활성 종목 전체.
FROM stocks s JOIN markets mk ON mk.market_id = s.market_id
WHERE s.is_active
GROUP BY mk.code
HAVING COUNT(*) < :min_samples
ORDER BY mk.code
