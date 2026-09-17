# SWEA 페이지 구조 조사 노트 (M0 spike)

조사일: 2026-09-16. 기준 호스트 `https://swexpertacademy.com`.
비로그인 관찰은 `requests` 로 직접 확인함. 로그인 후 페이지는 사용자가 브라우저에서 저장해 준 HTML(Solving Club 문제 페이지, 문제 풀기 편집 화면)로 확인함. 남은 `TODO` 는 일반 `problemDetail.do` 페이지와 첨부 없는 문제 확인 건.

## 로그인

- **판정: (a) requests 폼 POST 로 가능** (JS 암호화·CSRF 토큰·캡차 없음). 사용자 계정은 브라우저 로그인 시 2단계 인증 화면이 뜨지 않음을 확인(2026-09-16) → MFA 분기는 방어 코드로만 유지
- 로그인 페이지: `GET /main/identity/anonymous/loginPage.do` (200, UTF-8)
- 폼: `<form id="LoginForm" name="LoginForm" method="POST">` — `action` 속성 없음. 실제 전송은 JS `loginSecurityPledge()` 가 jQuery `$.ajax` 로 수행
  - **POST `/main/identity/anonymous/login.do`**, `application/x-www-form-urlencoded` (jQuery 기본), `dataType: json`
  - 전송 필드: `id`, `pwd` (**평문**), `lang` (`ko_KR`), `clientTimezone` (예: `Asia/Seoul`, hidden input `#clientTimezone` 에 jstz 로 채움)
  - 숨은 필드: `clientTimezone` 뿐. CSRF 토큰 없음 (`csrf|token|encrypt|RSA|captcha` 검색 결과 0건)
  - 폼 입력 선택자: `#id` (`input[name=id]`), `#pwd` (`input[name=pwd]`), 버튼 `button.btn_login[onclick="loginSecurityPledge()"]`
- 성공 판별: 응답 JSON `{"success": true, "message": ..., "returnPath": "/..."}` → 브라우저는 `"/main" + returnPath` 로 이동
  - `message == "mfa"` 이면 2단계 인증 페이지(`returnPath`)로 이동해야 하므로 폼 POST 만으로는 완료 불가
  - `message == "tempPwd"` 는 성공이나 임시 비밀번호 상태
- 실패 판별: `success == false`, `message` 값
  | message | 의미 |
  |---|---|
  | `LoginIdFail` | 없는 ID |
  | `LoginIdPwdFail` | 비밀번호 틀림 (**5회 실패 시 잠금** 경고) |
  | `LoginPwdErrorCount` | 5회 초과 → 관리자 문의 |
  | `DormancyAccount` | 휴면 계정 (`/main/identity/user/dormancyRecovery.do` 로 복구 후 재로그인) |
  | `LoginInactive`, `BlockedId`, `tempPwdExpired`, `mfaError` | 각각 비활성/차단/임시PW만료/MFA오류 |
  - 빈 `id`/`pwd` 로 POST 하면 200 + 빈 본문 (JSON 아님) → 파싱 전에 본문 비어 있는지 검사할 것
- 세션 쿠키: **`SESSION`** (Spring Session 스타일, base64 UUID). 그 외 `SCOUTER`(APM), `LANGUAGE`, `returnPath`, `lastActivityTime` 도 첫 요청에서 발급됨. `JSESSIONID` 는 사용하지 않음
- 세션 확인 URL: `GET /main/userpage/userInformation.do` — 비로그인 시 **302 → `/main/identity/anonymous/loginPage.do`**, 로그인 시 200 (예상). `allow_redirects=False` 로 302 + `Location` 에 `loginPage.do` 포함 여부로 판별
- 로그인 여부 판별 대안: 문제 상세 페이지 자체도 비로그인 시 같은 302 → `fetch` 가 302 + `loginPage.do` 를 "세션 만료" 신호로 쓰면 됨

## 문제 페이지

SWEA 에는 문제 관련 페이지가 **세 종류** 있고, 사용자의 실제 사용 경로는 (B) → "문제 풀기" → (C) 이다. **문제 번호는 (C) 에만 있다.**

| | (A) 일반 문제 상세 | (B) Solving Club 문제 상세 (SSAFY 모의고사 등) | (C) 문제 풀기(코드 편집) 화면 |
|---|---|---|---|
| URL | `GET /main/code/problem/problemDetail.do?contestProbId={id}` | `POST /main/talk/solvingClub/problemView.do` (hidden `solveclubId`, `probBoxId`, `contestProbId`) | `POST /main/solvingProblem/solvingProblem.do` (hidden `contestProbId`, `categoryId`, `categoryType=BOX`, `isPostMethod=Y`, `do_url`) — **GET 으로 열면 오류 페이지** |
| 번호 | (미확인) | 없음 | **있음** `h3.problem_title` |
| 첨부 링크 | (미확인) | `div.down_area` | `div.down_area` (동일) |
| 확인 상태 | 비로그인 302 만 확인. **TODO** | 픽스처 `problem_with_attachments.html` | 픽스처 `problem_solver_page.html` |

