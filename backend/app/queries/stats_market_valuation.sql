-- 시장별 평균 PER·PBR·ROE (양수 PER·PBR만), 시총 합계(원화). 표본 3개 이상인 시장만(HAVING)
SELECT mk.code AS market, mk.country, mk.currency,
       COUNT(*)                                                AS stocks,
       COUNT(vm.per) FILTER (WHERE vm.per > 0)                 AS per_samples,
       ROUND(AVG(vm.per) FILTER (WHERE vm.per > 0), 2)         AS avg_per,
       ROUND(MIN(vm.per) FILTER (WHERE vm.per > 0), 2)         AS min_per,
       ROUND(MAX(vm.per) FILTER (WHERE vm.per > 0), 2)         AS max_per,
       ROUND(AVG(vm.pbr) FILTER (WHERE vm.pbr > 0), 2)         AS avg_pbr,
       ROUND(AVG(vm.roe), 4)                                   AS avg_roe,
       ROUND(SUM(vm.market_cap_krw), 0)                        AS total_market_cap_krw
FROM v_stock_metrics vm
JOIN stocks s   ON s.stock_id = vm.stock_id
JOIN markets mk ON mk.market_id = s.market_id
WHERE s.is_active AND s.coverage = 'featured'      -- 통계는 노출 종목 기준
GROUP BY mk.code, mk.country, mk.currency
HAVING COUNT(*) >= :min_samples
ORDER BY total_market_cap_krw DESC NULLS LAST
