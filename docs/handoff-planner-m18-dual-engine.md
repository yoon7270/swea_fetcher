# M18 핸드오프: AI 코치 "둘 다" 모드 (GPT + Claude 동시 요청, 답 2개 표시)

작성: planner / 대상: builder, designer, tester. 코드 미수정 (설계만). 최종 승인자는 사용자.
기준: v0.10.0 + cc16610 (main) -> 목표 v0.11.0 (기능 추가 minor; 버전 번호는 메인이 조정 가능). 기준 문서: `docs/handoff-planner-m17-ai-coach.md`(이하 M17), `design/design-spec.md`.

---

## 1. 목표와 범위

AI 코치 엔진 설정에 **"GPT & Claude (둘 다)"** 를 추가한다. 같은 요청(코드 평가 / 힌트 / 정답 풀이 / 연결 테스트)을 Codex 와 Claude Code 에 **동시에** 보내 답 2개를 나란히 보여준다. 기존 단일 엔진 동작(자동/GPT/Claude)은 그대로 유지한다.

범위 밖: 3개 이상 엔진, 두 답의 자동 요약/비교/합의, 엔진별 모델 지정, CLI/MCP 노출(M17 과 동일), 둘 다 모드의 "먼저 온 답만 쓰고 나머지 취소".

## 2. 가정

- 실측 응답 ~15초/엔진, 병렬이면 체감 ~15초 (느린 쪽). 프로세스 2개 동시 기동은 사용자 PC 에서 문제 없다고 본다 (node 2개).
- 기존 M17 안전 원칙(stdin 전달, 빈 임시 폴더, 읽기 전용/도구 차단, 동의, 프롬프트 미로깅)은 엔진마다 그대로 적용된다. 요청마다 임시 폴더가 엔진별로 따로 생긴다 (`run()` 이 이미 그렇게 동작).
- 캐시 파일 안의 기존 `engine` 필드는 **표시 이름(label)** 문자열이다 ("Codex" / "Claude Code") -> 마이그레이션 시 엔진을 복원할 수 있다 (5절).
- 표시 이름을 바꾸므로 기존 테스트 중 label 문자열("Codex", "Claude Code")을 단정하는 것은 갱신이 필요하다 (builder 가 grep).

## 3. 결정표

| # | 결정 | 이유 |
|---|---|---|
| E1 | `SWEA_AI_ENGINE` 값에 `both` 추가. 콤보 순서: **자동(Codex 우선) / GPT (Codex) / Claude (Claude Code) / GPT & Claude (둘 다)**. **기본값은 `auto` 유지** | 둘 다는 구독 사용량 2배 -> 옵트인. 기존 사용자 무변화. 사용자 제안 3개 + 자동. (제안의 1.Claude 2.GPT 순서 대신 코드의 우선순위 순서 GPT 먼저로 통일 — 표시 순서 GPT 왼쪽, Claude 오른쪽 고정) |
| E2 | 표시 이름: 전체 `GPT (Codex)` / `Claude (Claude Code)`, 짧은 이름 `GPT` / `Claude`(패널 제목·상태줄). CLI 안내 문구는 기존처럼 `Codex CLI` / `Claude Code CLI` | 사용자 친화 + 설치 안내는 실제 CLI 이름이 필요 |
| E3 | 병렬은 **service 계층(`ask_coach_multi`) 안의 스레드풀**(엔진당 1스레드)에서. 결과 콜백은 **호출 스레드(=CoachWorker 스레드)** 에서 발생 | Qt 비의존 코어 유지(테스트 용이). 워커는 여전히 1개(`CheckPage._coach_worker`) -> 기존 busy/취소/종료 대기 구조 재사용. 콜백을 as_completed 루프에서 호출해 스레드 안전 문제 없음 |
| E4 | 자료 수집(지문 fetch·샘플·코드)은 **1회만** 하고 두 엔진이 공유. 모든 엔진이 캐시 적중이면 수집도 생략 | 네트워크 2회/불일치 방지 |
| E5 | 부분 실패 허용: 한쪽 실패·미설치·타임아웃이어도 다른 쪽 답은 그대로 표시, 실패 쪽은 **해당 패널 안에 인라인 오류**(배너 아님). **두 쪽 모두 실패일 때만 오류 배너** | 사용자 요구. "오류 팝업 금지" 규칙과 일관 |
| E6 | `both` 에서 한 CLI 가 미설치면: 설치된 쪽만 실행 + 미설치 패널에 설치 안내(+[설정으로 이동]). 둘 다 없으면 `AiEngineMissing`. **고정 엔진(`codex`/`claude`) 미설치 시 폴백 없음은 그대로** | 동의받은 벤더 외 전송 금지 원칙 유지 |
| E7 | 캐시·힌트 단계는 **엔진별로 분리** (같은 문제 파일 1개 안에 엔진별 슬롯). 힌트 단계 카운트는 **공통**: 요청 단계 `L = (대상 엔진들의 받은 단계 수 중 최소) + 1` | 두 엔진이 같은 단계를 동시에 받음. 앞서 있는 엔진은 캐시에서 `hints[:L]` 만 표시(엔진 호출 없음)해 뒤처진 엔진을 따라잡게 하고, 실패했던 엔진을 다음 클릭에서 자연히 재요청 |
| E8 | 정답 풀이·코드 평가도 **두 엔진 모두** 받는다. 오답 누적 리셋·복습 예약(`mark_solution_viewed`)은 **첫 성공 시 1회** (재호출해도 멱등) | 사용자 요구. 복습 예약이 2회 갱신되지 않게 |
| E9 | 동의: 실행 대상 중 미동의 엔진을 **한 다이얼로그에 모아** 1회 (동의 항목은 QSettings 에 엔진별로 저장, 키 불변). 취소하면 둘 다 미실행 | 사용자 요구. 다이얼로그가 두 번 뜨지 않게 |
| E10 | 취소: `CoachWorker.cancel()` 이 등록된 모든 프로세스 트리를 kill, 아직 안 뜬 엔진은 `on_start` 시점에 kill. **이미 도착해 표시된 답은 유지** | 점진 표시와 정합. 취소가 이미 받은 답을 지우면 낭비 |
| E11 | 개별 [다시 받기]: 패널마다 버튼. 해당 엔진만 재요청(`engines=[key]`, `force_new`), 다른 패널은 그대로 | 실패한 쪽만 재시도 (사용량 절약) |
| E12 | UI: **좌우 `QSplitter`(기본), 결과 영역 폭 < 800px 이면 위아래로 자동 전환** (`setOrientation`). 하위 탭/별도 창 안 씀 | 비교가 이 기능의 핵심 -> 동시에 보여야 함. 880px 기본 창 폭이면 패널당 ~430px(본문·복잡도 표 충분, 코드 블록은 가로 스크롤). 720px 최소 창은 위아래로 |
| E13 | 사용량 고지: 설정 콤보 항목명/힌트문, 코치 바 문구·툴팁, 동의 다이얼로그에 "요청 1건마다 두 서비스의 구독 사용량이 각각 소모됩니다" | 사용자 요구. 막기 아닌 알리기 원칙 |
| E14 | 연결 테스트: `both` 면 설치된 두 엔진을 병렬 ping, 결과 배너에 엔진별 성공/실패 나열 | 사용자 요구 |

