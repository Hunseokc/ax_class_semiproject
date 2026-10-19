# 00. 팀원 환경 설정 프롬프트 (A · B · C · D 공통, 최초 1회)

대상 레포: https://github.com/Hunseokc/ax_class_semiproject (팀 레포) · 참조 원본: https://github.com/Hunseokc/ax_class_stockmind

## 사용법 (먼저 읽기)

1. **새 빈 폴더**를 하나 만든다. 예: `StockMind-workspace` (이미 파일이 있는 폴더, 다른 프로젝트 폴더, 바탕화면·홈 폴더 직접 사용 금지)
2. 그 빈 폴더에서 Claude Code를 실행한다.
3. 아래 코드 블록 **전체**를 붙여넣는다.
4. Claude가 고지문을 보여주면 읽고 `확인`이라고 답한다. 이후 질문(깃허브 아이디·역할·단계)에 답한다.
5. 끝나면 Claude가 알려주는 대로 **세션을 종료하고 `ax_class_semiproject` 폴더에서 Claude Code를 다시 실행**한다. (CLAUDE.md는 그 폴더에서 시작한 세션에만 적용된다.)

설정이 끝나면 폴더는 이렇게 된다.
```
StockMind-workspace/          ← 빈 폴더였던 곳
├─ ax_class_semiproject/      ← 팀 레포. 여기서만 작업·커밋·PR
└─ ax_class_stockmind/      ← 원본. 읽기 전용 정답지 (push 차단됨)
```

## 붙여넣을 프롬프트

````
너는 지금부터 StockMind 팀 프로젝트의 "개발 환경 설정 도우미"다. 아래 절차를 순서대로 실행한다. 절차에 없는 일은 하지 않는다. 각 단계의 결과를 한 줄로 보고하고, 실패하면 "문제 대처"의 안내를 출력한 뒤 거기서 멈춘다(다음 단계로 넘어가지 않는다).

대상:
- 팀 레포: https://github.com/Hunseokc/ax_class_semiproject (콜라보레이터로 이미 등록됨)
- 참조 원본(읽기 전용): https://github.com/Hunseokc/ax_class_stockmind

════════ 0단계. 고지문 출력 후 확인 받기 ════════
아무 명령도 실행하기 전에 아래 고지문을 그대로 출력하고, 사용자가 "확인"이라고 답할 때까지 기다린다.

────────────────────────────────────────
【StockMind 환경 설정 — 시작 전 고지】

① 이 프롬프트는 반드시 "새로 만든 빈 폴더"에서 실행해야 합니다. 폴더 안에 파일이 있으면 아무것도 하지 않고 중단합니다.
② 이 팀은 PR(Pull Request)로만 작업을 합칩니다.
   - main, stage1~6 브랜치에는 직접 push 할 수 없습니다 (설정이 차단합니다).
   - 내 작업은 feat/ 브랜치에서 하고, push 후 PR을 만들어 stage 브랜치로 보냅니다.
   - 강제 push(--force), .env 파일 커밋은 금지입니다. API 키는 각자 .env에만 두고 올리지 않습니다.
③ 이 설정이 하는 일 (모두 이 폴더 안에서만 일어나며 컴퓨터 전역 설정은 바꾸지 않습니다):
   1) 빈 폴더 확인  2) git·gh(GitHub CLI) 설치 확인  3) GitHub 로그인 확인  4) 레포 초대 수락·권한 확인
   5) 팀 레포 clone  6) 원본 레포 clone (push 차단)  7) 이 레포 한정 git 설정(이름·이메일·pull/push 방식)
   8) main·stage 직접 push 차단 훅 설치 (A·B·C만)  9) 내 작업 브랜치 생성  10) 점검표 출력
④ 설정이 끝나면 이 세션을 닫고 ax_class_semiproject 폴더에서 Claude Code를 새로 실행해야 팀 규칙(CLAUDE.md)이 적용됩니다.
⑤ 로그인이 필요하면 브라우저가 열리고, 몇몇 명령은 실행 허가를 물을 수 있습니다.

진행하려면 "확인"이라고 입력하세요.
────────────────────────────────────────

════════ 1단계. 빈 폴더 확인 ════════
- 현재 폴더(pwd)를 보여주고, `ls -A`로 내용을 확인한다. `.claude` 폴더 하나만 있는 경우는 빈 폴더로 본다.
- 그 외 파일·폴더가 있으면: "빈 폴더가 아닙니다. 새 빈 폴더를 만들어 그 안에서 다시 실행하세요."를 출력하고 중단한다. 어떤 것도 지우거나 옮기지 않는다.

