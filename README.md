# swea-fetcher

SWEA(SW Expert Academy) 문제의 샘플 입출력 첨부를 받아 풀이 저장소의 `swea\{주제}\{번호}\` 폴더 규칙대로 `input.txt`, `output.txt`, `{번호}.py` 뼈대를 한 번에 만들어 주는 명령줄 도구.

```powershell
swea-fetch init                 # 최초 1회: 계정 설정 + 로그인 확인
swea-fetch 25730 IM_test        # 문제 번호 + 주제 폴더 → swea\IM_test¯30\ 에 3개 파일 생성
swea-fetch 25730 IM_test --force
```

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

- 저장 위치: `%USERPROFILE%\.swea-fetch\.env` (프로젝트 폴더 **밖**이라 git 에 올라가지 않음). 같은 폴더에 로그인 세션 캐시 `session.json` 과 실패 카운터 `login_state.json` 이 생깁니다.
- 작성 직후 실제 로그인을 한 번 해서 확인합니다. `[OK] 로그인 확인 완료. 세션 저장됨` 이 나오면 끝. 오류가 나면 `.env` 는 그대로 두므로 `swea-fetch init` 을 다시 실행해 고치면 됩니다.
- 로그인 확인 없이 파일만 쓰려면 `swea-fetch init --no-check`.

## 사용법

```
swea-fetch <target> <topic> [--num N] [--force] [-v]
```

### `target` — 문제를 가리키는 값

**문제 번호**만 넣으면 됩니다. 문제 화면 상단에 `25730. [07] 항아리 게임` 처럼 보이는 그 숫자입니다.

```powershell
swea-fetch 25730 IM_test
```

번호를 주면 도구가 가입한 Solving Club 의 문제 상자(최신순)를 훑어 문제를 찾습니다. 오늘 상자의 문제는 1~3초, 한 번 본 상자는 `%USERPROFILE%\.swea-fetch\problem_index.json` 에 캐시돼 다음부턴 즉시 찾습니다. 못 찾으면(클럽 밖 문제 등) 아래 형식으로 직접 지정하세요.

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
| `-v` | 상세 로그. 오류 제보 시 이 출력을 첨부 |

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
| 1 | 2단계 인증 (`MfaRequired`) | 계정의 MFA 를 해제하거나 수동 세션 주입 기능(M3 예정) 필요 |
| 2 | 입력 해석 실패 (`InvalidInput`) | 번호가 가입 클럽 상자에 없거나, URL 에 ID 가 없음(주소창 URL). 번호를 확인하거나 첨부 링크로 지정 |
| 2 | 문제 없음 (`ProblemNotFound`) | `contestProbId` 가 맞는지, 그 문제에 접근 권한(클럽 가입 등)이 있는지 확인 |
| 2 | 번호/제목 파싱 실패 (`ParseError`) | `--num` 으로 지정하거나 `-v` 출력을 제보 |
| 3 | 파일 충돌 (`AlreadyExists`) | 기존 파일 확인 후 `--force` |
| 4 | 첨부 없음 (`AttachmentNotFound`) | 샘플 첨부가 없는 문제. 본문에서 직접 복사 (`--skeleton-only` 는 M3 예정) |
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
swea-fetch logout --all      # session.json, login_state.json, .env 삭제
```

나머지 정리 항목은 `docs/project-plan.md` 10절 체크리스트 참고. `swea-fetch logout` (옵션 없이) 은 세션 캐시만 지우고 계정 설정은 남깁니다.

## 사이트 구조가 바뀌었을 때

파싱 대상 페이지·선택자·로그인 방식 조사 기록: [docs/swea-page-notes.md](docs/swea-page-notes.md).
선택자는 [swea_fetcher/parser.py](swea_fetcher/parser.py) 상단 상수(`SEL_*`, `TITLE_RE`)에 모여 있어 그 부분만 고치면 됩니다. 테스트 픽스처는 `tests/fixtures/` (계정 정보 치환본).

## 개발

```powershell
pip install -e ".[dev]"
pytest
```
