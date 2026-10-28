-- 매력도 1단계(모델 v2): 종목별 지표 원값 (기준: 종목별 최신 거래일 종가·최신 밸류에이션·최신 FY 재무)
-- 대상: 파라미터 stock_id가 NULL이면 매력도 유니버스(활성 노출 종목 + 비교군, listed 제외)
--       stock_id를 주면 그 종목만(상장 종목 목록의 참고 점수 계산용 — app/services/reference_score.py)
-- 지표 정의·NULL 사유는 개발산출물/09 2절(D-002). 한 종목당 10행(값이 없으면 raw_value NULL)
-- note: 대체 계산 메모, null_note: 규칙으로 일부러 비운 지표의 사유(missing_metrics에 기본 사유 대신 쓴다)
-- fy_count: 이어지는 FY 수(최대 3) — 배지(재무 이력 짧음)
-- value_rules: 저평가 보수 규칙 중 쓸 수 있는 수(D-040) — 3년 평균 이익(t·t−1·t−2 이익이 모두 있음) + 가치 함정 신호
--   (t−2가 있고 신호 3개 이상, 금융은 t−2만 있으면 — 해당 없음). 0 → 저평가 × 1/3, 1 → × 2/3, 2 → 그대로(score_aggregate.sql)
-- price_date: 점수에 쓴 최신 일봉 날짜(sanity PRICE-same-date — 국가마다 하나여야 함, R4-5)
-- fy_end·ni0·oi0(·ni1·oi1·ni2·oi2): FY t(·t−1·t−2) 결산일·순이익·영업이익 — 경고 배지(순이익 > 영업이익·결산 시점, D-003·D-029)를
--   scoring.py가 만든다
-- 재무 FY: 자산과 이익(순이익 또는 영업이익)이 있는 FY만 쓴다(일부 칸만 들어온 최신 FY는 건너뜀).
--   t = 그중 최신, t−1·t−2 = 바로 뒤 FY 결산일보다 330~400일 앞선 FY(결산월 변경으로 끼어든 행은 건너뜀)
-- 묶음(family, v_stock_theme): general / financial(순이익 기준, 매출·부채 지표 없음) / none(행을 만들지 않음)
-- 해마다 저평가 이익 e = min(지배주주 순이익, after_tax × 영업이익) — 일회성 이익은 자르고 이자·비지배 몫은 남긴다.
--   순이익이 없으면 after_tax × 영업이익, 영업이익이 없으면 순이익. 금융은 순이익
-- 국내 우선주(D-029): e는 보통주·우선주 전체 주주 몫, 시총은 보통주만이다. KRX BPS의 주식수(= 최신 FY 지배 자본 ÷ BPS)가
--   보통주보다 3% 넘게 많으면 e × 보통주 수 ÷ BPS 주식수로 보통주 몫만 쓴다(B/P와 같은 주식수 기준). 3% 이하는 기준일·반올림 차이로 본다
-- 표본에서 빼는 종목(D-039, 09 2절): 지표 행은 만들고 값을 비워 사유를 적는다(순위·중립화 평균에 들어가지 않음)
--   거래정지(R4-7): 마지막 일봉이 같은 국가 비교 표본의 최근 21번째 거래일보다 앞섬 → 모든 지표
--   분할(R4-8): 파라미터 ca_*(config universe.yaml corporate_actions)의 완료일이 최신 FY 결산일보다 뒤 → 저평가 지표
-- 자본 ≤ 0(최신 FY 지배 자본 또는 BPS)이면 B/P를 비운다(D-027 — 자사주 매입 우량 기업을 '가장 비싼 종목'으로 세지 않음)
--   자본과 BPS가 모두 없으면(신고값 0을 채우지 못한 파트너십 등 — 수정 4 R4-9) 사유 '자본 정보 없음'
WITH cal AS (                         -- 국가별 비교 표본의 거래일(최근부터 번호) — 거래정지 판정
    SELECT x.country, x.trade_date, ROW_NUMBER() OVER (PARTITION BY x.country ORDER BY x.trade_date DESC) AS rk
    FROM (SELECT DISTINCT m.country, d.trade_date
          FROM daily_prices d
          JOIN stocks s  ON s.stock_id = d.stock_id AND s.is_active AND s.coverage <> 'listed'
          JOIN markets m ON m.market_id = s.market_id
          WHERE d.trade_date >= CURRENT_DATE - 120) x
),
ca AS (
    SELECT * FROM unnest(CAST(:ca_tickers AS text[]), CAST(:ca_countries AS text[]), CAST(:ca_dates AS date[]),
                         CAST(:ca_whats AS text[])) AS x(ticker, country, done, what)
),
base AS (
    SELECT vm.stock_id, vm.country, vm.close, vm.bps, vm.volatility_1y,
           COALESCE(vm.market_cap, CAST(vs.shares_outstanding AS numeric) * vm.close) AS mcap,
           CAST(vs.shares_outstanding AS numeric) AS shares,
           COALESCE(t.family, 'general') AS family,
           vm.as_of AS last_trade, COALESCE(vm.as_of < cut.trade_date, false) AS halted,
           ca.done AS ca_done, ca.what AS ca_what
    FROM v_stock_metrics vm
    JOIN stocks st ON st.stock_id = vm.stock_id
     AND CASE WHEN CAST(:stock_id AS int) IS NULL THEN st.is_active AND st.coverage <> 'listed'
              ELSE st.stock_id = :stock_id END
    LEFT JOIN v_stock_theme t ON t.stock_id = vm.stock_id
    LEFT JOIN LATERAL (SELECT x.shares_outstanding FROM valuation_snapshots x
                       WHERE x.stock_id = vm.stock_id ORDER BY x.as_of DESC LIMIT 1) vs ON true
    LEFT JOIN cal cut ON cut.country = vm.country AND cut.rk = 21
    LEFT JOIN ca      ON ca.ticker = st.ticker AND ca.country = vm.country
    WHERE COALESCE(t.family, 'general') <> 'none'
),
fy AS (                               -- 쓸 수 있는 FY
    SELECT f.stock_id, f.period_end, f.revenue, f.operating_income, f.net_income, f.total_assets, f.total_debt, f.total_equity
    FROM financial_statements f
    WHERE f.period_type = 'FY' AND f.total_assets IS NOT NULL
      AND (f.net_income IS NOT NULL OR f.operating_income IS NOT NULL)
      AND f.stock_id IN (SELECT b.stock_id FROM base b)
),
t0 AS (
    SELECT DISTINCT ON (fy.stock_id) fy.* FROM fy ORDER BY fy.stock_id, fy.period_end DESC
),
chain AS (                            -- t, t−1, t−2 (결산일 간격 330~400일로 이어지는 FY)
    SELECT t0.stock_id, t0.period_end AS end0,
           t0.revenue AS rev0, t0.operating_income AS oi0, t0.net_income AS ni0, t0.total_assets AS ta0, t0.total_debt AS debt0,
           t0.total_equity AS eq0,
           p1.period_end AS end1, p1.operating_income AS oi1, p1.net_income AS ni1,
           p2.period_end AS end2, p2.revenue AS rev2, p2.operating_income AS oi2, p2.net_income AS ni2,
           p2.total_assets AS ta2, p2.total_debt AS debt2
    FROM t0
    LEFT JOIN LATERAL (SELECT fy.* FROM fy WHERE fy.stock_id = t0.stock_id
                         AND fy.period_end BETWEEN t0.period_end - 400 AND t0.period_end - 330
                       ORDER BY fy.period_end DESC LIMIT 1) p1 ON true
    LEFT JOIN LATERAL (SELECT fy.* FROM fy WHERE fy.stock_id = t0.stock_id AND p1.period_end IS NOT NULL
                         AND fy.period_end BETWEEN p1.period_end - 400 AND p1.period_end - 330
                       ORDER BY fy.period_end DESC LIMIT 1) p2 ON true
),
px AS (                               -- 최신 거래일부터 거꾸로 번호(rn = 1이 t)
    SELECT d.stock_id, d.close, ROW_NUMBER() OVER (PARTITION BY d.stock_id ORDER BY d.trade_date DESC) AS rn
    FROM daily_prices d
    WHERE CAST(:stock_id AS int) IS NULL OR d.stock_id = :stock_id
),
mom AS (                              -- t−21, t−126, t−252 거래일 종가
    SELECT px.stock_id,
           MAX(px.close) FILTER (WHERE px.rn = 22)  AS c_21,
           MAX(px.close) FILTER (WHERE px.rn = 127) AS c_126,
           MAX(px.close) FILTER (WHERE px.rn = 253) AS c_252
    FROM px
    WHERE px.rn IN (22, 127, 253)
    GROUP BY px.stock_id
),
inp AS (
    SELECT b.*, c.end0, c.rev0, c.oi0, c.ni0, c.ta0, c.debt0, c.eq0, c.end1, c.oi1, c.ni1, c.end2, c.rev2, c.oi2, c.ni2, c.ta2, c.debt2,
           m.c_21, m.c_126, m.c_252, (b.family = 'financial') AS fin,
           CASE WHEN c.stock_id IS NULL THEN 0 WHEN c.end1 IS NULL THEN 1 WHEN c.end2 IS NULL THEN 2 ELSE 3 END AS fy_count
    FROM base b
    LEFT JOIN chain c ON c.stock_id = b.stock_id
    LEFT JOIN mom m   ON m.stock_id = b.stock_id
),
earn AS (                             -- 해마다 저평가 이익 e와 수익성·성장성에 쓰는 이익 p(일반 영업이익, 금융 순이익)
    SELECT i.*,
           CASE WHEN i.fin THEN i.ni0 WHEN i.ni0 IS NULL THEN CAST(:after_tax AS numeric) * i.oi0 WHEN i.oi0 IS NULL THEN i.ni0
                ELSE LEAST(i.ni0, CAST(:after_tax AS numeric) * i.oi0) END AS e0,
           CASE WHEN i.fin THEN i.ni1 WHEN i.ni1 IS NULL THEN CAST(:after_tax AS numeric) * i.oi1 WHEN i.oi1 IS NULL THEN i.ni1
                ELSE LEAST(i.ni1, CAST(:after_tax AS numeric) * i.oi1) END AS e1,
           CASE WHEN i.fin THEN i.ni2 WHEN i.ni2 IS NULL THEN CAST(:after_tax AS numeric) * i.oi2 WHEN i.oi2 IS NULL THEN i.ni2
                ELSE LEAST(i.ni2, CAST(:after_tax AS numeric) * i.oi2) END AS e2,
           CASE WHEN i.fin THEN i.ni0 ELSE i.oi0 END AS p0,
           CASE WHEN i.fin THEN i.ni2 ELSE i.oi2 END AS p2,
           i.debt0 / NULLIF(i.ta0, 0) AS la0,
           i.debt2 / NULLIF(i.ta2, 0) AS la2
    FROM inp i
),
calc AS (
    SELECT e.*,
           -- 업황 정점 방지: 3개 FY가 이어지면 min(최신 e, 3년 평균 e) (모든 업종 — 원자재 테마만이 아님)
           CASE WHEN e.fy_count = 3 AND e.e1 IS NOT NULL AND e.e2 IS NOT NULL
                THEN LEAST(e.e0, (e.e0 + e.e1 + e.e2) / 3) ELSE e.e0 END AS e_cons,
           -- 가치 함정 신호(일반만, t vs t−2): 영업흑자·영업이익↑·매출↑·영업이익률↑·부채/자산↓ 중 계산할 수 있는 것.
           -- 이익 관련 두 신호는 2년 전이 흑자일 때만 센다(흑자 전환 기저효과 방지)
           CASE WHEN e.oi0 IS NOT NULL THEN 1 ELSE 0 END
         + CASE WHEN e.oi0 IS NOT NULL AND e.oi2 > 0 THEN 1 ELSE 0 END
         + CASE WHEN e.rev0 IS NOT NULL AND e.rev2 IS NOT NULL THEN 1 ELSE 0 END
         + CASE WHEN e.oi0 IS NOT NULL AND e.oi2 > 0 AND e.rev0 > 0 AND e.rev2 > 0 THEN 1 ELSE 0 END
         + CASE WHEN e.la0 IS NOT NULL AND e.la2 IS NOT NULL THEN 1 ELSE 0 END AS sig_n,
           CASE WHEN e.oi0 > 0 THEN 1 ELSE 0 END
         + CASE WHEN e.oi2 > 0 AND e.oi0 > e.oi2 THEN 1 ELSE 0 END
         + CASE WHEN e.rev0 > e.rev2 THEN 1 ELSE 0 END
         + CASE WHEN e.oi2 > 0 AND e.rev0 > 0 AND e.rev2 > 0 AND e.oi0 / e.rev0 > e.oi2 / e.rev2 THEN 1 ELSE 0 END
         + CASE WHEN e.la0 < e.la2 THEN 1 ELSE 0 END AS sig_yes,
           COALESCE(e.eq0 <= 0, false) OR COALESCE(e.bps <= 0, false) AS neg_book,
           -- 보통주 몫(국내, BPS 주식수가 보통주보다 3% 넘게 많을 때만) = 보통주 수 ÷ (지배 자본 ÷ BPS)
           CASE WHEN e.country = 'KR' AND e.shares > 0 AND e.eq0 > 0 AND e.bps > 0 AND e.eq0 / e.bps > 1.03 * e.shares
                THEN e.shares / (e.eq0 / e.bps) END AS common_share
    FROM earn e
)
SELECT c.stock_id, c.fy_count, c.end0 AS fy_end, c.ni0, c.oi0, c.ni1, c.oi1, c.ni2, c.oi2,
       CASE WHEN c.fy_count = 3 AND c.e1 IS NOT NULL AND c.e2 IS NOT NULL THEN 1 ELSE 0 END
     + CASE WHEN c.end2 IS NOT NULL AND (c.fin OR c.sig_n >= 3) THEN 1 ELSE 0 END AS value_rules,
       c.last_trade AS price_date,
       v.metric, v.factor,
       CASE WHEN c.halted OR (c.ca_done > c.end0 AND v.factor = 'value') THEN NULL ELSE v.raw_value END AS raw_value,
       CASE WHEN c.halted OR (c.ca_done > c.end0 AND v.factor = 'value') THEN NULL ELSE v.note END AS note,
       CASE WHEN c.halted THEN '거래 정지 — 마지막 거래일 ' || c.last_trade || '(20거래일 넘게 거래 없음)'
            WHEN c.ca_done > c.end0 AND v.factor = 'value'
            THEN '최신 FY 결산(' || c.end0 || ') 뒤 ' || c.ca_what || '(' || c.ca_done || ') — 분할 전 재무를 분할 뒤 시총·주가와 나누지 않음'
            ELSE v.null_note END AS null_note
