-- 최근 1년 DAILY 환율 (스파크라인·전일 대비·52주 범위용), 최신순
-- full_year = 가장 최근 DAILY 1년 전 이전 값도 있는지 (52주 범위는 1년치가 쌓였을 때만 계산)
WITH daily AS (
    SELECT (rate_at AT TIME ZONE 'Asia/Seoul')::date AS date, usd_krw
    FROM fx_rates
    WHERE granularity = 'DAILY'
),
bound AS (
    SELECT (MAX(date) - INTERVAL '1 year')::date AS since FROM daily
)
SELECT d.date, d.usd_krw,
       EXISTS (SELECT 1 FROM daily o, bound b WHERE o.date <= b.since) AS full_year
FROM daily d, bound b
WHERE d.date > b.since
ORDER BY d.date DESC
