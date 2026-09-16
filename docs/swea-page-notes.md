# SWEA 페이지 구조 조사 노트 (M0 spike)

조사일: 2026-09-16. 기준 호스트 `https://swexpertacademy.com`.
비로그인 관찰은 `requests` 로 직접 확인함. 로그인 후 페이지는 사용자가 브라우저에서 저장해 준 HTML(Solving Club 문제 페이지 1건)로 확인함. 남은 `TODO` 는 일반 `problemDetail.do` 페이지 확인 건.

## 로그인

- **판정: (a) requests 폼 POST 로 가능** (JS 암호화·CSRF 토큰·캡차 없음. 단, 계정에 MFA 가 걸려 있으면 (b) 또는 수동 세션 주입 필요 — 사용자 계정 1회 로그인으로 확인 필요)
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

SWEA 에는 문제 페이지가 **두 종류** 있고, 사용자의 실제 사용 경로는 (B) Solving Club 이다.

| | (A) 일반 문제 | (B) Solving Club 문제 (SSAFY 모의고사 등) |
|---|---|---|
| URL | `GET /main/code/problem/problemDetail.do?contestProbId={id}` | `POST /main/talk/solvingClub/problemView.do` (hidden form `solveclubId`, `probBoxId`, `contestProbId`) — 주소창에는 파라미터가 안 보임 |
| 확인 상태 | 비로그인 302 만 확인. 로그인 후 구조 **TODO** | 픽스처 확보 (`problem_with_attachments.html`) |

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

### (A) 일반 문제 페이지 (TODO)
- 공개 목록 페이지 `/main/code/problem/problemList.do` 는 비로그인 200 이며 각 문제가
  ```html
  <div class="header-caption">
    <span class="week_num">27008.</span>
    <span class="week_text"><a href="#none" onclick="javascript:fn_move_page('AZ8R9tAKeaPHBITH');">A+B…</a></span>
  </div>
  ```
  → 상세 페이지도 같은 위젯이면 `span.week_num` / `span.week_text` 가 후보
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

- A1-1: **확정(조건부)** — ID/PW 를 평문 form-urlencoded 로 `login.do` 에 POST 하면 JSON 으로 결과가 온다. 캡차·CSRF·JS 암호화 없음. 예외는 계정 단위 MFA(`message == "mfa"`) — 사용자 계정으로 1회 확인 필요. → `auth` 는 requests 만으로 구현, Playwright 불필요
- A2: **부분 확정 → 수정 필요** — 첨부는 `div.down_area a[href*=contestProbDown.do]` 로 존재하고 `downType=in|out` 으로 입·출력이 구분된다. 단 **파일명은 `sample_input.txt` 고정이 아니라 `input7_sample.txt` 처럼 가변** → 파서는 파일명이 아니라 `downType` 으로 판별. 첨부 없는 문제의 형태는 미확인
- A3: **불성립 (Solving Club 페이지)** — 제목은 `p.problem_title` 의 `"[07] 항아리 게임"` 이며 `[07]` 은 상자 내 순번. SWEA 문제 번호는 페이지에 없음. → 번호는 (1) 일반 `problemDetail.do` 페이지에서 얻거나 (2) `--num` 옵션으로 사용자가 지정해야 함. 일반 페이지의 번호 노출 여부는 TODO

## 픽스처

| 파일 | 상태 | 비고 |
|---|---|---|
| `tests/fixtures/login_page.html` | 저장됨 | 비로그인 페이지. 계정 문자열 없음 확인 |
| `tests/fixtures/login_redirect.html` | 해당 없음 | 302 응답이며 본문이 비어 있음 (위 설명) |
| `tests/fixtures/problem_with_attachments.html` | 저장됨 | Solving Club 문제 페이지 (`problemView.do`). 닉네임·사용자 키 치환 완료 |
| `tests/fixtures/problem_without_attachments.html` | TODO | 사용자가 로그인 후 저장 (있으면) |
| `tests/fixtures/error_page.html` | 저장됨 | 잘못된 `contestProbId` 로 `problemDetail.do` 접근 시 시스템 오류 페이지. 계정 정보 없음 (관리자 메일 `swexpert@samsung.com` 만 있음, 공개 정보) |
| `tests/fixtures/problem_detail_regular.html` | TODO | 일반 `problemDetail.do` 페이지 (번호 노출 확인용) — 일반 문제(예: 목록의 `27008`)로 열어야 함 |
