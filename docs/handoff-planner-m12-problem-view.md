# M12 구성안: 가져온 문제 지문을 "문제" 탭에서 바로 읽기

작성: planner / 상태: **사용자 승인 대기** (승인 전 개발 시작 금지) / 대상: swea_fetcher (CLI + PySide6 GUI)

## 1. 요구사항과 확정 제약

- GUI 에서 fetch 하면 곧바로 "문제" 화면으로 넘어가 지문을 바로 읽을 수 있어야 한다.
- 사용자 결정: 지문을 문제 폴더/루트에 **파일로 저장하지 않는다** (problem.md 금지). GitHub 푸시 대상이 되면 안 된다. SWEA 지문은 삼성 저작물.
- 최소 범위 우선. 실계정·실네트워크 테스트 금지 (픽스처 기반).

### 가정 (불명확한 부분은 추측하지 않고 명시)
1. "문제 탭" = 사이드바 내비에 새 항목 "문제" 를 추가한 페이지 (기존 QStackedWidget 구조에 맞춤).
2. 다시 보기(디스크 캐시)는 사용자가 명시하지 않았다. 본 문서는 P0 = 메모리 보관만, P1 = 앱 캐시 디렉터리 캐시로 나눴다. 디스크 캐시 기본값(ON/OFF)은 **승인 시 사용자가 정해야 한다** (권장: ON, 설정에서 끄기·삭제 가능. 근거는 §5).
3. 픽스처 3종은 box3/box4 구조가 같다고 메인 세션이 확인했다. 클럽 상세(page_kind="club") 는 client.fetch_problem_page 가 돌려주지 않으므로(solver|detail 만) 지문 추출 대상에서 제외한다. 파서는 kind 와 무관하게 동일 규칙을 쓴다.
4. 실제 일반 문제(4014 픽스처)의 지문 이미지는 대부분 `data:image/png;base64,...` 로 HTML 에 **인라인**되어 있다 (img 11개 중 페이지 로고 등 지문 밖 2개를 제외하면 지문 내 이미지는 data URI). 상대 URL 이미지가 나오는 경우는 예외 경로로 취급한다.

## 2. 핵심 결정 요약

| # | 결정 | 이유 |
|---|------|------|
| D1 | 지문은 어떤 파일로도 루트 아래에 쓰지 않는다. 메모리(+선택적으로 `config_dir/cache/`)에만 둔다 | 저작물 + git 푸시 방지를 "쓰지 않음" 으로 구조적으로 보장 (.gitignore 의존 X) |
| D2 | 표시는 **QTextBrowser** (QWebEngine 미도입) | PySide6 기본 포함, 추가 의존성 0. QWebEngine 은 +100MB 급, PyInstaller 배포·기동 시간 부담. 지문은 p/ul/table/img/sub/sup 수준이라 QTextBrowser 로 충분 |
| D3 | 파서에서 **허용 목록(allowlist) sanitize** + `style`/`class`/`href` 전부 제거, 이미지는 `swea-img:N` 토큰으로 치환 | 스크립트·외부 요청 원천 차단, 원문 인라인 스타일(font-family 등)이 앱 테마·다크모드를 깨는 것 방지 |
| D4 | 이미지는 data URI 디코드 → 그 외 SWEA 도메인 상대/절대 URL 만 세션으로 다운로드 (기존 `client.download`, 호스트 화이트리스트) → QTextDocument 리소스로 주입. QTextBrowser 는 네트워크를 직접 열지 않는다 | 로그인 쿠키 필요 대응 + 외부 호스트로 요청이 나가지 않음 + 이미지 실패가 fetch 실패로 번지지 않음 |
| D5 | 지문 추출은 `FetchOptions.with_content` (GUI 만 True) 로 옵트인. CLI 는 동작·네트워크 호출 변화 없음 | CLI 영향 0, 이미지 다운로드로 CLI 가 느려지지 않음 |
| D6 | 자동 전환은 저장/뼈대 성공 시. dry-run 은 지문만 로드하고 전환하지 않음. 전환 토글은 설정에 둔다 | "자동 + 설정 토글" 선호 (사용자 과거 피드백), 미리보기의 목적(저장 확인)을 방해하지 않음 |

