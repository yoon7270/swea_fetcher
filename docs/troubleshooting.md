# 문제 해결 / FAQ

막히면 먼저 **진단 정보**를 뽑으세요. 이슈를 올릴 때 이 출력을 그대로 붙이면 됩니다 (비밀번호·쿠키·ID 는 포함되지 않습니다).

- exe: 설정 페이지 → **[진단 정보 복사]** → 이슈에 붙여넣기
- 소스:

```powershell
swea-fetch doctor
```

출력 예:

```
swea-fetch 0.6.4  (exe)
Python: 3.12.4  C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe  (출처: PATH)
OS: Windows 11 10.0.26200
설정 폴더: C:\Users\you\.swea-fetch  (.env 있음 / session.json 있음 / login_state 실패 0회 / problem_index 12건)
루트: C:\Users\you\Desktop\swea  (존재함, 주제 폴더 7개)
설정: 정상 (비밀번호 출처: keyring)
git: 2.45.1 / 저장소: C:\Users\you\Desktop\swea (main → origin/main)
로그인 상태: 세션 유효
keyring: 항목 있음
최신 버전: 0.6.4 (현재와 같음)
```

## 자주 나오는 오류

| 화면에 보이는 것 | 원인 | 조치 |
|---|---|---|
| `설정이 없습니다: SWEA_ROOT, SWEA_ID` | 첫 실행이거나 설정을 지웠음 | GUI: 설정 페이지에서 루트·ID·비밀번호 입력 후 [저장 후 로그인 확인]. CLI: `swea-fetch init` |
| `SWEA_ROOT 가 존재하는 폴더가 아닙니다` | 루트 폴더가 이동·삭제됨 | 설정 페이지에서 루트를 다시 지정 |
| `로그인 실패` / `아이디 또는 비밀번호` | ID/비밀번호 오타 | 브라우저에서 먼저 로그인이 되는지 확인 → 설정 페이지에서 비밀번호 다시 입력. **SWEA 는 5회 연속 실패 시 계정을 잠급니다.** 도구는 3회에서 스스로 멈춥니다 |
| `자동 로그인을 중단했습니다` (`LoginLocked`) | 도구의 3회 실패 가드 | 브라우저 로그인 확인 후 `%USERPROFILE%\.swea-fetch\login_state.json` 삭제 (또는 설정 페이지 [세션 삭제]) |
| `2단계 인증` (`MfaRequired`) | 계정에 MFA 가 켜져 있음 | 자동 로그인은 MFA 계정을 지원하지 않습니다 |
| `문제 번호 25730 을 찾지 못했습니다` | 색인에 없음 (새 문제 상자, Contest, 미가입 클럽) | [색인 새로고침] 체크 후 다시 → 그래도 안 되면 첨부 링크 URL 이나 `contestProbId` 를 직접 입력 ([README §번호로 못 찾는 문제](../README.md#번호로-못-찾는-문제)) |
| `contestProbId 를 찾을 수 없습니다` | 주소창 URL 을 넣음 (`solvingProblem.do` 등 POST 페이지) | 문제 번호를 넣으세요 |
| `이미 저장된 파일이 있습니다` (`AlreadyExists`) | 같은 문제를 이미 저장함 | 덮어쓰려면 [덮어쓰기] / `--force`. `{번호}.py` 는 어떤 경우에도 덮어쓰지 않습니다 |
| `첨부 링크가 없습니다` (`AttachmentNotFound`) | 샘플 첨부가 없는 문제 | [뼈대만] / `--skeleton-only` 로 폴더·뼈대·빈 `input.txt` 만 만들고 본문의 예제를 직접 복사 |
| `풀이를 실행할 Python 을 찾지 못했습니다` | exe 로 검증하는데 PC 에 Python 이 없거나 PATH 에 없음 | 아래 [검증에 쓸 Python 지정](#검증에-쓸-python-지정) |
| `[시간 초과] 10초를 넘어` | 무한 루프 또는 큰 입력 | 코드 확인. 제한 시간은 설정 페이지 타임아웃 / `check --timeout 30` |
| `네트워크` (`NetworkError`) | 연결 끊김, 사내망 차단 | 연결 확인 후 재시도. `swea-fetch doctor --offline` 은 네트워크 없이도 동작 |
| `내부 오류` | 예상 못 한 예외 | CLI 는 `-v` 를 붙여 다시 실행한 출력, GUI 는 오류 배너의 본문(선택·복사 가능)과 [진단 정보 복사] 결과를 이슈에 첨부 |

## 종료 코드 (CLI)

| 코드 | 의미 |
|---|---|
| 0 | 성공 |
| 1 | 설정·로그인 문제 (`ConfigMissing`, `LoginFailed`, `LoginLocked`, `MfaRequired`) |
| 2 | 입력·문제 해석 실패 (`InvalidInput`, `ProblemNotFound`, `ParseError`) |
| 3 | 파일 충돌 (`AlreadyExists`) |
| 4 | 첨부 없음 (`AttachmentNotFound`) |
| 5 | 네트워크 (`NetworkError`) |
| 6 | 검증 실패 (`swea-fetch check` 에서 출력이 다름) |
| 7 | git 커밋/푸시 실패 (`GitError`) → [아래](#git-커밋--푸시-종료-코드-7) |
| 8 | SWEA 제출 불가 또는 채점 결과 오답 (`SubmitError`) → [아래](#swea-제출-종료-코드-8) |
| 10 | 내부 오류 |
| 130 | Ctrl+C |

## SWEA 제출 (종료 코드 8)

[SWEA 제출] / `swea-fetch submit` 은 사이트의 제출 버튼과 같은 요청(컴파일 → 제출)을 보내고 채점 결과를 응답에서 읽습니다. 제출 횟수는 사이트와 똑같이 1회 소모됩니다.

| 메시지 | 원인 | 조치 |
|---|---|---|
| `허용하지 않는 키워드가 사용되었습니다 (SWEA 는 import sys 를 거부합니다)` | 도구가 `import sys` / `sys.stdin = open(...)` 줄은 빼고 보내지만, 다른 형태(예: `import sys, os`)가 남음 | 코드에서 `sys` 를 완전히 제거 |
| `제출 코드에 sys. 사용이 남아 있습니다` | `sys.stdin.readline`, `sys.setrecursionlimit` 등 | `input()` 으로 바꾸고 재귀 제한 설정은 제거 (SWEA 웹 에디터에서도 같은 제약) |
| `컴파일 오류: …` | 문법 오류 | 로컬 검증([실행])으로 먼저 확인 |
| `허용하지 않는 라이브러리` / `파일 입력 메소드` / `System call` | SWEA 제약 | 표준 입출력만 사용 |
| `제출 횟수를 다 채웠습니다` | 문제당 제출 한도 소진 | 사이트에서 확인. 도구로는 더 제출할 수 없음 |
| `오답: 10개 테스트케이스 중 7개 통과` | 채점 실패 (종료 코드 8, 푸시 안 함) | 코드 수정 후 재제출. `제한시간 초과` 가 붙으면 성능 문제 |
| `풀이 화면을 열지 못했습니다` | 접근 권한 없는 문제(미가입 클럽·Contest) 또는 세션 만료 | 브라우저에서 그 문제가 열리는지 확인 → 설정 [세션 삭제] 후 재시도 |
| `제출 응답이 JSON 이 아닙니다` | 로그인이 풀렸거나 사이트 구조 변경 | 설정 [세션 삭제] 후 재시도. 계속되면 이슈에 `doctor` 출력 첨부 |

## git 커밋 + 푸시 (종료 코드 7)

도구는 문제 폴더만 `git add`/`commit` 하고 `git push` 합니다. force push·pull 은 하지 않으므로 아래 상황은 **사용자가 git 으로 해결**한 뒤 다시 누르면 됩니다. 실패 시 GUI 는 "git" 탭에, CLI 는 오류 아래 `→` 줄에 git 출력을 보여 줍니다.

| 메시지 | 원인 | 조치 |
|---|---|---|
| `루트 폴더가 git 저장소가 아닙니다` | 루트에서 `git init` 을 한 적 없음 | [README 'GitHub 연동'](../README.md#github-연동) 의 4줄. 도구는 저장소를 만들어 주지 않습니다 |
| `원격 저장소(origin)가 없습니다` | `git remote add origin …` 을 안 함 | 루트에서 `git remote add origin https://github.com/<계정>/<저장소>.git` → 첫 푸시는 `git push -u origin main` |
| `GitHub 인증 실패 — 브라우저 로그인 창이 뜨지 않았다면 …` | Git Credential Manager 가 없거나 자격증명이 만료 | 루트에서 직접 `git push` 를 한 번 실행해 로그인 창을 띄우세요. Git for Windows 를 다시 설치하면 GCM 이 포함됩니다 |
| `원격에 새 커밋이 있습니다. git pull 후 다시 시도` | non-fast-forward (다른 PC 에서 먼저 푸시). **로컬 커밋은 이미 만들어졌고 푸시만 거부된 상태** | 루트에서 `git pull` (자동 merge, 충돌 나면 해결 후 `git add`+`git commit`) → 다시 [커밋 + 푸시]. force push 는 하지 않음 |
| `병합(merge)/리베이스(rebase) 진행 중입니다` | 끝내지 않은 merge/rebase | `git status` 로 확인 → 끝내거나 `git merge --abort` / `git rebase --abort` |
| `브랜치가 아닌 상태(detached HEAD)` | 특정 커밋을 checkout 한 상태 | `git switch main` |
| `git 사용자 이름/이메일이 없습니다` | 첫 커밋 전 설정 누락 | `git config --global user.name "이름"` / `git config --global user.email "메일"` |
| `풀이 파일이 없습니다` | `{번호}.py` 가 없음 | 저장 페이지에서 먼저 받거나 파일 이름 확인 |
| `푸시 시간 초과(30초)` | 인증 창이 뒤에 숨어 있거나 네트워크 | 작업 표시줄의 로그인 창 확인 → 없으면 네트워크 확인 |
| `이 저장소에 푸시 권한이 없습니다` | 다른 계정으로 로그인됨 / 협업자 아님 | 자격 증명 관리자에서 `git:https://github.com` 항목을 지우고 다시 푸시해 올바른 계정으로 로그인 |

### 자동 푸시를 되돌리려면

"SWEA 제출 결과가 Pass 이면 자동으로 커밋 + 푸시" 로 올라간 커밋을 취소하려면 (도구는 revert 를 실행하지 않습니다):

```powershell
git revert HEAD --no-edit
```

```powershell
git push
```

이미 공개 저장소에 올라간 내용은 revert 해도 히스토리에 남습니다. 자동 모드는 설정 페이지에서 언제든 끌 수 있습니다.

## 백신이 exe 를 차단할 때

PyInstaller 로 만든 단일 exe 는 일부 백신이 오탐합니다. 순서대로:

1. Release 페이지의 `.sha256` 파일과 비교해 파일이 손상되지 않았는지 확인:

```powershell
Get-FileHash .\swea-fetch-gui.exe -Algorithm SHA256
```

2. 백신 예외 목록에 exe 를 추가하거나, 회사·학교 PC 라서 불가능하면 **소스로 설치**해 `swea-fetch-gui` 명령으로 실행 ([README §5분 시작 (소스/CLI)](../README.md#5분-시작-소스cli)).
3. 직접 빌드할 수 있다면 `packaging\swea-fetch-gui.spec` 의 `ONEFILE = False` 로 폴더형 빌드 — 오탐이 훨씬 적습니다 ([development.md](development.md)).

## 검증에 쓸 Python 지정

exe 는 자기 안에 Python 을 품고 있지만 **풀이 실행에는 PC 의 Python** 을 씁니다 (exe 자신을 실행하면 창이 복제됩니다). 찾는 순서: 설정 `SWEA_PYTHON` → 환경변수 `SWEA_PYTHON` → PATH 의 `python` / `python3` / `py`.

PATH 에 없으면 `%USERPROFILE%\.swea-fetch\.env` 에 한 줄 추가:

```
SWEA_PYTHON=C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe
```

경로는 아래로 확인할 수 있습니다:

```powershell
py -3 -c "import sys; print(sys.executable)"
```

## 새 버전 알림이 안 뜨거나, 끄고 싶을 때

- 하루 1회만 GitHub 에 물어봅니다. 오프라인이거나 실패하면 조용히 넘어갑니다
- 끄기: 설정 페이지의 **새 버전 알림** 체크 해제 / CLI `--no-update-check` / 환경변수 `SWEA_NO_UPDATE_CHECK=1`
- 지금 바로 확인: `swea-fetch doctor` 의 `최신 버전` 줄

## 설정·캐시 파일 위치

`%USERPROFILE%\.swea-fetch\`

| 파일 | 내용 | 지워도 되나 |
|---|---|---|
| `.env` | `SWEA_ROOT`, `SWEA_ID`, (선택) `SWEA_INPUT_NAME`, `SWEA_OUTPUT_NAME`, `SWEA_PYTHON`. **비밀번호 없음** | 지우면 설정을 다시 입력 |
| `session.json` | 로그인 세션 쿠키 | 지우면 다음 실행 때 다시 로그인 |
| `login_state.json` | 연속 로그인 실패 횟수 | 잠금 해제용으로 지움 |
| `problem_index.json` | 문제 번호 → ID 색인 캐시 | 지우면 다시 찾음 (조금 느려짐) |
| `update_check.json` | 새 버전 확인 시각·결과·알림 끔 여부 | 지워도 됨 |

`.env` 의 git 관련 키 (설정 페이지에서도 바꿀 수 있음): `SWEA_COMMIT_TEMPLATE` (커밋 메시지 템플릿), `SWEA_AUTO_PUSH=1` (SWEA 제출 Pass 시 자동 커밋+푸시, 기본 0 — CLI·GUI 모두 적용, CLI 는 `swea-fetch submit --no-push` 로 1회만 해제).

비밀번호는 여기 없고 **Windows 자격 증명 관리자** (제어판 → 자격 증명 관리자 → Windows 자격 증명 → `swea-fetch`) 에 있습니다.
