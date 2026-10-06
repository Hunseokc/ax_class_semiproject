-- HAVING으로 제외된 시장 (표본 부족)
SELECT mk.code AS market, COUNT(*) AS stocks
FROM stocks s JOIN markets mk ON mk.market_id = s.market_id
WHERE s.is_active
GROUP BY mk.code
HAVING COUNT(*) < :min_samples
ORDER BY mk.code