## 3. 파서 (swea_fetcher/parser.py, models.py)

### 3.1 모델 (models.py 추가, `ProblemInfo` 는 변경하지 않음)
- `ImageRef` (frozen): `data: bytes | None`, `url: str | None` (절대 URL, 다운로드 필요 시), `alt: str`, `error: str | None`.
- `ProblemContent` (frozen): `limits_html: str` (box3, 없으면 ""), `body_html: str` (box4), `images: dict[str, ImageRef]` (키 = `swea-img:0`, `swea-img:1` …).
- `ProblemInfo` 를 건드리지 않는 이유: frozen dataclass 로 기존 테스트·`dataclasses.replace` 흐름이 있고, 지문은 수십~수 MB 라 정보 객체와 분리하는 것이 안전.
- `FetchOutcome` 에 `content: ProblemContent | None = None` 필드 추가 (기본값 있음 → 기존 생성 코드 호환).

### 3.2 추출 규칙: `parser.parse_content(html: str) -> ProblemContent | None`
1. 파서 상수 블록에 `SEL_LIMITS = "div.box3"`, `SEL_BODY = "div.box4"` 추가 (사이트 변경 시 이곳만 수정하는 기존 규약 유지).
2. `soup.select_one(SEL_BODY)` 의 내부 HTML 을 본문으로, `select_one(SEL_LIMITS)` 를 제한사항으로 취한다. 페이지 종류(solver/detail)별 분기 없음 — 픽스처 3종 모두 동일 클래스. 구현자는 각 픽스처에서 box3/box4 개수를 세어 테스트로 고정한다. 2개 이상이면 첫 번째 것을 쓰고 `log.warning` (후보가 지문 밖 영역이면 solver 는 `div.panel-body`, detail 은 `div.problem_box` 조상 범위로 한정하는 것을 구현자가 픽스처로 판단).
3. box4 가 없거나 정리 후 텍스트·이미지가 모두 비면 **`None` 반환** (예외 아님). service 가 알림 "지문 영역을 찾지 못했습니다" 를 notices 에 추가. 저장 파이프라인은 지문 실패로 중단되지 않는다. 폴백 파싱(넓은 선택자로 재시도)은 하지 않는다.
4. 제목·번호는 기존 `ProblemInfo` 것을 화면 헤더에 쓴다 (지문 HTML 에 제목을 넣지 않음).
5. `span.math-inline` 등 수식 span 은 **보이는 텍스트를 그대로 사용** (`data-math` 의 LaTeX 는 화면 텍스트와 다를 수 있음 — 픽스처에서 `4 \le N \le 500` vs 화면 `4 <= N <= 20`). 화면에 보이던 값이 정답.

### 3.3 sanitize (허용 목록, `_sanitize(tag)`)
- 먼저 통째로 제거(decompose): `script, style, iframe, object, embed, form, input, button, select, textarea, link, meta, svg, canvas, video, audio, noscript`, HTML 주석, `.hide` 클래스 요소.
- 허용 태그: `p br div span b strong i em u s sub sup ul ol li table thead tbody tfoot tr th td caption pre code blockquote hr h1..h6 img`. 그 외 태그는 **unwrap** (텍스트 보존).
- 속성: 전부 제거. 예외는 `td/th` 의 `colspan rowspan`, `img` 의 `src`(아래 치환)와 `alt`. 따라서 `on*` 핸들러·`style`(font-family "Google Sans" 등)·`class`·`href`·`data-*` 모두 사라진다.
- `<a>` 는 unwrap (링크 텍스트만 남김; 링크 열기는 P2).
- 빈 `<p>`(텍스트·img 없음) 제거, 연속 `<br>` 3개 이상은 2개로 정리. 공백·탭·개행은 HTML 규칙에 맡긴다. `pre` 안은 보존.
- 결과는 문자열로 직렬화. 원본 HTML 전체나 지문 밖 영역은 어디에도 남기지 않는다.

