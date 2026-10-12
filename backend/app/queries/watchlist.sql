-- 관심종목 카드: 현재가·등락률·매력도(preset 프리셋)·메모·목표가, 정렬순
-- target_gap = (목표가 − 현재가) / 현재가 — 목표가는 종목 통화 기준
-- sparkline = 최근 30거래일 종가(대시보드 컴팩트 보기의 작은 추이선)
SELECT w.sort_order, w.added_at, s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency,
       lp.trade_date AS as_of, lp.close, lp.change, lp.change_rate, sc.score,
       w.memo, w.target_price, w.updated_at,
       ROUND((w.target_price - lp.close) / NULLIF(lp.close, 0), 6) AS target_gap,
       COALESCE(sp.points, '[]'::json) AS sparkline
FROM watchlist_items w
JOIN stocks s  ON s.stock_id = w.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN v_latest_price lp ON lp.stock_id = s.stock_id
LEFT JOIN LATERAL (SELECT st.score FROM stock_scores st WHERE st.stock_id = s.stock_id
                     AND st.preset_id = (SELECT preset_id FROM scoring_presets WHERE code = :preset)
                   ORDER BY st.as_of DESC LIMIT 1) sc ON true
LEFT JOIN LATERAL (SELECT json_agg(json_build_object('date', d.trade_date, 'close', d.close) ORDER BY d.trade_date) AS points
                   FROM (SELECT trade_date, close FROM daily_prices
                         WHERE stock_id = s.stock_id ORDER BY trade_date DESC LIMIT 30) d) sp ON true
WHERE w.user_id = :user_id
ORDER BY w.sort_order, w.added_at
