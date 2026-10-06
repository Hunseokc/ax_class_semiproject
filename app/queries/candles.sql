-- 기간 일봉: 해당 종목 최신 거래일 기준 months 파라미터 개월 수
SELECT d.trade_date AS date, d.open, d.high, d.low, d.close, d.volume
FROM daily_prices d
WHERE d.stock_id = :stock_id
  AND d.trade_date > (SELECT MAX(trade_date) FROM daily_prices WHERE stock_id = :stock_id)
                     - make_interval(months => :months)
ORDER BY d.trade_date
