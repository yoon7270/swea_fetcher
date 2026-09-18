# builder → planner 전달 (M11: GitHub 자동 동기화, 2026-09-18)

대상: `docs/project-plan.md` 12절. 태그 `v0.7.0`, 772 테스트(기존 유지, M11 §8 테스트는 tester 예정).
지시서 `docs/m11-work-order.md` 의 §1~§7 builder 범위 구현. §8 테스트·§9 step5 는 tester.

## 1. 구현

- **config** (`SWEA_AUTO_PUSH` 재사용 + `SWEA_AUTO_PUSH_SCOPE`, `SWEA_AUTO_PUSH_ON`): `Settings.auto_push/auto_push_scope/auto_push_on(frozenset)` 추가, `auto_push_on_pass = auto_push and "pass" in on` 으로 계산(하위호환). 잘못된 값 기본값+WARNING, 빈 시점→`pass`.
- **gitops**: `changed_problem_dirs`(status→{topic}/{num}/ 묶기, 중첩 주제·root 밖 제외), `commit_and_push_scope(scope)`(problem=문제폴더 pathspec, root=`add -A -- {root}` .gitignore 적용), `_scope_message`(`solve: 1225, 1226 (Queue)` / `sync: 날짜`). 기존 `commit_and_push` 는 `_commit_push` 로 일반화하되 외부 동작 동일.
- **service.sync_now(reason, scope, problem_dir, dry_run)**: 예외 없이 `GitResult|None`. reason 필터(manual 항상), remote 없음/저장소 아님/merge·rebase·detached → None 또는 note. `submit_problem` 은 scope=root 일 때 sync_now 로, 아니면 기존 push_problem(문제 scope). `fetch_problem` 저장 후 reason=save 훅.
- **autosync** (`gui/autosync.py`): QTimer 30s 폴링 → `git status` 해시 → 디바운스 90s → `sync_now(reason=watch)`. 다른 워커 실행 중 건너뜀, 반복 실패 시 일시 중지+60s 재시도, 종료 시 1회. 순수 판정 `_decide(state, now, hash, busy)` 분리(테스트용).
- **GUI**: 설정 "GitHub 자동 동기화" 그룹(켜기·범위 radio·시점 checkbox·종료시 동기화·[지금 동기화]), 켤 때 경고 1회, 루트 전체 첫 선택 시 파일 수·예시 확인창. 상태바 배지(⟳/⚠, 클릭→설정). `main_window` 가 `AutoSyncController` 소유, reload_settings→configure, closeEvent→sync_on_close.
- **CLI**: `sync [--scope] [--dry-run]`, `fetch`/`check` 에 `--no-push`, `check` 통과 후 자동 동기화, `doctor` 에 `자동 동기화` 줄.
- **docs**: README "자동 동기화" 절(범위·시점 표, 변경 감지, .gitignore 예시), troubleshooting "자동 동기화가 일시 중지됐을 때", CHANGELOG v0.7.0.

## 2. 설계 판단 (구성안 반영)

- 트리거 4종을 한 설정 그룹으로 통합. `SWEA_AUTO_PUSH=1` 단독은 `problem`+`pass` (M7/M8 과 동일) → 기존 사용자 무변경.
- root 범위 + pass 는 `submit_problem` 이 sync_now(scope=root) 로 처리(제출 Pass 후 루트 전체 커밋). problem 범위 pass 는 기존 push_problem(단일 문제) 유지 → M8 GUI/CLI 테스트 무변경.
- 변경 감지는 파일와처 대신 `git status` 폴링(.gitignore 자동 적용, 중첩 주제 안정). GUI 전용, 앱 실행 중에만.
- 실패는 예외로 흐름을 끊지 않고 GitResult.note. 자동 경로(watch/save)는 조용히 로그.

## 3. 미검증·확인 필요

- **실제 GitHub push 는 offscreen bare 저장소로만 검증.** 실 원격 자동 동기화(변경 감지 2분 대기, non-fast-forward 일시 중지)는 M11 §10 사용자 확인 항목.
- watch 폴링/디바운스/종료 동기화의 실시간 타이밍은 `_decide` 단위 로직만 검증. 실제 30s/90s 타이머 동작은 사용자 확인.
- §8 테스트(autosync fake clock, gitops scope, config, sync_now, GUI 그룹, CLI sync)는 **tester** 가 작성 예정.

## 4. 참고 위치

- 코드: `swea_fetcher/gitops.py`(scope), `service.py`(`sync_now`), `gui/autosync.py`, `gui/pages/settings_page.py`(그룹), `gui/main_window.py`(배지·close), `cli.py`(`sync`)
- 설정 키: `SWEA_AUTO_PUSH` / `_SCOPE` / `_ON` — `docs/troubleshooting.md` 설정 파일 표
- 스크린샷: `docs/gui-screenshots/12-autosync-settings.png`
