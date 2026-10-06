-- FY 재무 추이 (최근 limit 파라미터 개수의 결산기, 오래된 순) + 영업이익률·ROE
SELECT * FROM (
    SELECT f.period_end, f.period_type, f.revenue, f.operating_income, f.net_income,
           f.total_assets, f.total_equity, f.total_debt, f.data_source, f.accounting_std,
           ROUND(f.operating_income / NULLIF(f.revenue, 0), 6) AS operating_margin,
           CASE WHEN f.total_equity > 0 THEN ROUND(f.net_income / f.total_equity, 6) END AS roe
    FROM financial_statements f
    WHERE f.stock_id = :stock_id AND f.period_type = 'FY'
    ORDER BY f.period_end DESC
    LIMIT :limit
) t ORDER BY period_end
