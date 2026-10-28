-- =====================================================================
-- 미국 시가총액 바로잡기 (개발산출물/09 2절 '미국 시가총액', 검토_장부 D-039·R4-3·R4-4) — 멱등.
-- SEC 발행주식수는 원주 기준이라 ADR은 '원주 수 × ADS 종가'로 수백~수천 배 부풀었다(AKTX 1.19조 달러, ONC 13배).
--   cap_usd: 순위(cap_rank)를 매길 때 쓴 시가총액(달러, yfinance 시총 — 없으면 SEC 원주 수 × 종가)
--   share_ratio: SEC 발행주식수 ÷ 상장 단위 주식수(yfinance 시총 ÷ 종가). 1에서 20% 넘게 벗어날 때만(ADR·주식 종류 여럿).
--                미국 밸류에이션(기초값 × 종가)이 SEC 발행주식수를 이 값으로 나눠 쓴다
-- 실행: python -m app.ingest migrate 017_us_cap → background 순위(rank_us force) → benchmark --reselect
-- =====================================================================
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS cap_usd NUMERIC(20,0);
ALTER TABLE stocks ADD COLUMN IF NOT EXISTS share_ratio NUMERIC(14,6);
DO $$ BEGIN
  ALTER TABLE stocks ADD CONSTRAINT ck_stocks_share_ratio CHECK (share_ratio > 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
