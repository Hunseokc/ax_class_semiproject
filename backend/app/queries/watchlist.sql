-- 관심종목 카드: 현재가·등락률·매력도(preset 프리셋), 정렬순
-- 정렬: 사용자가 정한 sort_order가 먼저, 같으면 먼저 담은 순(added_at)으로 항상 같은 순서를 보장한다
-- LEFT JOIN v_latest_price: 방금 담아 시세가 아직 없는 종목도 카드에서 빠지지 않는다(시세 칸만 NULL)
-- 메모·목표가·target_gap은 Stage 5에서 컬럼과 JOIN을 추가한다
SELECT w.sort_order, w.added_at, s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency,
       lp.trade_date AS as_of, lp.close, lp.change, lp.change_rate, sc.score
FROM watchlist_items w
JOIN stocks s  ON s.stock_id = w.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN v_latest_price lp ON lp.stock_id = s.stock_id
LEFT JOIN LATERAL (SELECT st.score FROM stock_scores st WHERE st.stock_id = s.stock_id
                     AND st.preset_id = (SELECT preset_id FROM scoring_presets WHERE code = :preset)
                   ORDER BY st.as_of DESC LIMIT 1) sc ON true
WHERE w.user_id = :user_id
ORDER BY w.sort_order, w.added_at