**사용자 확인이 필요한 항목**: 없음(전부 기본값 확정). 이견이 있을 만한 것 두 가지만 승인 시 참고 — (a) 기본값을 `both` 가 아닌 `auto` 로 둠(E1), (b) 좌우 배치(E12).

## 4. 엔진 계층 (`ai_engine.py`) 변경

| 항목 | 변경 |
|---|---|
| 상수 | `ENGINE_LABELS = {"codex": "GPT (Codex)", "claude": "Claude (Claude Code)"}` (전체 이름), 신규 `ENGINE_SHORT = {"codex": "GPT", "claude": "Claude"}`, `CLI_NAMES = {"codex": "Codex CLI", "claude": "Claude Code CLI"}`. 설치 안내/`--help` 오류 문구는 `CLI_NAMES` 사용, 실행 실패 제목("… 실행 실패") 등은 `label` |
| `EngineInfo` | `short_label` 프로퍼티 추가. 나머지 불변 |
| `AI_ENGINE_CHOICES` | (config) `("auto","codex","claude","both")` |
| `resolve(pref)` | 불변 (auto/codex/claude 단일). **`both` 를 넘기면 `ValueError`** (호출자가 `resolve_all` 사용해야 함을 조기에 드러냄) |
| `resolve_all(pref) -> EngineSelection` (신규) | `EngineSelection(engines: list[EngineInfo], missing: list[str])`. pref 가 단일이면 `engines=[resolve(pref)]`, `missing=[]`. `both` 면 `_which` 로 두 엔진 확인, 있는 것만 `engines`(codex, claude 순), 없는 것은 `missing`(키). `engines` 가 비면 `AiEngineMissing(hint=install_hint())` |
| `run()` | 시그니처 불변. 스레드 안전 점검: 요청별 `mkdtemp`, `_HELP_CACHE` 는 키가 다른 dict 쓰기(GIL 하 안전, 같은 키 동시 채움은 중복 `--help` 정도의 무해한 경합), `on_start`/`is_cancelled` 는 엔진별 클로저 |
| `detect()` | 불변 (이미 두 엔진 모두). 설정 페이지 상태줄만 label 갱신 |

`kill_tree` 불변. 두 엔진 동시 실행이라 `taskkill` 이 두 번 호출될 수 있음 -> 각각 독립.

## 5. 데이터 모델 · 캐시 마이그레이션 (`coach.py`)

### 5.1 `records.json`
**변경 없음** (문제 단위 기록, 엔진 무관). 오답 횟수·복습 예약은 요청당 1회만 갱신된다 (E8).

### 5.2 `answers/{num}.json` v2

```
{"version": 2, "num": 25730, "code_sha256": "...",
 "engines": {
   "codex":  {"hints": [{"level":1,"markdown":"...","at":"..."}, ...],   // 최대 3
              "review": {"markdown","at"} | null,
              "solution": {"markdown","at"} | null},
   "claude": { ...같은 구조... }}}
```

- 엔트리의 `engine` 필드는 v2 에서 쓰지 않는다 (슬롯 키가 엔진). 표시 이름은 `ENGINE_LABELS[key]`.
- 무효화 규칙은 M17 과 동일하되 **모든 슬롯에 적용**: 코드 해시가 다르면 모든 슬롯의 `hints`/`review` 폐기, `solution` 유지.
- 데이터클래스:
  ```
  EngineSlot: hints: list[dict], review: dict|None, solution: dict|None
  AnswerCache: num, code_sha256, engines: dict[str, EngineSlot]
     slot(key) -> EngineSlot   # 없으면 생성
  ```
  기존 `cache.hints/review/solution` 직접 접근 코드(service, 테스트)는 `cache.slot(key).*` 로 바꾼다 (builder 가 grep).
- **v1 -> v2 마이그레이션** (`load_answers` 안에서 메모리상 변환, 파일은 다음 `save_answers` 때 v2 로 다시 쓰임 — 로드 시 쓰기 금지):
  1. 엔트리의 `engine` 문자열을 소문자로 보고: `codex` 또는 `gpt` 포함 -> `codex`, `claude` 포함 -> `claude`, 그 외/없음 -> 그 엔트리 **버림**(DEBUG 로그).
  2. `review`/`solution` 은 매핑된 슬롯에 그대로 넣는다.
  3. `hints` 는 첫 엔트리의 엔진 슬롯에 넣고, 다른 엔진으로 매핑되는 엔트리는 버린다 (엔진을 바꿔 가며 받은 혼합 힌트는 단계 연속성이 깨지므로). 레벨이 1..k 연속이 아니면 연속 구간까지만 유지.
  4. 결과가 비면 빈 캐시.