### 3.4 이미지 URL 절대화·치환 (`img`)
- `src` 종류별:
  - `data:image/(png|jpeg|gif|webp|bmp);base64,` → base64 디코드해 `ImageRef.data`. 디코드 실패·미지원 MIME(svg 포함)·개당 5MB 초과 → `error` 지정.
  - `http(s)://` 또는 `//` 또는 `/path` 또는 상대 경로 → `urljoin(BASE, src)`. 호스트가 `swexpertacademy.com` / `www.` 가 아니면 `error="외부 이미지 생략"` 이고 **요청하지 않는다**. (추적 픽셀·외부 서버로의 요청 방지)
  - 그 외 스킴(`file:`, `javascript:` 등) → `error`.
- 치환: 태그의 `src` 를 `swea-img:{n}` 토큰으로 바꾸고 `ImageRef` 를 `images` 에 등록. 지문당 이미지 상한 30개, 합계 20MB — 초과분은 `error`. `alt` 가 비면 "이미지 n".
- 이 단계는 **네트워크를 쓰지 않는다** (순수 함수, 픽스처 테스트 가능). 다운로드는 service 가 한다 (§4).

## 4. 서비스 (swea_fetcher/service.py)

- `FetchOptions.with_content: bool = False` 추가.
- `fetch_problem` 에서 `parser.parse(...)` 직후 `with_content` 이면:
  1. `content = parser.parse_content(html)`; None 이면 notices 에 안내.
  2. `content = _load_images(session, settings, content, progress)`: `url` 만 있고 `data` 없는 이미지를 순차로 `client.download(session, url, settings)` (호스트 화이트리스트·세션 만료 재로그인 재사용). 개별 실패는 `SweaFetchError` 를 잡아 `ImageRef.error` 에 사유를 넣고 계속 (fetch 실패 아님). 진행 메시지 `"지문 이미지 {i}/{n}"`. 받은 바이트가 이미지가 아니면(QImage 디코드 실패는 GUI 에서) error.
  3. dry-run 이 아니고 캐시 사용이 켜져 있으면(P1) 저장 단계 **전에** 캐시에 기록 (이유: 아래 §5 충돌 케이스).
- `FetchOutcome.content = content`. 지문 관련 어떤 실패도 기존 성공 경로·예외 경로를 바꾸지 않는다.
- 파일 시스템 쓰기 없음 (P0). `storage.py`, `save_problem`, `save_skeleton`, `push`/`auto_sync` 는 **수정하지 않는다** → 지문이 커밋 대상이 될 경로 자체가 없음.

## 5. 재열람과 캐시

| 단계 | 범위 |
|------|------|
| **P0** | 문제 페이지가 마지막 `ProblemContent` 를 **메모리에** 보관 → 다른 탭에 갔다 와도 유지. 앱 종료 시 사라짐. 디스크에 아무것도 쓰지 않음 |
| **P1** | 디스크 캐시 (사용자 승인 필요). 위치: `{settings.config_dir}/cache/statements/{num}.json` (기본 `~/.swea-fetch/cache/...`, 루트 폴더 밖). 내용: num, topic, title, fetched_at, `limits_html`, `body_html`, 이미지(base64). 최근 50건 LRU (mtime 기준 초과분 삭제). `Settings.cache_dir` 프로퍼티 추가 (config.py). **가드**: `cache_dir` 가 `settings.root` 안이면(`resolve()` 후 `relative_to` 성립) 쓰지 않고 경고 로그 |
| P1 | "최근" 페이지 항목 우클릭/버튼에 **[문제 보기]** — **캐시만** 읽는다 (네트워크 없음). 캐시가 없으면 항목을 비활성 처리하고 툴팁 "저장 탭에서 다시 가져오면 볼 수 있습니다". 저장된 문제 폴더 스캔으로 지문을 복원하려는 시도는 하지 않는다 (지문이 폴더에 없으므로 불가) |
| P1 | 저장 실패가 "이미 저장된 파일" 충돌일 때, 지문은 이미 캐시에 있으므로 배너에 [문제 보기] 조치 추가. (캐시 OFF 면 조치 없음.) 재가져오기로 읽기만 하려는 흔한 시나리오 대응 |
| P1 | 설정 페이지: 체크박스 "지문 캐시 사용", 버튼 [캐시 지우기]. `logout --all` 에서도 `cache/` 삭제 |
| P2 | 캐시 만료 기간, 검색, 지문 내 링크 열기 |

