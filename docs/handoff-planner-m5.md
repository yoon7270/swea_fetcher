# tester → planner 전달 (M5 검증 완료, 2026-09-17)

대상: `docs/project-plan.md` 의 M5 마감 · 테스트 전략 · 미결 항목 상태 갱신.
검증 대상 커밋 `cea5683` (태그 `v0.3.4`). builder 의 M4 전달문 `docs/handoff-planner-m4.md` 에 이어지는 문서.

## 1. 테스트 결과

```
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q
```

**통과 491 / 실패 0 / 스킵 0** (약 10s, 3회 연속 동일). M4 마감 시점 470 → M5 에서 21개 추가 (checker 13 · config 2 · gui 6).

| 모듈 | 테스트 파일 | 개수 | M5 에서 추가·변경된 것 |
|---|---|---|---|
| parser | `tests/test_parser.py` | 57 | builder 가 detail 페이지 폴백 삭제(M5 #1)에 맞춰 2건의 기대값을 `(None, "")` 로 바꿈 — 사용자 승인된 스펙 변경이라 그대로 인정 |
| checker | `tests/test_checker.py` | 42 | **+13**: `resolve_python`(설정→환경변수→sys.executable→PATH 순서, 동결 시 GUI exe 배제, 미발견 시 note), `_python_cmd`(py 런처 `-3`), `on_start` 핸들 전달, 취소 시 `cancelled=True` |
| config | `tests/test_config.py` | 34 | **+2**: `SWEA_PYTHON` 로드 |
| gui | `tests/gui/test_gui.py` | 46 | **+6**: `CheckWorker.cancel` (실행 중 / 프로세스 뜨기 전 / 종료 후), CheckPage [취소] 버튼 표시·비활성·배지 "취소됨"·재실행 |
| 그 외 (auth, client, storage, lookup, service, cli, errors, template) | — | 312 | 변경 없음, 전부 통과 |

M5 3개 항목 모두 회귀 테스트로 고정됨:
- **#1 폴백 삭제** → `test_parse_detail_ignores_list_widgets`, `test_parse_detail_problem_title_without_number_returns_none`
- **#2 README 범위 명시** → 코드 변경 없음 (문서만)
- **#3 검증 취소** → `test_check_worker_cancel_*` 3건, `test_check_page_cancel_*` 3건, `test_run_and_compare_cancelled_via_on_start`

## 2. 구성안에 반영할 사실

1. **테스트 전략 (구성안 9절/리스크 갱신용)** — 네트워크·자격 증명·레지스트리를 전혀 건드리지 않는 단위 테스트로 전 모듈 커버.
   - HTTP: `tests/conftest.py` `FakeSession`/`FakeResponse` + 실제 페이지 픽스처 5종 (`tests/fixtures/`).
   - keyring: `FakeKeyring` autouse 스텁. `config.CONFIG_DIR` 도 tmp 로 강제 → `load_settings()` 를 인자 없이 불러도 실제 `~/.swea-fetch` 를 읽지 않음.
   - GUI: PySide6 offscreen + pytest-qt. `QSettings` 는 `main_window.QSettings` 를 ini 팩토리로 교체(org/app 생성자는 `setDefaultFormat` 을 무시하고 레지스트리를 씀).
   - 풀이 검증: 실제 `python` subprocess 를 띄움 (정답/오답/런타임 에러/1초 타임아웃/취소).
2. **exe 검증의 인터프리터 탐색 (v0.3.3)** — `checker.resolve_python` 이 동결 상태에서 `sys.executable`(=GUI 자신)을 절대 쓰지 않는 것을 테스트로 고정. `.env` 의 `SWEA_PYTHON` 이 새 설정 키로 추가됨 (구성안 3절 설정 키 목록에 반영 필요).
3. **취소 의미론** — 취소는 검증(subprocess kill)에만 있고 저장(requests)에는 없음. 취소된 결과는 `passed=False, timed_out=False, cancelled=True, note="취소했습니다"`, diff 비어 있음.

## 3. 테스트 관점 관찰 (수정 요청 아님 — 우선순위 판단용)

| # | 관찰 | 영향 | 제안 |
|---|---|---|---|
| T1 | `SWEA_PYTHON` 에 존재하지 않는 경로를 넣으면 조용히 다음 후보(sys.executable/PATH)로 넘어감. 사용자가 오타를 알아채기 어려움 | 낮음 | 설정 페이지나 `init` 에서 경로 존재 여부를 한 번 검사하거나, 자동 폴백 시 로그 WARNING |
| T2 | 취소 판정이 `Popen` 객체의 동적 속성(`proc._swea_cancelled`)에 의존 | 낮음 (동작은 정상, 테스트로 고정됨) | P2 에서 손댈 일이 있으면 `CheckWorker` 가 `cancelled` 플래그를 직접 결과에 얹는 구조로 정리 |
| T3 | 저장(FetchWorker)에는 취소가 없어 네트워크가 느리면 창 제목 "저장 중…" 상태로 대기만 가능 | 중간 (UX) | `_request` 의 15s 타임아웃 × 재시도 2회 = 최대 ~50s. 구성안 P2 "저장 취소" 항목으로 두거나 타임아웃 단축 검토 |
| T4 | GUI 테스트는 offscreen 이라 실제 렌더링(글꼴·DPI)은 검증하지 않음. `docs/gui-screenshots/` 캡처와 사용자 실사용 승인(M4b/M4c)이 그 역할 | — | 구성안 테스트 전략에 "GUI 는 동작만 자동 검증, 외관은 스크린샷+수동" 으로 명시 |
| T5 | `tests/test_checker.py`·GUI 취소 테스트는 실제 프로세스를 띄우므로 느린 PC 에서 1~2s 타임아웃 테스트가 흔들릴 가능성. 3회 연속 실행에선 안정 | 낮음 | CI 도입 시 `timeout` 여유를 늘리거나 `-p no:cacheprovider` 유지 |

## 4. 남은 미결 (M4 전달문 §3 기준 현황)

| # | 항목 | 상태 |
|---|---|---|
| 1 | detail 페이지 `span.week_num` 폴백 | **삭제 완료** (M5 #1), 테스트 반영 |
| 2 | Contest / 미가입 클럽 문제 | **범위 밖으로 README 명시** (M5 #2) |
| 3 | 작업 취소 | **검증만 구현** (M5 #3). 저장 취소는 미구현 → T3 |
| 4 | 다크 테마 | 보류 (변경 없음) |
| 5 | exe 배포 | GitHub Release `v0.3.4` 발행 (builder 보고). 테스트는 소스 기준이며 exe 자체의 자동 검증은 `SWEA_FETCH_SELFTEST` 훅만 있음 |
| 6 | P2 후보 (일괄 저장, 상자 picker, 다중 TC) | 보류 |

## 5. 참고 위치

- 테스트: `tests/` (모듈별 1파일, GUI 는 `tests/gui/`), 공통 픽스처 `tests/conftest.py`, `tests/gui/conftest.py`
- 이전 tester 산출물: `docs/tester-feedback-m1.md` (M1 실패 2건 — M2 에서 모두 수정됨)
- 실행 환경: `.venv` (pytest 9.1, pytest-qt, PySide6 6.11), Windows 11