════════ 2단계. 도구 확인 ════════
- `git --version`, `gh --version`을 실행한다.
- 없으면 설치 방법만 안내하고 중단한다 (자동 설치하지 않는다):
  · git — Windows: https://git-scm.com/download/win (Git Bash 포함) / macOS: `xcode-select --install`
  · gh — Windows: `winget install --id GitHub.cli` / macOS: `brew install gh` / 공식: https://cli.github.com
  설치 후 터미널·Claude Code를 새로 열어 이 프롬프트를 다시 실행하도록 안내한다.
- `docker --version`도 확인한다. 없으면 "지금은 괜찮지만 Stage 1 실행 전에 Docker Desktop이 필요합니다"라고 경고만 하고 계속 진행한다.

════════ 3단계. GitHub 로그인 ════════
- `gh auth status`로 확인한다.
- 로그인이 안 되어 있으면 사용자에게 다음을 안내하고 기다린다:
  "Claude Code 입력창에 `! gh auth login` 을 입력하세요. GitHub.com → HTTPS → 'Login with a web browser' 순서로 선택하고, 브라우저에서 로그인하세요. 끝나면 '완료'라고 알려주세요."
  (`!`는 이 세션에서 직접 명령을 실행하는 접두어다. 너는 이 대화형 명령을 직접 실행하지 않는다.)
- 사용자가 완료하면 `gh auth status`를 다시 확인한다.
- 성공하면 `gh auth setup-git`을 실행해 git이 gh의 인증을 쓰도록 한다. (전역 credential 설정에 gh 항목이 추가되는 것은 정상이며, 이것이 이 설정에서 유일한 전역 변경임을 사용자에게 말해 준다.)
- GitHub 아이디를 `gh api user --jq .login`, 숫자 id를 `gh api user --jq .id`로 읽어 둔다.

════════ 4단계. 레포 초대 수락·권한 확인 ════════
- 대기 중인 초대 확인:
  `gh api user/repository_invitations --jq '.[] | select(.repository.full_name=="Hunseokc/ax_class_semiproject") | .id'`
- id가 나오면 `gh api -X PATCH user/repository_invitations/<id>`로 수락하고 "초대를 수락했습니다"라고 보고한다.
- 이어서 권한 확인: `gh api repos/Hunseokc/ax_class_semiproject --jq .permissions.push`
  · `true`면 통과
  · 그 외/404/403이면 "문제 대처 — 권한"을 출력하고 중단한다.

════════ 5단계. 팀 레포 clone ════════
- `git clone https://github.com/Hunseokc/ax_class_semiproject.git`
- clone 후 레포가 비어 있는지 확인한다: `git -C ax_class_semiproject rev-parse HEAD` 가 실패하면(커밋 없음) "문제 대처 — 빈 레포"를 출력하고 중단한다.
- 다음 파일이 있는지 확인하고 결과를 표시한다: `CLAUDE.md`, `.github/pull_request_template.md`, `team/prompts/`.
  하나라도 없으면 경고로 표시하고 "시니어에게 알리세요"를 덧붙인다(중단은 하지 않는다).

════════ 6단계. 원본 레포 clone (읽기 전용) ════════
- `git clone https://github.com/Hunseokc/ax_class_stockmind.git`
- 실수로 push 하지 못하도록: `git -C ax_class_stockmind remote set-url --push origin DISABLED_READ_ONLY`
- 이 폴더는 참조용이다. 절대 수정하지 않는다.

════════ 7단계. 사용자 정보 입력 + 이 레포 한정 git 설정 ════════
AskUserQuestion(없으면 일반 질문)으로 아래를 묻는다.
1) 역할: A(프론트엔드) / B(백엔드 API·DB) / C(데이터 수집·분석 로직) / D(시니어·통합)
2) 현재 진행할 단계: 1 / 2 / 3 / 4 / 5 / 6 (단계 번호는 시니어가 알려준 것)
3) 커밋에 쓸 이메일: ① GitHub noreply 주소(권장, 실제 이메일이 공개되지 않음): `<id>+<login>@users.noreply.github.com` ② 직접 입력
   커밋에 쓸 이름: 기본값은 GitHub 아이디. 팀원 본인을 알아볼 수 있는 이름이면 변경해도 된다.

그다음 `ax_class_semiproject` 안에서 **--local(이 레포 한정)** 으로만 설정한다 (--global 금지):
```
git config --local user.name  "<이름>"
git config --local user.email "<이메일>"
git config --local pull.rebase false        # pull은 merge 방식 (충돌 시 이해하기 쉬움)
git config --local push.autoSetupRemote true # 첫 push에서 upstream 자동 설정
git config --local fetch.prune true
git config --local init.defaultBranch main
git config --local core.autocrlf input       # Windows 줄바꿈 혼입 방지 (레포의 .gitattributes와 함께 동작)
```