캐시 ON 권장 근거: 지문은 앱 사용자 본인의 로컬 홈 디렉터리(`~/.swea-fetch`)에만 있고 git 과 무관하며, 없으면 저장 후 지문을 다시 읽을 방법이 SWEA 사이트뿐이다. 다만 저작물의 로컬 보관이므로 사용자가 OFF 를 택할 수 있어야 한다.

## 6. GUI

### 6.1 내비와 페이지
- 새 파일 `gui/pages/problem_page.py` 의 `ProblemPage(QWidget)`. `objectName("page")`, 기존 페이지와 같은 여백(`SPACE*3`)·`title` 클래스 헤더.
- `PAGES` 를 `저장, 문제, 검증, 최근, 설정` 순으로 변경 (문제 = key `"problem"`, 아이콘 `nav-problem` 신규). 단축키 `Ctrl+1..5` (`range(4)` 하드코딩 → `len(PAGES)`), `Ctrl+,` 유지.
- **주의 (회귀 위험)**: `window/last_page` 가 행 번호로 저장돼 있어 순서 변경 시 복원 페이지가 어긋난다 → `window/last_page_key` (key 문자열) 로 저장하고, 옛 값은 읽기만 하고 무시(기본 fetch).
- `main_window` 연결: `fetch_page.problem_ready` → `problem_page.show_outcome(outcome)`; 자동 전환이면 `goto("problem")`. `problem_page.status_message`, `goto_requested` 를 기존 페이지와 동일하게 연결. `set_settings` 도 다른 페이지처럼 전달.

### 6.2 문제 페이지 구성
- 헤더: 제목 `"{num}. {title}"` (class `title`), 오른쪽에 배지 (`저장됨` success / `미리보기 — 저장 안 됨` idle / `캐시` idle), 그 아래 hint 한 줄 (주제·저장 경로 ElidedLabel).
- 버튼 줄: [폴더 열기] [PyCharm 에서 열기] (저장 성공 시에만 표시, 기존 fetch_page 의 `open_in_explorer`/`open_with_default_app` 재사용) · [글자 −] [글자 +] (QTextBrowser zoom, 값은 QSettings `problem/zoom`).
- 본문: `QFrame[class="card"]` 안 **QTextBrowser 서브클래스 `_StatementBrowser`**. 위쪽에 제한사항(limits_html)을 구분선과 함께, 아래에 본문. 스크롤은 브라우저 자체 (페이지 QScrollArea 로 감싸지 않음 — 이중 스크롤 방지).
- 하단 hint: "지문은 파일로 저장되지 않습니다 (앱 캐시 사용 시 `~/.swea-fetch/cache`)". 캐시 OFF 면 앞부분만.
- 빈 상태: 기존 `empty-title` / `empty-body` 클래스 — "아직 가져온 문제가 없습니다 / 저장 탭에서 문제를 가져오면 지문이 여기에 표시됩니다".
- 이미지 실패가 있으면 상단에 `Banner("info", "이미지 n개를 불러오지 못했습니다", ...)`; 본문에는 자리표시 텍스트 "[이미지 불러오기 실패: 사유]".
- 지문 없음(`content is None`, 파싱 실패): 빈 상태 대신 warning 배너 "지문 영역을 찾지 못했습니다" + [저장 탭으로] 조치.

