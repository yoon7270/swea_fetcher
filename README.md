# swea-fetcher

SWEA(SW Expert Academy) 문제의 샘플 입출력 첨부를 받아 풀이 저장소의 `swea\{주제}\{번호}\` 폴더 규칙대로 `input.txt`, `output.txt`, `{번호}.py` 뼈대를 한 번에 만들어 주는 명령줄 도구.

```powershell
swea-fetch init                 # 최초 1회: 계정 설정 + 로그인 확인
swea-fetch 25730 IM_test        # 문제 번호 + 주제 폴더 → swea\IM_test\25730\ 에 3개 파일 생성
swea-fetch 25730 IM_test --force
```

## 창 프로그램 (GUI)

명령줄 대신 창으로 쓰려면:

```powershell
pip install -e ".[gui]"
swea-fetch-gui
```

- **저장**: 문제 번호 + 주제 → Enter. 결과 카드에서 [폴더 열기] / [PyCharm 에서 열기]. Ctrl+Enter 미리보기.
- **검증**: 주제·번호를 고르거나 `{번호}.py`(또는 그 폴더)를 창에 끌어다 놓고 [실행] → `input.txt` 로 실행해 `output.txt` 와 줄 단위 비교(≠ 다름 / − 누락 / + 초과). 타임아웃은 설정에서.
- **최근**: 저장한 문제 목록. 더블클릭 → 검증, 우클릭 → 폴더 열기.
- **설정**: 루트 폴더·ID·비밀번호(자격 증명 관리자에만 저장) / 세션 삭제 / 계정 정보까지 삭제.

CLI 와 같은 설정(`%USERPROFILE%\.swea-fetch\`)을 공유합니다. 명령줄에서도 검증할 수 있습니다: `swea-fetch check IM_test 25730` (실패 시 종료 코드 6).

디자인 스펙: [design/design-spec.md](design/design-spec.md), 화면 캡처: [docs/gui-screenshots/](docs/gui-screenshots/).

### 실행 파일(exe) 만들기 — 바탕화면 더블클릭용

```powershell
pip install -e ".[gui]" pyinstaller pillow
python packaging\make_ico.py                                   # design\iconspp.ico 생성 (1회)
pyinstaller packaging\swea-fetch-gui.spec --noconfirm           # → dist\swea-fetch-gui.exe (약 55 MB)
```

`dist\swea-fetch-gui.exe` 를 바탕화면에 바로 가기로 두면 됩니다. CLI 와 같은 설정·자격 증명을 사용하고 Python 설치가 없어도 실행됩니다. exe 는 저장소에 커밋하지 않습니다.

- **백신 오탐**: 공용 PC 백신이 PyInstaller onefile 을 차단하면 `packaging\swea-fetch-gui.spec` 의 `ONEFILE = False` 로 바꿔 폴더형(`dist\swea-fetch-gui\`)으로 빌드하거나, venv 의 `swea-fetch-gui` 명령으로 실행하세요.
- 빌드 검증: `set SWEA_FETCH_SELFTEST=%TEMP%\swea_selftest.txt && dist\swea-fetch-gui.exe` → 창 없이 진단 결과(아이콘·자격 증명 백엔드·설정 로드)를 파일에 쓰고 종료.

## 설치

PowerShell 에서 (가상환경 권장):

```powershell
cd C:\Users\SSAFY\Desktop\swea_fetcher
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .
```

가상환경 없이 어디서나 `swea-fetch` 를 쓰려면 활성화 없이 전역에 설치해도 됩니다:

```powershell
pip install -e C:\Users\SSAFY\Desktop\swea_fetcher
```

Python 3.11 이상 필요.

## 초기 설정 — `swea-fetch init`

```powershell
swea-fetch init
```

물어보는 것:

| 항목 | 설명 |
|---|---|
| `SWEA_ROOT` | 풀이 저장소 폴더. `C:\Users\<you>\Desktop\swea` 가 있으면 Enter 로 수락 |
| `SWEA_ID` | SWEA 로그인 ID(이메일) |
| `SWEA_PW` | 비밀번호 2회. **입력해도 화면에 표시되지 않습니다** |

- 저장 위치
  - `SWEA_ROOT`, `SWEA_ID` → `%USERPROFILE%\.swea-fetch\.env` (프로젝트 폴더 **밖**이라 git 에 올라가지 않음)
  - **비밀번호 → Windows 자격 증명 관리자** (서비스 `swea-fetch`, 사용자명 = `SWEA_ID`). `.env` 에는 비밀번호가 기록되지 않습니다. 제어판 → 자격 증명 관리자 → Windows 자격 증명에서 `swea-fetch` 항목으로 확인·삭제할 수 있습니다
  - 같은 폴더에 세션 캐시 `session.json`, 실패 카운터 `login_state.json`, 번호 색인 `problem_index.json` 이 생깁니다
- 작성 직후 실제 로그인을 한 번 해서 확인합니다. `[OK] 로그인 확인 완료. 세션 저장됨` 이 나오면 끝. 오류가 나면 설정은 그대로 두므로 `swea-fetch init` 을 다시 실행해 고치면 됩니다.
- 로그인 확인 없이 파일만 쓰려면 `swea-fetch init --no-check`.

**한계를 정직하게**: Windows 자격 증명 관리자는 *같은 Windows 계정으로 로그인한 사람이면 읽을 수 있습니다.* 공용 PC 에서 Windows 계정을 공유한다면 평문 파일보다 "우연히 열어 보는" 위험은 줄지만 근본 보호는 아닙니다. 자리 반납 시 `swea-fetch logout --all` 은 여전히 필수입니다.

### 예전 버전에서 올라온 경우 — `init --migrate`

0.1.x 는 비밀번호를 `.env` 에 평문으로 저장했습니다. 실행 시 `평문 비밀번호가 .env 에 있습니다` 경고가 보이면 한 번만:

```powershell
swea-fetch init --migrate
```

프롬프트 없이 `.env` 의 `SWEA_PW` 를 자격 증명 관리자로 옮기고 `.env` 에서 그 줄을 지웁니다.

비밀번호 결정 순서(참고): 환경변수 `SWEA_PW` → `.env` 의 `SWEA_PW`(경고) → 자격 증명 관리자. 환경변수는 자격 증명 관리자를 쓸 수 없는 환경의 우회용이며 권장하지 않습니다.

## 사용법

```
swea-fetch <target> <topic> [--num N] [--force] [--skeleton-only] [--dry-run] [--refresh-index] [-v]
```

### `target` — 문제를 가리키는 값

**문제 번호**만 넣으면 됩니다. 문제 화면 상단에 `25730. [07] 항아리 게임` 처럼 보이는 그 숫자입니다.

```powershell
swea-fetch 25730 IM_test
```

번호를 주면 도구가 이 순서로 문제를 찾습니다 — 로컬 캐시 → SWEA 공개 Problem 목록 검색 → User Problem 목록 검색 → 가입한 Solving Club 의 문제 상자(최신순). 일반 문제·모의고사 문제 모두 번호만으로 됩니다 (보통 1~3초, 한 번 찾은 문제는 `%USERPROFILE%\.swea-fetch\problem_index.json` 에 캐시). 어디서도 못 찾으면 아래 형식으로 직접 지정하세요.

| 형식 | 예 |
|---|---|
| 첨부파일 링크 (문제 페이지 하단 `input*_sample.txt` 우클릭 → 링크 주소 복사) | `https://swexpertacademy.com/main/common/contestProb/contestProbDown.do?downType=in&contestProbId=AZq-gSmq_RfHBISS` |
| 일반 문제 URL | `https://swexpertacademy.com/main/code/problem/problemDetail.do?contestProbId=AZq-gSmq_RfHBISS` |
| `contestProbId` 16자 | `AZq-gSmq_RfHBISS` |

