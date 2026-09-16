# SWEA 페이지 구조 조사 노트 (M0 spike)

조사일: 2026-09-16. 기준 호스트 `https://swexpertacademy.com`.
비로그인 관찰은 `requests` 로 직접 확인함. **로그인 후 문제 상세 페이지 항목은 사용자가 저장해 준 HTML 로 채울 예정 (아래 `TODO` 표시)**.

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

- URL: `/main/code/problem/problemDetail.do?contestProbId={id}` (`id` 는 `AWXRDL1qsNMDFAX3` 같은 16자 영숫자, 문제 번호와 무관)
- 비로그인 접근: **302 → `http://swexpertacademy.com/main/identity/anonymous/loginPage.do`** (본문 0 byte, 이후 301 로 https 로 승격). 빈 페이지가 아니라 리다이렉트이므로 `login_redirect.html` 픽스처는 따로 없음 (302 응답 헤더만 의미 있음)
- 번호·제목 선택자 (**TODO: 로그인 후 상세 페이지 HTML 로 확정**)
  - 참고: 공개 목록 페이지 `/main/code/problem/problemList.do` 는 비로그인으로도 200 이며 각 문제가
    ```html
    <div class="header-caption">
      <span class="week_num">27008.</span>
      <span class="week_text"><a href="#none" onclick="javascript:fn_move_page('AZ8R9tAKeaPHBITH');">A+B…</a></span>
    </div>
    ```
    형태 → 상세 페이지도 같은 위젯을 쓰면 `span.week_num` / `span.week_text` 가 후보. 목록 이동은 `searchForm` 을 `contestProbId`, `categoryId`, `categoryType=CODE` 로 POST 하지만 GET 쿼리스트링으로도 동작함(302 로 확인)
- 첨부 링크 선택자, href 패턴: **TODO** (로그인 필요)
- 첨부 없는 경우 특징: **TODO** (로그인 필요)

## 요청 조건

- `User-Agent` 없이도 로그인 페이지 200 (61KB). 단 브라우저 UA 를 붙여 두는 편이 안전
- `Referer` 불필요 (비로그인 범위에서 확인). 로그인 POST 는 브라우저와 같게 `Referer: .../loginPage.do`, `X-Requested-With: XMLHttpRequest` 를 붙일 것
- 봇 차단·캡차: 로그인 페이지에 없음. Cloudflare 류 챌린지 없음 (requests 로 바로 200)
- 응답 인코딩: `Content-Type` 에 charset 이 없어 requests 가 ISO-8859-1 로 추정함 → **`r.encoding = "utf-8"` 강제 필요** (meta charset 은 UTF-8)

## 확정된 가정

- A1-1: **확정(조건부)** — ID/PW 를 평문 form-urlencoded 로 `login.do` 에 POST 하면 JSON 으로 결과가 온다. 캡차·CSRF·JS 암호화 없음. 예외는 계정 단위 MFA(`message == "mfa"`) — 사용자 계정으로 1회 확인 필요. → `auth` 는 requests 만으로 구현, Playwright 불필요
- A2: **미확정 (TODO)** — 로그인 후 상세 페이지 HTML 필요
- A3: **부분 확정** — 목록 페이지에서는 `span.week_num` 에 `"27008."` 형태로 번호가, `span.week_text` 에 제목이 노출됨. 상세 페이지의 동일 구조 여부는 TODO

## 픽스처

| 파일 | 상태 | 비고 |
|---|---|---|
| `tests/fixtures/login_page.html` | 저장됨 | 비로그인 페이지. 계정 문자열 없음 확인 |
| `tests/fixtures/login_redirect.html` | 해당 없음 | 302 응답이며 본문이 비어 있음 (위 설명) |
| `tests/fixtures/problem_with_attachments.html` | TODO | 사용자가 로그인 후 저장 |
| `tests/fixtures/problem_without_attachments.html` | TODO | 사용자가 로그인 후 저장 (있으면) |
