# M16 핸드오프: MCP 서버 (다운로드 전용, 로컬 stdio)

작성: planner / 대상: builder, tester. 코드 미수정 (설계만). 최종 승인자는 사용자.

## 1. 목표와 범위
- AI 앱(Claude Desktop / Claude Code / Cursor)에서 "1231번 DFS1 에 받아줘" 로 기존 `fetch` 파이프라인을 호출한다.
- 비용 0: 사용자 PC 에서 AI 앱이 자식 프로세스로 띄우는 stdio 서버. 호스팅·원격 전송(HTTP/SSE) 없음.
- 포함: 저장, 미리보기, 주제 목록, 최근 저장 목록, 상태 확인 (도구 5개).
- 제외: 검증(check), 제출(submit), git 동기화·push, 지문 반환, 자격증명 설정/변경, 로그아웃.

## 2. 가정
- GitHub 저장소는 공개이거나 사용자 PC 에 git 이 있고 접근 가능 (`pip install git+https://...` 전제). 비공개면 README 절차가 막힌다 -> 승인 전 확인 필요.
- 사용자는 SSAFY Windows PC + Python 3.11+ 보유 (기존 README "소스/CLI" 와 동일 전제). PyInstaller exe 사용자는 MCP 를 못 쓴다 (exe 에 mcp 를 넣지 않음).
- `mcp` 공식 Python SDK 1.x 의 `mcp.server.fastmcp.FastMCP` 를 쓴다. 정확한 최소 버전·import 경로는 builder 가 설치 후 실측해 pyproject 에 확정 (구조화 출력이 필요하면 1.10 이상으로 추정). SDK 의존 코드는 `mcp_server.py` 한 파일에만 둔다.
- AI 앱 3종의 설정 파일 위치/키 이름은 2026-09 기준 공개 문서 지식이며, 수동 검증에서 사용자가 확인한다.

## 3. 핵심 결정
| 결정 | 내용 | 이유 |
|---|---|---|
| D1 도구 로직과 SDK 분리 | `mcp_tools.py`(SDK import 없음) + `mcp_server.py`(FastMCP 등록만) | SDK 없이 단위 테스트, SDK 변경 영향 격리 (M12 service 분리와 같은 원칙) |
| D2 자격증명 | 도구 인자에 ID/PW/쿠키 없음. `swea-fetch init` 선행. 설정 없으면 `config_missing` + init 안내 | 대화 기록·AI 벤더 서버에 비밀번호가 남지 않게 |
| D3 자동 push 차단 | MCP 경로에서는 `auto_push_on` 에서 `save` 를 항상 뺀다 (CLI `--no-push` 와 같은 방식). 결과에 `auto_sync` 로 알림 | AI 가 사용자 확인 없이 원격 저장소로 커밋·push 하는 것을 막음. 켜는 옵션은 P2 로 보류 |
| D4 지문 도구 제외 | 지문(문제 본문)을 AI 에게 반환하는 도구를 만들지 않음 | GUI 표시는 로컬 화면에서 끝나지만, MCP 반환은 대화 기록과 AI 벤더 서버로 전송되는 별개의 재배포. 요구도 "다운로드만". P2 옵트인 후보로 기록만 |
| D5 호출 직렬화 | 프로세스 내 모든 도구 호출을 전역 락 1개로 직렬화 | session.json / problem_index.json / login_state.json 쓰기가 원자적이지 않고 같은 문제 동시 저장 시 충돌 검사가 경쟁함 |
| D6 오류는 예외 대신 구조화 결과 | 모든 도구가 `{"ok": false, "code", "message", "hint", "retryable"}` 를 반환 | AI 가 코드로 분기, hint 를 그대로 사용자에게 전달. 서버 예외/트레이스백이 대화에 새지 않음 |
| D7 설정은 호출마다 로드 | 서버 시작 시 설정 없어도 정상 기동, 도구 호출마다 `config.load_settings()` | 서버 켠 채로 `swea-fetch init` 을 해도 재시작 불필요. 키링 조회는 로컬 호출이라 비용 미미 |

## 4. 도구 명세
공통: 이름 접두사 `swea_` (다른 MCP 와 충돌 방지). 반환은 JSON 직렬화 가능한 dict. 모든 문자열 결과는 5절 redact 를 거친다.

공통 오류 봉투:
```
{"ok": false, "status": "error", "code": "<5절 코드>", "message": "...", "hint": "...", "retryable": false}
```