- `contestProbId` 는 `AZq-gSmq_RfHBISS` 같은 16자 영숫자(`-`,`_` 포함). 문제 번호와 무관
- 비로그인 접근: **302 → `/main/identity/anonymous/loginPage.do`** (본문 0 byte). `login_redirect.html` 픽스처는 따로 없음
- **오류 페이지**: 잘못된 ID 등으로 접근하면 HTTP 200 에 `<title>::: Error :::</title>`, 본문 `"죄송합니다. 시스템 오류입니다."` 가 오는 안내 페이지 (`div.content_sub` 없음). `fetch` 는 `title == '::: Error :::'` 를 `ProblemNotFound` 로 처리할 것
- 세션 유지: 페이지 JS 가 60초마다 `POST /main/identity/anonymous/sessionExtension.do` 호출 (도구는 불필요)

### (B) Solving Club 페이지 구조 (확인됨)
- 컨테이너: `div.content_sub > div.club_wrap > div.right_con`
- 문제 상자 제목: `h4.club_box_tit` → `"09.10 모의 (5)"`
- **제목 선택자: `p.problem_title`** → 텍스트 `"[07] 항아리 게임"` + `span.badge` 에 난이도 `"D1"`.
  - `[07]` 은 상자 내 순번이지 SWEA 문제 번호가 **아님**. 페이지 어디에도 `NNNN.` 형태 번호 없음 (4~5자리 숫자 검색 결과: 메모리 제한 등만) → **A3 는 이 페이지에서 불성립**
  - 파서 규칙: `p.problem_title` 의 직접 텍스트에서 `^\[(\d+)\]\s*(.+)$` 로 순번·제목 분리, `span.badge` 는 제외
- **첨부 링크 선택자: `div.down_area a[href*="contestProbDown.do"]`** (입력·출력 각 1개, 총 2개)
  ```html
  <div class="down_area">
    <a href="#"><span>
      <a href="/main/common/contestProb/contestProbDown.do?downType=in&contestProbId=AZq-gSmq_RfHBISS&_menuId=AVtnUz06AA3w6KZN&_menuF=true">input7_sample.txt</a>
    </span><i><span class="hide">다운로드</span></i></a>
  </div>
  ```
  - href 패턴: `/main/common/contestProb/contestProbDown.do?downType={in|out}&contestProbId={id}&_menuId=...&_menuF=true`
  - **입력/출력 구분은 파일명이 아니라 `downType=in` / `downType=out` 쿼리로** 하는 것이 안전 (파일명은 `input7_sample.txt` 처럼 문제마다 다름 — `sample_input.txt` 고정 가정은 틀림)
  - 다운로드 URL 에 `contestProbId` 가 들어 있으므로 페이지에서 문제 ID 역추출 가능. hidden `#problemForm input[name=contestProbId]` 에도 있음
  - 다운로드 시 필요한 것: 로그인 세션 쿠키 `SESSION`. 추가 헤더 필요 여부는 M1 에서 실측 (Referer 는 붙여 두는 것을 권장)
- 첨부 없는 경우 특징: **TODO** (첨부 없는 문제 페이지 미확보). 예상: `div.down_area` 자체가 없음 → 파서는 `down_area` 0개를 "첨부 없음"으로 처리
- 본문: `div.tabcon > div.box4` (문제 설명), 제한사항 `div.box3 ul.list_type2`

### (C) 문제 풀기 화면 구조 (확인됨) — **`parse` 의 1차 대상**
- 새 창(팝업)으로 열림. `form#mainForm[action=/main/solvingProblem/solvingProblem.do]` 안에 전체 내용
- **번호·제목 선택자: `h3.problem_title`** (부모 `div.problem_box`, 그 위 `div#problem_right.problem_right > div.problem_wrap`)
  - 텍스트: `"25730. [07] 항아리 게임"` → 정규식 `^(\d+)\.\s*(?:\[\d+\]\s*)?(.+)$` 로 번호 `25730`, 제목 `항아리 게임` 추출 (`[07]` 은 모의고사 순번, 일반 문제에선 없을 수 있으므로 선택 그룹)
