-- 최근 공시 N건
SELECT d.rcept_no, d.title, d.report_type, d.filed_at, d.url, d.data_source
FROM disclosures d
WHERE d.stock_id = :stock_id
ORDER BY d.filed_at DESC, d.rcept_no DESC
LIMIT :limit
