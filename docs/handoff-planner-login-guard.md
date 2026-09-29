# planner → builder 전달 (로그인 가드 개선: GUI 장기 실행 대응, 2026-09-29)

대상: `swea_fetcher/auth.py` 의 프로세스당 1회 가드. 코드 수정 없이 명세만 작성. 구현은 builder, 테스트 수정은 tester.

## 1. 원인 검증 (코드 확인 완료)

- `auth.py:44` `_login_attempted` 는 모듈 전역 bool. `login()` 이 `auth.py:142-144` 에서 성공/실패와 무관하게 첫 시도에 True 로 세우고 이후 모든 호출을 `LoginFailed("이 실행에서 이미 로그인을 시도했습니다 …")` 로 막는다. 리셋 경로는 테스트 전용 `_reset_process_guard` 뿐.
- CLI 는 명령마다 프로세스가 새로 떠서 문제없음. GUI 는 한 프로세스가 오래 살아 아래 두 경로가 모두 재현된다.
  - A. 로그인 성공, 세션 만료 후 `get_session`/`client._with_relogin`(client.py:79) 이 `login` 호출, 가드에 막힘.
  - B. 비밀번호 오류, 설정 페이지에서 수정 후 저장, `workers.py:68` → `service.verify_login` → `get_session` → `login`, 가드에 막힘. 같은 프로세스에서 새 자격증명은 한 번도 시도되지 않았는데도 막힌다.
- 문구 문제: "명령을 다시 실행하세요" 는 CLI 전용. `errors.py:54` `LoginFailed.default_hint` 의 `swea-fetch init` 도 CLI 전용(`ConfigMissing`, errors.py:47 은 GUI 병기 선례). GUI 배너는 `e.hint` 를 그대로 표시(`workers.py:36`).
- 보호 계층은 두 겹이며 가드 개선 후에도 유지한다: (1) 영속 누적 실패 카운터 `login_state.json`(3회에서 `LoginLocked`, 서버 실패 응답만 카운트), (2) 이 인메모리 가드. 실제 잠금 방지의 주력은 (1). (2) 의 목적은 "같은 틀린 자격증명으로 자동 재시도가 연쇄되는 것" 차단이다.

## 2. 설계 결정

가드를 "프로세스당 1회" 에서 **"직전 실패한 자격증명 지문과 같으면 자동 재시도 차단"** 으로 바꾼다.

- 성공 후 재로그인(세션 만료): 허용. 성공이 곧 자격증명이 유효하다는 증거이므로 막을 이유가 없다.
- 실패 후 같은 자격증명 자동 재시도: 차단(잠금 방지 의도 유지).
- 실패 후 자격증명이 바뀜(설정 저장): 지문이 달라져 자동으로 허용. 별도 리셋 훅 불필요, 설정 저장 코드 수정 없음.
- 사용자가 명시적으로 누른 확인(`verify_login`: GUI [저장 후 로그인 확인], CLI `init` 직후 확인)은 지문 차단을 우회한다. 이유: 휴면 계정을 브라우저에서 복구하거나 서버 측 일시 문제 후 같은 자격증명으로 다시 시도하는 것은 정당한 흐름이며, 누적 3회 영속 카운터가 여전히 상한을 건다. 자동 경로(fetch/check/submit 의 `get_session`, `_with_relogin`)는 우회 불가.

## 3. 구체 동작 규칙 (`auth.py`)

