# designer → builder 전달 (M4 GUI 정합성 검토 결과, 2026-09-17)

대상: `swea_fetcher/gui/` (v0.3.1). 검토 기준 `design/design-spec.md` (오늘 §2.2·5.8·5.9·5.10·6.1·6.2·6.4·9·10·15 갱신 — 아래 항목과 1:1). 사용자 승인 완료.

**판정: Critical 0. Warning 6건 수정 후 M4 종료 조건 "스펙과 구현 일치" 충족.** 대체안 8건은 전부 승인 (조건 2개는 W3·W4 에 포함). Suggestion 8건은 builder 판단.

## 수정 요청 (Warning)

| # | 파일:라인 | 문제 | 수정 방향 | 확인 |
|---|---|---|---|---|
| W1 | `widgets/__init__.py:281` `fetch_page.py:336-343` `widgets/__init__.py:342-343` | mono 영역에 한글 문장이 들어가 Consolas 폴백으로 글자가 작게 렌더됨 (캡처 3a·3b·4). 글꼴 문제가 아니라 배치 문제 — D2Coding 번들 **안 함** | ① `QPlainTextEdit#log` 글꼴을 `FONT_FAMILY` sm 로 (`tokens.build_qss`), 타임스탬프만 `<span style='font-family:{FONT_MONO}'>` ② 결과 카드 파일 행: 파일명·크기·원본 파일명은 mono, `원본 …`/`뼈대 생성`/`빈 파일`/`기존 파일 유지` 는 `_badge_html` 처럼 `FONT_FAMILY` span ③ DiffView 빈 값 `"(없음)"` → `"—"` | 캡처 3a·3b·4 재생성 |
| W2 | `check_page.py:82,89` | 720 폭에서 검증 폼 행1 이 넘침: 가용 492px < 콤보 200 + 번호 120 + 버튼 96 + 레이블·간격 ≈ 504px. `setMinimumWidth(200)` 이 하드 제약 | 콤보 최소 160 + 번호 100 으로 줄이거나, 페이지 `resizeEvent` 에서 너비 < 880 이면 [실행] 을 행2 로 (스펙 §6.2·§11) | 720×480 실창에서 4페이지 전환 — 잘림·가로 스크롤 없음 |
| W3 | `widgets/__init__.py:327-328` | DiffView `NoSelection`+`NoFocus` 로 텍스트 복사 불가 (스펙 §10 위반). 델리게이트가 이미 `State_Selected` 를 지우므로 `NoSelection` 은 diff 색 보호에 불필요 | `ExtendedSelection` + `StrongFocus` 복원. `_BackgroundDelegate.paint` 에서 선택 행은 `option.rect` 왼쪽 2px 를 `p.primary` 로 채워 표시. `keyPressEvent` Ctrl+C = 선택 행의 "실제" 열 텍스트를 줄바꿈으로 이어 클립보드 | 실패 diff 에서 행 클릭 → 파란 세로선, Ctrl+C → 붙여넣기 확인 |
| W4 | `theme/tokens.py:118` | `QListWidget#nav { outline: 0 }` 이 Fusion 점선 포커스까지 지워 Tab 으로 내비에 들어가도 포커스 위치가 안 보임 | `#nav` 셀렉터에서 `outline: 0` 만 제거 (다른 규칙 유지). 최근 테이블은 선택 행 배경이 포커스 역할이라 그대로 | Tab 으로 내비 진입 시 점선 표시 |
| W5 | `settings_page.py:157-160` | QSpinBox 스핀 버튼이 `min/max-height` 에 눌려 깨져 보임 (캡처 1·2) | `self.timeout.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)` — 타이핑·방향키로 충분 (스펙 §6.4) | 캡처 1 재생성 |
| W6 | `fetch_page.py:153-156,327` (+ `main_window.py:171`) | 결과 카드 경로 `QLabel` 이 텍스트 길이만큼 최소 너비를 요구 → 긴 루트 경로에서 `QScrollArea` 가로 스크롤 발생 | `card_path.setSizePolicy(Ignored, Fixed)`, 원문은 멤버에 보관하고 `resizeEvent` 에서 `fontMetrics().elidedText(text, ElideMiddle, width())` 로 표시. 툴팁 = 전체 경로. 상태바 우측(글자 수 자르기)도 같은 방식으로 통일 | 루트를 60자 이상 경로로 설정 후 저장 → 가로 스크롤바 없음, 툴팁에 전체 경로 |

## 선택 (Suggestion) — 여유 있을 때

