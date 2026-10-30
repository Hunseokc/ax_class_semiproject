#!/usr/bin/env bash
# 배포 DB 일일 스냅샷 (D-041 개정) — Cloud Run Job `stockmind-snapshot`, Cloud Scheduler 매일 07:02 KST.
# 07:00 benchmark의 점수 계산 완료를 DB 기록(ingestion_logs)으로 확인한 뒤 바로 뜬다 — 07:05 refresh가 가격·환율을 쓰기 전.
# 결과(GCS 버킷 마운트 /snapshots): deploy_<YYYYMMDD_HHMM>.dump + 같은 이름 .txt(메타). 사용자 데이터 표는 구조만 남긴다.
# 기준 스냅샷 S1·S2는 이 덤프 중 메타의 `mixed_writes: 0`인 날을 고른다.
set -euo pipefail
export TZ=Asia/Seoul PGCONNECT_TIMEOUT=20
URL=${DATABASE_URL/+psycopg/}            # 앱 비밀값(SQLAlchemy 형식)을 libpq 형식으로
OUT=${SNAPSHOT_DIR:-/snapshots}
WAIT_MIN=${WAIT_MIN:-20}                 # 07:00 계산이 늦으면 이만큼 기다린다
q() { psql "$URL" -XAtqc "$1"; }

TODAY="(now() AT TIME ZONE 'Asia/Seoul')::date"
# 07:00 benchmark 일일 실행(label daily — 메모가 '일일:'로 시작)이 오늘 성공한 시각
DONE_SQL="SELECT max(finished_at) FROM ingestion_logs
          WHERE job_type = 'BENCHMARK' AND status = 'SUCCESS' AND stock_id IS NULL AND error LIKE '일일:%'
            AND (finished_at AT TIME ZONE 'Asia/Seoul')::date = $TODAY"

DONE=
for _ in $(seq $((WAIT_MIN * 2))); do
  DONE=$(q "$DONE_SQL" || true)          # 연결이 잠깐 끊겨도 기다리는 동안 다시 시도
  [ -n "$DONE" ] && break
  echo "대기: 오늘 07:00 benchmark 완료 기록 없음(또는 DB 연결 실패)"
  sleep 30
done
[ -n "$DONE" ] || { echo "중단: ${WAIT_MIN}분 안에 오늘 07:00 benchmark 완료 기록이 없음 — 덤프 안 함"; exit 1; }
[ "$(q "SELECT max(as_of) = $TODAY FROM stock_scores")" = t ] || { echo "중단: stock_scores as_of가 오늘이 아님"; exit 1; }

NAME=deploy_$(date +%Y%m%d_%H%M)
START=$(q "SELECT now()")                # pg_dump는 시작 시점의 한 스냅샷을 뜬다
pg_dump -Fc -n public "$URL" \
  --exclude-table-data=public.users --exclude-table-data=public.user_preferences \
  --exclude-table-data=public.portfolios --exclude-table-data=public.portfolio_items \
  --exclude-table-data=public.watchlist_items \
  -f "/tmp/$NAME.dump"

# 07:00 계산이 끝난 뒤 ~ 덤프 시작 전에 다른 수집이 쓴 기록 수(0이어야 점수와 입력이 같은 시점)
MIXED=$(q "SELECT count(*) FROM ingestion_logs WHERE status = 'SUCCESS' AND job_type NOT IN ('BENCHMARK', 'SCORES')
           AND started_at > '$DONE' AND started_at < '$START'")
cat > "/tmp/$NAME.txt" <<EOF
name: $NAME.dump
sha256: $(sha256sum "/tmp/$NAME.dump" | cut -d' ' -f1)
bytes: $(stat -c %s "/tmp/$NAME.dump")
dump_start: $(q "SELECT to_char('$START'::timestamptz AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') || ' KST'")
benchmark_finished: $(q "SELECT to_char('$DONE'::timestamptz AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD HH24:MI:SS') || ' KST'")
as_of: $(q "SELECT max(as_of) FROM stock_scores")
scores: $(q "SELECT error FROM ingestion_logs WHERE job_type = 'SCORES' AND status = 'SUCCESS' ORDER BY finished_at DESC LIMIT 1")
mixed_writes: $MIXED
execution: ${CLOUD_RUN_EXECUTION:-local}
server: $(q "SHOW server_version")
pg_dump: $(pg_dump --version)
data_excluded: users, user_preferences, portfolios, portfolio_items, watchlist_items
EOF
cp "/tmp/$NAME.dump" "/tmp/$NAME.txt" "$OUT/"
cat "/tmp/$NAME.txt"