### 6.3 `_StatementBrowser` 보안·렌더링 규칙
- `setOpenLinks(False)`, `setOpenExternalLinks(False)`, `setReadOnly(True)`; `loadResource` 를 오버라이드해 `swea-img:` 토큰 외 모든 리소스(file/http/qrc 포함)를 `None` 반환 → 로컬 파일 읽기·네트워크 접근 불가.
- 이미지 주입: 워커가 아닌 **UI 스레드**에서 `QImage.loadFromData(bytes)` → `document().addResource(QTextDocument.ImageResource, QUrl(token), image)`. 디코드 실패 시 자리표시.
- 너비 맞춤: QTextBrowser 는 큰 이미지를 자동 축소하지 않는다. 렌더 시 각 `<img>` 에 `width` 를 `min(원본 폭, 뷰포트 폭 − 여백)` 로 부여해 HTML 을 다시 세팅하고, `resizeEvent` 에서 100ms 디바운스로 갱신 (스크롤 위치 보존).
- 스타일: `document().setDefaultStyleSheet(build_statement_css(palette))`. 이 함수는 `tokens.LIGHT`(=활성 팔레트) 필드만 사용 — `text`, `text_2`, `border`, `surface_alt`, `FONT_FAMILY`, `FONT_MONO`, `FONT_SIZE`. 위젯·CSS 에 색상 리터럴 금지 (tokens 규약). `pre/code` 는 `FONT_MONO` + `surface_alt` 배경, `table/td` 는 `border`. 다크 팔레트(`tokens.DARK`)가 채워지면 `build_qss(DARK)` 와 함께 CSS 도 같은 Palette 로 재생성되도록 `apply_palette(p)` 메서드를 둔다 (현재 다크는 스펙상 범위 밖이므로 라이트만 검증). 투명 배경 PNG 는 다크에서 안 보일 수 있음 → 이미지 뒤에 `surface` 배경을 깔지 않고, 다크 도입 시점에 재검토 (검토 노트).
- 위젯 기본 스타일: 기존 QSS 의 `QTextEdit` 규칙이 QTextBrowser 에 적용되므로 별도 QSS 추가 최소 (디자이너가 확인).

### 6.4 fetch_page 변경과 상황별 동작
- `FetchPage` 에 `problem_ready = Signal(object)` (FetchOutcome) 추가. `start()` 의 옵션에 `with_content=True` 세팅 (`_rerun` 은 `FetchOptions(**opts.__dict__...)` 로 필드를 그대로 이어받으므로 자동 전파).
- `_on_done` 마지막에 `outcome.content is not None` 이면 `problem_ready.emit(outcome)`.
- 자동 전환은 `MainWindow` 가 결정: 아래 표. 설정 토글 QSettings `fetch/auto_open_problem` (기본 True), 설정 페이지에 체크박스 "저장 후 문제 탭으로 이동".

| 상황 | 문제 페이지 | 자동 전환 |
|------|-------------|-----------|
| 저장 성공 | 지문 표시, 배지 `저장됨`, 폴더/PyCharm 버튼 | 예 (토글 ON) |
| 뼈대만(skeleton-only) 성공 | 동일 (샘플 첨부 없는 문제에서 특히 유용) | 예 |
| 미리보기(dry-run) | 지문 로드, 배지 `미리보기 — 저장 안 됨`, 폴더 버튼 숨김. 캐시 기록 안 함 (메모리만) | **아니오**. 결과 카드에 [문제 보기] 버튼 추가 (클릭 시 이동) |
| 실패 (네트워크·로그인·첨부 없음 등) | 이전 내용 유지 | 아니오 (기존 배너 그대로) |
| 실패 = "이미 저장된 파일" 충돌 | (P0) 변경 없음 / (P1) 캐시에 지문이 있으므로 배너에 [문제 보기] 조치 | 아니오 |
| 지문 추출 실패(None) | warning 배너 | 아니오, 저장 결과 카드 + 알림 배너에 안내 |
- 전환 후 포커스: 문제 브라우저 (키보드 스크롤). `_page_changed("fetch")` 의 target 포커스 로직은 유지.
- 저장 완료 상태바 메시지는 유지. 기존 `saved` → history 갱신은 그대로.