- **첨부 링크: `div.down_area a[href*="contestProbDown.do"]`** 2개 — (B) 와 같은 구조. href 는 `.../contestProbDown.do?downType=in&contestProbId=AZq-gSmq_RfHBISS` (여기선 `_menuId` 없음)
- 문제 ID: `#mainForm input[name=contestProbId]`, 상자 ID: `input[name=categoryId]` (= (B) 의 `probBoxId`)
- 사용자 개인 정보가 들어 있는 곳: 헤더 `span.name` (실명+회원번호), `textarea#textSource` (제출 코드), `div.CodeMirror` (에디터 렌더링) → 픽스처에서 `DUMMY_USER` / `# DUMMY_SOURCE` / `DUMMY_EDITOR` 로 치환
- 픽스처는 Chrome "웹페이지, 전체" 로 저장한 것이라 CSS/JS/이미지 경로가 `./raw_solver_files/...` 로 바뀌어 있음 (선택자·href 파싱엔 영향 없음). "HTML만" 저장은 GET 재요청이라 오류 페이지가 저장됨
- **M1 에서 실측할 것**: requests 로 `POST solvingProblem.do` 에 `contestProbId`(+`categoryId`, `categoryType=BOX`) 를 보내면 같은 HTML 이 오는지. `categoryId` 없이도 되는지

### 도구 입력 방식 후보 (M1 착수 시 결정)
(C) 화면은 POST 라 주소창 URL 을 붙여넣을 수 없다. 사용자가 쉽게 복사할 수 있는 값은:
1. (B)/(C) 화면에서 `input7_sample.txt` 우클릭 → "링크 주소 복사" → `contestProbDown.do?downType=in&contestProbId=...` — `contestProbId` 가 들어 있음. `categoryId` 는 없음
2. `contestProbId` 문자열 직접 입력
→ `cli` 는 URL 이든 ID 든 받아 `contestProbId` 를 뽑고, `fetch` 가 (C) 를 POST 로 가져오는 구조가 유력

### (A) 일반 문제 페이지 (M2 확인, M3 파서 반영)
- 공개 목록 페이지 `/main/code/problem/problemList.do` 는 비로그인 200 이며 각 문제가
  ```html
  <div class="header-caption">
    <span class="week_num">27008.</span>
    <span class="week_text"><a href="#none" onclick="javascript:fn_move_page('AZ8R9tAKeaPHBITH');">A+B…</a></span>
  </div>
  ```
  → 상세 페이지는 이 위젯이 아니라 **`p.problem_title` = `"4014. [모의 SW 역량테스트] 활주로 건설"`** (픽스처 `problem_detail_regular.html`). `parser._parse_detail_title` 은 이 요소만 읽는다 (목록 위젯 `span.week_num` 폴백은 M5 에서 삭제 — 실사용 경로에서 실행된 적 없음). 실패해도 예외 대신 `(None, "")` 을 돌려주고 cli/GUI 가 `--num` 을 요구
- Solving Club 의 `contestProbId`(`AZq-gSmq_RfHBISS`) 로 `problemDetail.do?contestProbId=...` 를 열면 **시스템 오류 페이지**가 뜸 (로그인 상태에서 확인, 픽스처 `error_page.html`). 즉 Solving Club 문제는 일반 페이지로 우회할 수 없고, 번호 획득 경로는 별도 확인 필요

### 계정 정보 제거 내역 (픽스처)
- 헤더의 닉네임 `span.name` → `DUMMY_USER`, `userInformationPopup('...')` 의 사용자 키 → `DUMMY_USER_KEY`
- `solveclubId` / `probBoxId` / `_menuId` 는 계정이 아닌 클럽·메뉴 식별자라 유지

## 요청 조건

- `User-Agent` 없이도 로그인 페이지 200 (61KB). 단 브라우저 UA 를 붙여 두는 편이 안전
- `Referer` 불필요 (비로그인 범위에서 확인). 로그인 POST 는 브라우저와 같게 `Referer: .../loginPage.do`, `X-Requested-With: XMLHttpRequest` 를 붙일 것
- 봇 차단·캡차: 로그인 페이지에 없음. Cloudflare 류 챌린지 없음 (requests 로 바로 200)
- 응답 인코딩: `Content-Type` 에 charset 이 없어 requests 가 ISO-8859-1 로 추정함 → **`r.encoding = "utf-8"` 강제 필요** (meta charset 은 UTF-8)

## 확정된 가정

