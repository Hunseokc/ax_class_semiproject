-- =====================================================================
-- 재무 표시통화 (개발산출물/09 2절, 검토_장부 D-026) — 멱등.
-- K-IFRS 1021은 원화 외 표시통화를 허용한다(두산밥캣 USD). 금액은 시장 통화(국내 원화)로 환산해 저장하고,
-- 공시의 원래 통화(currency)와 환산에 쓴 결산일 환율(fx_rate, 원화 공시면 NULL)을 남긴다. 기존 행은 NULL(기록 전).
-- 실행: python -m app.ingest migrate 014_fin_currency  →  외화 공시 종목 financials 재수집  →  scores
-- =====================================================================
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS currency VARCHAR(3);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(12,4);
DO $$ BEGIN
  ALTER TABLE financial_statements ADD CONSTRAINT ck_fin_fx_rate CHECK (fx_rate > 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
