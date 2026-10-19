-- 지수별 최신값·전일 대비·최근 1년 스파크라인(화면에서 1개월·3개월·1년으로 자른다)·52주 범위
-- 52주 범위는 기준일로부터 1년 안의 종가 최고·최저 (1년치가 쌓였을 때만 — 기준일 1년 전 이전 종가가 있어야 함)
-- 위치 = (현재값 − 52주 저점) / (52주 고점 − 52주 저점), 0~1
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
       spark.points AS sparkline,
       CASE WHEN cov.full_year THEN spark.high_52w END AS high_52w,
       CASE WHEN cov.full_year THEN spark.low_52w END  AS low_52w,
       CASE WHEN cov.full_year
            THEN ROUND((cur.close - spark.low_52w) / NULLIF(spark.high_52w - spark.low_52w, 0), 6) END AS position_52w
FROM indices i
LEFT JOIN markets m ON m.market_id = i.market_id
LEFT JOIN ranked cur  ON cur.index_id  = i.index_id AND cur.rn = 1
LEFT JOIN ranked prev ON prev.index_id = i.index_id AND prev.rn = 2
LEFT JOIN LATERAL (
    SELECT json_agg(json_build_object('date', r.trade_date, 'close', r.close) ORDER BY r.trade_date) AS points,
           MAX(r.close) AS high_52w, MIN(r.close) AS low_52w
    FROM ranked r
    WHERE r.index_id = i.index_id AND r.trade_date > (cur.trade_date - INTERVAL '1 year')::date
) spark ON true
LEFT JOIN LATERAL (
    SELECT EXISTS (SELECT 1 FROM index_daily_prices o
                   WHERE o.index_id = i.index_id AND o.trade_date <= (cur.trade_date - INTERVAL '1 year')::date) AS full_year
) cov ON true
ORDER BY i.display_order