- A1-1: **확정** — ID/PW 를 평문 form-urlencoded 로 `login.do` 에 POST 하면 JSON 으로 결과가 온다. 캡차·CSRF·JS 암호화 없음. 사용자 계정에 MFA 없음 확인. → `auth` 는 requests 만으로 구현, Playwright 불필요
- A2: **부분 확정 → 수정 필요** — 첨부는 (B)/(C) 모두 `div.down_area a[href*=contestProbDown.do]` 로 존재하고 `downType=in|out` 으로 입·출력이 구분된다. 단 **파일명은 `sample_input.txt` 고정이 아니라 `input7_sample.txt` 처럼 가변** → 파서는 파일명이 아니라 `downType` 으로 판별. 첨부 없는 문제의 형태는 미확인
- A3: **확정 (단, 페이지 한정)** — 번호는 (C) 문제 풀기 화면의 `h3.problem_title` 에 `"25730. [07] 항아리 게임"` 형태로만 노출됨. (B) Solving Club 상세 페이지의 `p.problem_title` 은 `"[07] 항아리 게임"` 으로 번호가 없음. → `parse` 는 (C) 를 대상으로 하고, `--num` 은 예비 수단으로 유지

## 픽스처

| 파일 | 상태 | 비고 |
|---|---|---|
| `tests/fixtures/login_page.html` | 저장됨 | 비로그인 페이지. 계정 문자열 없음 확인 |
| `tests/fixtures/login_redirect.html` | 해당 없음 | 302 응답이며 본문이 비어 있음 (위 설명) |
| `tests/fixtures/problem_with_attachments.html` | 저장됨 | Solving Club 문제 페이지 (`problemView.do`). 닉네임·사용자 키 치환 완료 |
| `tests/fixtures/problem_without_attachments.html` | TODO | 사용자가 로그인 후 저장 (있으면) |
| `tests/fixtures/problem_solver_page.html` | 저장됨 | (C) 문제 풀기 화면 (`solvingProblem.do`, "웹페이지, 전체" 저장). 실명·회원번호·제출 코드 치환 완료 |
| `tests/fixtures/error_page.html` | 저장됨 | 잘못된 `contestProbId` 로 `problemDetail.do` 접근 시 시스템 오류 페이지. 계정 정보 없음 (관리자 메일 `swexpert@samsung.com` 만 있음, 공개 정보) |
| `tests/fixtures/problem_detail_regular.html` | 저장됨 | 일반 `problemDetail.do` (4014). 실명·회원번호 → `DUMMY_USER`. 출제자 공개 닉네임은 유지 |

## M1 실측 과제 → M2 E2E 에서 확정 (2026-09-16, 실제 세션)

E2E: `swea-fetch -v <첨부 링크 URL> _e2e_test` (문제 `AZq-gSmq_RfHBISS`, 25730). 결과 폴더는 확인 후 삭제.

| 과제 | 결과 |
|---|---|
| `POST solvingProblem.do` 에 `categoryId` 없이 `{contestProbId, categoryType=BOX, isPostMethod=Y}` 만 보내도 되는가 | **된다.** HTTP 200, `h3.problem_title` 포함 81 KB solver 페이지 → `page_kind == "solver"`, 번호 25730 추출. `categoryId`/`probBoxId` 불필요 → §5 대응 절차 불필요, 도구 입력은 `contestProbId` 만으로 충분 |
| `contestProbDown.do` 다운로드에 추가 헤더가 필요한가 | **불필요.** 세션 쿠키 + `Referer: .../solvingProblem.do` 만으로 200, 본문은 텍스트(`3
4
0 1 2 0...`). 사용자가 브라우저로 받아 둔 `input7_sample.txt` 와 바이트 단위 동일 (출력은 끝 줄바꿈만 도구가 추가) |
| 세션 캐시 재사용 | `session.json` 복원 후 `GET userInformation.do` 200 → 재로그인 없이 진행됨 |
| 일반 (A) `problemDetail.do` 페이지 선택자 | `p.problem_title` 로 확정(4014 픽스처). 목록 위젯 폴백은 M5 에서 삭제 |

## Solving Club 색인 API (M2, 실제 세션으로 확인) — 문제 번호 → contestProbId

주소창 URL 로는 문제를 특정할 수 없으므로(모든 클럽 화면이 POST 폼 이동), 문제 번호로 찾는 경로를 마련함. `lookup.py`.

