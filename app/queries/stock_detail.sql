-- 종목 상세: 기본 정보 + 최신 시세·밸류에이션·매력도·소속 그룹·관심 여부
SELECT s.stock_id, s.ticker, s.name, s.name_en, s.corp_code, s.cik,
       m.code AS market, m.country, m.currency, m.timezone,
       lp.trade_date AS as_of, lp.close, lp.prev_close, lp.change, lp.change_rate, lp.volume,
       v.as_of AS valuation_as_of, v.per, v.pbr, v.eps, v.bps, v.market_cap, v.shares_outstanding, v.source AS valuation_source,
       ROUND(v.market_cap * CASE WHEN m.currency = 'USD' THEN fx.usd_krw ELSE 1 END, 0) AS market_cap_krw,
       sc.as_of AS score_as_of, sc.score,
       (SELECT json_agg(json_build_object('group_id', g.group_id, 'name', g.name) ORDER BY g.name)
          FROM peer_group_members gm JOIN peer_groups g ON g.group_id = gm.group_id
         WHERE gm.stock_id = s.stock_id) AS groups,
       EXISTS (SELECT 1 FROM watchlist_items w WHERE w.stock_id = s.stock_id AND w.user_id = :user_id) AS is_watched
FROM stocks s
JOIN markets m ON m.market_id = s.market_id
LEFT JOIN v_latest_price lp ON lp.stock_id = s.stock_id
LEFT JOIN LATERAL (SELECT * FROM valuation_snapshots vs WHERE vs.stock_id = s.stock_id
                   ORDER BY vs.as_of DESC LIMIT 1) v ON true
LEFT JOIN v_fx_latest fx ON true
LEFT JOIN LATERAL (SELECT st.as_of, st.score FROM stock_scores st WHERE st.stock_id = s.stock_id
                   ORDER BY st.as_of DESC LIMIT 1) sc ON true
WHERE m.code = :market AND s.ticker = :ticker
