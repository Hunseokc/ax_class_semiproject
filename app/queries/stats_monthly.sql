-- 종목 월별 집계: 최근 months개월(시장 현지 기준 이번 달 포함)
-- 월 구분은 date_trunc + GROUP BY, 월초·월말 종가는 월 파티션 윈도우(FIRST_VALUE·LAST_VALUE)
-- monthly_return = 그 달 마지막 거래일 종가 / 첫 거래일 종가 - 1 (월초 대비 월말)
-- is_partial = 아직 끝나지 않은 달(시장 현지 날짜 today가 속한 달)
-- 주의: text()는 주석 안의 콜론+이름도 바인드 파라미터로 읽으므로 주석에 쓰지 않는다
WITH bars AS (
    SELECT p.trade_date, p.high, p.low, p.close, p.volume,
           date_trunc('month', p.trade_date)::date AS month_start,
           FIRST_VALUE(p.close) OVER m AS first_close,
           LAST_VALUE(p.close)  OVER m AS last_close
    FROM daily_prices p
    WHERE p.stock_id = :stock_id
      AND p.trade_date >= (date_trunc('month', CAST(:today AS date)) - make_interval(months => :months - 1))::date
      AND p.trade_date <= CAST(:today AS date)
    WINDOW m AS (PARTITION BY date_trunc('month', p.trade_date) ORDER BY p.trade_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT to_char(b.month_start, 'YYYY-MM')                          AS month,
       COUNT(*)                                                   AS trading_days,
       MIN(b.trade_date)                                          AS first_date,
       MAX(b.trade_date)                                          AS last_date,
       ROUND(AVG(b.close), 4)                                     AS avg_close,
       MAX(b.high)                                                AS max_high,
       MIN(b.low)                                                 AS min_low,
       MAX(b.first_close)                                         AS first_close,   -- 파티션 안에서 모두 같은 값
       MAX(b.last_close)                                          AS last_close,
       ROUND(MAX(b.last_close) / NULLIF(MAX(b.first_close), 0) - 1, 6) AS monthly_return,
       SUM(b.volume)                                              AS total_volume,
       ROUND(AVG(b.volume), 0)                                    AS avg_volume,
       b.month_start = date_trunc('month', CAST(:today AS date))::date AS is_partial
FROM bars b
GROUP BY b.month_start
ORDER BY b.month_start