### 4.1 `swea_status(check_login: bool = False)` — 읽기 전용
- 인자: `check_login` true 면 네트워크로 로그인 확인 (`auth.get_session(settings)`, **explicit 를 쓰지 않는다** = 지문 가드 유지. `verify_login` 은 가드를 우회하므로 호출 금지).
- 반환(설정 있음): `{"ok": true, "configured": true, "version", "root", "root_exists", "user_id_masked" (앞 2글자+***+@도메인), "password_stored": true, "session_cached", "login_ok": null|true, "auto_sync_on_save": bool, "auto_sync_note"}`.
- 반환(설정 없음, ConfigMissing): `{"ok": true, "configured": false, "message": <예외 메시지>, "next_step": "터미널에서 `swea-fetch init` 실행 (비밀번호는 AI 대화에 입력하지 마세요)"}`. 상태 조회 자체는 성공이므로 ok=true.
- `check_login=true` 실패 시 오류 봉투 (login_failed 등).
- 비밀번호 값, 출처(`password_source`)는 반환하지 않는다 (있다/없다만).

### 4.2 `swea_fetch(problem, topic, force=False, skeleton_only=False, refresh_index=False)` — 파일 씀
- `problem`: `int | str` (SDK 가 숫자를 int 로 넘겨도 받도록). 문제 번호, 문제 URL, contestProbId. 내부에서 `str().strip()`. 빈 값/bool/300자 초과 -> `invalid_input`.
- `topic`: `str`, 필수. 예 `DFS1`, `test/IM_test`. 길이 100자 초과 -> `invalid_input`. 경로 검증은 `storage.normalize_topic`/`resolve_problem_dir` 가 담당 (`..`, 숫자만, 4단계 초과, 루트 밖 거부) -> `InvalidInput`.
- `force`: 기본 false. 도구 설명에 "사용자가 덮어쓰기를 명시적으로 승인했을 때만 true" 를 적는다. `{num}.py`(사용자 코드)는 force 여도 보존됨 (storage 기존 동작).
- `skeleton_only`: 샘플 첨부 없는 문제용. `refresh_index`: 번호 색인 재구축.
- 내부: `FetchOptions(force, skeleton_only, dry_run=False, refresh_index, with_content=False, cache_content=False)`, settings 는 `dataclasses.replace(settings, auto_push_on=settings.auto_push_on - {"save"})` 적용 후 `service.fetch_problem(settings, str(problem), topic, opts, progress=None)`.
- 성공: 
```
{"ok": true, "status": "saved", "num": 1231, "title": "...", "topic": "DFS1",
 "problem_dir": "C:\\...\\DFS1\\1231",
 "files": [{"name": "input.txt", "action": "written"}, {"name": "output.txt", "action": "written"}, {"name": "1231.py", "action": "written"|"kept"}],
 "notices": ["기존 폴더 'DFS1' 를 사용합니다 ..."],
 "auto_sync": "off" | "disabled_in_mcp"}
```
  `files.action` 은 `SaveResult.written -> "written"`, `skipped -> "kept"`. `auto_sync` 는 원래 설정이 `auto_push and "save" in auto_push_on` 이었으면 `disabled_in_mcp` (message 에 "GUI/CLI 로 동기화하세요" 안내).
- 이미 파일 있음 (force=false): `ok=false, status="exists", code="already_exists"`, `existing`: 파일명 목록, `hint`: "덮어쓰려면 사용자 확인 후 force=true 로 다시 호출". 기존 파일은 그대로 (storage 가 쓰기 전에 검사).
- 저장 도중 실패는 storage 가 롤백 (기존 동작, 테스트 재확인 불필요).

### 4.3 `swea_preview(problem, topic, force=False, skeleton_only=False, refresh_index=False)` — 저장 안 함
- `swea_fetch` 와 같은 검증, `dry_run=True`. 로그인·페이지·첨부 다운로드는 하지만 디스크에 쓰지 않는다 (색인/세션 캐시 갱신 제외).
- 반환: `{"ok": true, "status": "preview", "num", "title", "topic", "problem_dir", "files": [{"name", "action": create|overwrite|keep|conflict|create_empty, "source", "size"}], "needs_force": bool, "notices": [...]}`.
- FilePlan.preview(샘플 첫 줄 텍스트)는 반환하지 않는다 (크기만). 도구 별도 분리 이유: 클라이언트가 읽기 전용 도구를 승인 없이 허용할 수 있게 `readOnlyHint=true` 어노테이션 부여 (`swea_fetch` 는 `readOnlyHint=false`, `openWorldHint=true`).
- 내부 구현은 `_run_fetch(dry_run)` 한 함수 공유.

### 4.4 `swea_list_topics()` — 읽기 전용, 네트워크 없음
- `service.list_topics(settings)` -> `{"ok": true, "root", "topics": ["DFS1", "test/IM_test"], "count"}`. 최대 200개, 넘으면 `truncated: true`.