════════ 8단계. main·stage 직접 push 차단 훅 (역할 A·B·C만) ════════
- 역할이 D면 이 단계를 건너뛴다 (시니어는 stage 브랜치에서 충돌 해결 후 push 해야 하므로). 건너뛴 사실을 보고한다.
- A·B·C: `ax_class_semiproject/.git/hooks/pre-push` 파일을 아래 내용 그대로 Write 도구로 만든다. 그리고 실행 권한을 준다 (`chmod +x`; Windows Git Bash에서도 동일하게 실행).
```
#!/bin/sh
# StockMind 팀 규칙: main, stage1~6 로는 직접 push 금지 (PR로만 합친다)
while read local_ref local_sha remote_ref remote_sha; do
  if echo "$remote_ref" | grep -Eq '^refs/heads/(main|stage[0-9]+)$'; then
    echo "" >&2
    echo "✖ $remote_ref 로 직접 push 할 수 없습니다." >&2
    echo "  feat/ 브랜치에서 push 한 뒤 PR을 만드세요:  gh pr create --base stage<번호>" >&2
    echo "" >&2
    exit 1
  fi
done
exit 0
```
- 훅 동작 검증(ax_class_semiproject 폴더 안에서, 실제 원격에는 어떤 push도 하지 않는다):
  `echo "refs/heads/x 0 refs/heads/main 0" | .git/hooks/pre-push origin url; echo $?`  → 1 이어야 하고,
  `echo "refs/heads/x 0 refs/heads/feat/s1-a-x 0" | .git/hooks/pre-push origin url; echo $?` → 0 이어야 한다.
  기대와 다르면 훅 파일 내용을 다시 쓴다.

════════ 9단계. 내 작업 브랜치 만들기 ════════
- `git -C ax_class_semiproject fetch origin`
- 원격에 `stage<단계>` 브랜치가 있는지 확인: `git -C ax_class_semiproject ls-remote --heads origin stage<단계>`
  없으면 "문제 대처 — stage 브랜치 없음"을 출력하고 중단한다.
- 브랜치 이름은 `ax_class_semiproject/team/prompts/stage<단계>.md`에서 읽는다: 파일의 "## 팀원 <역할>" 절 안의 `[브랜치]` 줄. 한 절에 브랜치가 두 개(①②)면 ①을 쓰고 사용자에게 ②는 ①을 PR 한 뒤에 만든다고 알려 준다. 역할이 D면 브랜치를 만들지 않고 `stage<단계>`를 체크아웃만 한다 (`git switch stage<단계>`).
- A·B·C: `git -C ax_class_semiproject switch -c <브랜치> origin/stage<단계>` 로 stage 브랜치에서 갈라져 나오게 만든다. (main이 아니라 stage<단계> 기준이다.)

════════ 10단계. 점검표 출력 ════════
다음 명령을 실행해 결과를 확인하고, 아래 형식의 표로 정리해 출력한다. (✔/✖)
- `gh auth status` → GitHub 로그인
- `gh api repos/Hunseokc/ax_class_semiproject --jq .permissions.push` → 쓰기 권한
- `git -C ax_class_semiproject config --local user.name / user.email` → 커밋 작성자
- `git -C ax_class_semiproject remote -v` → origin이 Hunseokc/ax_class_semiproject
- `git -C ax_class_stockmind remote -v` → push 가 DISABLED_READ_ONLY
- `git -C ax_class_semiproject branch --show-current` → 내 작업 브랜치
- pre-push 훅 존재(A·B·C) / 건너뜀(D)
- CLAUDE.md · PR 템플릿 · team/prompts 존재 여부
- docker 설치 여부(경고만)
점검표에 ✖가 하나라도 있으면 해결 방법을 함께 적는다.

════════ 11단계. 마무리 안내 (아래 형식 그대로 출력, <> 는 값으로 치환) ════════
────────────────────────────────────────
✅ 설정 완료 — 역할 <A/B/C/D> · Stage <N> · 브랜치 <브랜치>

▶ 지금 할 일
1. 이 세션을 종료합니다. (`/exit`)
2. 터미널에서 `cd ax_class_semiproject` 로 이동해 `claude` 를 새로 실행합니다.
   → 이때부터 팀 규칙(CLAUDE.md)이 자동 적용됩니다. (파일 하나씩 설계 설명 → 승인 → 작성 → 돌려 보기 → 해설 → 질문 → 테스트)
3. 다음 중 하나를 입력합니다.
   - `team/prompts/stage<N>.md 의 "팀원 <X>" 절에 있는 코드 블록 프롬프트를 그대로 실행해 줘`
   - 또는 그 파일을 열어 코드 블록을 복사해 붙여넣기
