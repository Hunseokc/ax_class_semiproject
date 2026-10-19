-- 상단 검색 자동완성: 노출 종목·비교군·상장 종목 목록(listed) 전체에서 이름·영문명·티커 부분 일치
-- 검색어 q는 서버가 LIKE 특수문자(%, _, \)를 이스케이프해 넘긴다
-- 정렬: 티커 완전 일치 → 티커 앞부분 → 이름 앞부분 → 부분 일치, 같은 순위면 노출 종목·비교군 먼저, 짧은 이름 먼저
-- 상장 종목 1만여 행은 순차 스캔으로 수 ms — 트라이그램 인덱스(pg_trgm)는 확장 설치가 필요해 두지 않는다
SELECT s.stock_id, m.code AS market, m.country, m.currency, s.ticker, s.name, s.name_en, s.coverage
FROM stocks s
JOIN markets m ON m.market_id = s.market_id
WHERE s.is_active
  AND (s.ticker ILIKE '%' || :q || '%' OR s.name ILIKE '%' || :q || '%' OR s.name_en ILIKE '%' || :q || '%')
ORDER BY CASE WHEN UPPER(s.ticker) = UPPER(:q)                        THEN 0
              WHEN s.ticker ILIKE :q || '%'                           THEN 1
              WHEN s.name ILIKE :q || '%' OR s.name_en ILIKE :q || '%' THEN 2
              ELSE 3 END,
         s.coverage = 'listed', LENGTH(s.name), s.name, s.stock_id
LIMIT :limit
