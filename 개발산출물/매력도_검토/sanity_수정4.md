# sanity 결과 — 수정 4 (검토_장부 D-039~D-042, PR A 수집 · PR B 표본·시총·분류 · PR C 계산 규칙)

> **데이터**: 이 PC(Windows)에 새로 적재한 개발 DB `stockdb_fix4`(로컬 Docker). 수정 3 때와 같은 순서(`init-db` → `master` → `listing` → fx·indices·prices → 미국 시가총액 순위 → 노출 종목 재무·밸류에이션 → `benchmark --reselect` → 비교군 재무 3년 → 밸류에이션 → `scores`)로 **옛 코드(origin/main, v2.5)** 를 돌려 기준선을 만들었다. 일봉·밸류에이션 2026-10-27. 라운드 4의 `stockdb_fix3`(맥)와 비교군 선정일·데이터 기준일이 달라 기준선부터 수치가 조금 다르다 — 수정 4의 효과는 **이 DB 기준선과의 차이**로 읽는다.
> 단계마다 그 브랜치 코드로 같은 DB에 이어서 실행했다. 기준선 점수 행은 점수 계산일을 2026-10-27로 옮겨 두고(R9가 이전 모델과 비교하게), PR A·B·C는 2026-10-28.
> - PR A: `migrate 016_fin_collection` → `financials --scope sample`(미국·국내 1/2·국내 2/2 동시) → `scores` → `sanity`
> - PR B: `migrate 017_us_cap` → `master --offline` → 미국 시가총액 순위(`rank_us` force) → `benchmark --reselect` → `sanity`
> - PR C: `prices` → `benchmark`(07:00 흐름 — 일봉·밸류에이션·재무 뒤 점수) → `sanity`
>
> **4칸**(D-030): 통과 / 감수한 실패(known_fail·결정 번호) / target 실패 / 미검증(데이터 없음·실행 불가). required 실패는 따로 적는다(종료를 막음).
>
> **화면 코드 검사 6개**(SCREEN-no-phi-number·SCREEN-theme-position·SCREEN-theme-position-momentum·FIN-pb-roe-view·GROWTH-label·FIN-no-composite)는 측정 컨테이너에 `frontend/`를 마운트하지 않아 기준선·PR A·PR B 표에서 **화면 코드 부분만** 실패로 나온다(DB 부분은 모두 맞음). 수정 4는 `frontend/`를 바꾸지 않았고(origin/main과 차이 0줄), PR C 최종 점수에 `frontend/`를 마운트해 다시 돌리면 6개 모두 통과한다(PR C 절). 아래 요약의 '화면 코드 제외' 칸은 이 6개를 뺀 수다.

## 기준선 — 모델 v2.5 (수정 4 전, 같은 DB)

**통과 44 · 감수한 실패 2 · target 실패 3 · 미검증 3** · required 실패 10 (화면 코드 6개를 빼면 **4**)

- 화면 코드 밖 required 실패 4개: SEC-tags-scored(OSK가 이 DB 표본에 없음 — 기계·로봇 미국 시가총액 상위 10 밖), DAEHAN-SHIPBUILDING-value(대한조선 가치 15위 ≤ 20), MU-value(MU 가치 10위 ≤ 10), R10-independent-benchmark(이상 20 > 16, 거짓 음성 20). 수정 3 최종(맥 `stockdb_fix3`)의 required 실패는 대한조선·R10 두 개였다 — 비교군을 오늘 시가총액으로 다시 고른 차이다. 합격선은 이 데이터로 바꾸지 않는다(D-030·D-041).
- 미검증 3: THEME-main-business-unjudged(판정 못한 6종목), INSURER-oci-roe(총포괄이익 미수집), DEPLOY-sanity-ran(배포 DB에서만).

<details><summary>기준선 전체 표</summary>