### 4.5 `swea_list_recent(limit: int = 10)` — 읽기 전용, 네트워크 없음
- `limit` 는 1~50 으로 clamp. `service.list_recent(settings, limit)` -> `{"ok": true, "items": [{"num", "title" (없으면 null), "topic", "path", "saved_at" (ISO 8601)}]}`.
- 주의: root 전체 폴더를 훑는다. root 가 비정상적으로 크면 느릴 수 있음 (리스크 표 참고).

## 5. 오류 매핑 (`errors.py` 예외 -> 결과)
매핑은 `mcp_tools.map_error(exc, settings|None) -> dict` 한 함수. **서브클래스를 먼저 검사** (MfaRequired/LoginLocked 가 LoginFailed 보다 앞). `errors.py` 는 수정하지 않는다. CLI 전용 문구(`--force`, `--skeleton-only`, `--num`, GUI 설정 페이지)는 AI 에게 혼란을 주므로 hint 를 MCP 용으로 덮어쓴다. message 는 원칙적으로 `str(e)` 를 쓰되 아래에 명시한 경우만 재구성한다.

| 예외 | code | retryable | message | hint (MCP 용) |
|---|---|---|---|---|
| `ConfigMissing` | `config_missing` | false | `str(e)` | "사용자에게 터미널에서 `swea-fetch init` 을 실행하도록 안내하세요. 비밀번호를 대화에 적게 하지 마세요. init 후에는 서버 재시작 없이 다시 시도할 수 있습니다" |
| `MfaRequired` | `mfa_required` | false | `str(e)` | e.hint 그대로 (2단계 인증 해제 안내) + "재시도 금지" |
| `LoginLocked` | `login_locked` | false | `str(e)` | e.hint 그대로 + "재시도 금지, 사용자가 브라우저에서 로그인 확인 후 login_state.json 삭제" |
| `LoginFailed` (code=="guard") | `login_guard` | false | GUARD_MSG | "같은 자격증명 재시도는 계정 잠금 위험으로 차단됨. 사용자가 `swea-fetch init` 으로 고친 뒤에만 다시 시도" |
| `LoginFailed` (그 외) | `login_failed` | false | `str(e)` | "재시도하지 말고 사용자에게 알리세요 (5회 실패 시 계정 잠금). 사용자가 `swea-fetch init` 으로 자격증명을 확인해야 합니다" |
| `SessionExpired` | `session_expired` | true | `str(e)` | "잠시 후 한 번만 다시 시도" (client 가 내부 재로그인하므로 보통 노출 안 됨) |
| `InvalidInput` | `invalid_input` | false | `str(e)` | "문제 번호(숫자) 또는 문제 URL 과 주제 폴더 이름을 확인하세요" |
| `ProblemNotFound` | `problem_not_found` | false | `str(e)` | e.hint 그대로 (접근 권한/ID 확인) |
| `ParseError` | `parse_error` | false | `str(e)` | "SWEA 페이지 구조가 바뀌었을 수 있습니다. 사용자가 저장소 이슈로 제보하도록 안내" (`--num`/`-v` 문구 제거) |
| `AttachmentNotFound` | `attachment_not_found` | false | "샘플 입출력 첨부가 없는 문제입니다" + 찾은 첨부(`e.found`) | "skeleton_only=true 로 다시 호출하면 폴더 + {번호}.py + 빈 input.txt 만 만듭니다" |
| `AlreadyExists` | `already_exists` (status="exists") | false | **재구성**: "이미 저장된 파일이 있어 덮어쓰지 않았습니다: " + 파일명(경로 아님) 목록 (`str(e)` 의 `--force` 문구 회피) | "사용자에게 덮어써도 되는지 확인한 뒤 force=true 로 다시 호출. {번호}.py 는 유지됨" |
| `NetworkError` | `network_error` | true | `str(e)` (redact 적용) | e.hint 그대로 |
| `GitError` | `git_error` | false | `str(e)` | 도달 불가 예상 (fetch 는 sync_now 예외를 삼킴). 방어용 |
| `CheckFailed`, `SubmitError` | `unsupported` | false | 도달 불가 예상. 방어용 | - |
| 기타 `SweaFetchError` | `error` | false | `str(e)` | e.hint |
| 그 외 `Exception` | `internal_error` | false | `"내부 오류: " + type(e).__name__` **만** (메시지·트레이스백 미반환) | "서버 로그(stderr)를 확인하세요". 전체 트레이스백은 `log.exception` 으로 stderr 에만 |
| 락 대기 초과 | `busy` | true | "다른 요청 처리 중입니다" | "잠시 후 다시 시도" |

