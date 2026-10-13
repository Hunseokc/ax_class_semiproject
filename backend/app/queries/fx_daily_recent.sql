-- 최근 1년 DAILY 환율 (스파크라인·전일 대비용, 화면에서 1개월·3개월·1년으로 자른다), 최신순
-- DAILY만 쓴다: SNAPSHOT은 조회 시각마다 쌓여 하루 점이 여러 개가 되기 때문. DAILY는 서울 자정(Asia/Seoul) 기준이라 서울 날짜로 바꾼다
-- 가장 최근 DAILY 날짜 기준 1년: market_indices의 스파크라인과 같은 구간 (원본과 같은 기준)
-- Stage 1: 52주 범위(full_year)는 이후 단계에서 추가한다
WITH daily AS (
    SELECT (rate_at AT TIME ZONE 'Asia/Seoul')::date AS date, usd_krw
    FROM fx_rates
    WHERE granularity = 'DAILY'
),
bound AS (
    SELECT (MAX(date) - INTERVAL '1 year')::date AS since FROM daily
)
SELECT d.date, d.usd_krw
FROM daily d, bound b
WHERE d.date > b.since
ORDER BY d.date DESC