required(known_fail 포함) 51개: 통과 38 + 감수한 실패 2 · 미검증 1 (DEPLOY-sanity-ran) · 실패 10

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 137/264 가치 140/264 성장 174/264 |
| RIVN-growth | required | 통과 | RIVN: 균형 243/264 가치 254/264 성장 180/264 |
| INTC-growth | required | 통과 | INTC: 균형 249/264 가치 248/264 성장 245/264 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 표본에 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 286/297 가치 285/297 성장 286/297 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 75/297 가치 69/297 성장 194/297 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0882 (기대 0.0882) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1326 (기대 0.1326) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 24/264 가치 105/264 성장 8/264 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 64/297 가치 48/297 성장 167/297 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 64/297 가치 48/297 성장 167/297 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 실패 | 없음 ['상위 ${topPercent'] · 남음 ['toPos(', 'erf('] |
| SCREEN-theme-position | required | 실패 | 없음 ['theme_position', '소속 테마'] · 남음 [] |
| SCREEN-theme-position-momentum | required | 실패 | 없음 ['THEME_FACTORS = ["value", "quality", "growth", "momentum"]', '중립화 전'] · 남음 [] |
| GLD-IAU-not-scored | required | 통과 | GLD: 표본에 없음 · IAU: 표본에 없음 |
| DAOU-family | required | 통과 | 023590: 표본에 없음 |
| HOLDING-equity-method | required | 통과 | 000240: 표본에 없음 |
| FIN-consolidated-nonfinancial | required | 통과 | 000880: 표본에 없음 · 023590: 표본에 없음 |
| SKSQUARE-not-scored | required | 통과 | 402340: 표본에 없음 |
| SEC-tags-scored | required | 실패 | XOM: 균형 77/264 가치 62/264 성장 134/264 · CLX: 균형 216/264 가치 205/264 성장 204/264 · EMN: 균형 129/264 가치 74/264 성장 173/264 · EXP: 균형 147/264 가치 82/264 성장 199/264 · GTX: 균형 169/264 가치 165/264 성장 144/264 · OSK: 표본에 없음 · AEIS: 균형 205/264 가치 197/264 성장 190/264 |
| DAEHAN-SHIPBUILDING-value | required | 실패 | 439260: 균형 49/297 가치 15/297 성장 113/297 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 실패 | MU: 균형 1/264 가치 10/264 성장 1/264 |
| SIRI-value | required | 통과 | SIRI: 균형 137/264 가치 140/264 성장 174/264 |
| KGSTEEL-value | target | 통과 | 016380: 균형 57/297 가치 13/297 성장 177/297 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 27/264 가치 1/264 성장 109/264 |
| DNAUTO-weak-theme-first | target | 통과 | 007340: 균형 15/297 가치 9/297 성장 25/297 |
| THEME-main-business-KR | required | 통과 | 35종목 중 다름 0 [] |
| THEME-main-business-US | required | 통과 | 30종목 중 다름 0 [] |
| THEME-main-business-unjudged | target | 확인 못함 | 판정 못함 048410 정밀화학 · HON 항공우주·방산 · CTAS 레저·의류·소비서비스 · FISV 인터넷 플랫폼 · CPAY 인터넷 플랫폼 · PYPL 인터넷 플랫폼 |
| SPEAR-business-combination-growth | known_fail | 실패(감수 D-005) | 347700: 균형 54/297 가치 198/297 성장 3/297 |
| BOBCAT-currency | required | 통과 | 지표 0.0872 vs KRX EPS÷종가 0.0859 (비율 1.02) |
| NEG-EQUITY-bp | required | 통과 | BKNG: 자본 -5,578,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · HCA: 자본 -6,027,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · MCD: 자본 -1,791,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · PM: 자본 -9,994,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · YUM: 자본 -7,325,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 |
| FIN-pb-roe-view | required | 실패 | US 보험 10개 regression · US 은행·카드 7개 median · US 증권·자산운용 10개 regression · KR 보험 10개 regression · KR 은행·카드 10개 regression · KR 증권·자산운용 10개 regression · 규칙 어긋남 [] · 없음 ['financial_profile', 'ROE 대비 P/B', '회귀선', 'P/E'] · 남음 [] |
| INSURER-oci-roe | target | 확인 못함 | 총포괄이익(지배)을 아직 수집하지 않음 — D-033 수집 뒤 required |
| GROWTH-label | required | 실패 | 없음 ['label: "과거 실적 성장"'] · 남음 ['label: "성장성"'] · 성장 프리셋 설명 '최근 실적이 크게 늘어난 회사 중심 — 미래 성장 예측이 아닙니다' |
| MSI-balanced | target | 실패 | MSI: 균형 189/264 가치 178/264 성장 195/264 |
| ADP-balanced | target | 실패 | ADP: 균형 150/264 가치 123/264 성장 168/264 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.3481 · PM -0.2101 vs 잠식+적자 중앙값 -2.4206000000000003 (n=2) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 2 ['039420', '016380'] |
| R4-cycle-value | target | 통과 | US 3 ['EPD', 'MLI', 'MU'] / KR 1 ['003650'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 9종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 6.4% / KR 14.8% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 7 US성장 8 US균형 7 US가치 6 KR위험 6 KR성장 8 KR균형 6 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 모델 점수 없음 — 비교 대상 없음 |
| R10-independent-benchmark | required | 실패 | 이상 종목 20(≤16) · 우량 거짓 음성 20(≤27) · {'US위험': 4, 'US성장': 2, 'US균형': 1, 'US가치': 1, 'KR위험': 4, 'KR성장': 3, 'KR균형': 3, 'KR가치': 2} |
| TRAP-penalty-only | required | 통과 | 555종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 29개 (기록만) · US위험 3['IRDM', 'SW', 'IPAR'] US성장 1['IRDM'] US균형 3['IPAR', 'VZ', 'NEU'] US가치 4['T', 'DIS', 'FSLR', 'EXEL'] KR위험 3['457190', '462870', '024840'] KR성장 4['462870', '457190', '112610', '268280'] KR균형 6['236200', '268280', '458870', '068270', '007340', '018290'] KR가치 5['018290', '145020', '007340', '236200', '214150'] |
| THEME-position-raw | required | 통과 | 테마·팩터 315칸 중 차이 0 [] |
| CLIP-order | required | 통과 | 18개 지표 최저 0.58 |
| CURRENCY-krw | required | 통과 | 593개 값 중 50배 넘게 어긋남 0 [] |
| NEG-EQUITY-no-bp | required | 통과 | 자본 ≤ 0 20종목 ['ABBV', 'PM', 'DELL', 'MCD', 'MO', 'SBUX', 'MCK', 'BKNG', 'LOW', 'MAR', 'HCA', 'EPD'] 중 B/P 있음 0 [] |
| ONEOFF-badge-recurring | required | 통과 | 배지 47개 중 단정 문구 0 [] |
| PREF-share-basis | required | 통과 | 대상 23종목 ['005930(+13%)', '005380(+29%)', '097950(+6%)', '000210(+8%)', '375500(+8%)', '051900(+12%)', '066570(+11%)', '051910(+11%)'] · 다름 0 [] |
| FIN-no-composite | required | 실패 | 금융 60종목 중 종합 점수 있음 0 [] · 홈 금융 순위 행 0 · 홈 금융 탭이 업종 비교가 아님 |
| DEPLOY-sanity-ran | required | 확인 못함 | 배포 DB Job(--save --env deploy)에서만 확인 — 이번 실행은 기록 안 함 |
| TOP20-theme-reviewed | target | 통과 | 고유 77종목 (기록만) · US위험 16['MU', 'FIX', 'STX', 'LITE', 'SCCO', 'NEM', 'WDC', 'IRDM', 'EXEL', 'POWL', 'LLY', 'MNST', 'MRK', 'HALO', 'SW', 'IPAR'] US성장 15['MU', 'STX', 'FIX', 'NEM', 'SCCO', 'WDC', 'EXEL', 'LLY', 'POWL', 'LITE', 'IRDM', 'CDE', 'MNST', 'APH', 'PM'] US균형 18['MU', 'MNST', 'EXEL', 'NEM', 'MLI', 'IPAR', 'JNJ', 'MRK', 'EPD', 'SCCO', 'FAST', 'DUK', 'VZ', 'NEU', 'CF', 'AEP', 'D', 'PM'] US가치 19['T', 'PHM', 'EPD', 'DUK', 'TOL', 'MLI', 'VZ', 'MNST', 'GNTX', 'MU', 'IPAR', 'DIS', 'FISV', 'PFE', 'AEP', 'EXEL', 'D', 'MCD', 'JNJ'] KR위험 17['458870', '278470', '462870', '161390', '062040', '024840', '080220', '440110', '236200', '041830', '000500', '257720', '131290', '307950', '009150', '003230', '483650'] KR성장 16['458870', '462870', '278470', '257720', '062040', '003230', '236200', '161390', '483650', '042700', '214150', '080220', '268280', '218410', '031980', '214450'] KR균형 17['462870', '236200', '161390', '039420', '268280', '271560', '458870', '214150', '259960', '145020', '257720', '033780', '062040', '278470', '041830', '002960', '018290'] KR가치 19['462870', '039420', '071320', '271560', '018290', '003480', '145020', '161390', '003650', '236200', '259960', '016380', '093050', '439260', '005880', '004690', '214150', '017940', '073240'] |

</details>

## PR A — 수집 (D-039 한 경로 재수집 · D-033 확장 · 20-F · LP 자본), 모델 v2.5 그대로

**통과 47 · 감수한 실패 2 · target 실패 3 · 미검증 3** · required 실패 10 (화면 코드 6개를 빼면 **4** — 기준선과 같음)

- 새 required 3개 모두 통과:
  - DATA-dart-fy-path — 국내 표본 327종목 FY가 모두 `path=DART_API`, 사유 없이 빠진 해 0. 시프트업(462870) FY 2023~2025, 대한조선(439260) 2024~2025(그 앞 해는 '직전 연도 없음' 사유 — 2025년 상장), 이마트(139480) 2021~2025.
  - DATA-sec-op-path — 미국 표본 FY 1,453행 모두 현재 코드 경로(`SEC_API`·`YFINANCE`). yfinance 보완 결산기가 있는 종목 7(AMRZ·CLS·CLX·GEV·JHX·MH·SW). 실행기는 외부를 부르지 않으므로 라운드 4 제안의 '다시 받은 값과 5% 안'을 '현재 코드가 쓴 행'으로 확인한다(변경안과 다른 점).
  - LP-equity-not-zero — 자본 0 & 자산 − 부채 ≠ 0 종목 0. EPD는 파트너 자본(PartnersCapital)으로 채움 → NEG-EQUITY-no-bp의 자본 ≤ 0 목록에서 EPD가 빠짐(20 → 19종목).
- required 실패는 기준선과 같은 4개(+ 화면 코드 6). 계산 규칙을 바꾸지 않아 점수도 거의 그대로다.
- 순위 영향(기준선 → PR A, 일반 묶음 × 프리셋 4): 2,244건 |Δ| 중앙값 **0계단**, 최대 4, 20계단 이상 0건. 이 DB는 기준선도 현재 코드로 새로 받은 재무라 한 경로 재수집의 차이가 작다 — 배포 DB(수정 1 이전 경로 값이 남은 R4-2)에서 차이가 난다. 바뀐 것: EPD 가치 3 → 7위(자본 0.00 → 파트너 자본, B/P가 생김), XOM 가치 62 → 65위.

<details><summary>PR A 전체 표</summary>

required(known_fail 포함) 54개: 통과 41 + 감수한 실패 2 · 미검증 1 (DEPLOY-sanity-ran) · 실패 10

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 137/264 가치 140/264 성장 174/264 |
| RIVN-growth | required | 통과 | RIVN: 균형 243/264 가치 254/264 성장 180/264 |
| INTC-growth | required | 통과 | INTC: 균형 249/264 가치 248/264 성장 245/264 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 표본에 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 286/297 가치 285/297 성장 286/297 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 75/297 가치 69/297 성장 194/297 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0882 (기대 0.0882) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1326 (기대 0.1326) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 24/264 가치 105/264 성장 8/264 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 64/297 가치 48/297 성장 167/297 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 64/297 가치 48/297 성장 167/297 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 실패 | 없음 ['상위 ${topPercent'] · 남음 ['toPos(', 'erf('] |
| SCREEN-theme-position | required | 실패 | 없음 ['theme_position', '소속 테마'] · 남음 [] |
| SCREEN-theme-position-momentum | required | 실패 | 없음 ['THEME_FACTORS = ["value", "quality", "growth", "momentum"]', '중립화 전'] · 남음 [] |
| GLD-IAU-not-scored | required | 통과 | GLD: 표본에 없음 · IAU: 표본에 없음 |
| DAOU-family | required | 통과 | 023590: 표본에 없음 |
| HOLDING-equity-method | required | 통과 | 000240: 표본에 없음 |
| FIN-consolidated-nonfinancial | required | 통과 | 000880: 표본에 없음 · 023590: 표본에 없음 |
| SKSQUARE-not-scored | required | 통과 | 402340: 표본에 없음 |
| SEC-tags-scored | required | 실패 | XOM: 균형 78/264 가치 65/264 성장 135/264 · CLX: 균형 216/264 가치 205/264 성장 204/264 · EMN: 균형 129/264 가치 74/264 성장 173/264 · EXP: 균형 147/264 가치 82/264 성장 199/264 · GTX: 균형 169/264 가치 165/264 성장 144/264 · OSK: 표본에 없음 · AEIS: 균형 205/264 가치 197/264 성장 190/264 |
| DAEHAN-SHIPBUILDING-value | required | 실패 | 439260: 균형 49/297 가치 15/297 성장 113/297 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 실패 | MU: 균형 1/264 가치 10/264 성장 1/264 |
| SIRI-value | required | 통과 | SIRI: 균형 137/264 가치 140/264 성장 174/264 |
| KGSTEEL-value | target | 통과 | 016380: 균형 57/297 가치 13/297 성장 177/297 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 27/264 가치 1/264 성장 109/264 |
| DNAUTO-weak-theme-first | target | 통과 | 007340: 균형 15/297 가치 9/297 성장 25/297 |
| THEME-main-business-KR | required | 통과 | 35종목 중 다름 0 [] |
| THEME-main-business-US | required | 통과 | 30종목 중 다름 0 [] |
| THEME-main-business-unjudged | target | 확인 못함 | 판정 못함 048410 정밀화학 · HON 항공우주·방산 · CTAS 레저·의류·소비서비스 · FISV 인터넷 플랫폼 · CPAY 인터넷 플랫폼 · PYPL 인터넷 플랫폼 |
| SPEAR-business-combination-growth | known_fail | 실패(감수 D-005) | 347700: 균형 54/297 가치 198/297 성장 3/297 |
| BOBCAT-currency | required | 통과 | 지표 0.0872 vs KRX EPS÷종가 0.0859 (비율 1.02) |
| NEG-EQUITY-bp | required | 통과 | BKNG: 자본 -5,578,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · HCA: 자본 -6,027,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · MCD: 자본 -1,791,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · PM: 자본 -9,994,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 · YUM: 자본 -7,325,000,000 · B/P 없음 · 자본 음수(자사주 매입 등) — 장부가 기준 저평가를 계산하지 않음 |
| FIN-pb-roe-view | required | 실패 | US 보험 10개 regression · US 은행·카드 7개 median · US 증권·자산운용 10개 regression · KR 보험 10개 regression · KR 은행·카드 10개 regression · KR 증권·자산운용 10개 regression · 규칙 어긋남 [] · 없음 ['financial_profile', 'ROE 대비 P/B', '회귀선', 'P/E'] · 남음 [] |
| INSURER-oci-roe | target | 확인 못함 | 총포괄이익(지배)을 아직 수집하지 않음 — D-033 수집 뒤 required |
| GROWTH-label | required | 실패 | 없음 ['label: "과거 실적 성장"'] · 남음 ['label: "성장성"'] · 성장 프리셋 설명 '최근 실적이 크게 늘어난 회사 중심 — 미래 성장 예측이 아닙니다' |
| MSI-balanced | target | 실패 | MSI: 균형 189/264 가치 178/264 성장 195/264 |
| ADP-balanced | target | 실패 | ADP: 균형 150/264 가치 123/264 성장 168/264 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.3481 · PM -0.2101 vs 잠식+적자 중앙값 -2.42065 (n=2) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 2 ['039420', '016380'] |
| R4-cycle-value | target | 통과 | US 3 ['MLI', 'EPD', 'MU'] / KR 1 ['003650'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 9종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 6.4% / KR 14.8% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 7 US성장 8 US균형 7 US가치 6 KR위험 6 KR성장 8 KR균형 6 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 모델 점수 없음 — 비교 대상 없음 |
| R10-independent-benchmark | required | 실패 | 이상 종목 20(≤16) · 우량 거짓 음성 20(≤27) · {'US위험': 4, 'US성장': 2, 'US균형': 1, 'US가치': 1, 'KR위험': 4, 'KR성장': 3, 'KR균형': 3, 'KR가치': 2} |
| TRAP-penalty-only | required | 통과 | 555종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 29개 (기록만) · US위험 3['IRDM', 'SW', 'IPAR'] US성장 1['IRDM'] US균형 3['IPAR', 'VZ', 'NEU'] US가치 4['T', 'DIS', 'FSLR', 'EXEL'] KR위험 3['457190', '462870', '024840'] KR성장 4['462870', '457190', '112610', '268280'] KR균형 6['236200', '268280', '458870', '068270', '007340', '018290'] KR가치 5['018290', '145020', '007340', '236200', '214150'] |
| THEME-position-raw | required | 통과 | 테마·팩터 315칸 중 차이 0 [] |
| CLIP-order | required | 통과 | 18개 지표 최저 0.58 |
| CURRENCY-krw | required | 통과 | 593개 값 중 50배 넘게 어긋남 0 [] |
| NEG-EQUITY-no-bp | required | 통과 | 자본 ≤ 0 19종목 ['ABBV', 'PM', 'DELL', 'MCD', 'MO', 'SBUX', 'MCK', 'BKNG', 'LOW', 'MAR', 'HCA', 'HLT'] 중 B/P 있음 0 [] |
| ONEOFF-badge-recurring | required | 통과 | 배지 47개 중 단정 문구 0 [] |
| PREF-share-basis | required | 통과 | 대상 23종목 ['005930(+13%)', '005380(+29%)', '097950(+6%)', '000210(+8%)', '375500(+8%)', '051900(+12%)', '066570(+11%)', '051910(+11%)'] · 다름 0 [] |
| FIN-no-composite | required | 실패 | 금융 60종목 중 종합 점수 있음 0 [] · 홈 금융 순위 행 0 · 홈 금융 탭이 업종 비교가 아님 |
| DEPLOY-sanity-ran | required | 확인 못함 | 배포 DB Job(--save --env deploy)에서만 확인 — 이번 실행은 기록 안 함 |
| TOP20-theme-reviewed | target | 통과 | 고유 77종목 (기록만) · US위험 16['MU', 'FIX', 'STX', 'LITE', 'SCCO', 'NEM', 'WDC', 'IRDM', 'EXEL', 'POWL', 'LLY', 'MNST', 'MRK', 'HALO', 'SW', 'IPAR'] US성장 15['MU', 'STX', 'FIX', 'NEM', 'SCCO', 'WDC', 'EXEL', 'LLY', 'POWL', 'LITE', 'IRDM', 'CDE', 'MNST', 'APH', 'PM'] US균형 18['MU', 'MNST', 'EXEL', 'NEM', 'MLI', 'IPAR', 'JNJ', 'MRK', 'SCCO', 'EPD', 'FAST', 'DUK', 'VZ', 'NEU', 'CF', 'AEP', 'D', 'PM'] US가치 19['T', 'PHM', 'DUK', 'TOL', 'VZ', 'MLI', 'EPD', 'MNST', 'GNTX', 'MU', 'IPAR', 'DIS', 'FISV', 'PFE', 'AEP', 'D', 'EXEL', 'MCD', 'JNJ'] KR위험 17['458870', '278470', '462870', '161390', '062040', '024840', '080220', '440110', '236200', '041830', '000500', '257720', '131290', '307950', '009150', '003230', '483650'] KR성장 16['458870', '462870', '278470', '257720', '062040', '003230', '236200', '161390', '483650', '042700', '214150', '080220', '268280', '218410', '031980', '214450'] KR균형 17['462870', '236200', '161390', '039420', '268280', '271560', '458870', '214150', '259960', '145020', '257720', '033780', '062040', '278470', '041830', '002960', '018290'] KR가치 19['462870', '039420', '071320', '271560', '018290', '003480', '145020', '161390', '003650', '236200', '259960', '016380', '093050', '439260', '005880', '004690', '214150', '017940', '073240'] |
| DATA-dart-fy-path | required | 통과 | 국내 표본 327종목 · API 밖 경로 0 [] · 사유 없이 빠진 해 0 [] · 462870 FY [2023, 2024, 2025] · 439260 FY [2024, 2025] · 139480 FY [2021, 2022, 2023, 2024, 2025] |
| DATA-sec-op-path | required | 통과 | 미국 표본 FY 1453행 · 현재 코드 경로가 아닌 종목 0 [] · yfinance 보완 결산기가 있는 종목 7 ['AMRZ', 'CLS', 'CLX', 'GEV', 'JHX', 'MH', 'SW'] |
| LP-equity-not-zero | required | 통과 | 자본 0 · 자산−부채 ≠ 0: 0 [] · 파트너 자본·자산−부채로 채운 종목 ['EPD'] |

</details>
