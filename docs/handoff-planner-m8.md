# builder → planner 전달 (M8: SWEA 제출 연동, 2026-09-17)

대상: `docs/project-plan.md` 12절(로드맵) 갱신. 현재 태그 `v0.6.2`, 490 테스트 통과, 저장소 public.
M7(`v0.5.0`) 의 "검증 통과 시 커밋+푸시" 를 사용자 요청대로 **"SWEA 제출 Pass 시"** 로 바꾼 것이 M8.

## 1. 무엇을 만들었나

요청 원문(#5·#6 통합): "문제 풀이 시 깃허브와 연동시켜 자동적으로 push", 이어서 "SWEA에 제출해서 pass일 때 업로드".

흐름: **번호로 저장 → 로컬 검증(선택) → [SWEA 제출] → SWEA 채점 → Pass 면 그 문제 폴더만 커밋+푸시**.

- `swea_fetcher/submit.py`: 풀이 화면 JS(`onEditSubmit`)와 동일하게 `compile.do` → `submit.do`. 채점 결과가 submit 응답 JSON 에 바로 옴(폴링 없음). 소스 변환(SWEA 가 `import sys` 거부 → 해당 줄 제거), 결과 판정은 사이트 `processSubmit()` 그대로.
- `service.submit_problem(push=…)` → `SubmitOutcome`. `errors.SubmitError` 종료 코드 8.
- CLI: `swea-fetch submit <topic> <num> [--push] [-m] [-y]` (확인 프롬프트, 오답 exit 8). M7 의 `check --push` 는 삭제.
- GUI: 검증 페이지 [SWEA 제출](확인 다이얼로그 "제출 횟수 1회 감소") → 결과 배지 → Pass 면 [커밋 + 푸시] 배너 또는 자동. 최근 페이지 우클릭 "SWEA 제출…". 설정의 자동 모드는 이제 **SWEA Pass** 기준.

## 2. 구성안에 반영할 사실 (실측)

`docs/swea-page-notes.md` "제출 API" 절에 상세. 핵심:

1. **제출 = `POST /main/commonCompileRun/compile.do` → `submit.do`**, 같은 폼 파라미터 `{source, langType, probId(=contestProbId), categoryId, categoryType, useOptimize}`. 헤더 세션쿠키 + `X-Requested-With` + `Referer`. CSRF 없음. 채점 결과는 즉시 응답(`vo.runValue "Pass"/…`, `usrScore`, `testCaseNo/correctedCases`, `timeOut`, `runError`).
2. **SWEA 는 Python `import sys` 를 거부** (compile 응답 `exitValue=NK`). 뼈대의 `import sys` / `sys.stdin = open(...)` 줄을 빼고 제출. 다른 `sys.` 사용이 남으면 제출 거부(안내).
3. **제출 이력은 맥락(category)별로 따로 집계된다.** 같은 문제 번호가 공개 Problem(`CODE`) 과 Solving Club 문제 상자(`BOX`) 에 **같은 contestProbId** 로 동시에 존재할 수 있는데(1225 실측: 같은 ID `AV14uWl6AF0CFAYD`), 풀이 화면의 '제출횟수/제출결과' 는 CODE 2회 / BOX 1회로 서로 다르게 집계됨. → 제출 대상은 사용자가 채점받는 맥락이어야 함. `lookup.find_category` 가 번호가 내 클럽 상자에 있으면 **BOX 우선**(없으면 CODE), `box_scanned` 플래그로 재스캔 방지. 색인에 `club_id/box_id` 저장.
4. 언어: 현재 **Python(`langType=py`) 전용**. 다국어는 보류(#1)와 함께.

## 3. 실사용에서 잡은 버그 (릴리스별)

| 버전 | 증상 | 원인 / 수정 |
|---|---|---|
| v0.6.1 | 제출은 되는데 문제 '제출결과' 에 기록 안 됨 | 제출에 category 누락. 문제를 연 경로의 `(categoryType, categoryId)` 필요 → `find_category` 추가 |
| (auth) | 두 번째 실행이 "세션 확인 중 예상 밖 응답 HTTP 302" 로 멈춤 | 세션 만료 시 `loginPage.do` 아닌 곳으로 302 → `is_logged_in` 이 모든 리다이렉트를 로그아웃으로 보고 재로그인 |
| v0.6.2 | 제출이 "공개 Problem" 에 기록되고 사용자가 보는 "모의 테스트(클럽 상자)" 엔 안 뜸 | §2-3. 클럽 상자(BOX) 우선으로 제출. **사용자 최종 확인: 모의 제출 이력에 기록됨** |

교훈(기록): HTTP 조회 결과 하나로 "됐다" 단정하지 말 것 — 사용자가 보는 인스턴스(모의)와 다른 인스턴스(공개)를 조회해 오판했음. 실제 `submit.do` 는 분류기가 실제 제출을 막아 builder 가 직접 못 돌리고, **사용자 1회 제출로 검증**함.

## 4. 종료 코드 (errors.py)

기존 0~7 에 **8 = 제출 실패·오답(`SubmitError`)** 추가. troubleshooting.md 에 "SWEA 제출(종료 코드 8)" 표.

## 5. 보류·다음 (사용자 결정 대기)

- **#1 다른 언어 지원 / 속도**: 제출이 Python 전용. `langType` 매핑(C=`c`, C++=`cpp`, Java=`java`)과 언어별 소스 변환(예: Java 는 `import` 제약 다름)이 필요. 요청자에게 "어떤 언어를 실제로 쓰는지" 확인 후 재평가.
- **#4 확장프로그램**: 의미 미확인(브라우저 확장? IDE 플러그인?). 요청자에게 확인 필요.
- 테스트: submit/lookup.find_category/GUI 제출 흐름은 tester 가 아직 작성 전 (builder 는 offscreen·실세션 스모크로만 검증). `tests/test_submit.py`, `find_category`(BOX 우선·box_scanned), GUI [SWEA 제출] 흐름 권장.

## 6. 참고 위치

- 코드: `swea_fetcher/submit.py`, `lookup.py`(`find_category`), `service.py`(`submit_problem`), `gui/pages/check_page.py`(`request_submit`)
- 문서: `docs/swea-page-notes.md`("제출 API"), `README.md`("GitHub 연동"), `docs/troubleshooting.md`("SWEA 제출"), `CHANGELOG.md`
- 진단: 제출할 때마다 `%USERPROFILE%\.swea-fetch\last_submit.json` 에 요청 category + 서버 응답 저장(쿠키·비밀번호 없음), GUI "git / 제출 응답" 탭에도 표시