- 다운그레이드(구버전 앱이 v2 파일을 읽음): 구버전은 `hints` 키가 없어 빈 캐시로 취급 -> 무해. 별도 조치 없음.
- 저장 경합: 두 엔진 결과가 거의 동시에 도착하므로 `service` 에 모듈 락 `_CACHE_LOCK` 을 두고 **락 안에서 `load_answers` -> 해당 슬롯만 수정 -> `save_answers`** (read-modify-write 를 매 엔진 결과마다). 락 밖에서 들고 있던 오래된 `AnswerCache` 객체를 저장하지 않는다.
- `MAX_ANSWER_FILES=50`, `MAX_HINTS=3` 불변. 파일 크기는 최대 약 2배(수십 KB) — 무시.
- `clear()` 불변.

### 5.3 설정
`SWEA_AI_ENGINE=both` 허용. 잘못된 값은 기존처럼 `auto` + WARNING. `Settings` 필드/기본값 불변 (`ai_engine: str = "auto"`). `config.AI_ENGINE_CHOICES` 에 `both` 추가, 모듈 docstring 갱신.

## 6. 서비스 계층 (`service.py`) API

```
@dataclass CoachFailure:  code: str ("missing"|"failed"|"timeout"), title: str, hint: str, stderr: str = "", argv: list[str] = []
@dataclass EngineOutcome: engine: str (key), label: str,
                          answer: CoachAnswer | None, failure: CoachFailure | None,
                          cancelled: bool = False
@dataclass CoachResult:   kind: str, outcomes: list[EngineOutcome]   # codex, claude 순 (실행 대상 + 미설치 슬롯)
                          hint_done: int = 0        # 요청 후 대상 엔진들의 받은 힌트 단계 수 중 최소 (코치 바용)
                          review_due: date | None   # solution 성공 시 복습 예정일 (1개)
                          properties: cancelled (요청이 취소됨), succeeded (answer 있는 outcome 목록), all_failed
```

- `CoachAnswer`: 필드 유지 + `engine_key: str = ""` 추가. `engine` 은 label(신규 이름). `review_due` 는 결과 수준(`CoachResult.review_due`)에도 채운다.
- `resolve_engines(settings) -> ai_engine.EngineSelection` (신규, `resolve_all` 래퍼). 기존 `resolve_engine(settings)` 는 단일 모드에서만 유효(`both` 면 ValueError) — 사용처를 `resolve_engines` 로 이동하고 `resolve_engine` 은 남기되 docstring 에 명시.
- **`ask_coach_multi(settings, kind, topic="", num=0, *, submit_summary="", run_error="", execution_time=None, progress=None, on_start=None, is_cancelled=None, on_engine_done=None, force_new=False, engines: Sequence[str] | None = None) -> CoachResult`** (신규)
  - `on_start(engine_key, proc)`; `on_engine_done(outcome)` 는 outcome 이 확정될 때마다 **호출 스레드**에서 호출 (캐시 적중 즉시 반환분 포함, 미설치 슬롯은 시작 직후 즉시).
  - `engines` 로 대상 부분집합 지정(개별 [다시 받기]). None 이면 설정(`resolve_engines`) 전체.
  - 호출 전 사용자 동의 필수 (docstring 명시, M17 과 동일).
  - 흐름:
    1. `resolve_engines` (엔진 없으면 `AiEngineMissing` 그대로 raise — 자료 수집 전). `engines` 지정 시 교집합.
    2. `ping`: 자료 없이 엔진별 병렬 실행, 결과는 `CoachAnswer("ping", …)`.
    3. 그 외: 문제 폴더/코드 읽기(오류는 기존처럼 `InvalidInput` 등 raise = 전체 실패), 엔진별 캐시 검사(`slot(key)`): review/solution 적중 -> 즉시 outcome(from_cache). hint: 엔진별 `done`, 공통 `L = min(done)+1` (E7), `force_new` 면 대상 엔진 슬롯의 마지막 힌트를 pop 한 뒤 계산. `done>=L` 인 엔진은 `hints[:L]` 합본을 캐시로 반환. 모든 힌트가 3 이상이면 전부 캐시(`level=3`).
    4. 엔진 호출이 필요한 엔진이 하나라도 있으면 자료 수집 1회 (`_gather_statement`, 샘플, 코드) -> 프롬프트는 **엔진별로 `previous_hints` 만 다르게** 생성.
    5. `ThreadPoolExecutor(max_workers=호출 엔진 수)`. 각 작업 = 기존 단일 실행 본문(`_run_one`: `ai_engine.run` -> `clean_titles` -> hint 필터 -> 락 안 슬롯 저장 -> `CoachAnswer`). 예외 매핑: `AiError` -> `CoachFailure(code=e.code, title=str(e), hint=e.hint, stderr, argv)`, 그 외 `Exception` -> `code="failed"`, 제목 "내부 오류: …"(스택은 로그). 스레드 예외가 다른 엔진을 죽이지 않는다.
    6. 메인 루프 `as_completed` 로 outcome 을 모아 `on_engine_done` 호출. `is_cancelled()` 가 True 이면 이후 outcome 은 `cancelled=True`.
    7. `solution` 이고 성공 outcome 이 하나라도 있으면 `coach.mark_solution_viewed` **1회** -> `CoachResult.review_due`, 모든 성공 answer 의 `review_due` 에도 동일 값.
    8. 반환 직전 `hint_done` 계산 (락 안 재로드).
  - 진행 메시지: 단일 `"{짧은이름} 에게 묻는 중"`, 둘이면 `"GPT · Claude 에게 묻는 중"`.
