-- 경쟁 그룹별 평균·최고·최저 지표 (그룹당 1행)
WITH m AS (
    SELECT g.group_id, g.name AS group_name, vm.stock_id,
           CASE WHEN vm.per > 0 THEN vm.per END AS per,
           CASE WHEN vm.pbr > 0 THEN vm.pbr END AS pbr,
           vm.roe, vm.operating_margin, vm.revenue_yoy, vm.return_1y, vm.market_cap_krw, mk.country
    FROM peer_groups g
    JOIN peer_group_members gm ON gm.group_id = g.group_id
    JOIN v_stock_metrics vm    ON vm.stock_id = gm.stock_id
    JOIN stocks s              ON s.stock_id = gm.stock_id AND s.coverage = 'featured'   -- 노출 종목 기준
    JOIN markets mk            ON mk.market_id = s.market_id
)
SELECT group_id, group_name,
       COUNT(*)                                  AS members,
       COUNT(*) FILTER (WHERE country = 'KR')    AS kr_members,
       COUNT(*) FILTER (WHERE country = 'US')    AS us_members,
       ROUND(AVG(per), 2) AS avg_per, ROUND(MIN(per), 2) AS min_per, ROUND(MAX(per), 2) AS max_per,
       ROUND(AVG(pbr), 2) AS avg_pbr,
       ROUND(AVG(roe), 4) AS avg_roe, ROUND(MIN(roe), 4) AS min_roe, ROUND(MAX(roe), 4) AS max_roe,
       ROUND(AVG(operating_margin), 4) AS avg_operating_margin,
       ROUND(AVG(revenue_yoy), 4)      AS avg_revenue_yoy,
       ROUND(AVG(return_1y), 4) AS avg_return_1y, ROUND(MIN(return_1y), 4) AS min_return_1y, ROUND(MAX(return_1y), 4) AS max_return_1y,
       ROUND(SUM(market_cap_krw), 0)   AS total_market_cap_krw
FROM m
GROUP BY group_id, group_name
ORDER BY avg_roe DESC NULLS LAST