## 7. CLI 영향
- **없음.** `FetchOptions.with_content` 기본 False → 지문 파싱·이미지 다운로드·캐시 쓰기 모두 수행하지 않음. CLI 출력·종료 코드 불변. 새 플래그를 추가하지 않는다. (원하면 P2 로 `swea show <번호>` 를 캐시 기반으로 검토.)

## 8. 변경 파일

| 파일 | 변경 |
|------|------|
| `swea_fetcher/models.py` | `ImageRef`, `ProblemContent` 추가 |
| `swea_fetcher/parser.py` | `SEL_LIMITS/SEL_BODY`, `parse_content`, `_sanitize`, 이미지 치환 |
| `swea_fetcher/service.py` | `FetchOptions.with_content`, `FetchOutcome.content`, `_load_images`, (P1) 캐시 기록·조회 함수 |
| `swea_fetcher/config.py` | (P1) `Settings.cache_dir` 프로퍼티, 캐시 사용 여부 키 |
| `swea_fetcher/gui/pages/problem_page.py` | 신규 |
| `swea_fetcher/gui/pages/fetch_page.py` | `problem_ready` 시그널, `with_content=True`, dry-run 카드의 [문제 보기] |
| `swea_fetcher/gui/main_window.py` | PAGES 5개, 단축키, last_page_key, 연결, 자동 전환 |
| `swea_fetcher/gui/pages/settings_page.py` | 자동 전환 토글, (P1) 캐시 토글·삭제 |
| `swea_fetcher/gui/pages/history_page.py` | (P1) [문제 보기] |
| `swea_fetcher/gui/widgets/` | `nav-problem` 아이콘 |
| `swea_fetcher/gui/theme/tokens.py` | 원칙적으로 변경 없음 (필요 시 CSS 빌더만 theme 아래 새 함수) |
| `design/design-spec.md` | 문제 페이지 절 추가 (디자이너) |
| `docs/swea-page-notes.md` | box3/box4 구조·data URI 이미지 사실 추가 |
| `tests/…` | §10 |
| **수정 금지** | `storage.py`, `gitops.py`, `submit.py`, `auth.py`, `client.py`(다운로드는 기존 함수 재사용) |

## 9. 역할 분담

| 역할 키워드 | 담당 범위 | 산출물 경로 | 인터페이스 |
|-------------|-----------|-------------|------------|
| `core-builder` | 모델, `parse_content`, sanitize, `_load_images`, `FetchOptions/Outcome`, (P1) 캐시·`cache_dir` | models.py, parser.py, service.py, config.py, tests/test_parser_content.py, tests/test_service_content.py | GUI 에 `FetchOutcome.content: ProblemContent \| None` 제공. 데이터 계약은 §3.1 |
| `gui-builder` | ProblemPage, fetch_page/main_window/settings/history 연결, `_StatementBrowser`, 이미지 주입·너비 맞춤 | gui/pages/problem_page.py 외 gui 하위 | `ProblemContent` 소비. 색·간격은 tokens 만. 디자인 스펙 §문제 페이지 준수 |
| `designer` | design-spec 문제 페이지 절, `nav-problem` 아이콘, 지문 CSS 값(제목/표/코드 간격), 빈 상태 문구 | design/design-spec.md, gui/widgets 아이콘 자산 | gui-builder 에 토큰 매핑 표 전달. 색상 리터럴 금지 |
| `tester` | 픽스처 기반 단위·GUI 테스트, 루트 무변경 검증 | tests/ | §10 목록. 실네트워크·실계정 금지 (client.download 는 monkeypatch) |
| `planner`/메인 | 사용자 승인, 캐시 기본값 확인, 통합 검토 | docs/ | — |