### redact (결과·로그 공통)
- `redact(text, settings)`: `settings.password` 가 비어 있지 않으면 모든 출현을 `***` 로 치환. 도구 반환/로그 직전에 항상 적용. 쿠키 값은 애초에 예외 메시지에 들어가지 않지만(auth 는 값 미로깅) 방어로 `SESSION=...`, `Cookie:` 패턴도 치환.
- 반환 dict 에 `settings` 객체, 환경변수, 세션 쿠키, `.env` 원문을 넣지 않는다 (`user_id` 는 masked 만).

## 6. 동시성
- AI 앱은 한 세션에서 도구를 병렬 호출할 수 있고(예: "1231, 1232, 1233 받아줘"), FastMCP 는 동기 함수를 이벤트 루프에서 직접 실행해 서버 전체를 막는다. 따라서 `mcp_server.py` 의 도구는 `async def` 로 등록하고 `await anyio.to_thread.run_sync(tools.fetch, ...)` 로 스레드에 넘긴다.
- `SweaTools` 는 인스턴스에 `threading.Lock` 1개를 가지고 5개 도구 전부를 그 안에서 실행 (D5). 락 획득 대기 상한 120초(생성자 인자로 테스트에서 축소) -> 초과 시 `busy`.
- 효과: auth 의 `_login_lock`/실패 지문 가드(5df6da3)와 함께 "동시에 로그인 2회 -> 카운터 오염" 경로를 막는다. 다건 요청은 순차 처리되어 총 시간은 늘지만 SWEA 서버 부하 측면에서도 바람직.
- 스레드 취소는 불가: 클라이언트가 요청을 취소해도 스레드는 끝까지 실행 (저장은 롤백 보장이 있어 반쪽 저장 없음).
- **프로세스 간 경합은 보호하지 않는다**: Claude Desktop + Cursor 가 각자 서버를 띄우거나 GUI 와 동시에 쓰는 경우. 파일 락은 과설계로 보고 미도입 (리스크 표 R5).
- 첫 번호 조회는 색인 구축 때문에 오래 걸릴 수 있다 (실측 필요, 15초 요청 타임아웃 × 여러 상자). 클라이언트 도구 타임아웃 리스크는 R2.

## 7. 로깅과 stdout 규율
- stdout 은 MCP 프레임 전용. `mcp_tools.py`/`mcp_server.py` 에서 `print`, `sys.stdout` 사용 금지 (정적 테스트로 강제, 9절).
- `main()` 첫 줄에서 `logging.basicConfig(stream=sys.stderr, level=WARNING, force=True)`. `SWEA_MCP_DEBUG=1` 이면 INFO 까지만 (DEBUG 금지: urllib3 등 하위 로거가 URL/헤더를 찍을 수 있음). `urllib3`/`requests` 로거는 WARNING 고정.
- `service.fetch_problem` 의 `progress` 콜백은 None (진행 메시지는 로그 INFO 로만 남고 기본 레벨에서 안 보임).
- `mcp` 미설치 시 `mcp_server.main()` 은 stderr 에 "`pip install \"swea-fetcher[mcp]\"` 로 설치하세요" 출력 후 exit 1 (스택트레이스 없이).

## 8. 파일 변경
| 파일 | 변경 |
|---|---|
| `swea_fetcher/mcp_tools.py` (신규, SDK 비의존) | `class SweaTools(config_dir=None, lock_timeout=120)` 메서드 `status/fetch/preview/topics/recent`; `map_error`, `redact`, `mask_user_id`, 입력 검증. `config.load_settings(config_dir)` 를 호출마다 실행 |
| `swea_fetcher/mcp_server.py` (신규) | `build_server(tools=None) -> FastMCP` (도구 5개 등록, 설명문·어노테이션·`async` 래퍼), `main()` (로깅 설정, mcp import 가드, `run(transport="stdio")`), `if __name__ == "__main__": main()` |
| `pyproject.toml` | `[project.optional-dependencies] mcp = ["mcp>=<실측>,<2"]`, `[project.scripts] swea-fetch-mcp = "swea_fetcher.mcp_server:main"`, `dev` 에 mcp 포함은 선택 (SDK 없이도 도구 테스트는 통과해야 함) |
| `swea_fetcher/__init__.py` | 버전 0.9.0 (승인 후) |
| `README.md` | 10절 절 추가 + "하는 일" 목록 1줄 |
| `docs/troubleshooting.md` | "MCP" 항목: 서버가 안 붙을 때, 오류 코드 표(5절 요약) |
| `CHANGELOG.md` | 0.9.0 항목 |
| `tests/test_mcp_tools.py` (신규), `tests/test_mcp_server.py` (신규, `pytest.importorskip("mcp")`) | 9절 |
| 변경 금지 | `errors.py`, `service.py`, `auth.py`, `config.py`, `storage.py` (기존 로직 재사용만). 부득이 필요하면 builder 가 사유를 보고하고 승인 받는다 |

