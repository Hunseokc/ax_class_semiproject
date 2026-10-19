-- =====================================================================
-- 공시 목록 증분 수집 기준점 — 멱등.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 008_ingest_cursor
-- =====================================================================

-- 소스별 마지막으로 처리한 접수번호. 모두 성공한 뒤에만 옮긴다(중간 실패 시 다음 실행이 같은 지점부터)
CREATE TABLE IF NOT EXISTS ingest_cursor (
  source        VARCHAR(20)  PRIMARY KEY,                    -- 'DART_A001' (DART 사업보고서 목록)
  last_rcept_no CHAR(14)     NOT NULL CHECK (last_rcept_no ~ '^[0-9]{14}$'),
  last_rcept_dt DATE         NOT NULL,
  updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
