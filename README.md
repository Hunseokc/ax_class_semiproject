# StockMind

국내(KOSPI·KOSDAQ)·미국(NASDAQ) 주식의 시세·지수·환율·재무·공시를 수집해 PostgreSQL에 구조화하고, FastAPI 조회·분석 API와 바닐라 HTML/CSS/JS 화면으로 제공하는 주식 분석 대시보드입니다. 4인 팀(시니어 1 · 주니어 3)이 6단계로 나눠 만듭니다.

- 완성본(읽기 전용 참조): https://github.com/Hunseokc/ax_class_semiproject
- 역할·기능 오너: [team/01_역할분담.md](team/01_역할분담.md)
- 단계별 파일 분해표: [team/02_단계별_로드맵.md](team/02_단계별_로드맵.md)
- 단계별 시작 프롬프트: [team/prompts/](team/prompts/)

---

## 팀원이 처음 할 일 (최초 1회)

1. 컴퓨터에 **새 빈 폴더**를 만듭니다. 이미 다른 git 저장소 안이 아닌 곳이 좋습니다.
2. 그 폴더에서 Claude Code를 실행하고 [team/prompts/00_setup.md](team/prompts/00_setup.md)의 내용을 붙여넣습니다.
   - git·gh(GitHub CLI) 설치 확인, GitHub 로그인, clone, git 설정, push 차단 훅, 작업 브랜치 생성까지 자동으로 진행합니다.
   - 도중에 역할(A/B/C/D)과 현재 단계 번호를 묻습니다. 시니어가 알려 준 값을 입력하세요.
3. 설정이 끝나면 세션을 닫고 `ax_stockmind` 폴더로 이동해 `claude`를 **새로 실행**합니다. 그때부터 [CLAUDE.md](CLAUDE.md)의 팀 규칙이 적용됩니다.
4. 아래처럼 입력해 내 파트의 작업을 시작합니다.
   ```
   team/prompts/stage<N>.md 의 "팀원 <X>" 절에 있는 코드 블록 프롬프트를 그대로 실행해 줘
   ```
5. Claude가 **작업 계획표**를 냅니다. 읽고 승인한 뒤 파일 하나씩 진행합니다.

Stage 1 실행 전에는 Docker Desktop이 필요합니다.

## 작업 방식

Claude Code는 파일 하나마다 아래 순서를 따릅니다.

> 설계 설명 → 내 승인 → 작성 → 코드 해설 → 이해 확인 질문 → 테스트

- 내가 직접 설명할 수 있는 코드만 PR로 올립니다.
- 담당 외 파일은 수정하지 않습니다. 필요하면 Claude가 만들어 주는 요청 메모를 해당 팀원에게 전달하세요.
- 이번 단계 범위 밖의 기능은 추가하지 않습니다.

## 브랜치와 PR

```
feat/s<단계>-<a|b|c>-<기능>  ──PR──▶  stage<단계>  ──PR──▶  main
```

- `main`, `stage1~6`에는 직접 push 할 수 없습니다. 항상 PR로만 합칩니다.
- 내 브랜치는 `main`이 아니라 `stage<N>`에서 갈라져 나옵니다.
- 커밋은 파일(또는 파일+테스트) 하나 단위로, 메시지는 `feat(scope): 한국어 요약` 형식입니다.
- 강제 push(`--force`)와 `.env` 커밋은 금지입니다. API 키는 각자 `.env`에만 둡니다.

### 작업을 마치고 PR 올리기

1. Claude에게 "PR 준비해 줘"라고 합니다. PR 본문 초안과 확인 질문 3개를 줍니다.
2. PR 본문의 **핵심 로직 설명**은 내가 직접 씁니다.
3. `git push` (첫 push는 upstream이 자동 설정됩니다)
4. `gh pr create --base stage<N> --title "[S<N>-<X>] <기능 한 줄>"` — base는 반드시 `stage<N>`입니다. 본문에는 [PR 템플릿](.github/pull_request_template.md)이 열립니다.
5. 시니어가 리뷰 후 `stage<N>`에 머지합니다. 수정 요청이 오면 같은 브랜치에 커밋하고 push 하면 PR이 갱신됩니다.

### 다른 팀원의 작업을 가져오기

다른 팀원의 PR이 `stage<N>`에 머지된 뒤에는 아래 명령을 씁니다.

```bash
git fetch origin
git merge origin/stage<N>
```

---

## 시니어(D) 운영 순서

레포에 키트(`CLAUDE.md`, `.github/`, `team/`)가 올라간 상태에서 진행합니다.

1. [team/prompts/stage0_senior.md](team/prompts/stage0_senior.md)로 Stage 0(뼈대)를 만들어 `main`에 올리고 태그 `v0.1`을 답니다.
2. `git push origin main:stage1`로 단계 브랜치를 만듭니다. 이후 단계도 `main:stage<N>` 형식입니다.
3. GitHub 설정 → Branches에서 `main`과 `stage*`에 **PR 필수 + 승인 1명** 보호 규칙을 켭니다.
4. 팀원에게 [team/prompts/00_setup.md](team/prompts/00_setup.md)와 단계 번호, 역할을 전달합니다.
5. 팀원 PR을 리뷰해 `stage<N>`에 머지합니다. 머지 방식은 **Merge commit**입니다. Squash를 쓰면 주니어의 커밋이 본인 계정으로 남지 않습니다.
6. 단계가 끝나면 통합 테스트 후 `stage<N>`을 `main`에 머지하고 태그를 답니다.

| 단계 | 결과물 | 태그 |
|---|---|---|
| Stage 0 | 뼈대·개발 환경 | v0.1 |
| Stage 1 | MVP — 샘플 데이터로 리스트·상세·지수 | v1.0 |
| Stage 2 | 사용자 기능 — 관심종목·모의 포트폴리오 | v2.0 |
| Stage 3 | 실데이터 — 4개 소스 수집·4시간 갱신 | v3.0 |
| Stage 4 | 분석 — 매력도·경쟁 비교·통계 | v4.0 |
| Stage 5 | 고도화 — 메모·목표가·통계 확장 | v5.0 |
| Stage 6 | 홈 대시보드 개편·상단 검색·최종 문서 | v6.0 |

## 폴더 구조

```
ax_stockmind/
├─ CLAUDE.md                        Claude Code 작업 규칙
├─ .github/pull_request_template.md PR 양식
├─ team/                            역할 분담, 로드맵, 단계별 프롬프트
├─ backend/                         FastAPI·DB (Stage 0부터 생성)
├─ frontend/                        바닐라 HTML/CSS/JS (Stage 0부터 생성)
└─ docs/                            기획·요구사항·도메인 모델 (Stage 0부터 생성)
```

작업 폴더에서는 `ax_stockmind/`와 나란히 `ax_class_semiproject/`(원본, 읽기 전용)가 놓입니다.

> 이 README는 Stage 0 이전의 초안입니다. 실행 방법(`docker compose up` 등)은 Stage 0 완료 후 시니어가 보강합니다.
