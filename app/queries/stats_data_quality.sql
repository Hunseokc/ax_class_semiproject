-- 작업 종류별 데이터 품질 (ingestion_logs 기준, GROUP BY + FILTER + MAX)
-- 건수는 since 이후. success·failed·skipped는 대상(종목·지수 등) 단위 행, partial은 갱신 실행 단위(source REFRESH,
-- 일부 대상만 실패한 실행)라 서로 겹치지 않게 센다. 격리 행 수는 로그 메모의 '격리 N행'을 더한다.
-- last_refresh_success_at: 4시간 갱신 작업의 TTL 판단 기준(RefreshService와 같은 작업 단위 기록)
-- 주의: text()는 주석 안의 콜론+이름도 바인드 파라미터로 읽으므로 주석에 쓰지 않는다
WITH failure AS (                       -- 작업 종류별 마지막 실패 1건(사유·대상)
    SELECT DISTINCT ON (l.job_type) l.job_type, l.finished_at, l.error, s.ticker
    FROM ingestion_logs l
    LEFT JOIN stocks s ON s.stock_id = l.stock_id
    WHERE l.status = 'FAILED'
    ORDER BY l.job_type, l.finished_at DESC, l.log_id DESC
)
SELECT l.job_type,
       MAX(l.finished_at) FILTER (WHERE l.status = 'SUCCESS')                             AS last_success_at,
       MAX(l.finished_at) FILTER (WHERE l.status = 'SUCCESS' AND l.source = 'REFRESH')    AS last_refresh_success_at,
       f.finished_at                                                                       AS last_failure_at,
       left(split_part(f.error, chr(10), 1), 300)                                          AS last_failure_reason,
       f.ticker                                                                            AS last_failure_target,
       COUNT(*) FILTER (WHERE l.started_at >= :since AND l.source <> 'REFRESH' AND l.status = 'SUCCESS') AS success,
       COUNT(*) FILTER (WHERE l.started_at >= :since AND l.source <> 'REFRESH' AND l.status = 'FAILED')  AS failed,
       COUNT(*) FILTER (WHERE l.started_at >= :since AND l.source = 'REFRESH' AND l.status = 'FAILED'
                          AND l.error LIKE 'PARTIAL%')                                     AS partial,
       COUNT(*) FILTER (WHERE l.started_at >= :since AND l.status = 'SKIPPED')            AS skipped,
       COALESCE(SUM((regexp_match(l.error, '격리 ([0-9]+)행'))[1]::int)
                FILTER (WHERE l.started_at >= :since), 0)                                  AS quarantined_rows
FROM ingestion_logs l
LEFT JOIN failure f ON f.job_type = l.job_type
GROUP BY l.job_type, f.finished_at, f.error, f.ticker
ORDER BY l.job_type