- **`ask_coach(...)` (기존)**: 시그니처·동작 유지, 내부를 `ask_coach_multi(engines=[해석된 단일 엔진])` 로 위임하고 단일 outcome 을 풀어 반환(실패는 원래 `AiError` 재발생). 설정이 `both` 이면 `codex` 우선 첫 설치 엔진 1개만 (호환 래퍼일 뿐, GUI 는 쓰지 않음). 기존 테스트가 이 경로를 쓰므로 회귀 방지용.
- `hint_level(settings, topic, num) -> int`: 대상 엔진들(설정 해석; 미설치는 제외, 하나도 없으면 0)의 받은 단계 수 중 **최소**. 코치 바의 "다음 힌트 (n/3)" 기준.
- `detect_engines`: 불변. 신규 없음.
- 로깅: 엔진 키만 (`ai_engine` 로거). 프롬프트·응답 미로깅 원칙 유지.

## 7. 워커 (`gui/workers.py`)

`CoachWorker` 개편:
- `_procs: dict[str, Popen]`, `_cancel_requested`. `cancel()` -> 플래그 + 모든 프로세스 `kill_tree`. `_on_start(key, proc)` -> 등록, 이미 취소면 즉시 kill. (락 불필요: 딕셔너리 단순 대입/순회, 순회는 `list(...)` 복사.)
- 신호: `engine_done = Signal(object)` (EngineOutcome, 점진 표시용), `finished_ok = Signal(object)` (CoachResult), `ai_failed`(code,title,hint: 요청 전체가 시작 못 한 경우 — 엔진 전혀 없음 등), `failed` 불변.
- `work()` -> `service.ask_coach_multi(..., on_start=self._on_start, on_engine_done=self.engine_done.emit, is_cancelled=..., **kwargs)`. `engine_done.emit` 은 워커 스레드에서 호출되므로 queued 연결로 UI 스레드에 전달됨.
- 종료 대기(`wait_workers`)는 기존과 같이 `cancel()` 먼저.

## 8. GUI 흐름 · 상태

### 8.1 요청 흐름 (`check_page.request_coach(kind, force_new=False, only: str | None = None)`)

1. `sel = service.resolve_engines(settings)`; `AiEngineMissing` -> 기존 warning 배너(설치 안내 + [설정으로 이동]). `only` 가 있으면 `sel.engines` 를 그 엔진으로 제한.
2. 동의: `need = [e for e in sel.engines if not has_consent(qs, e.name)]`. 비어 있지 않으면 **다이얼로그 1회**: `ask_consent(self, [e.label for e in need])` (기존 str 인자도 허용하도록 `str | list[str]`). 본문의 첫 줄만 "GPT (Codex), Claude (Claude Code) 로 다음을 보냅니다" 식으로 바뀌고, `both` 대상이 2개일 때 한 줄 추가: "요청 1건마다 두 서비스의 구독 사용량이 각각 소모되며 답이 2개 표시됩니다". 취소하면 프로세스 0개, 동의 시 각 엔진 `set_consent`.
3. `CoachWorker` 시작. `coach_tab.begin(sel.engines, sel.missing, only)`: 패널 구성/초기화 — 전체 요청이면 대상 패널 전부 로딩, `only` 면 그 패널만 로딩(다른 패널은 유지). `stack.setCurrentIndex(1)`, 탭 추가·선택은 기존과 동일.
4. `engine_done(outcome)` -> `coach_tab.apply_outcome(outcome, num)` (먼저 끝난 쪽부터 표시). 코치 바 힌트 진행/복습 갱신은 최종 결과에서 한 번.
5. `finished_ok(result)`:
   - `result.cancelled`: 이미 표시된 답이 하나라도 있으면 탭 유지(로딩 중이던 패널만 "취소됨"), 없으면 탭 제거. 둘 다 info 배너 "요청을 취소했습니다".
   - `all_failed`: **단일 대상**이면 기존 동작(탭 제거 + `_show_ai_error` 배너). **둘 대상**이면 탭 유지(패널마다 인라인 오류) + error 배너 "두 엔진 모두 응답하지 못했습니다" + [다시 시도].
   - 부분 성공: 배너 없음. 실패 패널은 인라인 오류 + [다시 시도]. 상태바 `flash`: "AI 코치 응답 — GPT (Codex) 15.2초 · Claude (Claude Code) 실패".
   - 코치 바: `set_hint_done(result.hint_done)`, solution 이면 `coach_changed.emit()` + `_refresh_coach_bar()`.
6. 패널의 [다시 받기]/[다시 시도] -> `request_coach(self._coach_kind, force_new=True, only=key)`. 실패했던 요청(force_new 아님)의 재시도도 `only=key`.
7. `_last_coach_request` 를 `(kind, force_new, only)` 로 확장 (배너 [다시 시도] 는 마지막 요청 그대로 재실행 — 부분 요청이었으면 그 부분만).
8. 요청 중에는 코치 바 버튼과 모든 패널의 [다시 받기] 비활성 (한 번에 요청 1건 원칙 유지 — 프로세스는 최대 2개).
9. 창 닫기: 기존 `wait_workers` 가 `cancel()` 후 대기 -> 두 프로세스 모두 종료.

### 8.2 `CoachTab` 구조 (`gui/coach_widgets.py`)

```
CoachTab
 ├─ 상단 줄: 종류 제목 + [취소] (로딩 패널이 하나라도 있는 동안만)
 ├─ QSplitter (가로; 결과 영역 폭 < 800 이면 세로로 전환. resizeEvent 에서 setOrientation)
 │    ├─ EnginePane "codex"
 │    └─ EnginePane "claude"       # 실행 대상/미설치 슬롯이 아닌 엔진은 hide → 단일 모드는 패널 1개가 전폭
 └─ 공통 footer: "AI 응답은 틀릴 수 있습니다. 정답 풀이는 {num}.py 에 저장되지 않습니다" (+ 복습 예정 info)
EnginePane (QFrame[class=card])
 ├─ 헤더 줄: 엔진 label(굵게) · 소요 시간 · "캐시" 배지 · (오른쪽) [다시 받기]
 ├─ 본문: 상태별 스택 — 로딩 / AnswerBrowser / 오류 / 미설치 / 취소됨
 └─ 패널 footer: notes(muted) · solution 이면 [코드 복사]
```

