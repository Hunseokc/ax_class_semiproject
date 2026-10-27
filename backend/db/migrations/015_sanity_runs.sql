-- =====================================================================
-- sanity 실행 기록 (검토_장부 D-030 — 배포 DB에서도 sanity를 돌려 결과를 남긴다) — 멱등.
-- python -m app.ingest sanity --save [--env deploy]가 한 행을 남긴다. 결과는 통과 / 감수한 실패(known_fail·결정 번호) /
-- target 실패 / 미검증(데이터 없음·실행 불가) 네 칸과 required 실패(종료를 막음)로 따로 센다.
-- 실행: python -m app.ingest migrate 015_sanity_runs
-- =====================================================================
CREATE TABLE IF NOT EXISTS sanity_runs (
  run_id        SERIAL       PRIMARY KEY,
  ran_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
  as_of         DATE         NOT NULL,                  -- 판정한 점수 계산일
  model_version VARCHAR(40),
  environment   VARCHAR(20)  NOT NULL CHECK (environment IN ('dev', 'deploy')),
  passed        INT          NOT NULL,
  known_fail    INT          NOT NULL,                  -- 감수한 실패(known_fail + 결정 번호)
  target_fail   INT          NOT NULL,
  unverified    INT          NOT NULL,                  -- 미검증(데이터 없음·실행 불가)
  required_fail INT          NOT NULL,                  -- 0이어야 종료 조건 2 충족
  ok            BOOLEAN      NOT NULL,
  results       JSONB        NOT NULL,                  -- [{id, status, result, value}]
  report        TEXT         NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sanity_runs_as_of ON sanity_runs (as_of, environment);