1. 상태: `_failed_fp: str | None = None`, `_login_lock = threading.Lock()`. `_login_attempted` 는 삭제.
2. 지문: `sha256(salt + user_id + "\0" + password)` 의 hexdigest. salt 는 모듈 로드 시 `os.urandom(16)`. 메모리에만 두고 로그·예외 메시지·파일에 절대 출력하지 않는다(시크릿 취급 유지). `_fingerprint(settings)` 헬퍼로 분리.
3. `login(session, settings, *, explicit: bool = False)` 순서:
   1. `_login_lock` 획득(GUI 워커 동시 호출 시 이중 POST 방지). 락 안에서 끝까지 수행.
   2. 영속 실패 카운터 >= 3 이면 `LoginLocked`(현행 유지, 가드보다 먼저, 가드 상태 불변).
   3. `not explicit and _failed_fp == _fingerprint(settings)` 이면 POST 없이 `LoginFailed(GUARD_MSG, code="guard", hint=GUARD_HINT)`. 카운터 증가 없음.
   4. 그 외 POST 수행(현행 로직).
4. 결과별 지문 갱신:
   - 서버가 `success is True`(MFA 아님): `_failed_fp = None`, 카운터 0 리셋(현행).
   - 서버가 `success` 가 True 가 아닌 JSON 응답(카운터가 증가하는 경로): `_failed_fp = 현재 지문`.
   - `mfa`, 빈 응답, JSON 해석 실패, `NetworkError`: 지문 갱신 안 함(자격증명 오류가 확정된 것이 아니고 카운터도 안 오름). 단 이 경로도 한 호출당 POST 1회이고 `_with_relogin` 은 재로그인을 호출당 1회만 하므로 무한 루프 위험 없음.
5. `get_session(settings, *, explicit: bool = False)` 는 `explicit` 을 `login` 에 전달. `service.verify_login` 만 `explicit=True` 로 호출. `client._with_relogin` 등 나머지 호출부는 기본값 유지(시그니처 호환).
6. `_reset_process_guard()` 는 이름 유지(conftest 호환), 본문은 `_failed_fp = None`.
7. 한 호출 안에서 "로그인 직후 곧바로 또 만료" 는 기존대로 `_with_relogin` 이 1회 재시도 후 `LoginFailed("재로그인 후에도 세션이 유효하지 않습니다")` 로 끝낸다(변경 없음). 이 메시지도 다음 8절 힌트 규칙을 따른다.

## 4. 메시지·힌트 (CLI/GUI 병기 방식)

`ConfigMissing` 선례대로 힌트에 CLI/GUI 안내를 한 문장으로 병기한다. 예외 클래스가 실행 환경을 알 필요가 없도록 분기 로직은 넣지 않는다(과설계 방지).

| 대상 | 새 문구 |
|---|---|
| `GUARD_MSG` | `직전 로그인이 같은 ID/비밀번호로 실패해 자동 재시도를 막았습니다 (계정 잠금 방지)` |
| `GUARD_HINT` | `ID/비밀번호를 고친 뒤 다시 시도하세요 (GUI: 설정 페이지에서 저장 후 로그인 확인 / CLI: swea-fetch init). 고치지 않았다면 브라우저에서 로그인이 되는지 먼저 확인하세요` |
| `LoginFailed.default_hint` (errors.py:54) | `SWEA_ID / 비밀번호를 확인하세요 (GUI: 설정 페이지, CLI: swea-fetch init 으로 재작성). SWEA 는 5회 연속 실패 시 계정이 잠깁니다` |

- "명령을 다시 실행하세요" 문구는 삭제.
- `LoginLocked`, `MfaRequired` 힌트는 이미 환경 중립이라 변경 없음.
- GUI 설정 페이지 `_on_failed`(settings_page.py:609)는 "입력한 설정은 저장됐습니다…" + `hint` 를 덧붙이므로, 그 경로에서 `GUARD_HINT` 가 노출될 일은 명시 확인(explicit)이라 사실상 없다. 다른 페이지(fetch/check/submit 배너)에서 가드가 발동하면 `GUARD_HINT` 가 배너에 그대로 표시된다.

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| `swea_fetcher/auth.py` | 3절 전부. 모듈 docstring 7행 "프로세스당 1회" 문구를 "같은 자격증명 실패 후 재시도 차단 + 누적 3회 중단" 으로 정정. `login`/`get_session` docstring 갱신 |
| `swea_fetcher/errors.py` | `LoginFailed.default_hint` 교체 |
| `swea_fetcher/service.py` | `verify_login` 의 `auth.get_session(settings)` → `auth.get_session(settings, explicit=True)` (233행) |
| `tests/test_auth.py`, `tests/test_service.py`, `tests/gui/test_gui.py` | 6절 |
| `docs/tester-feedback-m1.md` | 44행 항목에 "해소됨: docs/handoff-planner-login-guard.md" 한 줄 추가 |
| `README.md` / `docs/troubleshooting.md` | "프로세스당 1회" 를 언급한 곳이 있으면 새 규칙으로 정정(grep 후 해당 시만). 없으면 무변경 |
| `CHANGELOG.md` | Fixed 항목 1줄: GUI 에서 세션 만료 후/자격증명 수정 후 로그인이 막히던 문제 |

