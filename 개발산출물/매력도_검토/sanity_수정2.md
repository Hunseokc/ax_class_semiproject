# sanity 결과 — 수정 2 (검토_장부 D-023의 PR A~C)

> 데이터는 **개발 DB**(일봉 2026-10-26, 밸류에이션 2026-10-27)이고, PR마다 `python -m app.ingest scores` → `python -m app.ingest sanity`로 돌렸다.
> 배포 DB는 같은 버전을 배포하고 다시 계산해야 같은 결과가 나온다.

## PR A — V1(D-018) + 가치 함정 신호 중립화 해제 + R10 경계(D-021)

> 라운드 2 V1 측정과 같다: required 전부 통과, 이상 14 · 거짓 음성 24, 한일홀딩스 가치 41위, MU 가치 22위, 약한 테마 1등 20.

### sanity 결과 — 점수 계산일 2026-10-27 · 모델 v2.1-2026-10-27

required(known_fail 포함) 통과 **33/33**

| id | status | 결과 | 실제 값 |
|---|---|---|---|
| SIRI-growth | required | 통과 | SIRI: 균형 154/277 가치 161/277 성장 190/277 |
| RIVN-growth | required | 통과 | RIVN: 균형 265/277 가치 271/277 성장 236/277 |
| INTC-growth | required | 통과 | INTC: 균형 263/277 가치 265/277 성장 259/277 |
| LOTTE-HOLDINGS-growth | required | 통과 | 004990: 점수 없음 |
| ASIANA-growth | required | 통과 | 020560: 균형 284/298 가치 287/298 성장 289/298 |
| SARAMIN-balanced | required | 통과 | 143240: 균형 77/298 가치 63/298 성장 176/298 |
| KCC-oneoff-cut | required | 통과 | 순이익/영업이익 3.6배 → e = 0.78 × 영업이익, 지표 0.0903 (기대 0.0903) |
| MICHANG-oneoff-cut | required | 통과 | 순이익/영업이익 2.0배 → e = 0.78 × 영업이익, 지표 0.1339 (기대 0.1339) |
| KCC-MICHANG-badge | required | 통과 | 002380 있음 · 003650 있음 |
| WDC-value | required | 통과 | WDC: 균형 25/277 가치 107/277 성장 11/277 |
| HANIL-HOLDINGS-value | required | 통과 | 003300: 균형 73/298 가치 41/298 성장 156/298 |
| HANIL-HOLDINGS-value-strict | required | 통과 | 003300: 균형 73/298 가치 41/298 성장 156/298 |
| HOME-family-mix | required | 통과 | family 섞임 없음 |
| SCREEN-no-phi-number | required | 통과 | 화면 코드 확인 |
| SCREEN-theme-position | required | 통과 | 화면 코드 확인 |
| GLD-IAU-not-scored | required | 통과 | GLD: 점수 없음 · IAU: 점수 없음 |
| DAOU-family | required | 통과 | 023590: 균형 5/31 가치 2/31 성장 11/31 |
| SKSQUARE-not-scored | required | 통과 | 402340: 점수 없음 |
| SEC-tags-scored | required | 통과 | XOM: 균형 96/277 가치 90/277 성장 155/277 · CLX: 균형 208/277 가치 178/277 성장 186/277 · EMN: 균형 108/277 가치 45/277 성장 171/277 · EXP: 균형 130/277 가치 61/277 성장 192/277 · GTX: 균형 212/277 가치 233/277 성장 118/277 · OSK: 균형 28/277 가치 7/277 성장 70/277 · AEIS: 균형 235/277 가치 227/277 성장 226/277 |
| DAEHAN-SHIPBUILDING-value | required | 통과 | 439260: 균형 42/298 가치 23/298 성장 88/298 |
| CJ-LOGISTICS-history | required | 통과 | 이어지는 FY [2025, 2024, 2023] |
| MU-value | required | 통과 | MU: 균형 2/277 가치 22/277 성장 1/277 |
| SIRI-value | required | 통과 | SIRI: 균형 154/277 가치 161/277 성장 190/277 |
| KGSTEEL-value | target | 실패 | 016380: 균형 46/298 가치 8/298 성장 151/298 |
| T-value | known_fail | 실패(감수 D-001) | T: 균형 20/277 가치 1/277 성장 84/277 |
| DNAUTO-weak-theme-first | target | 통과 | 007340: 균형 2/298 가치 7/298 성장 5/298 |
| MSI-balanced | target | 실패 | MSI: 균형 222/277 가치 182/277 성장 239/277 |
| ADP-balanced | target | 실패 | ADP: 균형 187/277 가치 134/277 성장 213/277 |
| BUYBACK-vs-DISTRESSED | required | 통과 | MCK -0.1638 · PM -0.1896 vs 잠식+적자 중앙값 -2.7692 (n=1) |
| R1-oneoff-top10 | required | 통과 | 잘리지 않은 일회성 0개 [] |
| R2-turnaround-growth | required | 통과 | US 0 [] / KR 0 [] |
| R3-value-trap | required | 통과 | US 0 [] / KR 1 ['016380'] |
| R4-cycle-value | target | 실패 | US 1 ['MLI'] / KR 4 ['003650', '007340', '016380', '017940'] |
| R5-fiscal-gap-badge | required | 통과 | 대상 9종목 · 배지 없음 0 [] |
| R6-score-honesty | required | 통과 | 식 불일치 0 · 종합 순서 뒤집힘 0 · 구간 라벨 불일치 0 |
| R7-badge-inflation | target | 통과 | US 5.9% / KR 17.0% (원자재 배지 제외) |
| R8-top10-stability | target | 실패 | US위험 7 US성장 8 US균형 5 US가치 8 KR위험 7 KR성장 6 KR균형 5 KR가치 6 |
| R9-no-score-loss | required | 통과 | 이전 2026-10-26: 재무 칸 누락으로 잃음 0 [] · 재무 없음(표기 안 함, D-014) 13 ['NGG', 'MUFG', 'ENB', 'CP', 'DEO', 'HLN', 'RYAAY', 'BNTX', 'TM', 'SMFG', 'DRD', 'MESO', 'IPX'] · 점수 없음 테마 12 |
| R10-independent-benchmark | required | 통과 | 이상 종목 14(≤16) · 우량 거짓 음성 24(≤27) · {'US위험': 2, 'US성장': 1, 'US균형': 0, 'US가치': 0, 'KR위험': 3, 'KR성장': 4, 'KR균형': 3, 'KR가치': 1} |
| TRAP-penalty-only | required | 통과 | 559종목 중 양수 0 |
| WEAK-theme-first | target | 통과 | 20개 (기록만) · US위험 1['IRDM'] US성장 2['CRS', 'IRDM'] US균형 3['VZ', 'FTNT', 'IPAR'] US가치 5['T', 'OSK', 'FSLR', 'EXEL', 'DIS'] KR위험 3['007340', '322000', '181710'] KR성장 2['007340', '112610'] KR균형 2['007340', '326030'] KR가치 2['007340', '002380'] |
