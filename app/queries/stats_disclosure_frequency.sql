-- 기간별 공시 빈도: 기간(월·분기·주) × 출처, 정기보고서 수, 구성비, 누적 건수
WITH base AS (
    SELECT date_trunc(CAST(:period AS text), d.filed_at AT TIME ZONE 'Asia/Seoul')::date AS period_start,
           d.data_source,
           (d.report_type IN ('정기공시', '10-K', '10-K/A', '10-Q', '10-Q/A')) AS is_periodic
    FROM disclosures d
    WHERE d.filed_at >= now() - make_interval(days => :days)
),
agg AS (
    SELECT period_start,
           COUNT(*)                                      AS total,
           COUNT(*) FILTER (WHERE data_source = 'DART')  AS dart,
           COUNT(*) FILTER (WHERE data_source = 'SEC')   AS sec,
           SUM(CASE WHEN is_periodic THEN 1 ELSE 0 END)  AS periodic_reports
    FROM base
    GROUP BY period_start
)
SELECT period_start, total, dart, sec, periodic_reports,
       ROUND(total::numeric / SUM(total) OVER (), 4)                  AS share,
       SUM(total) OVER (ORDER BY period_start ROWS UNBOUNDED PRECEDING) AS cumulative
FROM agg
ORDER BY period_start
