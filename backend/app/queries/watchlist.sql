-- 관심종목 카드: 현재가·등락률·매력도(preset 프리셋)·메모·목표가, 정렬순
-- target_gap = (목표가 − 현재가) / 현재가 — 목표가는 종목 통화 기준
-- 정렬: 사용자가 정한 sort_order가 먼저, 같으면 먼저 담은 순(added_at)으로 항상 같은 순서를 보장한다
-- LEFT JOIN v_latest_price: 방금 담아 시세가 아직 없는 종목도 카드에서 빠지지 않는다(시세 칸만 NULL)
-- 현재가(price_quotes, 1시간 갱신 QUOTES)가 마지막 일봉의 장 마감(서울 15:30·뉴욕 16:00) 뒤에 받은 값이면 가격 칸은 현재가.
--   (마감 전에 받은 장중 값이 그날 확정 종가를 덮지 않게) 매력도·목표가 외 분석 값은 바꾸지 않는다
SELECT w.sort_order, w.added_at, s.stock_id, s.ticker, s.name, m.code AS market, m.country, m.currency,
       CASE WHEN q.stock_id IS NOT NULL THEN (q.quoted_at AT TIME ZONE m.timezone)::date ELSE lp.trade_date END AS as_of,
       COALESCE(q.price, lp.close) AS close,
       CASE WHEN q.stock_id IS NOT NULL THEN q.change ELSE lp.change END AS change,
       CASE WHEN q.stock_id IS NOT NULL THEN q.change_rate ELSE lp.change_rate END AS change_rate,
       q.quoted_at, sc.score,
       w.memo, w.target_price, w.updated_at,
       ROUND((w.target_price - COALESCE(q.price, lp.close)) / NULLIF(COALESCE(q.price, lp.close), 0), 6) AS target_gap
FROM watchlist_items w
JOIN stocks s  ON s.stock_id = w.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN v_latest_price lp ON lp.stock_id = s.stock_id
LEFT JOIN price_quotes q ON q.stock_id = s.stock_id
  AND (lp.trade_date IS NULL OR q.quoted_at > (lp.trade_date + CASE m.timezone WHEN 'Asia/Seoul' THEN time '15:30'
                                                                               ELSE time '16:00' END) AT TIME ZONE m.timezone)
LEFT JOIN LATERAL (SELECT st.score FROM stock_scores st WHERE st.stock_id = s.stock_id
                     AND st.preset_id = (SELECT preset_id FROM scoring_presets WHERE code = :preset)
                   ORDER BY st.as_of DESC LIMIT 1) sc ON true
WHERE w.user_id = :user_id
ORDER BY w.sort_order, w.added_at
