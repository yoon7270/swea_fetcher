# tester → planner 전달 (M9: 제출 경로 회귀 테스트 고정, 2026-09-17)

대상: `docs/project-plan.md` 12절 M9 마감. 지시서 `m9-work-order.md` 의 5개 항목 전부 작성. 검증 대상 `9886f99` (`v0.6.2`). 소스 코드 변경 없음 (테스트·픽스처·`tests/conftest.py` 만).

## 1. 결과

```
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q
```

**통과 630 / 실패 0 / 스킵 0** (약 8s, 3회 연속 동일). 490 → **+140**. **실서버(`compile.do`/`submit.do`) 호출 0** — 아래 §3-1 의 차단 픽스처로 보장.

| 지시서 항목 | 파일 | 추가 | 고정한 것 |
|---|---|---|---|
| 1 `submit.py` | `tests/test_submit.py` (신규) | 76 | 소스 변환 12케이스(뼈대 원형·변형·주석/빈 줄/행 번호 유지·`sys.` 잔존 거부·`import sys, os` 현 동작·100KB·빈 소스), `get_context` hidden 값/폴백/오류 페이지, **요청 파라미터 6개 + `X-Requested-With`/`Referer`/timeout 90/세션 쿠키 동일 세션**, compile 실패 코드 7종 매핑 + `<br>`/`&nbsp;` 정리, **compile 실패 시 `submit.do` 미호출**, `submitFailed` ES/TU/AP, 판정 7종(Pass/오답 개수/시간 초과/런타임 에러/점수만/gradingResult/빈 응답) + **Pass 는 4조건 모두 필요**, 302→`SessionExpired`, 픽스처 위생(계정·쿠키 문자열 0) |
| 2 `find_category` | `tests/test_lookup.py` | +9 | BOX(색인)→HTTP 0, `box_scanned`→CODE HTTP 0, 옛 색인(box_id 없음) 재스캔→BOX+색인 채움, 공개 전용→`box_scanned=True` 기록 후 재스캔 없음, **공개·상자 양쪽이면 BOX 우선**, 색인 필드 왕복, 재스캔 중 재로그인 1회, `fetch --refresh-index` 경로로 box_id 채워짐 |
| 3 `submit_problem` | `tests/test_service.py` | +17 | get_context→compile→submit 순서·같은 파라미터, Pass+push→`gitops.commit_and_push` 1회(메시지 인자/템플릿), Pass+push=False→미호출, 오답/시간초과/런타임에러→미호출·예외 없음, compile 실패→submit 미호출·`last_submit.json` 미생성, `sys.` 잔존/풀이 없음→HTTP 0, ES→`SubmitError`, 세션 만료 재로그인 1회/2회 실패→`LoginFailed`, **`last_submit.json` 에 category·응답 포함 + 쿠키·비밀번호·ID 없음**, 푸시 실패→`GitError`(진단 파일은 남음), `auto_push_on_pass` 는 service 가 무시 |
| 4 CLI `submit` | `tests/test_cli.py` | +23 | 프롬프트 기본 N(문구 "1회 감소"·`[y/N]`), 거부 5종/수락 4종, `-y` 생략, **비-tty 에서 `-y` 없으면 exit 2 + 미호출**, 오답 exit 8 + `[FAIL]`, `--push` 오답 시 "푸시하지 않았습니다", `-m`/`--message` 전달, `SubmitError` exit 8 + hint, 중첩 topic, 설정 없음 exit 1, **`check --push` 제거(argparse exit 2)** |
| 5 GUI 제출 흐름 | `tests/gui/test_submit_gui.py` (신규) | 15 | 다이얼로그 문구("제출 가능 횟수가 1회 감소", 자동/수동 안내 분기, 기본 버튼=제출, Esc=취소), 취소→미호출, 풀이 없음/설정 없음/폼 오류→다이얼로그 없음, Pass 수동→배지+[커밋 + 푸시] 배너+`push=False`, **Pass 자동→`push=True`+배너 버튼 없음+git 배지**, 오답(자동 모드여도)→배지+hint+푸시 없음, `SubmitError`→"제출 실패", 제출 중 재요청 무시, 진행/알림→상태바, **최근 페이지 우클릭 "SWEA 제출…"→검증 페이지 이동+같은 다이얼로그**, **"git / 제출 응답" 탭 = `last_submit.json["response"]` 와 동일 + 비밀번호·쿠키·ID 문자열 없음**(실제 service 경로, FakeSession 큐 소진 확인), `SubmitWorker` push 전달/오류 매핑 |

픽스처 `tests/fixtures/submit_*.json` 11종 — 실제 응답의 **키 구조**(`result/vo/submitFailed/compileTime/testInput/compile`, `vo` 18키, `testCaseNo` int·`correctedCases` str)만 참고해 값은 합성. 계정 식별자·쿠키 없음을 테스트가 매번 검사.

## 2. 지시서와 실제 코드의 불일치 (planner 판단 요청)

