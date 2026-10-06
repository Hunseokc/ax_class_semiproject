-- 종목 수치 분석: v_stock_metrics 1행 + 최신 매력도(팩터별)·data_quality
SELECT vm.*,
       sc.as_of AS score_as_of, sc.score, sc.valuation_score, sc.growth_score,
       sc.profitability_score, sc.momentum_score, sc.data_quality, sc.weights_version
FROM v_stock_metrics vm
LEFT JOIN LATERAL (SELECT * FROM stock_scores st WHERE st.stock_id = vm.stock_id
                   ORDER BY st.as_of DESC LIMIT 1) sc ON true
WHERE vm.stock_id = :stock_id