문제 화면의 **주소창 URL 은 쓸 수 없습니다** (`.../solvingProblem.do` 처럼 문제 ID 가 없는 POST 페이지). 번호를 쓰세요.

### `topic` — 주제 폴더 이름

기존 폴더 이름을 그대로 (`BFS`, `Queue`, `IM_test`, `A_test`, `swexpert`, `stack` …). 대소문자를 다르게 쓰면 다른 폴더가 생기니 주의.

### 옵션

| 옵션 | 설명 |
|---|---|
| `--num N` | 페이지에서 문제 번호를 못 찾았을 때 직접 지정. 찾았는데도 주면 `--num` 이 우선(경고 출력) |
| `--force` | 이미 있는 `input.txt` / `output.txt` 를 덮어씀. **`{번호}.py` 는 어떤 경우에도 덮어쓰지 않음** (풀이 코드 보호) |
| `--skeleton-only` | 첨부를 받지 않고 폴더 + `{번호}.py` + **빈** `input.txt` 만 생성. 샘플 첨부가 없는 문제용 (`output.txt` 는 만들지 않음). 첨부 없는 문제를 그냥 실행하면 이 옵션을 안내 |
| `--dry-run` | 로그인·페이지·첨부까지 다 가져오되 **저장만 생략**하고 무엇을 어디에 쓸지 미리보기. 이미 있는 파일이 있으면 `--force` 필요 여부도 알려줌 |
| `--refresh-index` | 번호 색인 캐시를 무시하고 다시 찾음. 클럽에 새 문제 상자가 추가됐는데 번호로 못 찾을 때 |
| `-v` | 상세 로그. 오류 제보 시 이 출력을 첨부 |

`--dry-run` 출력 예:

```
[DRY-RUN] 25730. 항아리 게임  (page_kind=solver, contestProbId=AZq-gSmq_RfHBISS)
  저장 예정: C:\Users\SSAFY\Desktop\swea\IM_test\25730\
    input.txt   ← input7_sample.txt (34 B)   미리보기: 3 / 4 / 0 1 2 0 ...
    output.txt  ← output7_sample.txt (17 B)  미리보기: #1 5 / #2 3 / #3 16
    25730.py    (생성 예정)
```