변경하지 않는 것: `client.py`, `lookup.py`, `gui/workers.py`, 설정 저장 코드, `login_state.json` 형식.

## 6. 테스트

기존 수정:
- `test_auth.py::test_login_locked_check_precedes_process_guard`(231행): `assert auth._login_attempted is False` → `auth._failed_fp is None`.
- `test_auth.py::test_login_only_once_per_process`(239행): 이름을 `test_login_blocks_same_credentials_after_failure` 로 바꾸고 `match="이미"` → `match="같은 ID/비밀번호"`. POST 없음(`s2.calls == []`)과 카운터 1 유지 단언은 그대로.
- `test_auth.py::test_login_guard_is_set_even_after_success`(250행): 의미가 반전됨. `test_login_allowed_again_after_success` 로 교체해 두 번째 로그인이 성공하고 POST 가 수행됨을 검증.
- `test_auth.py` 312행 `assert auth._login_attempted is False` → `auth._failed_fp is None`.
- `tests/conftest.py`: 변경 없음(`_reset_process_guard` 이름 유지).

추가 (`test_auth.py`):
1. `test_login_allowed_with_changed_password_after_failure`: 실패 후 비밀번호만 바꾼 Settings 로 로그인, POST 수행, 성공 시 지문 해제.
2. `test_login_allowed_with_changed_user_id_after_failure`: ID 만 변경.
3. `test_login_explicit_bypasses_fingerprint_guard`: 실패 후 같은 자격증명 `explicit=True` 는 POST 수행, 카운터 2로 증가.
4. `test_login_explicit_still_blocked_by_persistent_lock`: 카운터 3 이면 `explicit=True` 도 `LoginLocked`.
5. `test_login_success_clears_failed_fingerprint`: 실패 → 새 자격증명 성공 → 원래 실패 자격증명도 다시 지문 없음 상태(가드 해제)로 시도 가능.
6. `test_login_mfa_empty_body_and_network_error_do_not_set_fingerprint`: 세 경로 각각 후 같은 자격증명 재호출이 가드에 막히지 않음(parametrize).
7. `test_guard_error_has_code_and_gui_cli_hint`: `code == "guard"`, `hint` 에 "GUI" 와 "swea-fetch init" 둘 다 포함, "다시 실행하세요" 미포함.
8. `test_fingerprint_not_leaked`: `_failed_fp` 값과 예외 메시지·`caplog` 어디에도 비밀번호 원문이 없음. 같은 자격증명이면 지문이 같고 다르면 다름.
9. `test_get_session_relogin_after_earlier_success`: 성공 로그인 후 캐시 만료 상황에서 `get_session` 이 다시 로그인 성공(경로 A 회귀).
10. `test_get_session_blocked_after_failure_same_credentials_but_verify_allowed`: 경로 B 회귀. 실패 후 `get_session` 은 `LoginFailed(code="guard")`, `explicit=True` 는 통과.
11. `test_login_concurrent_calls_single_post`: 두 스레드가 동시에 `login` 호출 시 락으로 직렬화되어 실패 응답 1건 뒤 두 번째는 가드로 차단(POST 총 1회, 카운터 1).