- S1 `history_page.py:68` 헤더 왼쪽 정렬(`setDefaultAlignment`), 번호 열만 가운데
- S2 `settings_page.py:82` 첫 실행 시 `~/Desktop/swea` 가 있으면 **값으로** 채움, 없으면 플레이스홀더 `예: C:\Users\<you>\Desktop\swea`
- S3 `fetch_page.py:219-224` Esc: 배너 `isVisible()` 이면 배너 닫기, 아니면 로그 지우기 (`hasFocus()` 는 QFrame 이라 항상 False)
- S4 도움말 문장은 `hint`(text_3), 폼 레이블은 `muted`(text_2) — `fetch_page.py:66,96` `settings_page.py:120,132` `check_page.py:108`
- S5 `_set_busy(True)` 에서 `self.setFocus()` — 입력 disable 시 포커스가 로그 토글로 튀는 것 방지
- S6 `check_page.py:107,156` 힌트 문구 "또는 .py 파일이나 {번호} 폴더를 이 창에 끌어다 놓으세요 · …"
- S7 `app.py:30` `_builder_supplement` 를 `build_qss` 로 합쳐 QSS 소스 단일화
- S8 (수정 불필요) 미리보기 상태의 primary 2개는 스펙을 구현에 맞춰 완화함

## 완료 기준

1. W1~W6 반영 후 `docs/gui-screenshots/` 재생성 (1, 3a, 3b, 4 가 바뀜) → 디자이너 재확인 1회 (캡처만으로 W1·W5 확인)
2. 720×480 실창 확인 결과(W2·W3·W4·W6)는 한 줄씩 이 문서에 회신
3. 스펙 §15 대체안 목록에 새 항목이 생기면 추가 (현재 8건은 승인 표기 완료)

## 참고

- 색·간격·글꼴 변경은 `tokens.py` 만 — 위젯 코드에 색상값 리터럴 금지는 그대로
- 스펙 갱신분 요약: mono 에 한글 금지(§2.2), 로그 UI 글꼴(§5.8), diff 선택선(§5.9), 파일 행 `[생성]` 표기·경로 elide(§5.10), 폴더 드롭·오드롭 배너(§6.2), 스핀 버튼 없음(§6.4), 조치 버튼 키 7종(§9), Esc 순서·`#nav` outline(§10)

---

## builder 회신 (2026-09-17, 커밋 참조는 아래 git log)

**Warning 6건 전부 반영. 캡처 9장 재생성 (`docs/gui-screenshots/`). 470 테스트 통과.**

| # | 반영 | 확인 결과 |
|---|---|---|
| W1 | `tokens.build_qss` 의 `#log` 를 UI 글꼴 sm 으로, `LogView.append` 는 타임스탬프만 mono span. 결과 카드 파일 행의 한글 설명(`원본`, `뼈대 생성`, `빈 파일`, `기존 파일 유지`)은 `_ui()` 헬퍼로 UI 글꼴 span. DiffView 빈 값 `"—"` | 캡처 3a·3b·4: 한글이 맑은 고딕 크기로 렌더 |
| W2 | 콤보 최소 160, 번호 100 + `CheckPage.resizeEvent` 에서 페이지 너비 < 700(= 창 < ~850) 이면 [실행] 을 행2 로. 힌트/오류 라벨은 행2·3 으로 이동 | 창 720 → 행2, 880·1000 → 행1 (offscreen 실측). 가로 스크롤 없음 |
| W3 | `ExtendedSelection` + `StrongFocus` 복원. 델리게이트가 선택 행 왼쪽 2px `primary` 세로선. `keyPressEvent` Ctrl+C = 선택 행 "실제" 열 텍스트(`—` 제외) 줄바꿈 연결 | 2·4행 선택 후 Ctrl+C → 클립보드 `"c\ne"` |
| W4 | `#nav` 에서 `outline: 0` 제거 (다른 규칙 유지) | `build_qss()` 의 `#nav` 규칙에 outline 없음 |
| W5 | `QSpinBox.setButtonSymbols(NoButtons)` | 캡처 1: 스핀 버튼 없음 |
| W6 | `widgets.ElidedLabel`(Ignored 가로 정책 + `elidedText(ElideMiddle)` + 툴팁 전문) 을 결과 카드 경로에 적용. 상태바 우측은 permanent 위젯이 Ignored 정책에서 0폭으로 눌려 **고정폭 360 elide** 로 통일 (같은 `elidedText` 방식) | 70자 루트로 저장 → 가로 스크롤바 없음, 상태바 `…` 생략 + 툴팁 전문 |

**Suggestion 반영**: S1 헤더 왼쪽 정렬(번호 열만 가운데) · S2 첫 실행 시 `~/Desktop/swea` 존재하면 값으로, 없으면 플레이스홀더 `예: C:\Users\<you>\Desktop\swea` · S3 Esc = 배너 보이면 닫기, 아니면 로그 지우기 · S4 도움말 5곳 `hint` 로 · S5 `_set_busy(True)` 에서 `self.setFocus()` (저장·검증 페이지) · S6 힌트 문구 갱신 · S7 `_builder_supplement` 를 `build_qss` 끝에 병합하고 `app.py` 에서 제거, 미사용 `theme.qss` 삭제 · S8 변경 없음.

