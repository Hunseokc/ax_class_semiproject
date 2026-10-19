-- =====================================================================
-- 미국 시가총액 순위(백그라운드 재무 적재 우선순위) — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 009_cap_rank
-- =====================================================================

-- 국가 안 시가총액 순위(1 = 가장 큼). 상위 us_rank_pool(1,500)개만 값이 있고 나머지는 NULL.
-- SEC 발행주식수 × 종가로 30일마다 다시 매긴다(app/ingest/background.py rank_us). 화면에는 쓰지 않는다
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS cap_rank INT CHECK (cap_rank > 0);
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS cap_ranked_at TIMESTAMPTZ;