패널 상태:

| 상태 | 표시 |
|---|---|
| loading | "{label} 에게 묻는 중… 0:12 · 최대 5분" (탭의 1초 QTimer 하나가 로딩 패널 전부 갱신). [다시 받기] 비활성 |
| done | `AnswerBrowser`(M17 링크/리소스 차단 그대로), 헤더 소요 시간·캐시 배지, [다시 받기] 활성 |
| error | 본문에 오류 제목(error 색 + 텍스트 아이콘 없이 글자로 "오류"), hint, stderr 끝부분(선택·복사 가능), [다시 시도] |
| missing | "Claude (Claude Code) 를 찾지 못했습니다" + 설치 안내 + [설정으로 이동] (시그널 `settings_requested`) |
| cancelled | "취소했습니다" (muted) |

- 색만으로 상태를 구분하지 않는다 (텍스트 병기, M17 9.3 규칙). 새 색/간격 토큰 없음. 셀렉터: `EnginePane` objectName `CoachPane_{key}`, 헤더 `CoachPaneTitle`, 본문 `CoachPaneBody`, 재요청 버튼 `CoachPaneRetry` (designer 가 design-spec 에 계약 추가).
- 접근성: 각 브라우저 `setAccessibleName(f"{label} 답변")`, 재요청 버튼 `setAccessibleName(f"{short} 다시 받기")`.
- 단일 모드 외형: 패널 1개(카드) — 기존 M17 화면과 시각적으로 거의 동일(헤더 줄에 엔진명 포함). 기존 `CoachTab` 의 `header/browser/cache_badge/retry_btn` 은 패널로 이동, 기존 테스트가 이 이름을 참조하면 갱신.
- `_coach_code` (정답 코드 복사)는 `dict[str, str]` (엔진별). [코드 복사] 는 해당 패널 코드.
- 스크롤: 각 브라우저가 독립 스크롤. 세로 전환 시 각 패널 최소 높이 140px 를 보장하고 바깥 스크롤을 허용 (720x480 대응, AC 참조).

### 8.3 코치 바 (`CoachBar`)
- `set_dual(labels: list[str] | None)`: 대상이 2개일 때 안내 문장 끝에 muted 로 "· GPT · Claude 동시 요청 (사용량 2배)" 추가, 세 버튼 툴팁에 같은 고지 추가. 대상 엔진 수는 `_refresh_coach_bar` 에서 `resolve_engines` 결과(경로 존재 확인만, UI 스레드 허용)로 계산; 해석 실패 시 dual 표시 없음.
- 힌트 버튼 라벨 "다음 힌트 (n/3)" 의 n 은 `service.hint_level` (대상 엔진 최소). 3/3 이면 비활성 + 툴팁.

### 8.4 설정 페이지 (`settings_page.py`)
- 엔진 콤보 항목(데이터 값): `자동 (Codex 우선)`=auto, `GPT (Codex)`=codex, `Claude (Claude Code)`=claude, `GPT & Claude (둘 다)`=both. 저장 즉시 `.env`.
- `both` 선택 시 콤보 아래 muted 힌트: "요청 1건마다 GPT 와 Claude 구독 사용량이 각각 소모되고, 답이 2개 표시됩니다." (다른 값이면 숨김)
- 감지 상태줄은 label 갱신. `both` 이고 한쪽만 감지되면 "둘 다 모드는 설치된 쪽만 실행합니다" 한 줄 보조 문구.
- [연결 테스트]: `resolve_engines` -> 대상 미동의 엔진 모아 동의 1회(ping 문구) -> `CoachWorker(kind="ping")`. 결과 배너: 전부 성공 "GPT (Codex) 연결됨 (2.1초) · Claude (Claude Code) 연결됨 (3.4초)"(info/success 배너 종류는 기존 규칙), 일부 실패 warning(성공 목록 + 실패 엔진의 제목·실행 명령줄·stderr 끝 600자), 전부 실패 error. 단일 모드 출력은 기존과 동일 형식(label 만 신규).
- `wait_workers` 변경 없음(핑 워커 cancel 이 두 프로세스를 죽임).

## 9. 변경 파일

| 파일 | 변경 |
|---|---|
| `swea_fetcher/config.py` | `AI_ENGINE_CHOICES` 에 `both`, docstring |
| `swea_fetcher/ai_engine.py` | 라벨 상수, `short_label`, `EngineSelection`/`resolve_all`, `resolve("both")` ValueError, 안내 문구의 `CLI_NAMES` |
| `swea_fetcher/coach.py` | `EngineSlot`, `AnswerCache.engines`, v2 저장·v1 마이그레이션 로드 |
| `swea_fetcher/service.py` | `CoachFailure/EngineOutcome/CoachResult`, `resolve_engines`, `ask_coach_multi`, `ask_coach` 위임, `hint_level`, 캐시 락 |
| `swea_fetcher/gui/workers.py` | `CoachWorker` 다중 프로세스 취소, `engine_done` 신호 |
| `swea_fetcher/gui/coach_widgets.py` | `EnginePane`, `CoachTab` 개편(QSplitter), `CoachBar.set_dual`, `ask_consent(list)` |
| `swea_fetcher/gui/pages/check_page.py` | 8.1 흐름, `_last_coach_request` 확장, 코드 복사 dict |
| `swea_fetcher/gui/pages/settings_page.py` | 콤보 4항목, 사용량 힌트, 다중 연결 테스트 결과 |
| `design/design-spec.md` | §6.6 에 듀얼 패널(분할·상태표·셀렉터), 설정 콤보 항목 (designer) |
| `README.md`, `CHANGELOG.md`, `docs/troubleshooting.md`, `swea_fetcher/__init__.py` | 둘 다 모드 안내(사용량 2배, 전송 대상 2곳), 버전 |
| `tests/test_ai_engine.py`, `test_coach.py`, `test_service_coach.py`, `test_config.py`, `test_gui_coach.py` | 수정/추가 (10절) |
| **변경 없음** | `ai_prompts.py`(엔진별 `previous_hints` 로 충분), `cli.py`, `mcp_*.py`, `submit.py`, `checker.py`, `storage.py`, `auth.py`, `gitops.py`, 아이콘 |