빌드 스크립트(PyInstaller)가 있다면 `mcp` 가 exe 에 끌려 들어가지 않는지만 확인 (extra 이므로 기본 제외).

## 9. 테스트 (mcp SDK 없이도 도구 테스트 통과, 네트워크 금지)
기존 conftest 의 `_no_network`, `fake_keyring`, `_isolate_env`, `_isolate_config_dir` 자동 격리를 그대로 활용. 테스트에서 비밀번호는 환경변수 `SWEA_PW` 또는 `Settings` 더미로 주입 (실제 키링 접근 없음). `SweaTools(config_dir=tmp)` 로 격리.

`tests/test_mcp_tools.py` (SDK 불필요):
1. 통합 경로: `auth.get_session` 을 FakeSession 으로 대체, 기존 fixtures(`solver_html`, 첨부 응답)로 실제 `service.fetch_problem` 실행 -> tmp root 에 파일 3개 생성, 반환 스키마(키·타입) 검증, `files.action` 매핑, `auto_sync`.
2. 이미 있음: 같은 호출 2회 -> 2회째 `status="exists"`, 기존 파일 내용 불변, message 에 `--force` 없음. `force=True` -> 덮어쓰기, `{num}.py` 보존.
3. preview: 디스크 무변화 (폴더 미생성), `needs_force` 계산, `preview` 텍스트 키 없음.
4. 오류 매핑: `service.fetch_problem` 을 예외로 monkeypatch, errors.py 의 **모든 클래스**를 parametrize (`MfaRequired`, `LoginLocked`, `LoginFailed(code="guard")`, `LoginFailed`, `SessionExpired`, `InvalidInput`, `ProblemNotFound`, `ParseError`, `AttachmentNotFound(found=[...])`, `AlreadyExists(existing=[...])`, `NetworkError`, `GitError`, `CheckFailed`, `SubmitError`, `RuntimeError`) -> code/retryable/hint 기대값. errors.py 에 새 예외 클래스가 추가됐는데 표에 없으면 실패하는 가드 테스트 (모듈의 SweaFetchError 하위 클래스 전수 확인).
5. `internal_error`: message 에 예외 원문(비밀번호 문자열 포함시켜 검증)이 없고 타입명만.
6. redact: NetworkError 메시지에 더미 비밀번호를 넣어도 결과 JSON 에 미포함. 모든 도구의 성공/실패 결과를 `json.dumps` 한 문자열에 `DUMMY_PW`, 쿠키 문자열, "password" 값이 없음.
7. config: `.env` 없음 -> `swea_status` 는 `configured=false` + next_step, `swea_fetch` 는 `config_missing`. 서버 "실행 중"에 `.env` 를 만들면 다음 호출부터 성공 (D7).
8. 자동 push 차단: settings 에 `auto_push=True, auto_push_on={"save"}`, `service.sync_now` 를 기록용으로 monkeypatch -> fetch 후 호출 0회, `auto_sync == "disabled_in_mcp"`. 설정이 꺼져 있으면 `"off"`.
9. 지문 비추출: `service.fetch_problem` 호출 인자의 `FetchOptions.with_content is False`, `cache_content is False`.
10. 동시성: `service.fetch_problem` 대체 함수가 진입/이탈 카운터로 동시 실행 수를 기록 + 짧은 sleep -> 스레드 4개로 `fetch` 동시 호출 시 최대 동시 실행 1. `lock_timeout=0.05` 로 장시간 작업 중 두 번째 호출 -> `busy`.
11. 입력 검증: 빈 problem, bool, 301자 problem, 숫자 int 입력(=str 변환), topic `..`/숫자만/5단계 -> `invalid_input`, 어떤 경우도 root 밖에 파일 생성 없음.
12. list_recent limit clamp(0, 999), list_topics truncated.
13. status: `check_login=True` 는 `auth.get_session` 을 `explicit=True` 없이 호출 (가드 유지 확인: 가드가 선 상태에서 `login_guard` 반환).
14. 정적 검사: `mcp_tools.py`, `mcp_server.py` 소스에 `print(` / `sys.stdout` 없음. `mcp_tools.py` 는 `mcp` 를 import 하지 않음 (import 후 `sys.modules` 에 `mcp` 없음 확인).

`tests/test_mcp_server.py` (`pytest.importorskip("mcp")`):
- `build_server(SweaTools(tmp))` 의 도구 이름이 정확히 5개, 어떤 도구 스키마에도 `password|pw|pwd|cookie|user|id` 류 인자 없음 (`problem`, `topic` 등 허용 목록과 비교).
- 어노테이션: `swea_preview/list_topics/list_recent/status` 는 readOnlyHint=true, `swea_fetch` 는 false.
- 인메모리 클라이언트 세션(SDK 의 테스트용 in-memory 연결 유틸, builder 가 API 실측)으로 `swea_list_topics` 호출 왕복.
- subprocess 스모크: `python -m swea_fetcher.mcp_server` 실행, stdin 으로 `initialize` -> `tools/list` 를 보내고 stdout 의 모든 줄이 유효한 JSON-RPC 인지 확인 (설정 없이도 기동되어야 함). 네트워크 없음.

