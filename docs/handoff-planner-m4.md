# builder → planner 전달 (M0~M4 완료, 2026-09-17)

대상: `docs/project-plan.md` 갱신. 현재 태그 `v0.3.1`, `main` = `e624011`. 470 테스트 통과 (tester 승인).

## 1. 구성안과 달라진 결정 (구성안 반영 필요)

| 구성안 항목 | 원안 | 실제 (근거) |
|---|---|---|
| 2.4 A1-1 로그인 | 미정 (폼 POST / Playwright) | **requests 폼 POST 확정**. `POST /main/identity/anonymous/login.do` (id, pwd 평문, lang, clientTimezone) → JSON. 캡차·CSRF 없음, 계정 MFA 없음. **Playwright 항목 삭제** |
| 2.4 A2 첨부 | `sample_input.txt` 고정 | 파일명 가변(`input7_sample.txt`). `contestProbDown.do?downType=in\|out` 로 구분 |
| 2.4 A3 번호 위치 | 문제 페이지 제목 | **"문제 풀기" 편집 화면(`POST solvingProblem.do`)의 `h3.problem_title`** 에만 있음. Solving Club 상세엔 번호 없음. 일반 `problemDetail.do` 는 `p.problem_title` |
| 도구 입력 | 문제 링크 URL | **문제 번호** (`swea-fetch 25730 IM_test`). Solving Club 화면은 POST 라 주소창에 ID 가 없음 → `lookup.py` 가 번호→ID 조회 (캐시 → 공개 Problem 목록 → User Problem 목록 → 가입 클럽 문제 상자). URL/ID 직접 입력도 여전히 가능 |
| 3 기술 스택 | `.env` 에 ID/PW | **비밀번호는 Windows 자격 증명 관리자(keyring)**, `.env` 엔 ROOT/ID 만. `init --migrate` 로 이관. 한계(같은 Windows 계정이면 읽힘)는 README 명시 |
| 4 모듈 구조 | 8개 모듈 | 추가: `lookup.py`(번호 조회), `service.py`(CLI/GUI 공용 계층), `checker.py`(풀이 검증), `gui/`(PySide6). `cli.py` 는 `service` 호출만 |
| 5 기능 P1 | `--skeleton-only`, 유사 폴더 경고 | 전부 완료 + `--dry-run`, `--refresh-index`, `check` 서브커맨드(exit 6) |
| 6 종료 코드 | 0/1/2/3/4 | + 5 네트워크, 6 검증 실패, 10 내부 오류 |
| 8 보안 | `.env` 평문 임시 허용 | keyring 전환 완료. `logout --all` 이 `.env`+자격 증명+세션 일괄 삭제 (10절 체크리스트 1·2·6번 흡수) |
| 9 리스크 "HTML 구조 변경" | 선택자 상수화 | `parser.py`·`lookup.py` 상단 상수 + 픽스처 5종 (`tests/fixtures/`) |
| 7 마일스톤 | M0~M3 | M4a/b/c 추가 완료 (GUI + exe). 태그 `v0.1.0`(M2 E2E) `v0.1.1`(M2 승인) `v0.2.0`(M3) `v0.3.0`(M4b) `v0.3.1`(M4c) |

## 2. 사이트 실측 사실 (구성안 "남은 우려" 갱신용)

- 문제 페이지 3종: (A) `problemDetail.do` GET, (B) Solving Club `problemView.do` POST, (C) 편집 화면 `solvingProblem.do` POST. 도구는 (C) 를 `categoryType=BOX` 로 POST — **일반·User·클럽 문제 모두 200** (`categoryId` 불필요).
- 세션 쿠키 `SESSION`. 만료 판별 = 302 + `Location: loginPage.do`. 응답 charset 없음 → utf-8 강제.
- SWEA 잠금 5회 → 도구는 프로세스당 1회 + 누적 3회(`login_state.json`)에서 중단.
- 번호 조회 커버리지: 사용자 기존 폴더 번호 전부 (공개 목록 8, User Problem 1, 클럽 4).
- 상세: `docs/swea-page-notes.md`.

## 3. 미결 · 판단 요청

1. **일반 (A) 페이지의 `span.week_num` 폴백**은 미검증 코드 — solver 경로가 항상 먼저 성공해 실사용 영향 없음. 삭제할지 유지할지.
2. **Contest 문제 / 미가입 클럽 문제**는 번호로 못 찾음 → URL 입력 폴백만. 범위 밖으로 둘지.
3. **작업 취소 버튼** 없음 (requests 중단이 불안정). 검증(subprocess kill)만이라도 넣을지.
4. **다크 테마** 없음 (디자이너 미제작). 요청 시 `tokens.DARK` 채우면 됨.
5. **exe 배포**: `dist/` 미커밋. GitHub Release 첨부 여부는 사용자 결정. 공용 PC 백신 오탐 시 `ONEFILE=False`.
6. **P2 후보**: 여러 번호 일괄(`swea-fetch 25707 25708 IM_test`), 번호 없이 최신 상자 picker, 다중 테스트케이스.

## 4. 승인 이력

| 마일스톤 | 승인 | 비고 |
|---|---|---|
| M2 | 2026-09-16 | 번호 입력 UX 재작업 후 승인 ("링크 복사"는 사용자가 거부) |
| M3 | 2026-09-16 | `.env` 에 `SWEA_PW` 없음 확인 |
| M4b | 2026-09-16 | 저장·검증 실사용 확인 |
| M4c | exe 자가진단 통과, 사용자 더블클릭 확인 대기 |

## 5. 참고 위치

- 코드: `swea_fetcher/` (모듈별 docstring 에 계약), 진입점 `cli.py` / `gui/app.py`
- 문서: `README.md`, `docs/swea-page-notes.md`, `design/design-spec.md`(§15 대체안), `docs/gui-screenshots/`
- 빌드: `packaging/` (지시서의 `build/` 는 `.gitignore` 대상이라 변경)
