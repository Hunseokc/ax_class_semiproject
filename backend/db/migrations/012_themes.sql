-- =====================================================================
-- 테마 분류(섹터 → 테마 2단계) + 금융 전용 점수 + 원자재 지수 — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다. v_stock_theme은 views.sql에 있다(migrate가 다시 적용).
-- 실행: python -m app.ingest migrate 012_themes  →  python -m app.ingest master  →  python -m app.ingest benchmark --reselect
-- =====================================================================

-- 국내 업종 코드: DART 기업개황 induty_code(KSIC). 미국은 기존 sic. 둘 다 industry_checked_at 주기로 다시 확인
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS ksic VARCHAR(10);
-- 국내 industry_checked_at은 KRX 업종명 확인 시각이었다 → KSIC가 없는 국내 종목은 비워서 다음 선정 때 KSIC를 받게 한다
UPDATE stocks s SET industry_checked_at = NULL FROM markets m
WHERE m.market_id = s.market_id AND m.country = 'KR' AND s.ksic IS NULL AND s.industry_checked_at IS NOT NULL;

-- 테마(peer_groups): 부모 섹터, 점수 방식, 원자재 연동 여부 — config/universe.yaml themes
ALTER TABLE peer_groups ADD COLUMN IF NOT EXISTS sector VARCHAR(32);
ALTER TABLE peer_groups ADD COLUMN IF NOT EXISTS scoring VARCHAR(10) NOT NULL DEFAULT 'general';
ALTER TABLE peer_groups DROP CONSTRAINT IF EXISTS peer_groups_scoring_check;
ALTER TABLE peer_groups ADD CONSTRAINT peer_groups_scoring_check CHECK (scoring IN ('general','financial','none'));
ALTER TABLE peer_groups ADD COLUMN IF NOT EXISTS commodity_linked BOOLEAN NOT NULL DEFAULT false;

-- 원자재 선물을 지수와 같은 경로로 수집한다: category commodity, 가격 단위
ALTER TABLE indices ADD COLUMN IF NOT EXISTS category VARCHAR(10) NOT NULL DEFAULT 'index';
ALTER TABLE indices DROP CONSTRAINT IF EXISTS indices_category_check;
ALTER TABLE indices ADD CONSTRAINT indices_category_check CHECK (category IN ('index','commodity'));
ALTER TABLE indices ADD COLUMN IF NOT EXISTS unit VARCHAR(16);
