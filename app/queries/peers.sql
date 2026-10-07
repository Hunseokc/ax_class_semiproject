-- 경쟁 그룹 비교: 대상 종목이 속한 모든 그룹의 구성원 지표 + 그룹 내 순위(RANK)·그룹 평균(AVG OVER)
-- 순위는 값이 있는 구성원끼리만 매긴다 (PARTITION BY 그룹, 값 IS NULL). PER·PBR은 낮을수록 1위(양수만)
WITH target_groups AS (
    SELECT gm.group_id
    FROM peer_group_members gm
    WHERE gm.stock_id = :stock_id
),
members AS (
    SELECT g.group_id, g.name AS group_name, gm.stock_id,
           COUNT(*) OVER (PARTITION BY g.group_id) AS group_size
    FROM peer_groups g
    JOIN peer_group_members gm ON gm.group_id = g.group_id
    WHERE g.group_id IN (SELECT group_id FROM target_groups)
),
base AS (
    SELECT mb.group_id, mb.group_name, mb.group_size, s.stock_id, s.ticker, s.name,
           mk.code AS market, mk.country, mk.currency, vm.accounting_std,
           vm.return_1m, vm.return_3m, vm.return_1y,
           CASE WHEN vm.per > 0 THEN vm.per END AS per,
           CASE WHEN vm.pbr > 0 THEN vm.pbr END AS pbr,
           vm.roe, vm.operating_margin, vm.revenue_yoy, vm.market_cap_krw,
           sc.score,
           (s.stock_id = :stock_id) AS is_target
    FROM members mb
    JOIN stocks s   ON s.stock_id = mb.stock_id
    JOIN markets mk ON mk.market_id = s.market_id
    LEFT JOIN v_stock_metrics vm ON vm.stock_id = s.stock_id
    LEFT JOIN LATERAL (SELECT st.score FROM stock_scores st WHERE st.stock_id = s.stock_id
                         AND st.preset_id = (SELECT preset_id FROM scoring_presets WHERE code = :preset)
                       ORDER BY st.as_of DESC LIMIT 1) sc ON true
)
SELECT b.*,
       CASE WHEN b.return_1m IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.return_1m IS NULL ORDER BY b.return_1m DESC) END AS return_1m_rank,
       CASE WHEN b.return_3m IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.return_3m IS NULL ORDER BY b.return_3m DESC) END AS return_3m_rank,
       CASE WHEN b.return_1y IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.return_1y IS NULL ORDER BY b.return_1y DESC) END AS return_1y_rank,
       CASE WHEN b.per IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.per IS NULL ORDER BY b.per ASC) END AS per_rank,
       CASE WHEN b.pbr IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.pbr IS NULL ORDER BY b.pbr ASC) END AS pbr_rank,
       CASE WHEN b.roe IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.roe IS NULL ORDER BY b.roe DESC) END AS roe_rank,
       CASE WHEN b.operating_margin IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.operating_margin IS NULL ORDER BY b.operating_margin DESC) END AS operating_margin_rank,
       CASE WHEN b.revenue_yoy IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.revenue_yoy IS NULL ORDER BY b.revenue_yoy DESC) END AS revenue_yoy_rank,
       CASE WHEN b.market_cap_krw IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.market_cap_krw IS NULL ORDER BY b.market_cap_krw DESC) END AS market_cap_krw_rank,
       CASE WHEN b.score IS NOT NULL THEN RANK() OVER (PARTITION BY b.group_id, b.score IS NULL ORDER BY b.score DESC) END AS score_rank,
       -- 그룹 평균 (AVG는 NULL을 제외하고 계산)
       ROUND(AVG(b.return_1m) OVER g, 6)        AS return_1m_avg,
       ROUND(AVG(b.return_3m) OVER g, 6)        AS return_3m_avg,
       ROUND(AVG(b.return_1y) OVER g, 6)        AS return_1y_avg,
       ROUND(AVG(b.per) OVER g, 4)              AS per_avg,
       ROUND(AVG(b.pbr) OVER g, 4)              AS pbr_avg,
       ROUND(AVG(b.roe) OVER g, 6)              AS roe_avg,
       ROUND(AVG(b.operating_margin) OVER g, 6) AS operating_margin_avg,
       ROUND(AVG(b.revenue_yoy) OVER g, 6)      AS revenue_yoy_avg,
       ROUND(AVG(b.market_cap_krw) OVER g, 0)   AS market_cap_krw_avg,
       ROUND(AVG(b.score) OVER g, 2)            AS score_avg
FROM base b
WINDOW g AS (PARTITION BY b.group_id)
ORDER BY b.group_name, b.market_cap_krw DESC NULLS LAST, b.stock_id