작업 순서: core-builder(계약 고정) → designer 와 gui-builder 병렬 → tester. 계약(§3.1)이 바뀌면 core-builder 가 먼저 문서 갱신.

## 10. 수용 기준과 테스트

### 수용 기준
1. GUI 에서 저장(또는 뼈대만) 성공 시 토글 ON 이면 자동으로 "문제" 탭이 열리고 지문·제한사항이 보인다. 화면에 원문 인라인 스타일(글꼴·색)이 남지 않는다.
2. 저장 전후로 **루트 폴더 트리가 input.txt/output.txt/{num}.py 외에 아무 파일도 늘지 않는다**. `git status` 에 지문 관련 항목이 없다.
3. dry-run 은 전환하지 않고 [문제 보기] 로 이동 가능하며 디스크에 쓰지 않는다.
4. 이미지 다운로드·디코드 실패가 fetch 성공/실패를 바꾸지 않는다.
5. 허용 목록 외 태그·속성·스킴이 결과 HTML 에 없다. QTextBrowser 가 file/http 리소스를 로드하지 않는다.
6. CLI 의 `fetch` 출력·종료 코드·네트워크 호출 횟수가 M11 과 동일하다.
7. (P1) 캐시 파일은 `config_dir/cache` 아래에만 생기며 root 안이면 쓰지 않는다. 50건 초과 시 오래된 것부터 삭제.
8. 기존 테스트 전부 통과 (특히 내비 인덱스·last_page 관련 GUI 테스트는 key 기반으로 갱신).

### 테스트 (모두 픽스처·monkeypatch 기반)
- parser: 3종 픽스처에서 `parse_content` 가 box3/box4 를 추출 (제한사항 텍스트 "1초", "256MB" 포함, 지문 첫 문장 포함). box4 없는 HTML → None. 오류 페이지 픽스처(error_page.html) → None.
- sanitize: 주입 케이스 문자열 — `<script>`, `onerror=`, `<iframe>`, `style="…"`, `<a href="javascript:…">`, `<svg onload>`, 주석 → 결과에 없음. 수식 span 은 화면 텍스트 유지 (`4 <= N <= 20`). 빈 `<p>` 제거.
- 이미지: 4014 픽스처의 data URI 이미지 → `ImageRef.data` 가 PNG 시그니처로 시작, 토큰 치환. 상대 URL → 절대화. 외부 호스트 → error 및 다운로드 미호출. `file:`/`javascript:` → error. 5MB 초과·개수 상한. 깨진 base64 → error, 예외 없음.
- service: `client.download` monkeypatch 로 성공/`NetworkError`/HTML 응답(SessionExpired) → 개별 error 로 남고 `fetch_problem` 은 정상 반환. `with_content=False` 이면 `parse_content`·download 호출 없음 (CLI 회귀). dry-run 시 `tmp_path` 트리 무변경. 저장 성공 시 root 트리 파일 목록이 기존과 동일 (지문 관련 신규 파일 없음).
- (P1) 캐시: `config_dir/cache` 에만 생성, root 내부 `cache_dir` 는 쓰기 거부, 51번째 저장 시 가장 오래된 것 삭제, dry-run 은 미기록, 손상된 캐시 JSON → 무시하고 없음 처리.
- GUI (offscreen): 저장 성공 outcome 주입 → 문제 페이지 current, `_StatementBrowser.toPlainText()` 에 지문 포함. dry-run → 전환 없음 + [문제 보기] 노출. 실패 → 이전 내용 유지. 토글 OFF → 전환 없음. 빈 상태 문구. `loadResource` 가 http/file URL 에 None. 이미지 리소스 등록 후 `document().resource(...)` 존재. `Ctrl+2` 가 문제 탭, last_page_key 저장·복원.
- 보안 회귀: 코드 grep 테스트 — `problem.md` 등 지문 파일 쓰기가 storage 에 없음 (storage 의 쓰기 파일명 집합이 기존과 동일).

