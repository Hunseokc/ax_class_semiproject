-- =====================================================================
-- 로그인(2차) — 계정(이메일·비밀번호 / Google), 게스트 마지막 접속 시각, 사용자별 설정. 멱등.
-- 토큰은 DB에 두지 않는다: access token(JWT)은 서명으로만 검증하고, refresh token·로그인 시도 제한은 Redis에 둔다.
-- 새로 만드는 DB는 schema.sql에 반영되어 있다.
-- 실행: python -m app.ingest migrate 011_auth
-- =====================================================================

-- 계정 = email이 있는 사용자(비밀번호와 Google 중 하나 이상). 게스트·demo는 email이 NULL
ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254) UNIQUE CHECK (email = lower(email));
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(200);
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub VARCHAR(255) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
-- 게스트 마지막 접속(1시간에 한 번만 갱신). guest_retention_days(3일) 지난 게스트는 정리 작업이 지운다
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_account_check;
ALTER TABLE users ADD CONSTRAINT users_account_check
  CHECK (email IS NULL AND password_hash IS NULL AND google_sub IS NULL
         OR email IS NOT NULL AND (password_hash IS NOT NULL OR google_sub IS NOT NULL));

-- 사용자별 설정(테마·투자 성향·지표 선택 등). 키 목록은 app/services/auth.py PREF_KEYS
CREATE TABLE IF NOT EXISTS user_preferences (
  user_id    INT          PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  prefs      JSONB        NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(prefs) = 'object'),
  updated_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