### 주제 폴더 이름 안내

저장 전에 `SWEA_ROOT` 의 폴더 목록과 비교해서
- 대소문자만 다른 폴더가 있으면 (`bfs` ↔ `BFS`) **기존 이름을 사용**하고 `[알림]` 을 출력합니다. Windows 는 대소문자를 구분하지 않아 같은 폴더에 들어가지만, 다른 PC 에서 clone 하면 갈라지므로 이름을 맞춥니다.
- 비슷한 폴더가 있으면 (`Queue` ↔ `queue2`) `[알림] 비슷한 폴더가 있습니다: Queue — 새 폴더 'queue2' 를 만듭니다` 로 **알리기만** 하고 진행합니다 (묻지 않음).

## 결과물

```
swea\
└── IM_test\
    └── 25730\
        ├── input.txt      ← 첨부 input*_sample.txt (줄바꿈 LF, UTF-8 로 정규화)
        ├── output.txt     ← 첨부 output*_sample.txt
        └── 25730.py       ← 뼈대 (이미 있으면 유지)
```

뼈대 코드:

```python
# 25730. 항아리 게임
import sys
sys.stdin = open("input.txt", "r")
T = int(input())
for test_case in range(1, T + 1):
    pass
```

성공 출력 예:

```
[OK] 25730. 항아리 게임 → C:\Users\SSAFY\Desktop\swea\IM_test\25730
     input.txt   (1.2 KB, 원본 input7_sample.txt)
     output.txt  (0.3 KB, 원본 output7_sample.txt)
     25730.py    (뼈대 생성)
```

## 문제 해결

오류는 `[오류] 원인` 한 줄 + `→ 조치` 한 줄로 나옵니다.

| 종료 코드 | 상황 | 조치 |
|---|---|---|
| 1 | 설정 없음 (`ConfigMissing`) | `swea-fetch init` |
| 1 | 로그인 실패 (`LoginFailed`) | `.env` 의 ID/PW 확인 → `swea-fetch init` 으로 재작성. **SWEA 는 5회 연속 실패 시 계정을 잠급니다.** 도구는 3회에서 스스로 멈춤 |
| 1 | 자동 로그인 중단 (`LoginLocked`) | 브라우저에서 로그인이 되는지 확인 후 `%USERPROFILE%\.swea-fetch\login_state.json` 삭제 |
| 1 | 2단계 인증 (`MfaRequired`) | 계정의 MFA 를 해제해야 자동 로그인 가능 (현재 계정은 해당 없음) |
| 2 | 입력 해석 실패 (`InvalidInput`) | 번호를 어디서도 못 찾았거나 URL 에 ID 가 없음(주소창 URL). 번호 확인 → `--refresh-index` → 문제 URL 로 지정 |
| 2 | 문제 없음 (`ProblemNotFound`) | `contestProbId` 가 맞는지, 그 문제에 접근 권한(클럽 가입 등)이 있는지 확인 |
| 2 | 번호/제목 파싱 실패 (`ParseError`) | `--num` 으로 지정하거나 `-v` 출력을 제보 |
| 3 | 파일 충돌 (`AlreadyExists`) | 기존 파일 확인 후 `--force` |
| 4 | 첨부 없음 (`AttachmentNotFound`) | 샘플 첨부가 없는 문제. `--skeleton-only` 로 폴더·뼈대만 만들고 본문에서 직접 복사 |
| 5 | 네트워크 (`NetworkError`) | 연결 확인 후 재시도 |
| 10 | 내부 오류 | `-v` 로 다시 실행해 traceback 제보 |

## 다른 PC 에서 복원

```powershell
git clone https://github.com/yoon7270/swea_fetcher.git
cd swea_fetcher
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e .
swea-fetch init
```

## 자리 반납 시 (공용 PC)

```powershell
swea-fetch logout --all
```

한 줄로 `session.json`, `login_state.json`, `.env`, 그리고 **자격 증명 관리자의 비밀번호**까지 삭제합니다 (확인 프롬프트 1회). 나머지 정리 항목은 `docs/project-plan.md` 10절 체크리스트 참고. `swea-fetch logout` (옵션 없이) 은 세션 캐시만 지우고 계정 설정은 남깁니다.

## 사이트 구조가 바뀌었을 때

파싱 대상 페이지·선택자·로그인 방식 조사 기록: [docs/swea-page-notes.md](docs/swea-page-notes.md).
선택자는 [swea_fetcher/parser.py](swea_fetcher/parser.py) 상단 상수(`SEL_*`, `TITLE_RE`)에 모여 있어 그 부분만 고치면 됩니다. 테스트 픽스처는 `tests/fixtures/` (계정 정보 치환본).

## 개발

```powershell
pip install -e ".[dev]"
pytest
```