4. Claude가 작업 계획표를 내면 읽고 승인한 뒤 파일 하나씩 진행합니다.
   계획표의 "파트별 확인 지점"이 중요합니다. 파트 하나가 끝날 때마다 Claude가 실제로 돌려서 "여기까지 만든 것"을 보여 줍니다.

▶ 내가 만든 것을 직접 보는 법
- 화면: 브라우저에서 http://localhost:8000/ (홈), /stocks (리스트), /stocks/KOSPI/005930 (상세)
- API: 브라우저에서 http://localhost:8000/docs → 원하는 주소를 펼치고 "Try it out" → "Execute"
- 명령: Claude Code 입력창에 `!` 를 붙여 직접 실행 (예: `! docker compose ps`)
- 잘 모르겠으면 Claude에게 "지금까지 만든 거 보여줘" 라고 하세요. 실제로 실행해서 보여 줍니다.

▶ 작업이 끝나면 PR 만드는 법
1. Claude에게 "PR 준비해 줘" 라고 합니다. (최신 코드를 받고, PR 본문 초안과 핵심 로직 설명용 빈칸 틀 3개를 줍니다 — 빈칸만 채우면 됩니다)
2. PR 본문의 "핵심 로직 설명"은 내가 직접 씁니다. AI가 대신 써 주지 않습니다.
3. 다 쓰면 Claude에게 "올려줘" 라고 합니다. Claude가 push 하고 PR을 만듭니다. (base 는 main 이 아니라 stage<N>)
   - 앞 순서 팀원 작업이 아직 머지 전이면 **Draft PR**로 올라갑니다. 기다리지 않아도 됩니다. 시니어가 내 코드를 먼저 봅니다.
   - 앞 순서 작업이 머지되면 Claude가 알아채고 최신 코드를 합쳐 테스트한 뒤 같은 PR을 **Ready**로 바꿉니다.
     (먼저 알게 되면 Claude에게 "머지됐대" 라고만 말하면 됩니다)
4. 시니어가 Ready PR을 순서대로 stage<N> 에 머지합니다. 수정 요청이 오면 같은 브랜치에 커밋하고 push 하면 PR이 갱신됩니다.

▶ 다음 단계 시작하는 법
- `ax_class_semiproject` 폴더에서 Claude Code를 새로 실행하고 "Stage <다음 번호> 시작할게, 팀원 <X>" 라고 말합니다.
  Claude가 최신 코드를 받고, 새 단계 브랜치를 만들고, 최신 프롬프트를 읽어 작업 계획표를 보여줍니다.

▶ 평소 지킬 것
- 커밋은 파일(또는 파일+테스트) 하나 단위로, 메시지는 `feat(scope): 한국어 요약`
- 최신 코드 받기(pull)는 Claude가 작업 시작·PR 준비 때마다 알아서 합니다. "코드가 없다/다르다" 싶으면 "최신 코드 받아줘" 라고 하세요.
- 담당 외 파일은 수정하지 않습니다. 필요하면 Claude가 만들어 주는 "요청 메모"를 해당 팀원에게 전달하세요.
- `ax_class_stockmind` 폴더는 읽기만 합니다.
────────────────────────────────────────

════════ 문제 대처 (실패 시 해당 안내를 출력하고 중단) ════════
- 권한(403/404): "레포 초대를 아직 수락하지 않았거나 다른 GitHub 계정으로 로그인했을 수 있습니다. https://github.com/Hunseokc/ax_class_semiproject/invitations 에서 수락하거나, `! gh auth status` 의 계정이 초대받은 계정과 같은지 확인한 뒤 새 빈 폴더에서 다시 실행하세요. 계속 안 되면 시니어에게 콜라보레이터 등록 여부를 확인하세요."
- 빈 레포: "팀 레포에 아직 커밋이 없습니다. 시니어(D)가 Stage 0(뼈대)과 CLAUDE.md·team/ 폴더를 먼저 push 해야 합니다. 시니어에게 알린 뒤, 완료 연락을 받으면 새 빈 폴더에서 다시 실행하세요."
- stage 브랜치 없음: "시니어가 stage<N> 브랜치를 아직 만들지 않았습니다. 시니어에게 단계 시작 여부를 확인하세요. (ax_class_semiproject 와 ax_class_stockmind 는 이미 clone 되어 있으니 폴더를 지우지 말고, 시니어 안내 후 `cd ax_class_semiproject && git fetch` 로 이어서 하거나 새 빈 폴더에서 처음부터 다시 하세요.)"
- 네트워크/TLS 오류(백신·사내 프록시): "인증서 오류라면 백신(Norton 등)의 HTTPS 검사를 잠시 끄거나 시니어가 안내하는 루트 인증서 설정을 적용한 뒤 다시 시도하세요."

시작: 0단계의 고지문만 출력하고 "확인"을 기다려라.
````
