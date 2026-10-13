-- 지수별 최신값·전일 대비·최근 1년 스파크라인(화면에서 1개월·3개월·1년으로 자른다)
-- 거래일 번호(rn): rn=1 최신, rn=2 전일. 스파크라인은 지수별 최신 거래일 기준 1년 (원본과 같은 구간)
-- 일봉이 없는 지수도 행은 남는다(값은 NULL). sparkline이 NULL이면 라우터가 []로 바꾼다
-- Stage 1: 52주 범위(high_52w·low_52w·position_52w)와 장 상태(session_status)는 이후 단계에서 추가한다
WITH ranked AS (
    SELECT p.index_id, p.trade_date, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.index_id ORDER BY p.trade_date DESC) AS rn
    FROM index_daily_prices p
)
SELECT i.code, i.name, m.country, m.currency,
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
    FROM ranked r
    WHERE r.index_id = i.index_id AND r.trade_date > (cur.trade_date - INTERVAL '1 year')::date
) spark ON true
ORDER BY i.display_order
