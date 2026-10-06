-- 최근 30개 DAILY 환율 (스파크라인·전일 대비용)
SELECT (rate_at AT TIME ZONE 'Asia/Seoul')::date AS date, usd_krw
FROM fx_rates
WHERE granularity = 'DAILY'
ORDER BY rate_at DESC
LIMIT 30
