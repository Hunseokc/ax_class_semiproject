-- 지수별 최신값·전일 대비·최근 30거래일 스파크라인
WITH ranked AS (
    SELECT p.index_id, p.trade_date, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.index_id ORDER BY p.trade_date DESC) AS rn
    FROM index_daily_prices p
)
SELECT i.index_id, i.code, i.name, m.country, m.currency, i.display_order,
       cur.trade_date AS as_of, cur.close,
       prev.close AS prev_close,
       cur.close - prev.close AS change,
       ROUND(cur.close / NULLIF(prev.close, 0) - 1, 6) AS change_rate,
       spark.points AS sparkline
FROM indices i
LEFT JOIN markets m ON m.market_id = i.market_id
LEFT JOIN ranked cur  ON cur.index_id  = i.index_id AND cur.rn = 1
LEFT JOIN ranked prev ON prev.index_id = i.index_id AND prev.rn = 2
LEFT JOIN LATERAL (
    SELECT json_agg(json_build_object('date', r.trade_date, 'close', r.close) ORDER BY r.trade_date) AS points
    FROM ranked r WHERE r.index_id = i.index_id AND r.rn <= 30
) spark ON true
ORDER BY i.display_order