## 10. 수용 기준

- AC1 `both` 에서 버튼 클릭 전에는 어떤 AI 프로세스도 뜨지 않는다 (M17 AC1 유지).
- AC2 `both` 로 요청하면 두 엔진 프로세스가 **동시에** 시작되고(첫 프로세스 종료 전에 두 번째가 시작), 먼저 끝난 답부터 각 패널에 표시된다.
- AC3 한쪽이 실패/타임아웃/미설치여도 다른 쪽 답이 표시되고 실패 쪽 패널에 인라인 오류가 뜬다. 두 쪽 모두 실패일 때만 error 배너가 뜬다.
- AC4 [취소] 시 두 프로세스 트리가 모두 종료되고(아직 안 뜬 것은 뜨는 즉시 종료), 이미 표시된 답은 남는다. 창 닫기도 동일.
- AC5 캐시가 엔진별로 분리된다: GPT 힌트 1단계만 캐시된 상태에서 `both` 요청 시 GPT 는 캐시(호출 없음), Claude 만 호출한다. 힌트 단계 `L` 은 공통(E7)이며 한쪽 실패 후 다음 클릭에서 뒤처진 엔진만 호출된다.
- AC6 v1 캐시 파일이 크래시 없이 로드되고, 엔진 라벨이 매핑되는 항목은 해당 슬롯으로 이관되며 매핑 불가 항목은 버려진다. 로드만으로는 파일이 바뀌지 않는다.
- AC7 정답 풀이를 두 엔진이 모두 성공해도 복습 예약(`review_due`)은 1회만 갱신되고 `{num}.py` 는 바이트 불변이다. 한쪽만 성공해도 예약된다.
- AC8 동의: `both` 에서 미동의 엔진이 여러 개여도 다이얼로그는 1번, 취소하면 프로세스 0개, 동의 후 재묻지 않음. 이미 동의한 엔진은 목록에서 빠진다.
- AC9 개별 [다시 받기] 는 해당 엔진만 재호출하고 다른 패널은 유지된다.
- AC10 `both` 연결 테스트가 설치된 두 엔진을 모두 테스트하고 엔진별 결과를 표시한다. 단일 모드 결과 형식은 기존과 같다.
- AC11 고정 엔진(`codex`/`claude`) 미설치 시 폴백하지 않는 동작 유지. `both` 에서 한쪽 미설치면 그 패널에 설치 안내, 다른 쪽은 정상 실행. 둘 다 없으면 warning 배너.
- AC12 사용량 2배 고지가 설정 힌트, 코치 바, 동의 다이얼로그에 나온다.
- AC13 880px 창에서 좌우 분할, 결과 영역이 800px 미만이면 위아래 분할이 되고 720x480 에서 잘림 없이 스크롤로 접근 가능하다.
- AC14 프롬프트/로그/저장 파일에 SWEA ID·PW·쿠키·루트 경로가 없다 (M17 AC9 유지, 두 엔진 프롬프트 모두 검증).
- AC15 단일 모드(자동/GPT/Claude)의 기존 동작·기존 테스트가 (라벨 문자열 갱신 외) 통과한다. CLI/MCP 출력·종료코드 불변.

## 11. 테스트 (모킹 전용 — 실제 AI 호출·네트워크 금지, M17 autouse Popen 차단 픽스처 유지)

- `test_ai_engine.py`: `resolve_all` (단일 위임 / both 둘 설치 / 한쪽만 -> `missing` / 둘 다 없음 -> `AiEngineMissing`), `resolve("both")` ValueError, 고정 엔진 폴백 없음 유지, 라벨·`short_label`, 설치 안내에 `Codex CLI` 이름.
- `test_coach.py`: v2 저장/로드 왕복, 엔진별 슬롯 독립, 코드 해시 변경 시 모든 슬롯 hints/review 폐기·solution 유지, **v1 마이그레이션** (label "Codex"/"Claude Code" 매핑, 혼합 hints 처리, 미매핑 버림, 연속성 깨진 레벨 절단, 로드 시 파일 미변경, 손상 파일), 저장 후 v2.
- `test_service_coach.py` (가짜 `ai_engine.run` — 엔진별로 다른 응답/지연/예외를 주입):
  - 두 엔진 모두 호출·결과 2개·`on_engine_done` 순서(먼저 끝난 쪽 먼저: `threading.Event` 로 지연 제어), 호출 스레드에서 콜백.
  - 부분 실패(한쪽 `AiRunFailed`/`AiTimeout`) -> 다른 쪽 answer 유지 + failure 채움, 전체 예외 없음. 둘 다 실패 -> `all_failed`.
  - `both` 한쪽 미설치 -> 그쪽 failure(code=missing), 다른 쪽만 `run` 호출됨. 둘 다 없음 -> `AiEngineMissing`. 고정 엔진 미설치 -> raise.
  - 자료 수집 1회 (지문 fetch 호출 카운트 1, 모두 캐시 적중이면 0).
  - 힌트 공통 단계: (A=1,B=0) -> L=1 (A 캐시, B 호출); (A=2,B=1) -> L=2; 둘 다 3 -> 호출 0; B 실패 후 재요청 -> B 만 호출; 엔진별 `previous_hints` 가 자기 힌트만 포함; `force_new` 가 대상 엔진 마지막 힌트만 pop.
  - review/solution 캐시 엔진별 적중, 한쪽만 적중 시 다른 쪽만 호출.
  - solution: 두 성공 시 `mark_solution_viewed` 호출 1회, `review_due` 동일, `{num}.py` 바이트 불변; 한쪽만 성공해도 호출.
  - 캐시 동시 저장 경합: 두 엔진이 동시에 저장해도 두 슬롯 모두 보존 (`Barrier` 로 동시성 유도).
  - 취소: `is_cancelled` True 시 outcome.cancelled, 이미 끝난 outcome 유지. `on_start(key, proc)` 콜백에 엔진 키 전달.
  - `ask_coach` 래퍼 회귀(단일 모드 기존 케이스), `hint_level` 최소값.
  - ping both: 두 엔진 병렬, 한쪽 실패 시 다른 쪽 성공 결과.
  - 프롬프트에 ID/PW/root 경로 없음(두 프롬프트 모두).