| 단계 | 요청 | 응답 |
|---|---|---|
| 내 클럽 | `POST /main/talk/solvingClub/myClubList.do`, 본문 `{}` (`Content-Type: application/json`) | `data.myClubList[] {solveclubId, title}` |
| 클럽의 문제 상자 | `POST /main/talk/solvingClub/problemBoxList.do`, `{"solveclubId", "pageIndex"}` (JSON) | `data.problemBoxList[] {probBoxId, title}`, `data.endPage`. **최신순**. form-urlencoded 로 보내면 415 |
| 상자의 문제 목록 | `GET /main/talk/solvingClub/problemBoxDetail.do?solveclubId=&probBoxId=` (GET 가능) | `div.header-caption` 마다 `input[name=checkContestProbId]`(ID), `span.week_num`(`"25730 ."`), `span.week_text a`(`[07] 항아리 게임` + 상태 badge) |

- `clubView.do?solveclubId=` 도 GET 가능 (주소창에 노출되는 유일한 ID). `problemView.do`/`solvingProblem.do` 는 POST 전용
- 일반 문제 목록 `problemList.do` 의 `problemTitle` 검색은 **번호도 매칭**(검색창 placeholder "문제 번호, 키워드"). `4014`,`1209`,`20728` 등은 여기서, `16268` 은 `userProblemList.do` 에서 찾힘. 부분 일치라 `span.week_num == "{num}."` 로 정확 매칭 필요. 클럽 전용 문제(25730, 24973, 27482, 16456)는 두 목록 모두에 없음 → 클럽 상자 스캔
- 탐색 순서(`lookup.find_by_number`): 캐시 → Problem 목록 → User Problem 목록 → 클럽 상자(최신순). 성능: 목록 검색 ≈ 0.3초/회, 상자 1개 스캔 ≈ 0.7초. 본 상자·찾은 문제는 `problem_index.json` 에 캐시

## 제출 API (M8 spike, 2026-09-17 — 풀이 화면 JS 해석 + compile.do 실측)

풀이 화면(`solvingProblem.do`)의 `onEditSubmit()` 이 하는 일 = **컴파일 → 확인창 → 제출**. 두 요청 모두 같은 파라미터, 응답은 JSON. `contextPath="/main"`.

| 단계 | 요청 | 응답 (JSON) |
|---|---|---|
| 컴파일 (부작용 없음) | `POST /main/commonCompileRun/compile.do` form: `source`, `langType`(`py`/`java`/`c`/`cpp` — select 값 `Y`→`py`), `probId`(=contestProbId), `categoryId`(hidden, 공개 문제는 빈 값), `categoryType`(`BOX`), `useOptimize=""` | `{result:"success", vo:{exitValue, cmpError, …}, submitFailed, compile}` |
| 제출 ("제출 가능 횟수 1회 감소", 문제당 99회) | `POST /main/commonCompileRun/submit.do` 같은 파라미터 | `{result, submitFailed, vo:{runValue, usrScore, timeOut, runError, testCaseNo, correctedCases, gradingResult, executionTime, …}}` — **채점 결과가 응답에 바로 옴 (폴링 불필요)** |

- 헤더: 세션 쿠키 + `X-Requested-With: XMLHttpRequest` + `Referer: …/solvingProblem.do`. CSRF 토큰 없음. 실측: compile.do 200 `application/json`.
- `vo.exitValue` (compile 단계): `"0"` 정상 / `H` 컴파일 오류(`cmpError`) / `EB` 100KB 초과 / `NS` 허용되지 않는 라이브러리 / `FI` 파일 입력 메소드 사용 / `UP` package 선언 / `SC` system call / **`NK`(JS 미처리) = `import sys` 자체를 거부** — 실측: `import sys` 한 줄만 있어도 `NK`, `cmpError="import sys"`. 주석 처리해도 거부(정규식 검사). `from collections import deque` 는 통과.
- 따라서 제출용 소스 변환 필수: `import sys` 줄과 `sys.stdin = open(...)` 줄 제거 → 그래도 `sys.` 가 남으면(`sys.stdin.readline`, `setrecursionlimit`) 제출 불가로 안내.
- `submitFailed`: `""` 정상 / `ES` 제출 횟수 소진 / `TU` 제출 시간 종료 / `AP` (미확인).
- 판정 (`processSubmit`): `vo.runError` 비어 있지 않음 → 오답(런타임 에러); `runValue` 에 `"Pass"` 포함 **and** `timeOut == ""` and `usrScore != "0"` → **Pass**; 그 외 오답 — `testCaseNo`/`correctedCases` 가 있으면 "N개 중 M개", 없으면 `usrScore / 100.0`. `timeOut != ""` 는 제한시간 초과.
- 제출 후 화면은 `solvingProblem.do` 로 다시 이동할 뿐, 별도 결과 조회 API 없음.
- 미실측: `submit.do` 의 실제 응답 (분류기가 실제 제출을 막아 사용자가 1회 실행해 확인해야 함). `AP` 의미. 언어별 `langType` 은 Python 만 확인.
