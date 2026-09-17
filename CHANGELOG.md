# 변경 이력

형식: [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/). 버전은 `swea_fetcher/__init__.py` 의 `__version__` 하나로 관리한다.

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
