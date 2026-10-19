-- 시장·섹터 점수의 '섹터 흐름' 재료: 같은 국가·같은 업종 섹터(stocks.sector) 표본 종목의 5거래일 수익률 중앙값
-- 파라미터: country (KR·US), sector (stocks.sector 값), as_of (그 국가 마지막 마감 거래일), min_n (최소 표본 수 5)
-- 표본: 활성 노출 종목 + 비교군(listed 제외) — 매력도 섹터 중립화와 같은 섹터 분류. 이 종목 자신도 포함
-- ref_date: as_of 이하에서 일봉이 있는 표본 종목이 min_n개 이상인 가장 최근 날짜. 그런 날이 없으면(표본 자체가 적음)
--   표본 일봉이 있는 가장 최근 날짜 — 이때 n < min_n이라 점수에는 쓰지 않고 표본 수 안내에만 쓴다
--   (비교군 일봉은 매일 07:00에만 들어와서, 장 마감 직후에는 노출 종목만 그날 일봉이 있다 → 전 거래일로 계산)
-- 수익률 = ref_date 종가 / 그 종목의 5거래일 전 종가 − 1. ref_date 일봉이나 5거래일 전 일봉이 없는 종목은 뺀다
-- 결과는 항상 1행: sector_r5(표본 0개면 NULL), n(수익률을 낸 종목 수), ref_date(없으면 NULL)
WITH peers AS (
    SELECT s.stock_id
    FROM stocks s
    JOIN markets mk ON mk.market_id = s.market_id
    WHERE mk.country = :country AND s.sector = :sector AND s.is_active AND s.coverage IN ('featured', 'benchmark')
),
bars AS (                             -- 연휴가 길어도 6거래일이 들어가도록 30일
    SELECT d.stock_id, d.trade_date, d.close
    FROM daily_prices d
    JOIN peers p ON p.stock_id = d.stock_id
    WHERE d.trade_date <= CAST(:as_of AS date) AND d.trade_date > CAST(:as_of AS date) - 30
),
ref AS (
    SELECT COALESCE(MAX(c.trade_date) FILTER (WHERE c.cnt >= :min_n), MAX(c.trade_date)) AS ref_date
    FROM (SELECT b.trade_date, COUNT(*) AS cnt FROM bars b GROUP BY b.trade_date) c
),
ranked AS (                           -- ref_date부터 거꾸로 번호(rn = 1이 ref_date 이하 최신)
    SELECT b.stock_id, b.trade_date, b.close,
           ROW_NUMBER() OVER (PARTITION BY b.stock_id ORDER BY b.trade_date DESC) AS rn
    FROM bars b
    CROSS JOIN ref
    WHERE b.trade_date <= ref.ref_date
),
r AS (
    SELECT k.stock_id,
           MAX(k.close) FILTER (WHERE k.rn = 1) / NULLIF(MAX(k.close) FILTER (WHERE k.rn = 6), 0) - 1 AS r5
    FROM ranked k
    CROSS JOIN ref
    WHERE k.rn IN (1, 6)
    GROUP BY k.stock_id, ref.ref_date
    HAVING MAX(k.trade_date) FILTER (WHERE k.rn = 1) = ref.ref_date
       AND COUNT(*) FILTER (WHERE k.rn = 6) = 1
)
SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY r.r5) AS sector_r5,
       COUNT(r.r5)                                        AS n,
       (SELECT ref.ref_date FROM ref)                     AS ref_date
FROM r