추가 (`tests/test_service.py`):
12. `test_verify_login_passes_explicit_true`: `service.auth.get_session` 스텁이 `explicit=True` 를 받음. 기존 스텁 `get_session(settings)`(34행) 은 `explicit=False` 기본 인자를 받도록 시그니처 수정 필요(영향받는 스텁: test_service.py:34, 288, 456; gui/test_submit_gui.py:331 의 lambda 도 `**kw` 허용으로 수정).
13. 다른 서비스 함수(`fetch_problem` 등)는 `explicit` 미전달 단언.

추가 (`tests/test_errors.py` 또는 해당 파일):
14. `LoginFailed().hint` 에 "GUI"·"swea-fetch init" 포함 스냅샷.

추가 (`tests/gui/test_gui.py`):
15. `test_settings_verify_after_failure_can_retry_with_new_password`: `verify_login` 실제 경로를 네트워크 스텁 수준(`auth` 의 FakeSession 주입)으로 돌려, 1차 비밀번호 오류 → 설정 수정 → 2차 성공, 배너가 성공 상태가 되는지. 기존 스텁(331, 348, 521행)은 `verify_login` 자체를 대체하므로 이 회귀는 잡지 못한다. 그래서 auth 레벨 스텁 사용이 필수.

## 7. 수용 기준

1. GUI 에서 로그인 성공 후 세션이 만료돼도 fetch/check/submit 이 자동 재로그인으로 계속 동작한다(앱 재시작 불필요).
2. GUI 에서 비밀번호 오류 후 설정에서 고치고 [저장 후 로그인 확인] 을 누르면 로그인이 시도된다(재시작 불필요).
3. 같은 틀린 자격증명으로 자동 경로(fetch 등)를 연속 실행해도 서버 POST 는 최초 1회뿐이고 이후는 가드 메시지로 즉시 실패한다. `login_state.json` 카운터는 1 에서 멈춘다.
4. 명시 확인 반복 시에도 누적 3회에서 `LoginLocked` 로 중단된다.
5. 화면·로그·예외 어디에도 "명령을 다시 실행하세요" 가 없고, GUI/CLI 양쪽 조치가 힌트에 함께 표시된다.
6. 비밀번호 원문과 지문 값이 로그·예외·파일에 나타나지 않는다.
7. CLI 동작(종료 코드 1, 명령별 새 프로세스)은 변화 없음. 기존 테스트는 6절 수정분 외 무변경으로 통과하고 전체 스위트가 green.
8. 실계정 검증은 사용자 수행: (a) 로그인 후 `session.json` 을 지워 만료 상황을 만들고 GUI 에서 fetch(재로그인 성공), (b) 의도적으로 틀린 비밀번호는 **1회만** 시도해 가드/수정 흐름 확인. 계정 잠금 위험이 있으므로 tester 가 실계정 오답 반복 테스트를 하지 않는다.

## 8. 리스크·주의

- 지문 비교는 자격증명 문자열이 같은지만 본다. 서버 쪽 상태가 바뀐(휴면 해제 등) 경우는 explicit 경로로만 재시도 가능. 자동 경로에서 복구 안내는 `GUARD_HINT` 의 "브라우저 확인" 문구가 담당.
- 락은 `login` 내부에서만 잡고 네트워크 대기 중에도 유지된다(최대 약 2×`TIMEOUT`). GUI 워커가 잠깐 대기할 수 있으나 로그인은 드문 작업이라 수용.
- 별도 시간 기반 쿨다운·백오프는 도입하지 않는다(누적 3회 영속 카운터가 이미 상한이라 과설계).
- 정책 변경(자동 경로의 성공 후 재로그인 허용)으로 서버에 로그인 POST 가 늘 수 있으나, 성공 응답은 카운터를 0으로 리셋하므로 잠금 위험은 증가하지 않는다.