전체 기존 스위트 회귀 통과.

## 10. README 설치 절 (초안 요구사항)
제목: "AI 앱에서 쓰기 (MCP, 선택)". 대상은 Python 이 있는 Windows 사용자. PowerShell 기준, 한 블록에 한 명령 (기존 README 스타일). exe 사용자는 이 기능을 쓸 수 없다고 명시.

1. 전용 가상환경 만들기 (경로 예: `%USERPROFILE%\swea-fetch-venv`):
```powershell
py -3 -m venv $env:USERPROFILE\swea-fetch-venv
```
2. 설치 (git 필요):
```powershell
& $env:USERPROFILE\swea-fetch-venv\Scripts\pip install "swea-fetcher[mcp] @ git+https://github.com/yoon7270/swea_fetcher.git"
```
3. 계정 설정 — **터미널에서 직접 입력. AI 채팅창에 비밀번호를 적지 마세요**:
```powershell
& $env:USERPROFILE\swea-fetch-venv\Scripts\swea-fetch init
```
4. AI 앱 등록 (실행 파일 절대 경로 `C:/Users/<내이름>/swea-fetch-venv/Scripts/swea-fetch-mcp.exe`; JSON 에서는 백슬래시 대신 `/` 를 쓰거나 `\\` 로 이스케이프):
   - Claude Code: `claude mcp add --scope user swea -- C:/Users/<내이름>/swea-fetch-venv/Scripts/swea-fetch-mcp.exe`
   - Claude Desktop: 설정 -> 개발자 -> 구성 편집 (`claude_desktop_config.json`, 보통 `%APPDATA%\Claude\`; 앱 종류에 따라 위치가 다르므로 버튼으로 여는 방법을 우선 안내), 저장 후 앱 완전 종료·재실행:
```json
{
  "mcpServers": {
    "swea": {
      "command": "C:/Users/<내이름>/swea-fetch-venv/Scripts/swea-fetch-mcp.exe",
      "args": []
    }
  }
}
```
   - Cursor: `%USERPROFILE%\.cursor\mcp.json` 에 같은 `mcpServers` 블록.
5. 사용 예: "1231번 DFS1 에 받아줘", "먼저 미리보기만 해줘", "최근에 받은 문제 5개", "SWEA 설정 상태 확인해줘".
6. 업데이트: 2번 명령에 `--upgrade` 추가 후 AI 앱 재시작. 제거: AI 앱에서 서버 삭제(`claude mcp remove swea`) + 가상환경 폴더 삭제, 공용 PC 는 `swea-fetch logout --all`.
7. 주의 문구: 비밀번호는 MCP 를 통과하지 않음 / 저장만 하고 git push 는 하지 않음(자동 동기화 설정과 무관) / 문제 지문은 AI 에게 전달하지 않음 / 폴더 경로·문제 제목·마스킹된 ID 는 AI 앱(과 그 서비스)에 전달됨 / 덮어쓰기는 사용자 확인 후에만.
8. 문제 해결 링크: 서버가 목록에 없음(경로 오타, `claude mcp list`, 앱 재시작), `config_missing`(init), `login_*`(재시도 금지 안내).

(uv 를 쓰는 사용자용 한 줄 대안 `uvx --from "swea-fetcher[mcp] @ git+https://github.com/yoon7270/swea_fetcher.git" swea-fetch-mcp` 는 첫 실행 지연으로 클라이언트 시작 타임아웃 위험이 있어 README 본문에 넣지 않고 troubleshooting 에 "고급" 으로만 둔다.)

## 11. 수용 기준
- AC1: `pip install ".[mcp]"` 후 `swea-fetch-mcp` 가 설정 없이도 기동하고 stdout 에 JSON-RPC 외 출력이 없다.
- AC2: `tools/list` 가 정확히 5개 도구(4절)를 노출하고 어떤 인자에도 자격증명/쿠키가 없다.
- AC3: `swea_fetch` 가 CLI `swea-fetch 1231 DFS1` 과 같은 파일 3개를 만든다 (동일 storage 경로 사용).
- AC4: 기존 파일이 있으면 덮어쓰지 않고 `exists`; `force=true` 일 때만 input/output 을 덮고 `{num}.py` 는 보존.
- AC5: 자동 동기화가 켜진 설정에서도 MCP 저장은 커밋/푸시를 일으키지 않고 `auto_sync=disabled_in_mcp` 를 반환.
- AC6: 설정/자격증명 없음 -> `config_missing` + init 안내 (`swea_status` 는 `configured=false`).
- AC7: 5절 표의 모든 예외가 code/hint 로 매핑되고, `internal_error` 는 타입명 외 정보를 반환하지 않는다.
- AC8: 어떤 도구 결과·stderr 로그에도 비밀번호, 쿠키, 전체 ID 가 없다 (테스트 6, 14).
- AC9: 지문을 반환하는 도구/필드가 없다.
- AC10: 동시 호출이 직렬 실행된다 (테스트 10). 대기 초과는 `busy`.
- AC11: mcp 미설치 환경에서 `swea_fetcher.mcp_tools` import 와 그 단위 테스트가 통과하고, 기존 CLI/GUI 는 mcp 없이 그대로 동작한다.
- AC12: README 절차대로 새 Windows 계정(또는 깨끗한 venv)에서 설치 -> init -> Claude Code 등록 -> 저장까지 성공 (12절).
- AC13: 전체 pytest 통과.

## 12. 수동 검증 절차 (사용자 PC, Claude Code)
비밀번호 관련 단계는 사용자가 직접 한다. builder 는 비밀번호를 모른 채 사용자 init 이후에만 E2E 를 실측한다 (채팅에 비밀번호를 적지 마세요).

1. (사용자) README 10절 1~3 실행: venv 생성 -> 설치 -> `swea-fetch init`. `swea-fetch doctor` 로 설정 확인.
2. (사용자/tester) 서버 등록: `claude mcp add --scope user swea -- C:/Users/<이름>/swea-fetch-venv/Scripts/swea-fetch-mcp.exe` -> `claude mcp list` 에서 swea 가 Connected. Claude Code 안에서 `/mcp` 로 도구 5개 확인.
3. 상태: "swea_status 로 설정 상태 알려줘" -> `configured=true`, ID 마스킹, 비밀번호 값 없음. "로그인까지 확인" -> `login_ok=true` (1회만).
4. 목록: "swea_list_topics", "최근 저장한 문제 5개" -> 실제 root 와 일치.
5. 미리보기: "1231번 DFS1 미리보기" -> 폴더/파일 미생성 확인 (탐색기), 결과 files 표시.
6. 저장: "1231번 DFS1 에 받아줘" -> `root\DFS1\1231\` 에 input.txt/output.txt/1231.py. 파일 내용이 CLI 로 받은 것과 같은지 대조 (다른 번호로 CLI 저장 후 동일 구조 비교).
7. 재호출: 같은 요청 -> `exists`, AI 가 덮어쓸지 사용자에게 물어보는지 관찰 (도구 설명문 효과 확인). 승인 시 force 로 덮어쓰기, `1231.py` 에 임의 줄을 넣어두고 보존 확인.
8. 다건: "1232, 1233, 1234 를 DFS1 에 받아줘" -> 순차 성공, 오류 없음, 소요 시간 기록 (R2 실측).
9. 자동 push 차단: 테스트용 저장소를 root 로 두고 `SWEA_AUTO_PUSH=1`, `SWEA_AUTO_PUSH_ON=save` 를 .env 에 설정 -> MCP 로 저장 -> `git log` 에 새 커밋 없음, 결과 `auto_sync=disabled_in_mcp`. (같은 설정에서 CLI 는 푸시함을 확인해 차이를 문서화.) 확인 후 설정 원복.
10. 설정 없음: `%USERPROFILE%\.swea-fetch\.env` 를 임시로 이름 변경 -> 서버 재시작 없이 "받아줘" -> `config_missing` 안내가 사용자에게 전달되고 AI 가 비밀번호를 묻지 않는지 확인 -> 원복 후 재시도 성공 (D7).
11. 잘못된 입력: 존재하지 않는 번호, topic `..`, 문자열 "abc" -> 각각 오류 코드와 안내. **실계정에 틀린 비밀번호를 넣는 검증은 하지 않는다** (잠금 위험; 로그인 오류는 단위 테스트가 담당).
12. stdout 청결: `claude --mcp-debug` 로 시작 시 파싱 오류 메시지 없음. 서버 로그(stderr)에 비밀번호/쿠키 없음 (`session.json` 값을 검색해 로그와 대조).
13. (선택) Claude Desktop, Cursor 에 10절 JSON 으로 등록해 "1231번 받아줘" 1건씩 확인, 앱 재시작 필요 여부 기록.
14. 정리: `claude mcp remove swea`. 공용 PC 면 `swea-fetch logout --all`.

## 13. 마일스톤 (소규모, builder 1명)
| 단계 | 산출물 | 완료 조건 |
|---|---|---|
| M16-1 | `mcp_tools.py` + `tests/test_mcp_tools.py` | 9절 테스트 1~14 통과, mcp 미설치 환경 통과 |
| M16-2 | `mcp_server.py`, pyproject extra/script, `tests/test_mcp_server.py` | AC1, AC2, 스모크 통과 (SDK 버전 확정) |
| M16-3 | README/troubleshooting/CHANGELOG/버전 | 10절 반영, 명령 블록을 실제 실행해 검증 |
| M16-4 | 수동 검증 (12절) | 사용자 init 후 tester 실측 -> 사용자 실사용 확인 |

## 14. 우선순위
- P0: 도구 5개, 오류 매핑, redact, auto push 차단, 직렬화, stdio 규율, extra/script, 테스트, README.
- P1: `swea-fetch doctor` 에 "mcp 설치 여부/버전" 한 줄, 진행 알림(`ctx.report_progress`, 첫 색인 구축 시 클라이언트 타임아웃 완화), `num_override` 인자.
- P2 (요청 시 별도 승인): 지문 반환 도구(옵트인 환경변수 + 재배포 리스크 재검토), 저장 후 push 도구(명시 호출 전용), 다건 일괄 도구, exe 동봉 MCP, 파일 락(프로세스 간).

## 15. 리스크와 대응
| ID | 리스크 | 대응 |
|---|---|---|
| R1 | SDK API/버전 변동 (FastMCP 경로, 구조화 출력) | 버전 범위 고정, SDK 의존을 `mcp_server.py` 한 곳에, 스모크 테스트 |
| R2 | 첫 번호 조회(색인 구축)가 길어 클라이언트 도구 타임아웃 | 12절 8번 실측. 길면 P1 진행 알림, README/troubleshooting 에 Claude Code 의 MCP 타임아웃 환경변수 안내 (정확한 이름은 builder 가 공식 문서 확인) |
| R3 | AI 가 사용자 승인 없이 `force=true` 호출 | 도구 설명에 명시 + 클라이언트의 도구별 승인 프롬프트 활용 안내. 피해 범위는 재다운로드 가능한 input/output 뿐 ({num}.py 는 항상 보존) |
| R4 | AI 재시도 루프로 로그인 실패 누적 -> 계정 잠금 | 지문 가드 + 누적 3회 중단(기존) + `retryable=false` + hint "재시도 금지" + status 는 explicit 미사용 |
| R5 | 프로세스 간 경합 (여러 AI 앱, GUI 동시) | 미보호 (파일 락은 과설계). README 에 "동시에 여러 AI 앱에서 쓰지 마세요" 한 줄. 실사용에서 문제되면 P2 |
| R6 | 개인정보 노출: 경로(Windows 사용자명), 문제 제목, 마스킹 ID 가 AI 서비스로 전달 | README 7번 주의문. 전체 ID·비밀번호·쿠키는 결과에 없음 |
| R7 | 프롬프트 인젝션으로 임의 폴더 생성 | `normalize_topic`/`resolve_problem_dir` 로 루트 밖 차단 (테스트 11). 루트 아래 폴더 생성은 허용 위험으로 수용 |
| R8 | 설치 장벽 (git 필요, 비공개 저장소, Python 경로, JSON 백슬래시) | 절대 경로 + `/` 표기, venv 고정 경로, troubleshooting. 비공개면 승인 전 조정 |
| R9 | 저작물: 샘플 입출력은 기존처럼 로컬 파일로만, 지문은 미반환 | D4, AC9 |
| R10 | 공용 PC 에 서버 등록이 남음 | README 제거/logout 안내 (자격증명은 keyring 이라 서버만 남아도 다른 사용자 계정엔 영향 없음, 같은 Windows 계정 공유 시는 기존 경고와 동일) |

## 16. 검토 노트 (자기검토)
- 반영: 도구 6개 -> 5개로 축소(로그인 확인은 status 에 통합), 지문 도구 제외, auto push 는 조용히 끄지 않고 결과로 알림, `verify_login`(가드 우회) 사용 금지 명시, 서버 시작 시 설정 요구하지 않도록 함.
- 남은 우려: (1) 공개 저장소 여부와 git 요구는 사용자 확인 필요. (2) 색인 구축 시간이 클라이언트 타임아웃을 넘는지는 실측 전까지 불확실. (3) 일부 서비스 메시지(예: InvalidInput 의 "--num", MfaRequired 의 "M3")는 CLI/내부 용어가 남아 AI 가 그대로 전달할 수 있음 -- errors.py 를 건드리지 않는 대신 hint 로 상쇄, 거슬리면 후속으로 문구 정리. (4) 전역 락 대기 120초는 임의값, 실측 후 조정. (5) SDK 버전은 builder 실측 확정 필요.