## 11. 마일스톤

| 단계 | 내용 | 산출물 |
|------|------|--------|
| M12-a (P0 코어) | 모델·`parse_content`·sanitize·이미지 치환·`with_content`·`_load_images` + 단위 테스트 | 파서/서비스 테스트 통과 |
| M12-b (P0 GUI) | ProblemPage, 내비 5개, 자동 전환·토글, dry-run [문제 보기], 디자인 스펙 절 | GUI offscreen 테스트, 수동 확인 |
| M12-c (실측) | 사용자가 `init` 된 환경에서 실계정으로 실제 문제 1~2건 확인 (builder 는 실계정 사용 금지 원칙 유지 → 사용자 실행 후 결과 공유) | swea-page-notes 갱신 |
| M12-d (P1) | 디스크 캐시, 최근 목록 [문제 보기], 충돌 배너 조치, 캐시 삭제 UI | 캐시 테스트 |

## 12. 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| 저작물이 실수로 저장소에 올라감 | 지문을 root 에 쓰는 코드 자체가 없음. 캐시는 `~/.swea-fetch` 밖으로 안 나가고 root 안이면 쓰기 거부. 회귀 테스트 |
| QTextBrowser 가 일부 HTML/CSS 를 못 그림 | sanitize 가 스타일을 제거하고 단순 태그만 남기므로 위험 낮음. 표가 넓으면 가로 스크롤. 심각하면 P2 로 QWebEngine 재검토 (의존성 부담 감수 시) |
| 큰 base64 이미지로 메모리·지연 | 개당 5MB·합계 20MB·30개 상한, 디코드는 1회 |
| 이미지 다운로드로 fetch 가 느려짐 | 대부분 data URI 라 네트워크 0. 순차 15초 타임아웃 → 최악 지연은 상한 30개 기준으로 길 수 있으므로 원격 이미지는 개수 10개로 별도 제한하고 초과분은 자리표시 (구현자 판단으로 조정 가능) |
| 사이트 구조 변경 (box3/box4 이름) | 선택자를 파서 상수에 모으고, None 반환 + 안내로 저장은 계속 |
| 내비 순서 변경으로 저장된 last_page 어긋남 | key 기반 저장으로 전환 |
| 다크모드 도입 시 투명 PNG·CSS | CSS 를 Palette 로 생성, 다크 도입 시 디자이너가 이미지 대비 재검토 |
| 수식 표현 한계 (LaTeX 원문 아님) | 화면 텍스트 사용으로 일관, 렌더링은 범위 밖 |

## 13. 검토 노트 (자기검토)

- 누락 점검: 보안(sanitize·리소스 로더 차단·호스트 화이트리스트), 에러 처리(지문 실패 비치명), 로깅(warning/debug), 테스트, 배포(의존성 추가 없음) 반영. 인증은 기존 세션 재사용.
- 과설계 점검: QWebEngine·별도 마크다운 변환·지문 저장소·CLI 플래그를 배제. 디스크 캐시와 최근 목록 재열람은 P1 로 분리해 P0 만으로 요구가 충족되게 함.
- 남은 우려:
  1. **디스크 캐시 기본값**은 사용자 결정 사항 (저작물의 로컬 보관 여부).
  2. box3/box4 가 페이지 내에 복수로 존재하는지는 픽스처 계수 테스트로 구현 시 확정 (문서에서는 첫 번째 사용으로 가정).
  3. 클럽 상세 페이지는 현재 fetch 경로에 없어 검증하지 않음.
  4. 원격(상대 URL) 이미지가 실제로 로그인 쿠키를 요구하는지는 실측(M12-c) 전까지 미확인. 실패해도 자리표시로 안전.
  5. QTextBrowser 의 표 렌더링 품질은 실제 문제로 눈으로 확인 필요.