- `test_config.py`: `both` 허용, 잘못된 값 -> auto + WARNING.
- `test_gui_coach.py` (offscreen, `service.ask_coach_multi` 대체):
  - 동의 게이트: 미동의 2개 -> 다이얼로그 1회(대체 함수 호출 1회), 취소 시 워커 미시작, 일부 동의 상태에서는 남은 엔진만 목록.
  - `CoachTab`: 패널 2개 표시/단일 모드 1개, 점진 표시(한 outcome 적용 후 다른 패널은 로딩 유지), 오류 인라인, missing 패널의 설정 시그널, 재시도 버튼이 `only=key` 로 `request_coach`, 취소 후 표시된 답 유지, 로딩 중 재요청 버튼 비활성.
  - `QSplitter` 방향: 폭 900 -> Horizontal, 700 -> Vertical.
  - 전체 실패(둘) -> 배너 + 탭 유지, 단일 전체 실패 -> 탭 제거(기존).
  - 코치 바 `set_dual` 문구/툴팁, 힌트 카운트 = 최소값.
  - 설정: 콤보 4항목·`.env` 저장 `both`, 연결 테스트 결과 배너(전부/일부/전부 실패), 사용량 힌트 표시 토글.
  - `AnswerBrowser` 링크/리소스 차단은 두 패널 모두 (`loadResource` None).
- 워커 테스트: `CoachWorker.cancel()` 이 등록된 가짜 proc 전부에 `kill_tree` 호출, 취소 후 뜨는 proc 즉시 kill.
- 회귀: 전체 `pytest` + `swea-fetch-gui` selftest.

## 12. 수동 검증 (사용자 PC — Codex, Claude Code 둘 다 설치·로그인된 상태)

1. 설정에서 엔진 "GPT & Claude (둘 다)" 선택 -> 사용량 2배 힌트 문구 확인. [다시 감지] 로 두 엔진 감지.
2. [연결 테스트] -> 동의 다이얼로그 1번(두 엔진 명시) -> 두 엔진 결과가 한 배너에. 소요 시간이 합이 아니라 병렬(느린 쪽 수준)인지 확인.
3. 풀이 Pass 제출 -> [코드 평가 받기] -> AI 코치 탭에 좌우 두 패널, 먼저 끝난 쪽부터 채워짐. 각 패널에 엔진명·시간. 다시 누르면 양쪽 모두 "캐시".
4. 오답 제출 -> [힌트] 3회: 양쪽이 같은 단계로 진행, 3/3 에서 비활성. 한쪽만 [다시 받기] -> 그쪽만 갱신.
5. 오답 3회 -> 정답 풀이: 두 답 표시, 복습 예정일 1개, `{num}.py` 불변, 패널별 [코드 복사].
6. 창을 720 폭 가깝게 줄여 위아래 전환 확인, 다시 넓히면 좌우.
7. 한쪽 실패 유도(예: Claude CLI 를 PATH 에서 잠시 제거하고 앱 재시작, 또는 한쪽 로그아웃): 다른 쪽 답은 나오고 실패 패널에 안내/[다시 시도].
8. 요청 중 [취소] -> 작업 관리자에서 codex/claude/node 프로세스가 남지 않음. 이미 표시된 답은 유지. 요청 중 창 닫기도 동일.
9. 동의 초기화 후 `both` 요청 -> 다이얼로그 1번에 두 엔진. 취소하면 프로세스 미기동.
10. 엔진을 auto/GPT/Claude 로 되돌려 단일 패널 동작과 기존 캐시(v1 파일이 있던 문제)가 정상 표시되는지 확인. 첫 저장 후 해당 파일이 v2 가 됨.
11. 엔진을 `codex` 고정 + Codex 미설치 -> 폴백 없이 warning (기존 동작).

## 13. 역할 분담

| 역할 키워드 | 담당 범위 | 산출물 경로 | 인터페이스 |
|---|---|---|---|
| `builder-core` | 4~6절: config/ai_engine/coach/service, 캐시 마이그레이션, 코어 테스트, 라벨 문자열 회귀 정리 | `swea_fetcher/{config,ai_engine,coach,service}.py`, `tests/test_{ai_engine,coach,service_coach,config}.py` | GUI 에는 `resolve_engines`, `ask_coach_multi`, `CoachResult/EngineOutcome/CoachFailure`, `hint_level` 만 노출. Qt import 금지. 시그니처(6절)를 먼저 확정해 builder-gui 에 전달 |
| `designer` | design-spec §6.6 듀얼 패널(분할/전환, 패널 상태표, 셀렉터 계약), 설정 콤보·힌트문, 스크린샷 검토 | `design/design-spec.md`, `docs/gui-screenshots/` | 새 토큰 없이 기존 카드/muted/error 스타일 사용. 이견은 §15 "스펙 대체안" |
| `builder-gui` | 7~8절: workers, coach_widgets, check_page, settings_page, GUI 테스트 | `swea_fetcher/gui/**`, `tests/test_gui_coach.py` | 서비스 API 를 워커에서만 호출 (`resolve_engines` 는 경로 확인뿐이라 UI 스레드 허용). 동의는 QSettings |
| `tester` | 모킹 기반 AC1~15 검증, 12절 중 CLI 불필요 항목 offscreen 재현 | `docs/tester-feedback-m18.md` | 실제 AI 호출 금지 |
| `docs` (builder-core 겸임) | README/CHANGELOG/troubleshooting/버전 | 9절 표 | 사용량 2배·전송 대상 2곳 명시 |
| 사용자 | 12절 실측 (두 CLI 필요) | - | 실패 시 패널 오류의 명령줄·stderr 전달 |

