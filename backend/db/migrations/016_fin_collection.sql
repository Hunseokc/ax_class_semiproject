-- =====================================================================
-- 재무 수집 확장 (개발산출물/09 2절 '재무 수집', 검토_장부 D-033·D-039) — 멱등.
-- 비교 표본의 재무를 한 경로로 다시 받으면서 FY 5개·분기 20개(period_type Q1~Q4, 3개월치)와 아래를 함께 저장한다.
--   filed_at: 그 결산기 값이 처음 공시된 보고서 제출일(DART 접수일·SEC filed) — 신호가 유효해지는 시점
--   consolidated: 연결 true / 별도 false
--   notes: 수집 경로(path=DART_API·SEC_API·YFINANCE·DART_BULK·SEC_FRAMES)·대체 계정·전기값 — 어느 길로 들어온 값인지(R4-1·R4-2)
--   추가 계정 9개: 점수에는 아직 쓰지 않는다(측정 라운드 M1 — EV·TTM·F-Score·보험 포괄이익·지분법 e)
-- 기존 행은 NULL(기록 전). 실행: python -m app.ingest migrate 016_fin_collection → financials --scope sample → scores
-- =====================================================================
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS filed_at DATE;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS consolidated BOOLEAN;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS operating_cf NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS comprehensive_income NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS equity_method_income NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS borrowings NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS cash NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS goodwill NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS intangibles NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS interest_expense NUMERIC(24,2);
ALTER TABLE financial_statements ADD COLUMN IF NOT EXISTS nci_net_income NUMERIC(24,2);
