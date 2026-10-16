-- =====================================================================
-- 관심종목 메모·목표가 — 멱등. 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 004_watchlist_memo
-- 컬럼만 추가한다(기존 행의 값은 바꾸지 않음. 새 컬럼은 memo·target_price NULL, updated_at은 실행 시각).
-- =====================================================================

ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS memo VARCHAR(200);
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS target_price NUMERIC(20,4);
ALTER TABLE watchlist_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE watchlist_items DROP CONSTRAINT IF EXISTS watchlist_items_target_price_check;
ALTER TABLE watchlist_items ADD CONSTRAINT watchlist_items_target_price_check CHECK (target_price > 0);

DROP TRIGGER IF EXISTS trg_watchlist_items_updated_at ON watchlist_items;
CREATE TRIGGER trg_watchlist_items_updated_at
  BEFORE UPDATE ON watchlist_items FOR EACH ROW EXECUTE FUNCTION set_updated_at();