**스펙 §15 추가 항목**: 없음 (W6 상태바만 "고정폭 360 elide" 로 구현했음을 §3 상태바 줄에 반영 부탁).

**720×480 실창 확인 요청**: offscreen 에서 W2·W3·W4·W6 를 확인했으나 실제 창의 Tab 포커스 점선(W4)은 캡처로 볼 수 없어 디자이너 또는 사용자가 한 번 확인해 주세요.

---

## designer → builder: exe 재빌드 요청 (2026-09-17)

사용자가 실창 4장(저장 대기·검증 대기·최근·설정)을 보내 주셨는데 **W1~W6 수정 전 빌드**였습니다. 근거 2가지:

- 설정 페이지 타임아웃 QSpinBox 에 깨진 스핀 화살표가 그대로 (W5 미반영)
- 검증 페이지 힌트가 옛 문구 "또는 .py 파일을 이 창에 끌어다 놓으세요" (S6 미반영)

S1(최근 테이블 헤더 왼쪽 정렬)만 들어 있는 것으로 보아 사용자는 `dist/swea-fetch-gui.exe`(v0.3.1, M4c 빌드)를 실행 중입니다. 소스 수정만으로는 사용자 화면이 바뀌지 않습니다.

### 요청

1. `packaging/swea-fetch-gui.spec` 으로 **exe 재빌드** (W1~W6 + S1~S7 반영 커밋 기준). `--onefile --windowed --icon design/icons/app.ico` 그대로.
2. 빌드 후 `SWEA_FETCH_SELFTEST` 자가진단 통과 확인 + **실창 캡처 4장** 을 `docs/gui-screenshots/real/` 에 추가 (offscreen 아님, 사용자 PC 와 같은 Windows 렌더링):
   - `settings.png` — 스핀 버튼 없음 (W5)
   - `check-720.png` — 창 너비 720 에서 [실행] 이 행2 로 내려감 + 새 힌트 문구 (W2·S6)
   - `fetch-success.png` — 결과 카드의 `원본 …`/`뼈대 생성` 이 맑은 고딕 크기 (W1)
   - `check-fail-selected.png` — diff 행 하나 선택해 왼쪽 2px 파란 세로선 (W3)
3. 태그: 기존 `v0.3.1` 은 두고 **`v0.3.2`** 로 (디자인 검토 반영 빌드). 사용자에게는 exe 교체 안내 한 줄 — "바탕화면 exe 를 새 `dist/swea-fetch-gui.exe` 로 덮어쓰기".
4. `.gitignore` 상 `dist/` 는 미커밋 그대로. Release 첨부 여부는 사용자 결정 (planner 전달문 §3-5).

### 디자이너 확인 절차

위 캡처 4장이 오면 캡처만으로 W1·W2·W5·S6 확인 → 사용자가 새 exe 로 Tab 포커스(W4)와 Ctrl+C 복사(W3)를 한 번 눌러 보면 **M4 디자인 게이트 종료**. 추가 라운드 없음.

---

## builder 회신 2 (2026-09-17, 재빌드)

1. **exe 재빌드 완료** — `dist/swea-fetch-gui.exe` (55.8 MB, W1~W6·S1~S7 반영 커밋 기준, `packaging/swea-fetch-gui.spec` 그대로). 자가진단(`SWEA_FETCH_SELFTEST`) 통과: 아이콘 10개, `WinVaultKeyring`, 설정 로드, 창 생성 `● 로그인됨`.
2. **실렌더링 캡처 4장** — `docs/gui-screenshots/real/` (Windows QPA 로 실제 창을 띄워 `grab()`, offscreen 아님):
   - `settings.png` (W5 스핀 버튼 없음) · `check-720.png` (W2 [실행] 행2 + S6 새 힌트) · `fetch-success.png` (W1 카드 한글이 맑은 고딕) · `check-fail-selected.png` (W3 선택 행 왼쪽 2px 파란 세로선)
   - 캡처 중 발견·수정: 720 폭에서 검증 힌트가 잘려 `setWordWrap(True)` 추가.
3. **태그 `v0.3.2`** (버전 0.3.2). `v0.3.1` 은 유지. `dist/` 미커밋.
4. 사용자 안내: **바탕화면의 exe 를 새 `dist\swea-fetch-gui.exe` 로 덮어쓰기** (바로 가기를 만들었다면 대상은 그대로).

남은 확인 (사용자, 새 exe 로): Tab 으로 내비 진입 시 포커스 점선(W4), 검증 diff 에서 행 클릭 후 Ctrl+C 붙여넣기(W3). 이 둘이 되면 디자인 게이트 종료.
