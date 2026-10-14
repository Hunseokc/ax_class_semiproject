-- 포트폴리오 담은 종목 + 현재 시세·소속 경쟁 그룹 (평가는 서비스에서 Decimal로 계산)
-- 최신 매력도(score)는 Stage 4에서 stock_scores가 생기면 붙인다
SELECT pi.item_id, pi.stock_id, m.code AS market, m.country, m.currency, s.ticker, s.name,
       pi.quantity, pi.ref_price, pi.ref_fx_rate, pi.ref_date, pi.memo, pi.cost_krw,
       lp.trade_date, lp.close,
       (SELECT array_agg(g.name ORDER BY g.name)
          FROM peer_group_members gm JOIN peer_groups g ON g.group_id = gm.group_id
         WHERE gm.stock_id = pi.stock_id) AS groups
FROM portfolio_items pi
JOIN stocks s  ON s.stock_id = pi.stock_id
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN v_latest_price lp ON lp.stock_id = pi.stock_id
WHERE pi.portfolio_id = :pid
ORDER BY pi.cost_krw DESC, pi.item_id