FROM calc c
CROSS JOIN LATERAL (VALUES
    ('conservative_yield', 'value',
        CASE WHEN c.mcap > 0 THEN c.e_cons * COALESCE(c.common_share, 1) / c.mcap END,
        CASE WHEN c.e_cons IS NULL OR NOT c.mcap > 0 THEN NULL
             ELSE NULLIF(CONCAT_WS('; ',
                  CASE WHEN c.fy_count < 3 THEN '재무 이력 ' || c.fy_count || '년 — 3년 평균 없이 최신 FY 이익'
                       WHEN c.e_cons < c.e0 THEN '최신 이익이 3년 평균보다 커서 3년 평균 이익 사용(업황 정점 방지)' END,
                  CASE WHEN c.common_share IS NOT NULL
                       THEN 'BPS 주식수가 보통주보다 ' || ROUND(100 * (1 / c.common_share - 1)) || '% 많음(우선주 등) — 이익의 보통주 몫 '
                            || ROUND(100 * c.common_share) || '%만 보통주 시총과 비교' END), '') END,
        CAST(NULL AS text)),
    ('book_yield',       'value',
        CASE WHEN NOT c.neg_book THEN c.bps / NULLIF(c.close, 0) END, NULL,
        CASE WHEN c.neg_book THEN '자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음'
             WHEN c.eq0 IS NULL AND c.bps IS NULL THEN '자본 정보 없음 — 장부가 기준 저평가를 계산하지 않음' END),
    ('trap_signal',      'value',
        CASE WHEN NOT c.fin AND c.end2 IS NOT NULL AND c.sig_n >= 3 THEN CAST(c.sig_yes AS numeric) / c.sig_n END,
        NULL,
        CASE WHEN c.fin THEN '금융 업종 — 매출·영업이익 기준 신호는 쓰지 않음' END),
    ('return_on_assets', 'quality',  CASE WHEN c.ta0 > 0 THEN c.p0 / c.ta0 END, NULL, NULL),
    ('operating_margin', 'quality',  CASE WHEN NOT c.fin THEN c.oi0 / NULLIF(c.rev0, 0) END,
        NULL, CASE WHEN c.fin THEN '금융 업종 — 매출 기준 지표는 쓰지 않음' END),
    ('revenue_cagr2',    'growth',
        CASE WHEN NOT c.fin AND c.end2 IS NOT NULL AND c.rev2 > 0 AND c.rev0 IS NOT NULL
             THEN CASE WHEN c.rev0 > 0 THEN SQRT(c.rev0 / c.rev2) - 1 ELSE -1 END END,
        NULL, CASE WHEN c.fin THEN '금융 업종 — 매출 기준 지표는 쓰지 않음' END),
    -- 2년 이익 변화 ÷ 2년 전 총자산: 2년 전 흑자일 때만(흑자 전환을 이익 성장으로 세지 않음 — 매출 성장만 반영)
    ('profit_growth2',   'growth',
        CASE WHEN c.end2 IS NOT NULL AND c.ta2 > 0 AND c.p2 > 0 AND c.p0 IS NOT NULL THEN (c.p0 - c.p2) / c.ta2 END,
        NULL, CASE WHEN c.end2 IS NOT NULL AND c.p2 <= 0 THEN '2년 전 적자 — 흑자 전환은 이익 성장으로 세지 않음(매출 성장만 반영)' END),
    ('volatility',       'safety',   c.volatility_1y, NULL, NULL),
    ('liab_assets',      'safety',   CASE WHEN NOT c.fin THEN c.la0 END,
        NULL, CASE WHEN c.fin THEN '금융 업종 — 예금·보험부채가 영업 자산이라 부채 지표는 쓰지 않음' END),
    ('momentum',         'momentum', CASE WHEN c.c_252 IS NOT NULL THEN c.c_21 / c.c_252 - 1
                                          WHEN c.c_126 IS NOT NULL THEN c.c_21 / c.c_126 - 1 END,
        CASE WHEN c.c_252 IS NULL AND c.c_126 IS NOT NULL THEN '일봉 253개 미만 → 6-1개월 수익률로 대체' END, NULL)
) AS v(metric, factor, raw_value, note, null_note)
ORDER BY c.stock_id, v.metric
