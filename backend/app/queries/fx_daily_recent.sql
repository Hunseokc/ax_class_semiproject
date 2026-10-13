-- 최근 30개 DAILY 환율 (스파크라인·전일 대비용), 최신순
-- DAILY만 쓴다: SNAPSHOT은 조회 시각마다 쌓여 하루 점이 여러 개가 되기 때문. DAILY는 서울 자정(Asia/Seoul) 기준이라 서울 날짜로 바꾼다
-- 개수(LIMIT)로 자른다: market_indices의 30거래일과 같은 기준이라 휴일이 껴도 점 개수가 같다
-- Stage 1: 52주 범위(full_year)는 이후 단계에서 추가한다
WITH daily AS (
    SELECT (rate_at AT TIME ZONE 'Asia/Seoul')::date AS date, usd_krw
    FROM fx_rates
    WHERE granularity = 'DAILY'
)
SELECT d.date, d.usd_krw
FROM daily d
ORDER BY d.date DESC
LIMIT 30
