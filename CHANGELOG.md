# 변경 이력

형식: [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/). 버전은 `swea_fetcher/__init__.py` 의 `__version__` 하나로 관리한다.

## v0.6.1 — 2026-09-17

### 수정
- **제출 기록이 문제의 '제출결과' 에 남지 않던 문제**: 제출 시 문제를 연 경로의 category 를 보내야 한다. 공개 Problem / User Problem 은 `("CODE", contestProbId)`, Solving Club 문제 상자는 `("BOX", probBoxId)`. `lookup.find_category` 가 색인의 발견 경로로 정하고, 옛 색인에는 상자 ID 가 없어 클럽 상자를 다시 훑는다 (한 번만)
- `--refresh-index` 가 기존 색인을 지우던 동작 제거 (캐시만 무시)
- 테스트 픽스처의 클럽 이름을 `DUMMY_CLUB` 으로 치환

## v0.6.0 — 2026-09-17 "SWEA 제출 → Pass 면 푸시"

### 변경 (v0.5.0 의 트리거 교체)
- 커밋+푸시의 기준이 **로컬 샘플 검증 통과 → SWEA 채점 Pass** 로 바뀌었다. 검증 페이지 **[SWEA 제출]** 이 사이트의 제출 버튼과 같은 요청(compile.do → submit.do)을 보내고 응답의 채점 결과를 보여 준다. 오답이면 푸시하지 않는다
- 설정 "자동으로 커밋 + 푸시" 는 SWEA Pass 를 받았을 때만 동작한다 (로컬 통과로는 절대 올라가지 않음). `check --push` 옵션 삭제, 대신 `swea-fetch submit <topic> <num> [--push] [-y]` (오답 = 종료 코드 8)
- 제출용 소스 변환: SWEA 가 `import sys` 를 거부하므로 `import sys` / `sys.stdin = open(...)` 줄을 빼고 보낸다. 다른 `sys.` 사용이 남으면 제출하지 않고 안내
- 최근 페이지 우클릭 "SWEA 제출…"

## v0.5.0 — 2026-09-17 "검증 후 커밋 + 푸시"

### 추가
- **[커밋 + 푸시]** (검증 페이지, 최근 페이지 우클릭): 검증이 끝난 **문제 폴더만** `git add`/`commit`/`push`. 매번 확인 창(메시지 편집, [커밋만]/[커밋 + 푸시]). 도구는 자격증명을 다루지 않고(Git Credential Manager), force push·pull 도 하지 않는다
- **자동 모드 (옵트인)**: 설정 "검증 통과 시 자동으로 커밋 + 푸시" — 기본 꺼짐, 켤 때 경고 1회, 결과 카드에 되돌리기 안내
- CLI `swea-fetch push <topic> <num> [-m] [--no-push]`, `swea-fetch check … --push` (통과 시에만). 종료 코드 7 = git 실패
- 설정 "GitHub 연동": 저장소 상태(브랜치 → 원격), 커밋 메시지 템플릿 `SWEA_COMMIT_TEMPLATE` (변수 `{num} {title} {topic} {date}`)
- `doctor` 에 `git:` 줄 (버전, 저장소, 브랜치 → upstream)

### 변경
- 설정 저장 시 `.env` 의 다른 키(`SWEA_PYTHON` 등)를 더 이상 지우지 않는다

## v0.4.0 — 2026-09-17 "배포판"

### 추가
- **중첩 주제 폴더**: `swea-fetch 25730 test/IM_test` → `{루트}/test/IM_test/25730/`. `\` 도 `/` 로 취급, 깊이 4까지. GUI 주제 드롭다운·최근 목록도 중첩 경로를 그대로 보여준다
- **`swea-fetch doctor`**: 버전·Python·OS·설정 폴더·루트·로그인 상태·keyring·최신 버전을 한 번에 출력 (비밀번호·쿠키·ID 미포함). `--offline` 은 네트워크 항목 생략. GUI 설정 페이지 [진단 정보 복사] 버튼이 같은 내용을 클립보드로
- **새 버전 알림**: GitHub Release 를 하루 1회 확인. CLI 는 명령 끝에 한 줄, GUI 는 상태바 배지(클릭 → Release 페이지). 끄기: `--no-update-check`, 환경변수 `SWEA_NO_UPDATE_CHECK=1`, 설정 페이지 체크박스
- `LICENSE`(MIT), 이슈 템플릿(버그/기능 요청), 이 변경 이력

### 변경
- README 를 "exe 사용자 / 소스 사용자" 두 갈래로 전면 개편. 문제 해결·개발자 문서는 `docs/troubleshooting.md`, `docs/development.md` 로 분리
- 테스트 픽스처의 남은 계정 식별자를 `DUMMY_*` 로 치환하고 저장소를 public 으로 전환

## v0.3.4 — 2026-09-17

- GitHub Release 에 exe + sha256 첨부 시작
- 검증 페이지 [취소] 버튼: 실행 중인 풀이 프로세스를 중단하고 "취소됨" 표시
- 일반 문제 페이지 파서의 검증되지 않은 목록 위젯 폴백 삭제 (번호를 못 읽으면 `--num` 안내)
- README 에 범위 밖 항목(Contest·미가입 클럽 문제는 첨부 URL/ID 직접 입력) 명시

## v0.3.3 — 2026-09-17

- **수정**: exe 에서 검증을 실행하면 GUI 자신이 복제되어 뜨고 10초 타임아웃이 나던 문제. 동결 상태에서는 PATH 의 실제 Python 을 찾고(`SWEA_PYTHON` 으로 지정 가능) 콘솔 창 없이 실행

## v0.3.2 — 2026-09-16

- 디자인 검토 반영 (사이드바 아이콘·검증 페이지 좁은 폭 재배치·상태바 경로 생략 등 8건) 후 exe 재빌드

## v0.3.1 — 2026-09-16

- PyInstaller 단일 exe 빌드 (`packaging/swea-fetch-gui.spec`), 앱 아이콘, 자가진단 훅(`SWEA_FETCH_SELFTEST`)
- 동결 상태에서 keyring 백엔드(Windows 자격 증명 관리자) 명시 지정

## v0.3.0 — 2026-09-16

- **GUI** (PySide6): 저장 / 검증 / 최근 / 설정 4개 페이지. 문제 번호 + 주제만 넣으면 저장, 풀이 실행 후 `output.txt` 와 행 단위 비교, 드래그 앤 드롭
- CLI 와 GUI 가 같은 서비스 계층(`service.py`)을 쓴다
- `swea-fetch check <topic> <num>` (CLI 검증)

## v0.2.0 — 2026-09-16

- 비밀번호를 `.env` 평문 대신 Windows 자격 증명 관리자(keyring)에 저장. `swea-fetch init --migrate` 로 이관, `logout --all` 로 자리 반납
- `--skeleton-only` / `--dry-run` / `--refresh-index`, 주제 폴더 대소문자·유사 이름 안내

## v0.1.1 — 2026-09-16

- **문제 번호만으로 저장**: 공개 목록 → User Problem → Solving Club 문제 상자 순으로 번호를 찾고 `~/.swea-fetch/problem_index.json` 에 캐시

## v0.1.0 — 2026-09-16

- 첫 동작 버전: 첨부 링크 URL 또는 `contestProbId` 로 문제 페이지를 읽어 `input.txt` / `output.txt` / `{번호}.py` 뼈대를 `{루트}/{주제}/{번호}/` 에 저장. 로그인 세션 캐시, 5회 잠금 가드, 저장 실패 시 롤백