| # | 지시서 | 실제 | 처리 |
|---|---|---|---|
| D1 | §2 "`--refresh-index` 면 재스캔" | `find_category` 에 refresh 인자가 없고 `submit` 명령에도 `--refresh-index` 가 없다. 재스캔은 **`fetch --refresh-index`** 를 따로 실행해야 함(`find_by_number(refresh=True)` 가 club_id/box_id 를 채움) | 그 경로를 테스트로 고정. **UX 공백**: 공개 문제로 한 번 제출해 `box_scanned=True` 가 찍힌 뒤 클럽 상자에 같은 번호가 추가되면, 사용자가 `fetch --refresh-index` 를 떠올리지 않는 한 계속 CODE 로 제출됨(GUI 엔 안내 없음). `submit --refresh-index` 또는 `box_scanned` 에 만료 시각을 두는 것을 M10 후보로 |
| D2 | §3 "오답 → `SubmitError`" | `service.submit_problem` 은 오답을 **예외 없이 `passed=False`** 로 돌려주고, `SubmitError`(exit 8) 는 **CLI `run_submit` 이** 던진다 (GUI 는 예외 없이 배지) | 실제 계약대로 고정 (service 17건·CLI 23건). 구성안 6절 종료 코드 설명을 "CLI 한정" 으로 |
| D3 | §3 "`auto_push_on_pass` 와 `push` 우선순위" | service 는 설정을 보지 않고 `push` 인자만 본다. GUI 는 설정→`push=True` 로 번역. **CLI `submit` 은 설정을 무시**하고 `--push` 만 인정 — `docs/troubleshooting.md:154` 는 "`SWEA_AUTO_PUSH=1`: SWEA 제출 Pass 시 자동 커밋+푸시" 라고만 적어 CLI 도 되는 것처럼 읽힘 | service·GUI 동작은 고정. **CLI 쪽은 문서 수정 또는 `run_submit` 에서 `push or settings.auto_push_on_pass` 중 하나를 결정해 달라** (테스트로 고정하지 않음) |
| D4 | §5 "탭에 `last_submit.json` 내용 표시" | 탭은 서버 **응답 JSON**(`res.raw`) 만 보여준다 = 파일의 `response` 필드. 파일에 있는 `categoryType/categoryId/at` 는 탭에 없음(헤더 줄에 contestProbId 만) | 동일성(`shown == last["response"]`)으로 고정. 진단 시 category 가 핵심이므로 헤더 줄에 `categoryType/categoryId` 추가를 권장 (낮음) |

## 3. 관찰 (수정 요청 아님 — 우선순위 판단용)

| # | 관찰 | 영향 | 제안 |
|---|---|---|---|
| T1 | **기존 CLI 테스트 전부가 GitHub 에 실제 요청을 보내고 있었음** — `cli.main()` 이 끝날 때 `update.notice()` 를 부르는데 tmp config_dir 엔 캐시가 없어 매 테스트 `fetch_latest` 실행. 이번에 `tests/conftest.py` 에 `_no_network` autouse(업데이트 조회 + `requests` 전송 차단) 추가 → 전체 실행 18s → 8s | 중간 (공용 망에서 60/h 한도 소모, 오프라인 실패 가능성) | 테스트로 해결됨. 구성안 테스트 전략에 "네트워크 차단 픽스처 필수" 명시 |
| T2 | `import sys, os` 처럼 섞인 import 는 변환·검사 모두 통과 → `compile.do` 가 NK 로 거부(제출 횟수 미소모) | 낮음 (안전 방향) | 현 동작 고정. 안내 문구에 "한 줄에 `import sys` 만" 정도 추가 가능 |
| T3 | `sys.` 잔존 검사가 정규식이라 문자열/주석 안의 `sys.` 도 거부 | 낮음 (제출 안 하는 방향) | AST 기반으로 바꿀지는 P2 |
| T4 | 세션 만료 재시도는 `get_context→compile→submit` 전체를 다시 돈다. 302 는 "로그인 안 됨" 이라 첫 시도에서 제출이 기록될 수 없어 이중 제출 위험은 없음 — 단 `submit.do` 가 200 을 준 뒤 응답 파싱에서 실패하면 재시도하지 않고 `SubmitError`(횟수는 소모됨) | 낮음 | 응답 파싱 실패 메시지에 "제출은 됐을 수 있으니 SWEA 에서 확인" 을 붙이면 좋음 |
| T5 | `_rescan_box_id` 는 상자를 최신순으로 훑다 **처음 만나는** 상자를 택한다. 같은 번호가 두 상자에 있으면 최신 상자로 제출 | 낮음 | 의도와 맞는지 확인만 |
| T6 | M6(doctor/update)·M7(gitops 실제 git 실행) 은 여전히 테스트 0. 이번 M9 는 gitops 를 스텁으로만 사용 | 중간 | M10 후보: `gitops` 는 임시 저장소(`git init` + bare origin)로 commit/push 실측 가능 |
| T7 | GUI 제출 테스트는 다이얼로그를 `QMessageBox` 대역으로 바꿔 검증 — 실제 모달 렌더링·키 입력은 검증하지 않음 (M5 T4 와 같은 한계) | — | 그대로 |

## 4. 종료 조건 대조

- 490 → 630 전부 통과 ✔ / 실서버 호출 0 ✔ (`_no_network` 가 `requests` 전송 자체를 막으므로 이후 추가되는 테스트도 자동 보장) / 픽스처에 계정·쿠키 없음 ✔ / 버그 수정 없음 → 버전 유지(`v0.6.2`), 태그는 builder 결정.
- builder 에게 넘길 수정 사항은 **없음**. D3(CLI 자동 푸시)·D1(재스캔 UX) 은 스펙 결정이 먼저.

## 5. 참고 위치

- 신규: `tests/test_submit.py`, `tests/gui/test_submit_gui.py`, `tests/fixtures/submit_*.json`
- 수정: `tests/test_lookup.py`(find_category), `tests/test_service.py`(submit_problem), `tests/test_cli.py`(submit), `tests/conftest.py`(`_no_network`)
- 이전 전달문: `docs/handoff-planner-m5.md`(테스트 전략), `docs/handoff-planner-m8.md`(제출 설계·실측)