병렬: builder-core 와 designer 동시. builder-gui 는 6절 시그니처 확정 후 (스텁 합의로 조기 시작 가능).

## 14. 마일스톤

| M | 내용 | 완료 기준 |
|---|---|---|
| M18-1 | 코어: 라벨·`resolve_all`, 캐시 v2 + 마이그레이션, `ask_coach_multi`/래퍼, 워커 | 코어 테스트 + 기존 전체 pytest 통과 (AC3,5~7,11,14,15 코어) |
| M18-2 | 디자인 (M18-1 과 병렬) | design-spec 리뷰 |
| M18-3 | GUI: CoachTab/EnginePane, 동의, 요청 흐름, 코치 바 | AC1,2,4,8,9,12,13 (offscreen) |
| M18-4 | 설정(콤보·힌트·다중 연결 테스트), 문서·버전 | AC10, 문서 검토 |
| M18-5 | tester 모킹 검증 -> 사용자 12절 실측 | 사용자 승인 |

규모: 코어 1일, GUI 1~1.5일, 디자인·문서 0.5일.

## 15. 우선순위

- **P0**: `both` 설정값·콤보, 병렬 실행·점진 표시, 부분 실패 처리, 엔진별 캐시 + v1 마이그레이션, 공통 힌트 단계, 다중 프로세스 취소, 동의 1회 통합, 사용량 고지, 연결 테스트 다중, 코어/GUI 테스트.
- **P1**: 패널 간 스크롤 동기화 없음(수용) 대신 "한쪽 접기" 토글(패널 헤더 접기 버튼), 하나의 답만 클립보드로 복사(Markdown 전체 복사), 응답 시간 비교 표시 강화.
- **P2**: 두 답 자동 비교/요약, 3번째 엔진, 엔진별 모델 지정, 코치 바에서 요청 단위로 엔진 선택.

확장성: 응답 슬롯이 `engines: dict[key, EngineSlot]` 이고 UI 패널이 `dict[key, EnginePane]` 이라 세 번째 엔진은 `ENGINE_NAMES`/명령 빌더/패널 1개 추가로 확장된다.

## 16. 리스크와 대응

| # | 리스크 | 대응 |
|---|---|---|
| R1 | 구독 사용량 2배 소모 | 옵트인(기본 auto), 설정·코치 바·동의에서 고지 (E13) |
| R2 | 두 프로세스 동시 실행으로 PC 부하/한 CLI 의 동시 세션 제한 | 실패는 해당 패널에만 반영되고 다른 쪽은 유지, [다시 시도] 개별 제공. 수동 검증 2·3 에서 실측, 문제 시 순차 실행 옵션(P2) 검토 |
| R3 | 캐시 read-modify-write 경합 (두 엔진 동시 저장) | 서비스 락 안에서 재로드 후 슬롯 단위 갱신, 경합 테스트 |
| R4 | v1 캐시 이관 오류로 엉뚱한 슬롯에 들어감 | 라벨 매핑 실패 시 버림, 로드 시 쓰기 금지, 마이그레이션 테스트 |
| R5 | 힌트 단계 불일치로 UX 혼란 | 공통 단계 `min+1` 규칙 + 앞선 엔진은 `hints[:L]` 만 표시 (E7), 테스트로 고정 |
| R6 | 취소 시 두 번째 프로세스가 뒤늦게 기동 | `on_start` 등록 즉시 취소 플래그 확인 (M17 방식 확장), 워커 테스트 |
| R7 | 좁은 폭에서 두 답이 읽기 어려움 | 800px 미만 위아래 전환, 코드 블록 가로 스크롤, 패널 최소 높이 |
| R8 | 전송 대상이 2곳으로 늘어남(저작물 지문 포함) | 동의 다이얼로그에 두 엔진 명시, 벤더별 동의 유지, 미동의 벤더로는 전송 안 됨 |
| R9 | 라벨 변경이 기존 테스트/문구와 충돌 | builder 가 label 문자열 grep 후 일괄 정리, AC15 |
| R10 | 스레드 예외/콜백이 UI 스레드를 직접 건드림 | 콜백은 호출(워커) 스레드에서만, UI 갱신은 Qt 신호(queued)로만 (E3) |

## 17. 검토 노트 (자기검토)

- 누락 점검: 보안(동의·전송 항목·미동의 벤더 전송 금지)·에러 처리(부분 실패)·로깅(엔진 키만)·테스트·마이그레이션·배포 문서 모두 포함. 복습/기록의 중복 갱신 방지(E8) 반영.
- 과설계 점검: 스레드풀은 서비스 내부 1곳에 한정하고 워커는 1개 유지. UI 는 QSplitter 방향 전환 한 줄로 반응형 처리하고 하위 탭·비교 요약·순차 실행 옵션은 제외. 패널 단위 접기/복사는 P1.
- 남은 우려: (1) 두 CLI 동시 실행 시 실제 부하·동시 세션 제한은 실측 전까지 미확인(R2). (2) 좌우 배치의 가독성은 designer 스크린샷 검토에서 확정 — 부족하면 세로 배치를 기본으로 뒤집는 것이 한 줄 변경. (3) v1 마이그레이션이 혼합 힌트를 버리므로 엔진을 바꿔 가며 힌트를 받던 사용자는 1회 재요청이 필요할 수 있음(수용). (4) `CoachTab` 이 기존 GUI 테스트와 속성명이 달라지므로 builder 가 참조를 함께 갱신해야 함.
