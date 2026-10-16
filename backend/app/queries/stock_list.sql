-- 주식 리스트: 현재가·등락률·거래량·시총(원화 환산)·관심 여부, 정렬 기준별 순위
-- {order_col}·{order_dir}은 서버가 화이트리스트(volume / market_cap_krw, ASC / DESC)에서만 치환한다. 나머지는 모두 바인드 파라미터
-- 기본 목록은 노출 종목(featured)만. 검색어(q)가 있으면 매력도 비교군(benchmark)도 함께 찾는다 [S4-D]
-- 개선 후보: 검색어(q)의 LIKE 특수문자(%, _)를 이스케이프하지 않는다(원본 동작 유지) → ESCAPE 절 + like_escape 적용 검토
-- 주의: 주석에도 콜론+글자(바인드 변수 표기)를 쓰지 않는다. text()가 주석 안의 것까지 변수로 읽는다
WITH base AS (
    SELECT s.stock_id, s.ticker, s.name, s.name_en, m.code AS market, m.country, m.currency,
           lp.trade_date AS as_of, lp.close, lp.change, lp.change_rate, lp.volume,
           v.market_cap,
           ROUND(v.market_cap * CASE WHEN m.currency = 'USD' THEN fx.usd_krw ELSE 1 END, 0) AS market_cap_krw,
           (w.stock_id IS NOT NULL) AS is_watched
    FROM stocks s
    JOIN markets m ON m.market_id = s.market_id
    LEFT JOIN v_latest_price lp ON lp.stock_id = s.stock_id
    LEFT JOIN LATERAL (SELECT vs.market_cap FROM valuation_snapshots vs
                       WHERE vs.stock_id = s.stock_id ORDER BY vs.as_of DESC LIMIT 1) v ON true
    LEFT JOIN v_fx_latest fx ON true
    LEFT JOIN watchlist_items w ON w.stock_id = s.stock_id AND w.user_id = :user_id
    WHERE s.is_active
      AND (s.coverage = 'featured' OR CAST(:q AS text) IS NOT NULL)
      AND (CAST(:country AS text) IS NULL OR m.country = :country)
      AND (CAST(:grp AS text) IS NULL OR EXISTS (
            SELECT 1 FROM peer_group_members gm JOIN peer_groups g ON g.group_id = gm.group_id
            WHERE gm.stock_id = s.stock_id AND g.name = :grp))
      AND (CAST(:q AS text) IS NULL OR s.name ILIKE '%' || :q || '%' OR s.ticker ILIKE '%' || :q || '%'
           OR s.name_en ILIKE '%' || :q || '%')
)
SELECT b.*,
       RANK() OVER (ORDER BY b.{order_col} {order_dir} NULLS LAST) AS rank,
       COUNT(*) OVER () AS total
FROM base b
ORDER BY b.{order_col} {order_dir} NULLS LAST, b.stock_id
LIMIT :limit OFFSET :offset
