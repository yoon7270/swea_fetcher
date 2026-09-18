# tester → planner 전달 (M10 §2: gitops / update / doctor 테스트, 2026-09-18)

대상: `docs/project-plan.md` 12절 M10 마감. 검증 대상 `4894d34` (`0.6.3`, builder §1 + W1 수정 반영본). 소스 변경 없음 — 테스트·`tests/conftest.py`(`FakeResponse.raise_for_status`) 만.

## 1. 결과

```
PYTHONUTF8=1 .venv/Scripts/python -m pytest -q
```

**통과 772 / 실패 0 / 스킵 0** (약 35s, 2회 연속 동일). 639(builder §1 포함) → **+133**.
1차 실행(`00f0842`)에서 `update.check()` 버그 1건(W1)을 잡아 `docs/tester-feedback-m10.md` 로 전달 → builder 수정(`4894d34`) → 회귀 테스트 1건 추가 후 전부 통과. **§3 (CHANGELOG·Release) 진행 가능.**

| 지시서 항목 | 파일 | 추가 | 고정한 것 |
|---|---|---|---|
| `gitops.py` | `tests/test_gitops.py` (신규, git 없으면 전체 skip) | 54 | **실제 git**: `tmp_path` 에 `git init --bare` origin + clone(전역/시스템 설정 차단). 성공 push(원격 로그 = 로컬 로그), `push=False` 커밋만, 변경 없음(로컬/원격도 최신), **문제 폴더만 커밋**(루트의 미추적·스테이징된 다른 변경은 커밋에 안 섞이고 그대로 남음), 이전 미푸시 커밋 푸시, 첫 push 가 `-u` 로 upstream 설정, **non-fast-forward → note "git pull"**(로컬 커밋은 유지, force push 없음), 사용자 이름 없음 → `user.name` 안내, `toplevel` 이 root 상위 → pathspec `swea/Queue/1225`, push 시간 초과, 출력 토큰 마스킹, 한글/따옴표 커밋 메시지, `GIT_TERMINAL_PROMPT=0`. `find_repo` 필드/토큰 마스킹/dirty_outside/detached/remote 없음, `in_progress_operation` 3종, `preflight` 7케이스, `render_message` 9케이스, `classify_push_error` 8케이스, `mask_url` 7케이스 |
| `update.py` | `tests/test_update.py` (신규) | 59 | `parse_version`/`is_newer`, 캐시 병합·손상, 끄기(환경변수 8값·캐시 플래그), `check()`: 캐시 없음→조회+기록, **24h 내 캐시→HTTP 0**, stale→재조회, `force` 는 disabled·캐시 무시, 실패(타임아웃·401·JSON·기타)→None 무음, **실패 후 하루 백오프(성공 이력 없어도)**, stale 캐시+실패→캐시 반환, 절대 예외 없음; `notice()` 최신>현재만 문구; `fetch_latest` 원본을 FakeSession 으로(302 Location 우선·상대 Location·API 폴백·`html_url` 없음·API 401/404/JSON/빈 tag → 예외); CLI: 명령 끝 stderr 알림, **`--no-update-check`**, 알림 None, 명령 실패해도 알림, 알림 예외가 종료 코드 안 바꿈, doctor 는 생략; **`_no_network` 차단이 살아 있는지 회귀 테스트** |
| `doctor` | `tests/test_cli.py` | +20 | offline 행 8개 정확히·**HTTP 0**, online 은 로그인 상태·최신 버전 추가, 로그인 행 4상태, 최신 버전 행 4상태 + `force=True`, 설정 불완전 시 상세(ID·명령) 숨김, keyring 있음/없음/실패/ID 없음, 설정 폴더 카운트, 루트 3상태, git 행 6상태, Python 출처, 항목 실패 격리(`_safe`), **report 에 비밀번호·쿠키·`SESSION=`·ID 없음**, CLI `doctor --offline`/온라인 |

지시서 §2 "`_no_network` 우회 금지" 준수: `fetch_latest` 테스트는 모듈 import 시점의 원본 함수를 `FakeSession` 으로만 호출(실제 전송 차단은 그대로).

## 2. builder §1 (B1~B6) 확인

builder 가 함께 넣은 테스트 9건(`test_submit_gui.py` [다시 찾기]/맥락 문구, `test_cli.py` `--no-push`/`SWEA_AUTO_PUSH`/`--refresh-index`) 통과. 코드 대조: `find_category(refresh=)` ✔ / `run_submit` `push or (auto and not no_push)` ✔ / 응답 탭 헤더 `categoryType/categoryId` ✔ / 파싱 실패 문구 "접수됐을 수 있습니다" ✔ / `sys.` hint "한 줄에 단독으로" ✔ / README·page-notes "최신 상자" ✔ / troubleshooting.md CLI·GUI 동일 의미 ✔. **종료 조건 "제출 확인창에 대상 맥락이 보임" 은 사용자 스크린샷 1회가 남음** (offscreen 테스트는 문구만 검증).

## 3. 발견 (planner 판단)

| # | 내용 | 영향 | 상태 |
|---|---|---|---|
| **W1** | 새 버전 조회가 **한 번도 성공한 적 없으면** 실패 후 백오프가 안 됐음 → 오프라인·비공개·차단망에서 모든 CLI 명령이 매번 최대 ~6초 지연 | 중간 → **해소** | `4894d34` 에서 `fresh` 를 `checked_at` 만으로 판정. 회귀 테스트 2건 |
| T1 | `tests/test_gitops.py` 는 git 프로세스를 수백 번 띄워 **약 17초** — 전체의 절반 | 낮음 | CI 분리 시 마커 후보. 지금은 그대로 |
| T2 | gitops 는 `LC_ALL=C` 영어 메시지로 push 오류를 분류 — git 버전별 문구가 바뀌면 폴백(마지막 줄)으로 떨어짐. 실측(2.54)에선 정상 | 낮음 | 리스크 목록에 한 줄 |
| T3 | `doctor` 온라인 모드의 "최신 버전" 은 `force=True` 라 캐시를 무시하고 매번 조회 — 진단용 의도. 오프라인이면 `--offline` 안내가 이미 있음 | 낮음 | 그대로 |
| T4 | M10 으로 **전 모듈 테스트 커버**(cli/service/submit/lookup/gitops/update/doctor/checker/gui). 남은 미검증은 `packaging/`(PyInstaller spec, `_selftest` 훅)뿐 | — | 구성안 테스트 전략 표에 "exe: `SWEA_FETCH_SELFTEST` + 수동" 으로 명시 |

## 4. 종료 조건 대조

- 639 → gitops/update/doctor 추가 후 **772 전부 통과** (W1 수정 반영) ✔
- 제출 확인창 맥락 표시: 코드·문구 테스트 ✔, 사용자 스크린샷 대기
- `SWEA_AUTO_PUSH` CLI·GUI 동일 의미: builder 테스트 + 문서 확인 ✔

## 5. 참고 위치

- 신규: `tests/test_gitops.py`, `tests/test_update.py`, `docs/tester-feedback-m10.md`
- 수정: `tests/test_cli.py`(doctor 20건), `tests/conftest.py`(`FakeResponse.raise_for_status`)
- 이전: `docs/handoff-planner-m9.md`(§3 T1 `_no_network`, T6 이 이번 §2 의 근거)
