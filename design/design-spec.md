# swea-fetch GUI 디자인 스펙 (M4)

기준 문서: `docs/m4-work-order.md` §4·§5. 토큰 파일: `swea_fetcher/gui/theme/tokens.py` (이 문서 §2 와 1:1 — `Palette` 필드명은 builder 의 것을 따르고, 스펙 이름과의 대응은 §2.1 표 괄호 참고). QSS: `tokens.build_qss()` 가 생성 (별도 `.qss` 파일 없음). 목업: `design/mockups/index.html` (브라우저로 열기). 아이콘: `design/icons/`.

> 이 문서에 없는 값은 쓰지 않는다. 형용사 대신 토큰 이름과 px 로 말한다. 구현 중 스펙과 충돌하면 코드에 `# 스펙 대체안:` 주석을 남기고 이 문서 §15 에 항목을 추가한다.

---

## 1. 방향

**한 문장**: PyCharm 옆에 띄워 두는 보조 창이므로, 장식 없이 **"지금 무슨 상태인지"가 1초 안에 읽히는** 밀도 높은 도구 UI.

근거
- 사용 패턴이 "하루 여러 번 × 3~10초". 시선이 머무는 시간이 짧으니 상태(대기/진행/성공/오류)를 색·아이콘·문구 세 가지로 동시에 표현한다.
- 창이 작다(기본 880×600, 최소 720×480). 여백을 4px 스케일로 통제하고 페이지당 시각 요소를 "입력 블록 1 + 결과 블록 1 + 로그 1" 로 제한한다.
- Qt 위젯 제약: 그림자·그라데이션·애니메이션 **사용 안 함**. 깊이는 `border 1px` + 배경 2단계(`bg` / `surface`)로만 표현한다.
- 라이트 1종. 다크는 M4 범위 밖 (토큰 구조는 dict 라 추가 가능).

---

## 2. 디자인 토큰

### 2.1 색상 (라이트)

이름 표기: **스펙 이름 (`tokens.Palette` 필드명)**. 코드에서는 괄호 안 이름을 쓴다.

| 토큰 | 값 | 용도 |
|---|---|---|
| `bg` (`bg`) | `#F4F5F7` | 창 배경, 페이지 배경 |
| `surface` (`surface`) | `#FFFFFF` | 사이드바, 카드, 입력창, 테이블, 상태바 |
| `surface_sunken` (`surface_alt`) | `#EDEFF2` | 로그 영역, 테이블 헤더, hover 배경, 비활성 입력 배경 |
| `border` (`border`) | `#D5D9E0` | 모든 1px 테두리 |
| `border_strong` (`border_strong`) | `#B9BFC9` | 입력 hover 테두리, 스크롤바, primary disabled 배경 |
| `text` (`text`) | `#1F2328` | 본문 |
| `text_secondary` (`text_2`) | `#424A53` | 레이블, 보조 설명, 로그 본문, 배너 본문 |
| `text_muted` (`text_3`) | `#656D76` | 힌트, 플레이스홀더, 상태바, 테이블 헤더 |
| `text_disabled` (`text_disabled`) | `#8C959F` | 비활성 컨트롤 글자 (AA 예외) |
| `primary` / `_hover` / `_pressed` (`primary` / `primary_hover` / `primary_pressed`) | `#1F6FEB` / `#1A5FD0` / `#164FAD` | 주 버튼, 포커스 링, 진행 막대, 탭 밑줄 |
| `text_on_primary` (`primary_text`) | `#FFFFFF` | primary 배경 위 글자 |
| `primary_subtle` / `primary_subtle_text` (`primary_soft` / `primary_soft_text`) | `#DDEBFF` / `#0B4AA8` | 선택된 내비, info 배너, running 배지, diff extra |
| `success` / `_subtle` / `_text` (`success` / `success_bg` / `success_text`) | `#1A7F37` / `#DAFBE1` / `#116329` | 성공 배너·배지, 로그인됨 표시 |
| `warning` / `_subtle` / `_text` (`warning` / `warning_bg` / `warning_text`) | `#9A6700` / `#FFF8C5` / `#7D5300` | 경고 배너·배지, diff changed |
| `danger` / `_subtle` / `_text` (`error` / `error_bg` / `error_text`) | `#CF222E` / `#FFEBE9` / `#A40E26` | 오류 배너·배지, 입력 오류, 위험 버튼 |
| `diff_same` / `diff_changed` / `diff_missing` / `diff_extra` (동일) | `#FFFFFF` / `#FFF8C5` / `#FFEBE9` / `#DDEBFF` | diff 행 배경 (§5.9) |
| (`accent`) | `#1F6FEB` | **예약, 사용처 없음.** builder 뼈대에 있던 필드 — 새 용도를 만들지 않는다 |

대비 검증 (WCAG AA 4.5:1 기준, 계산값)

| 조합 | 비율 | 판정 |
|---|---|---|
| `text` on `surface` | 15.4:1 | ✓ |
| `text_secondary` on `surface` | 9.6:1 | ✓ |
| `text_muted` on `bg` | 4.8:1 | ✓ (가장 약한 조합 — 이보다 연한 회색 글자 금지) |
| `text_on_primary`(흰색) on `primary` | 4.7:1 | ✓ |
| `success_text` on `success_subtle` | 6.9:1 | ✓ |
| `warning_text` on `warning_subtle` | 6.5:1 | ✓ |
| `danger_text` on `danger_subtle` | 6.4:1 | ✓ |
| `primary_text` on `primary_subtle` | 7.4:1 | ✓ |
| `success` / `danger` / `warning` on `surface` (아이콘·단독 글자) | 4.9 / 5.3 / 4.9 | ✓ |
| `text_disabled` on `surface_sunken` | 3.0:1 | 비활성 컨트롤이므로 예외 |

규칙: 흰 배경 위에 `text_muted` 보다 연한 글자 금지. subtle 배경 위에는 반드시 짝이 되는 `*_text` 를 쓴다 (`danger` 원색을 `danger_subtle` 위에 글자로 쓰지 않는다).

### 2.2 타이포그래피

- UI 글꼴: `"Malgun Gothic", "Segoe UI", sans-serif`
- 고정폭: `Consolas, "Cascadia Mono", monospace` — 경로, 파일명, diff 값, 미리보기 3줄, 문제 번호 입력창, 로그의 타임스탬프
- **mono 사용 범위 규칙 (M4 검토 W1 로 추가)**: 고정폭에는 코드·경로·파일명·숫자·기호만 둔다. **한글 문장은 mono 금지** — Consolas 에 한글 글리프가 없어 폴백 글꼴로 크기가 달라진다. 로그 본문, 파일 행의 설명("원본 …", "뼈대 생성"), diff 의 빈 값 표시(`—` 기호 사용, "(없음)" 금지)는 UI 글꼴. 한 줄 안에 섞일 때는 `<span style='font-family:…'>` 로 부분 지정한다. 한글 지원 고정폭(D2Coding) 번들은 하지 않는다.
- **번들 안 함 결정**: Pretendard 를 번들하면 PyInstaller 산출물 +2MB 와 폰트 로딩 코드가 생긴다. Malgun Gothic 은 Win10/11 기본 탑재라 배포 부담이 0. 한글 가독성은 13px 이상에서 충분하다. (다크·브랜딩 필요가 생기면 재검토)
- Malgun Gothic 은 Bold(700) 만 있어 `semibold(600)` 지정 시 700 으로 렌더된다 — 의도된 허용.

| 토큰 (`tokens.py` 상수) | pt (≈px @96dpi) | 용도 |
|---|---|---|
| `xs` (`FONT_SIZE_XS`) | 8 (≈11) | 배지, 상태바, 테이블 헤더 |
| `sm` (`FONT_SIZE_SM`) | 9 (12) | 보조 설명, 힌트, 로그, diff, 테이블 본문, 배너 본문 |
| `base` (`FONT_SIZE`) | 10 (≈13) | 본문, 입력창, 버튼, 내비 |
| `md` (`FONT_SIZE_MD`) | 11 (≈15) | 카드 제목(`25730. 항아리 게임`), 섹션 제목, 앱 이름 |
| `lg` (`FONT_SIZE_LG`) | 13 (≈17) | 페이지 제목 |

글꼴 크기만 pt (Qt 가 DPI 에 맞춰 스케일), 그 외 길이는 px. 고정폭 줄 간격은 Qt 기본.

### 2.3 간격 (4px 스케일)

4 · 8 · 12 · 16 · 24 · 32. 코드에서는 `tokens.SPACE`(8) 의 배수로 쓴다: `SPACE//2`, `SPACE`, `SPACE+4`, `SPACE*2`, `SPACE*3`, `SPACE*4`. 이 밖의 값 금지 (단, 포커스 시 padding 1px 보정은 예외 — §13).

적용 규칙
- 페이지 내용 여백: 24 (상하좌우)
- 폼 행 사이: 12 / 레이블→입력: 4 / 블록(폼↔결과↔로그) 사이: 16
- 카드·배너 내부 패딩: 12 (배너) / 16 (카드)
- 버튼 사이: 8 / 아이콘↔글자: 8

### 2.4 모서리·선

`RADIUS_SM`=4 (입력, 버튼, 체크박스), `RADIUS`=6 (카드, 배너, 로그, 테이블), 배지는 10 (pill, 높이 20 의 절반). 테두리 1px. 포커스 링은 `primary` 2px (테두리 두께를 1→2 로 바꾸고 padding 1px 줄여 크기 유지).

### 2.5 컨트롤·레이아웃 크기

| 토큰 (`tokens.py`) | px |
|---|---|
| `CONTROL_H` (입력·콤보·버튼) | 32 |
| `CONTROL_H_SM` (배너 내 버튼, 테이블 행) | 28 |
| 아이콘 인라인 / 내비 | 16 / 20 |
| `NAV_ITEM_H` | 40 |
| `SIDEBAR_W` | 148 |
| 상태바 높이 | 26 |
| `PROGRESS_H` | 3 |
| `WINDOW_DEFAULT` / `WINDOW_MIN` | 880×600 / 720×480 |
| `LOG_H_DEFAULT` / `LOG_H_MIN` | 140 / 80 |

마우스 대상 최소 크기: 버튼·입력 32px 높이, 내비 40px, 테이블 행 28px, 아이콘 전용 버튼 28×28. (터치 44px 기준은 데스크톱 전용 앱이므로 적용하지 않되, 어떤 클릭 대상도 24px 미만 금지.)

---

## 3. 앱 셸 (MainWindow)

```
QMainWindow  880×600 (min 720×480)   배경 bg
├─ 중앙 위젯 QHBoxLayout (margin 0, spacing 0)
│  ├─ 사이드바 (w 148, surface, border-right 1px border)
│  │   ├─ QLabel[class=app-title]  "SWEA Fetch"  (md, semibold, padding 16 16 12 16)
│  │   └─ QListWidget#nav — 항목 4개 (아이콘 20 + 텍스트, h 40, 좌우 padding 12, 항목 간 2px)
│  │         저장 · 검증 · 최근 · 설정
│  └─ QStackedWidget  (페이지 4개, 각 QWidget#page)
│        └─ 각 페이지: QVBoxLayout margin 24, spacing 16
│             ├─ 헤더 행: QLabel[class=title] + (우측) 상태 배지/보조 버튼
│             ├─ QProgressBar#busy (h 3, 진행 중에만 visible)   ← 헤더 바로 아래
│             ├─ 배너 슬롯 (QFrame[class=banner][state=…], 없으면 hidden)
│             ├─ 페이지 본문 …
│             └─ (페이지별) 로그 영역
└─ QStatusBar (h 26, surface, border-top)
     ├─ 좌: QLabel[class=login]  "● 로그인됨" (state=ok, success_text) / "○ 세션 없음" (state=none, text_muted) / "○ 설정 없음" (state=none, ConfigMissing 일 때)
     ├─ 중: showMessage() 임시 메시지 (4초 후 자동 소거)
     └─ 우: 루트 경로 QLabel[class=hint], 중간 생략(elide middle), 전체 경로는 툴팁
```

- 내비 선택 상태: 배경 `primary_subtle`, 글자 `primary_text` semibold, 아이콘은 같은 SVG 를 `primary_text` 로 재착색 (§12).
- 페이지 전환은 즉시 (애니메이션 없음). 마지막 페이지는 QSettings 에 기억.
- 창 제목: `SWEA Fetch` / 작업 중 `SWEA Fetch — 저장 중…` (작업표시줄에서 진행 여부 확인용).
- **토스트 없음**: 짧은 확인("폴더를 열었습니다", "로그를 지웠습니다")은 상태바 임시 메시지. 결과·오류는 페이지 안 배너/카드. 이유: Qt 에서 토스트는 커스텀 오버레이가 필요하고, 창이 작아 겹침이 방해된다.

---

## 4. 화면 흐름

### 4.1 첫 실행 (ConfigMissing)
1. 앱 시작 → `load_settings` 실패 → 설정 페이지로 이동(내비 "설정" 선택).
2. 설정 페이지 상단에 **info 배너**: 제목 "처음 실행 — 계정 설정이 필요합니다", 본문 "루트 폴더·ID·비밀번호를 저장하고 로그인 확인까지 하면 바로 쓸 수 있습니다. 비밀번호는 Windows 자격 증명 관리자에만 저장됩니다."
3. 다른 페이지 내비는 **활성 상태 유지** (최근 페이지는 설정 없이도 의미가 있음). 저장/검증 페이지에서 실행을 누르면 error 배너 "설정이 없습니다" + [설정으로 이동] 버튼.
4. 설정 저장 + 로그인 확인 성공 → success 배너 + 상태바 `● 로그인됨` → 사용자가 "저장" 내비를 누른다 (자동 이동 없음 — 설정 결과를 확인할 시간을 준다).

### 4.2 평상시
앱 시작 → 마지막 페이지(기본 "저장") → 번호 입력(포커스 자동) → 주제는 마지막 선택이 채워져 있음 → Enter → 진행 막대 + 로그 스트리밍 → 결과 카드. 평균 경로에서 마우스 없이 끝난다.

### 4.3 오류 복구
오류는 항상 **페이지 상단 error 배너** 한 곳에 표시된다 (다이얼로그 팝업 금지 — 창이 작아 모달이 방해). 배너 = 제목(예외 메시지 요약) + 본문(`e.hint`) + 상황별 조치 버튼(§9). 배너는 다음 실행 시작 시 자동으로 사라진다. 닫기 버튼(×)도 제공.

---

## 5. 공통 컴포넌트

표기: `상태` 는 default / hover / focus / disabled / (invalid). 색은 토큰 이름.

### 5.1 TextInput (QLineEdit)
- h 32, surface 배경, border 1px `border`, radius 4, 좌우 padding 8, 글자 base.
- hover: border `border_strong`. focus: border 2px `primary`. disabled: 배경 `surface_sunken`, 글자 `text_disabled`.
- invalid(`[state="invalid"]`): border 2px `danger` + 입력 아래 4px 간격으로 `QLabel[class=error]` (sm, `danger_text`) 메시지. 아이콘 없이 문구로 전달(색 + 텍스트 두 채널). 수정 시작 시 `state` 제거.
- 플레이스홀더는 Qt 기본 회색. 문제 번호 입력창만 고정폭 글꼴(`[class=mono]`).
- 비밀번호: EchoMode.Password + 오른쪽에 체크박스 "표시" (토글 시 Normal). 저장 후 필드 비움.

### 5.2 ComboBox (주제, 편집 가능)
- TextInput 과 동일 외형 + 우측 24px 드롭 영역, `chevron-down.svg`.
- 목록: surface, border 1px, 항목 h 28, 선택 `primary_subtle`.
- 항목 = `list_topics()`, 마지막 선택 기억. 편집 가능(새 주제 입력).

### 5.3 Checkbox
- 16×16, border 1px `border_strong`, radius 4. checked: 배경 `primary` + `check-white.svg`. focus: border 2px `primary`. 레이블 간격 8. 행 높이 24.

### 5.4 Button (QPushButton)
| `class` | 배경 / 글자 / 테두리 | hover | pressed | disabled |
|---|---|---|---|---|
| `primary` | `primary` / 흰색 semibold / `primary` | `primary_hover` | `primary_pressed` | 배경 `border_strong`, 글자 흰색 |
| (없음 = secondary) | `surface` / `text` / `border` | 배경 `surface_sunken`, 테두리 `border_strong` | 배경 `border` | 글자 `text_disabled`, 배경 `surface_sunken` |
| `danger` | `surface` / `danger` / `border` | 배경 `danger_subtle`, 테두리 `danger` | — | 기본과 동일 |
| `link` | 투명 / `primary_subtle_text` / 없음 | 배경 `surface_sunken` | — | 글자 `text_disabled` |

- h 32, 좌우 padding 16, radius 4. primary 최소 너비 96. `class="sm"` 또는 배너 안 버튼은 자동으로 h 28, padding 12, 글자 sm.
- focus: border 2px `primary` (primary 버튼은 `primary_pressed`).
- 페이지당 primary 버튼 **1개**. 진행 중엔 primary 버튼 disabled + 라벨을 "저장 중…" 처럼 진행형으로 바꾼다 (스피너 대신 — Qt 에 기본 스피너가 없음).

### 5.5 Busy 인디케이터 (QProgressBar#busy)
- 헤더 바로 아래 h 3, 배경 `surface_sunken`, chunk `primary`, `setRange(0,0)` 인디터미넛. 진행 중에만 visible. 텍스트 없음.
- 상태 문구는 로그 마지막 줄과 상태바 임시 메시지(진행 메시지 그대로)로 전달.

### 5.6 Banner (QFrame[class=banner][state=…], `widgets.Banner`)
- radius 6, border 1px (state 색), padding 16 8 (좌우 16, 상하 8), 배경 `*_subtle`.
- 구조: `[상태 아이콘 16] [제목 QLabel[class=banner-title] (semibold, *_text)] ── [조치 버튼 sm] [✕ 닫기 QToolButton 24×24]` / 제목 아래 본문 `QLabel[class=muted]` (sm, `text_secondary`, 줄바꿈·선택 가능).
- state: `error`(status-error.svg) · `warning`(status-warning.svg) · `success`(status-success.svg) · `info`(아이콘 없음, 제목만 `primary_subtle_text`).
- 조치 버튼은 최대 1개 (builder 뼈대의 `action` 1개와 일치). 두 번째 조치가 필요하면 본문 문구로 안내한다.
- 아이콘 + 제목 문구 + 색 세 가지로 의미 전달 (색 단독 금지).
- 한 페이지에 배너는 최대 1개. 새 배너가 이전 것을 대체.

### 5.7 StatusBadge (QLabel[class=badge][state=…], `widgets.Badge`)
- pill(radius 10), h 20, padding 2 8, 글자 xs semibold. 항상 텍스트 포함.
- `success` "통과" · `error` "실패" / "시간 초과" · `warning` "기대 출력 없음" / "이미 있음" · `running` "실행 중…" · `idle` "대기" / "생성" / "유지" / "미리보기".

### 5.8 LogView (`widgets.LogView`, 본문 QPlainTextEdit#log)
- 배경 `surface_sunken`, border 1px, radius 6, **UI 글꼴 sm** (본문이 한국어 문장이므로 — §2.2 규칙), 글자 `text_secondary`, padding 8, 읽기 전용, 자동 스크롤.
- 헤더: QToolButton "▼ 로그" / "▶ 로그 (n줄)" (`▾/▸` 는 맑은 고딕에 글리프 없음) — 접기/펼치기, 접힘 상태 QSettings 기억. 오른쪽 QToolButton [지우기].
- 한 줄 형식: `HH:MM:SS  메시지` — 타임스탬프만 mono span. 예외의 traceback 은 여기만, 색 `danger_text`. 비밀번호·쿠키는 어떤 경우에도 표시 금지 (worker 가 필터).
- 빈 상태 플레이스홀더: "진행 로그가 여기에 표시됩니다" (`setPlaceholderText`).
- 높이 기본 140, 최소 80. 창 높이 < 560 이면 기본 접힘.

### 5.9 DiffView (QTableWidget#diff, `widgets.DiffView`)
- 열: `#`(줄 번호, w 40, `text_muted`) · `기대`(stretch) · `실제`(stretch). 고정폭 sm, 행 h 28, 헤더 `surface_sunken` xs.
- 행 종류별 배경(커스텀 델리게이트가 `BackgroundRole` 을 직접 칠함 — QSS `::item` 이 있으면 Qt 가 무시하므로) + **줄 번호 열의 마커 문자** (색 단독 금지):
- 선택·복사 가능해야 한다(§10). 선택 표시는 배경색 대신 **행 왼쪽 2px `primary` 세로선** (diff 색을 덮지 않게). Ctrl+C = 선택 행의 "실제" 열 텍스트 복사.

| kind | 배경 | `#` 열 표시 | 실제 열 |
|---|---|---|---|
| same | `diff_same` | `12` (번호만) | 값 |
| changed | `diff_changed` | `12 ≠` | 값 (글자 `warning_text`) |
| missing | `diff_missing` | `12 −` | `—` `text_muted` |
| extra | `diff_extra` | `12 +` | 값 (기대 열 `—`) |

`#` 열 너비 44 → 마커 포함 시 56. 툴팁에 kind 한글("불일치"/"누락"/"추가 출력").

- `extra` 를 초록이 아닌 `primary_subtle` 로 두는 이유: 검증 화면에서 초록 = "통과" 배지와 같은 의미로 읽혀 "추가 출력이 좋은 것"처럼 보이기 때문.
- 통과 시엔 diff 뷰 전체가 same 행이라 흰색 — 대신 상단 배지 `success` "통과" 로 상태를 확정한다.
- 1000행 초과 시 앞 1000행만 표시 + 하단 `text_muted` "…이하 N행 생략".

### 5.10 ResultCard (QFrame[class=card])
- surface, border 1px, radius 6, padding 16, 내부 spacing 8.
- 구조 §6.1 참고. 파일 행은 행마다 QLabel(rich text, 색은 `tokens.LIGHT.*` 만) — 파일명·크기·원본 파일명은 mono, 한글 설명은 UI 글꼴 span (§2.2).
- 행 끝 상태 표기는 pill 이 아니라 **대괄호 + 단어 + 색** (Qt rich text 가 span 의 radius/padding 을 못 그림): `[생성]` `[유지]` `text_2` / `[덮어씀]` `[이미 있음]` `warning_text`. 색 단독 아님.
- 경로 줄은 `QLabel` 을 `Ignored` 가로 정책 + `elidedText(ElideMiddle)` 로 그려 가로 스크롤을 만들지 않는다. 전체 경로는 툴팁.

### 5.11 EmptyState
- 중앙 정렬, 아이콘 없음(내비 아이콘 재활용 금지 — 의미 혼동). `QLabel[class=empty-title]`(md, `text_secondary`) + `QLabel[class=empty-body]`(sm, `text_muted`) + 선택적 secondary 버튼 1개. 세로 간격 8, 버튼 위 16.

### 5.12 Table (QTableWidget, 최근 목록)
- surface, border 1px, radius 6, 행 h 28, 헤더 xs `text_muted` on `surface_sunken`. hover `surface_sunken`, 선택 `primary_subtle`. 그리드선 없음, 행 아래 1px `surface_sunken`.

### 5.13 Tabs (QTabWidget — 검증 결과)
- 탭 바: 글자 sm `text_muted`, 선택 시 `text` + 밑줄 2px `primary`. pane: surface, border 1px, radius 6.

---

## 6. 화면별 스펙

### 6.1 저장 페이지 (FetchPage) — 메인

**목적**: 번호·주제 입력 → 3~10초 내 저장 완료 확인.

```
QWidget#page  (VBox, margin 24, spacing 16)
├─ 헤더 HBox
│   ├─ QLabel[class=title] "문제 저장"
│   └─ (stretch) QLabel[class=hint] "Enter 저장 · Ctrl+Enter 미리보기 · Esc 로그 지우기"
├─ QProgressBar#busy
├─ 배너 슬롯
├─ 폼 QFrame[class=card] (surface, padding 16)  — GridLayout, 레이블 열 w 72 우측정렬 text_secondary
│   ├─ 행1: "문제 번호"  QLineEdit[class=mono] (placeholder "25730  또는 문제 URL / contestProbId") … stretch
│   ├─ 행2: "주제"      QComboBox (편집 가능, w 240)   QLabel[class=hint] "루트 아래 폴더 이름"
│   ├─ 행3: (빈 레이블) 체크박스 HBox: [ ] 덮어쓰기   [ ] 뼈대만   [ ] 색인 새로고침   (간격 16)
│   └─ 행4: (빈 레이블) HBox: [저장](primary) [미리보기](secondary) (stretch)
├─ 결과 슬롯 (아래 상태 중 하나)
└─ 로그 영역 (LogView, 세로 stretch)
```

체크박스 툴팁(모두 필수): 덮어쓰기 "input.txt / output.txt 를 덮어씁니다. {번호}.py 는 유지" · 뼈대만 "첨부를 받지 않고 폴더 + {번호}.py + 빈 input.txt 만 만듭니다" · 색인 새로고침 "번호 색인 캐시를 무시하고 다시 찾습니다".

**상태**

| 상태 | 모습 |
|---|---|
| 대기 | 결과 슬롯 = EmptyState 없음(빈 공간), 로그 플레이스홀더. 번호 입력에 포커스. |
| 진행 중 | Busy 막대 표시, [저장]→"저장 중…" disabled, [미리보기] disabled, 입력 3개 disabled. 로그에 progress 메시지 append. 상태바 임시 메시지 = 마지막 progress. 창 제목 "— 저장 중…". |
| 성공 | Busy 숨김, 컨트롤 복원, 결과 슬롯 = ResultCard:<br>`[status-success 16] 25730. 항아리 게임` (md semibold)<br>경로 `C:\…\swea\IM_test\25730\` (mono sm, elide middle, 툴팁 전체)<br>`● input.txt — 생성 (1.2 KB, 원본 sample_input.txt)`<br>`● output.txt — 생성 (0.4 KB, 원본 sample_output.txt)`<br>`● 25730.py — 뼈대 생성` / 기존이면 `○ 25730.py — 기존 파일 유지`<br>버튼 행: [폴더 열기] [PyCharm 에서 열기] (secondary). 상태바 "저장 완료 · 25730".<br>notices(주제 이름 안내)가 있으면 카드 위에 **warning 배너** "기존 폴더 'BFS' 를 사용했습니다 (입력 'bfs')". 뼈대만이면 카드 아래 sm `text_secondary` "샘플은 문제 페이지에서 직접 input.txt 에 붙여넣으세요". |
| 미리보기(dry-run) | ResultCard 제목 앞 배지 `idle` "미리보기". 파일 행에 `← sample_input.txt (1.2 KB)` + 아래 mono sm 3줄 미리보기(`surface_sunken` 블록, padding 8). 이미 있는 파일은 배지 `warning` "이미 있음". 버튼 행: [이대로 저장](primary sm — 충돌이 있으면 라벨 "덮어쓰고 저장"). 폼의 [저장] 과 primary 가 2개가 되지만 블록이 다르고 라벨이 달라 혼동이 없음을 실측 확인 — 폼 [저장] 은 활성 유지 (M4 검토 S8). |
| 오류 | 배너 (§9). 결과 슬롯은 이전 내용 제거. 포커스는 원인 필드(InvalidInput→번호 입력)로. |
| 입력 검증 실패 | 번호 비어 있음 → 입력 invalid + "문제 번호 또는 URL 을 입력하세요". 주제 비어 있음 → 콤보 invalid + "주제 폴더 이름을 입력하세요". 워커를 띄우지 않는다. |

### 6.2 검증 페이지 (CheckPage)

**목적**: 저장한 풀이를 실행해 `output.txt` 와 비교, 틀린 줄을 바로 찾기.

```
QWidget#Page
├─ 헤더 HBox: QLabel[class=title] "풀이 검증"   (stretch)   Badge (결과 배지, 대기 시 hidden)   QLabel[class=hint] "0.12s" (경과, hidden)
├─ QProgressBar#busy
├─ 배너 슬롯
├─ 폼 QFrame[class=card] — GridLayout
│   ├─ 행1: "주제" QComboBox (w 200)   "번호" QLineEdit[class=mono] (w 120)   [실행](primary)
│   └─ 행2: QLabel[class=hint] "또는 .py 파일을 이 창에 끌어다 놓으세요 · 타임아웃 10초 (설정에서 변경)"
├─ 결과 슬롯 (세로 stretch)
│   ├─ 대기: EmptyState "실행하면 결과가 여기에 표시됩니다" / "최근 페이지에서 문제를 더블클릭해도 됩니다"
│   └─ 결과: QTabWidget  탭 "출력 비교" (DiffView) · "stderr" (stderr 있을 때만 탭 추가, CodeView `danger_text`)
└─ (로그 없음 — 결과 탭이 로그 역할. 실행 로그가 필요하면 stderr 탭)
```

드래그앤드롭: 페이지 전체가 drop target. **`.py` 파일 또는 `{번호}` 폴더** 드롭 → `{주제}\{번호}` 에서 주제·번호를 추출해 폼 채움 + 즉시 실행하지 않음(사용자가 [실행]). 자식 입력창은 드롭을 받지 않는다(경로가 텍스트로 들어간 사고 방지). 규칙에 맞지 않는 항목을 놓으면 warning 배너 "{주제}\{번호}\ 폴더 안의 .py 파일(또는 폴더)을 끌어다 놓으세요" + 본문 "놓은 항목: …". 드래그 중 카드 테두리 2px `primary` (`[state="drop"]`). 힌트 문구: "또는 .py 파일이나 {번호} 폴더를 이 창에 끌어다 놓으세요 · 타임아웃 N초 (설정에서 변경)".
너비 < 880 에서 행1 이 넘치면 [실행] 을 행2 로 내린다 (720 에서 콤보 200 + 번호 120 + 버튼 96 은 넘침 — M4 검토 W2).

**상태**

| 상태 | 모습 |
|---|---|
| 대기 | 배지 hidden, EmptyState. |
| 진행 중 | Busy, [실행]→"실행 중…" disabled, 배지 `running` "실행 중…". |
| 통과 | 배지 `success` "통과", 경과 "0.12s", DiffView 모든 행 same(흰색). 상단 **success 배너 없음** (배지로 충분, 배너는 오류 전용 위치). |
| 실패 | 배지 `error` "실패", DiffView 에 changed/missing/extra 행 강조, 첫 번째 불일치 행으로 스크롤 + 선택. 헤더 배지 옆 sm `text_secondary` "불일치 3줄". |
| 기대 출력 없음 | 배지 `warning` "기대 출력 없음", warning 배너 "output.txt 가 없습니다 — 뼈대만 받은 문제입니다. 문제 페이지의 출력 예시를 output.txt 에 붙여넣으세요". DiffView 는 실제 출력만(기대 열 `—`). |
| 타임아웃 | 배지 `error` "시간 초과", error 배너 "10초 안에 끝나지 않아 중단했습니다" + 본문 "무한 루프이거나 입력을 읽지 못한 경우입니다. 설정에서 타임아웃을 늘릴 수 있습니다" + [설정으로 이동] sm. |
| stderr 있음 | "stderr" 탭 자동 추가 + 탭 라벨에 배지 색 점 대신 라벨 텍스트 "stderr (오류)" — 실패 시 이 탭을 기본 선택. |
| 파일 없음 | error 배너 "25730.py 가 없습니다: {경로}" + [저장 페이지로] sm. |

### 6.3 최근 페이지 (HistoryPage)

**목적**: 방금 저장한 문제를 검증 페이지로 넘기거나 폴더를 연다.

```
QWidget#Page
├─ 헤더 HBox: QLabel[class=title] "최근 저장"  (stretch)  [새로고침](secondary)
├─ 배너 슬롯
└─ 결과 슬롯 (stretch)
    ├─ 목록: QTableView  열 = 번호(mono, w 80) · 제목(stretch, 없으면 "—" text_muted) · 주제(w 120) · 저장 시각(w 140, "09-16 14:02")
    └─ 빈 상태: EmptyState "아직 저장한 문제가 없어요" / "저장 페이지에서 문제 번호와 주제를 입력하면 여기에 쌓입니다" + [저장 페이지로](secondary)
```

- 페이지 진입 시마다 `list_recent(limit=20)` 재조회 (디스크만 읽으므로 UI 스레드 허용 — 20개 stat). 20개 넘으면 표에 표시하지 않고 헤더 오른쪽 sm `text_muted` "최근 20개".
- 더블클릭 / Enter → 검증 페이지로 이동 + 주제·번호 채움 (실행은 사용자가). 우클릭 컨텍스트 메뉴: "폴더 열기", "PyCharm 에서 열기", "검증하기".
- 헤더 아래 sm `text_muted` 안내 1줄: "더블클릭 = 검증 · 우클릭 = 폴더 열기".
- 루트 폴더 접근 실패(OSError) → error 배너 "루트 폴더를 읽을 수 없습니다: {경로}" + [설정으로 이동].

### 6.4 설정 페이지 (SettingsPage)

**목적**: 첫 실행 설정, 계정 변경, 자리 반납(세션·계정 삭제).

```
QWidget#Page  (QScrollArea 안에 — 최소 높이 480 에서 잘림 방지)
├─ 헤더: QLabel[class=title] "설정"
├─ QProgressBar#busy
├─ 배너 슬롯
├─ 섹션 "계정" QLabel[class=section]
│   └─ QFrame[class=card] — Grid (레이블 열 w 96)
│       ├─ "루트 폴더"   QLineEdit (stretch) [찾아보기](secondary)   ← QFileDialog (다이얼로그 1)
│       │                 QLabel[class=hint] "swea\{주제}\{번호}\ 가 만들어질 상위 폴더"
│       ├─ "SWEA ID"     QLineEdit (w 280)
│       ├─ "비밀번호"    QLineEdit (Password, w 280)  [ ] 표시
│       │                 QLabel[class=hint] "Windows 자격 증명 관리자에만 저장됩니다. 이미 저장돼 있으면 비워 두어도 됩니다"
│       └─ 버튼 행: [저장 후 로그인 확인](primary)  [저장만](secondary)
├─ 섹션 "검증"
│   └─ QFrame[class=card]: "타임아웃"  QSpinBox (w 96, 접미 " 초", 1~120, 기본 10, **스핀 버튼 없음** — 타이핑·방향키로 변경)  QLabel[class=hint] "풀이 실행 제한 시간"
└─ 섹션 "세션·계정 삭제"
    └─ QFrame[class=card]
        ├─ 행: QLabel "저장된 로그인 세션만 지웁니다. 계정 정보는 유지"   [세션 삭제](secondary)
        └─ 행: QLabel "자리 반납용 — .env 와 자격 증명 관리자의 비밀번호까지 삭제"   [계정 정보까지 삭제](danger)
```

- 테마 선택은 다크가 없으므로 **표시하지 않는다** (work-order 5-4 조건부 항목).
- 저장 성공: success 배너 "설정을 저장했습니다" (로그인 확인 시 "로그인 확인 완료 · 세션 저장됨"), 비밀번호 필드 비움, 상태바 `● 로그인됨`. 상태바 우측 루트 경로 갱신.
- 로그인 확인 실패: error 배너(§9) — 설정은 저장된 상태임을 본문에 명시 "입력한 설정은 저장됐습니다. ID/비밀번호를 고쳐 다시 확인하세요".
- 세션 삭제 → 상태바 `○ 세션 없음` + 상태바 임시 메시지 "세션을 삭제했습니다".
- 계정 정보까지 삭제 → **확인 다이얼로그(다이얼로그 2)** §7 → 성공 시 폼 비움 + info 배너 "계정 정보를 삭제했습니다. 다시 쓰려면 설정을 입력하세요".

**입력 검증 (저장 클릭 시)**
- 루트 폴더 없음 → invalid + "폴더가 없습니다: {입력값}"
- ID 비어 있음 → invalid + "SWEA 로그인 ID(이메일)를 입력하세요"
- 비밀번호 비어 있고 keyring 에도 없음 → invalid + "비밀번호를 입력하세요 (처음 저장할 때 필요)"
- 첫 invalid 필드로 포커스.

---

## 7. 다이얼로그 (2개)

1. **폴더 찾아보기** — `QFileDialog.getExistingDirectory`, 네이티브. 커스텀 없음.
2. **계정 정보 삭제 확인** — `QMessageBox` (Warning 아이콘):
   - 제목 "계정 정보 삭제"
   - 본문 "`.env` 와 Windows 자격 증명 관리자의 비밀번호가 삭제됩니다.\n다시 쓰려면 설정을 처음부터 입력해야 합니다."
   - 버튼: [삭제](danger 스타일, 기본 포커스 **아님**) · [취소](기본 포커스, Esc). Enter 로 실수 삭제 방지.

---

## 8. 폼 UX 규칙

- **검증 시점**: 제출(버튼/Enter) 시 한 번. 입력 중 실시간 검증 없음 (3초 사용에 방해). 사용자가 invalid 필드를 수정하기 시작하면 즉시 invalid 해제.
- 오류 메시지 위치: 필드 바로 아래 4px, `QLabel[class=error]`, sm. 필드가 짧은 행(주제·번호 나란히)이면 행 아래 한 줄로 합쳐 표시.
- 문구 톤: "~하세요" 명령형, 원인 + 조치. 감탄사·이모지 없음. 예) "폴더가 없습니다: C:\x" (원인) → 조치는 [찾아보기] 버튼이 담당.
- 배너 문구: 제목 = 예외 메시지(한 줄로 잘라 elide), 본문 = `e.hint` 그대로. CLI 명령(`--force`) 문구가 hint 에 섞여 있으면 service 쪽에서 GUI 문구로 정리하는 것이 원칙이나, M4 에서는 hint 를 그대로 쓰고 **조치 버튼이 GUI 대응**을 담당한다.
- 제출 후 결과가 나오면 포커스는 번호 입력으로 복귀 (다음 문제 바로 입력).

---

## 9. 오류 → 배너 매핑

| 예외 | 배너 state | 제목(예) | 조치 버튼 (sm) | 포커스 |
|---|---|---|---|---|
| `ConfigMissing` | error | 설정이 없습니다 | [설정으로 이동] | — |
| `LoginFailed` | error | 로그인 실패 (연속 n회) | [설정으로 이동] | — |
| `LoginLocked` | error | 로그인 시도가 차단됐습니다 | 없음 (hint 에 파일 삭제 안내) | — |
| `MfaRequired` | error | 2단계 인증 계정은 자동 로그인 불가 | 없음 | — |
| `InvalidInput` (번호 못 찾음) | error | 문제 번호를 찾지 못했습니다 | [색인 새로고침 후 재시도] (refresh_index=True 로 재실행) | 번호 입력 |
| `InvalidInput` (그 외) | error | 입력을 이해하지 못했습니다 | 없음 (hint 에 입력 예시) | 번호 입력 |
| `ProblemNotFound` | error | 문제를 찾을 수 없습니다 | 없음 | 번호 입력 |
| `ParseError` | error | 페이지에서 번호·제목을 읽지 못했습니다 | 없음 | — |
| `AttachmentNotFound` | warning | 샘플 첨부가 없는 문제입니다 | [뼈대만 저장] (skeleton_only=True 재실행) | — |
| `AlreadyExists` | warning | 이미 저장된 문제입니다 | [덮어쓰고 다시 저장] (force=True 재실행) · 본문에 기존 파일 목록 mono | — |
| `NetworkError` | error | 네트워크 오류 | [다시 시도] | — |
| 예상 밖 `Exception` | error | 내부 오류: {type} | [로그 보기] (로그 펼치고 스크롤) | — |

`AlreadyExists`·`AttachmentNotFound` 는 "실패"가 아니라 "선택이 필요한 상황"이므로 warning 이다. 배너의 재실행 버튼은 폼의 체크박스 상태도 함께 바꾼다 (덮어쓰기 체크 on) — 사용자가 무엇이 달라졌는지 보게.

조치 버튼 키 (구현 `Banner.action_clicked(key)`): `force` 덮어쓰고 다시 저장 · `skeleton` 뼈대만 저장 · `refresh` 색인 새로고침 후 재시도 · `retry` 다시 시도 · `settings` 설정으로 이동 · `fetch` 저장 페이지로 · `log` 로그 보기. 배너당 최대 2개, 본문 아래 오른쪽 정렬 행.

---

## 10. 키보드·접근성

- 탭 순서(저장): 번호 → 주제 → 덮어쓰기 → 뼈대만 → 색인 → [저장] → [미리보기] → 결과 카드 버튼 → 로그 토글. 내비는 Ctrl+1~4 (Tab 순서에서는 맨 앞).
- 단축키: Enter = 저장(번호·주제 입력에서), Ctrl+Enter = 미리보기, Esc(저장 페이지) = **배너가 보이면 배너 닫기, 아니면 로그 지우기** (배너는 포커스를 받지 않으므로 표시 여부로 판단), F5 = 최근 새로고침, Ctrl+, = 설정, Ctrl+1~4 = 페이지.
- 내비 `QListWidget#nav` 는 Fusion 기본 포커스 점선을 유지한다 (`outline: 0` 금지) — 키보드 포커스 위치가 보여야 함.
- 모든 입력에 `setBuddy` 레이블 + `setAccessibleName`. 아이콘 전용 버튼(배너 ×)에 `setToolTip` + `setAccessibleName("닫기")`.
- 포커스 링: 모든 포커스 가능 위젯에서 2px `primary` 가시. Qt 기본 점선 outline 은 QSS 로 제거하지 않는다(중복 허용).
- 색 단독 의미 전달 금지 체크: 배너(아이콘+제목), 배지(텍스트), diff(마커), 로그인 상태(● / ○ 기호 차이 + 텍스트), 입력 오류(문구). ✓
- 텍스트는 모두 선택·복사 가능해야 한다(경로, 로그, diff) — `TextSelectableByMouse`.
- 진행 중에도 페이지 전환·창 이동은 가능 (UI 스레드 비차단). 진행 중 페이지를 떠나도 워커 결과는 해당 페이지에 남는다.

---

## 11. 창 크기 규칙 (반응형)

브레이크포인트는 창 너비·높이. 사이드바는 접지 않는다(720 에서도 148 + 572 로 충분).

| 조건 | 변화 |
|---|---|
| 너비 ≥ 880 (기본) | 폼 행 가로 배치 그대로. 결과 카드 경로 한 줄. |
| 720 ≤ 너비 < 880 | 저장 페이지 체크박스 3개는 그대로(합계 ~300px). 검증 페이지 행1 이 넘치면 [실행] 버튼을 행2 로 내림. 카드 경로 elide middle. 최근 테이블 "저장 시각" 열 w 100 으로 축소("09-16 14:02" → "14:02" 은 아님, 날짜 유지). |
| 높이 < 560 | 로그 영역 기본 접힘(수동으로 펼치면 min 80). 설정 페이지 스크롤. |
| 최소 720×480 | 모든 페이지가 스크롤 없이(설정 제외) 표시돼야 한다. 결과 카드 + 접힌 로그 기준. |
| 창 크기·위치 | QSettings 기억. 화면 밖 복원 방지는 builder 몫(기본 위치로 fallback). |

HiDPI: 모든 값 px 토큰 → Qt 가 DPR 로 스케일. SVG 아이콘만 사용. 150% 에서 폰트 13px ≈ 20 물리 px.

---

## 12. 아이콘

`design/icons/` (20×20 내비, 16×16 상태, 256 앱). 스트로크 1.75, round cap/join, 색 `#424A53`(= `text_secondary`).

| 파일 | 용도 | 비고 |
|---|---|---|
| `nav-fetch.svg` | 내비 "저장" (아래 화살표 + 트레이) | |
| `nav-check.svg` | 내비 "검증" (사각 + 재생) | |
| `nav-history.svg` | 내비 "최근" (시계) | |
| `nav-settings.svg` | 내비 "설정" (슬라이더 3줄) | |
| `status-success.svg` / `status-error.svg` / `status-warning.svg` | 배너·카드 상태 아이콘, 채움형 | 색은 각 시맨틱 원색 + 흰 글리프 |
| `app.svg` | 앱 아이콘 (primary 둥근 사각 + 흰 트레이 화살표) | `.ico` 는 빌드 단계에서 생성: `python -c "from PIL import Image; ..."` 또는 `cairosvg` — 256/48/32/16 포함. 저장소에 `design/icons/app.ico` 로 커밋 (바이너리 ~50KB 허용) |
| `chevron-down.svg` / `check-white.svg` | QSS 전용 (콤보 화살표, 체크박스) | |

내비 선택 상태 착색: SVG 문자열의 `#424A53` 을 `primary_text`(`#0B4AA8`) 로 치환해 두 번째 QIcon 을 만든다 (`QIcon.addPixmap(…, QIcon.Normal, QIcon.On)`). 비활성은 `text_disabled` 로 같은 방식.

---

## 13. Qt 구현 계약 (builder 용)

셀렉터 규약 (builder 뼈대의 `widgets.set_class(w, cls, state)` 방식을 그대로 따른다):

| 대상 | objectName | `class` | `state` |
|---|---|---|---|
| 페이지 루트 | `page` | | |
| 내비 | `nav` (QListWidget) | | |
| 진행 막대 | `busy` (QProgressBar, range 0,0) | | |
| 로그 본문 | `log` (QPlainTextEdit) | | |
| diff | `diff` (QTableWidget) | | |
| 레이블 | | `title` `section` `muted` `hint` `error` `mono` `app-title` `banner-title` `empty-title` `empty-body` `login` | login: `ok` / `none` |
| 버튼 | | `primary` `danger` `link` `sm` (없으면 secondary) | |
| 입력 | | `mono` (번호 입력) | `invalid` |
| 카드 | | `card` | |
| 배너 | | `banner` | `error` `warning` `success` `info` |
| 배지 | | `badge` | `success` `error` `warning` `running` `idle` |

- 동적 프로퍼티를 바꾼 뒤 `style().unpolish(w); style().polish(w)` 필수 (`set_class` 가 이미 수행).
- 포커스·invalid 시 테두리 1→2px 로 두꺼워지며 내부가 1px 밀리는 것을 막기 위해 QSS 에서 padding 을 1px 줄여 보정했다. 위젯 코드에서 padding 을 덮어쓰지 말 것.
- 색·간격은 `tokens.LIGHT.<field>` / `tokens.SPACE` 배수 / `tokens.RADIUS*` 만. 위젯 코드에 `#RRGGBB` 리터럴이나 `setStyleSheet("…")` 인라인 금지. 예외 두 가지: diff 행 배경(`QColor(palette.diff_*)`), 결과 카드 rich text 색(`tokens.LIGHT.success` 등 — 리터럴 금지는 동일).
- 2026-09-17 정합성 검토 결과: 위 셀렉터 계약 준수 확인. 남은 수정 항목(builder 전달): W1 mono 한글 제거 · W2 검증 폼 720 폭 · W3 diff 선택/복사 · W4 `#nav` outline · W5 스핀 버튼 · W6 경로 elide.
- Qt 미지원·대체안: 스피너 없음 → 진행 막대 + 버튼 라벨. 토스트 없음 → 상태바 메시지. 배너 닫기 × 는 `QToolButton` 텍스트 "✕". dashed 드롭 테두리 불가 시 solid 2px `primary`.
- 진행 로그 시간 표기 `[HH:MM:SS]` 는 UI 스레드에서 붙인다(워커는 메시지만).

---

## 14. 자기검토 결과 (체크리스트 반영 내역)

- 접근성: §2.1 대비표 전 항목 AA 이상. `text_muted` 를 `#8B949E` 에서 `#656D76` 으로 올렸다(bg 위 4.2→4.8). 포커스 링 정의(§2.4). 색 단독 전달 없음(§10). 클릭 대상 최소 24px, 기본 32.
- 일관성: subtle 배경엔 항상 `*_text` 쌍. radius 는 4/6/pill 세 값. 간격 4 스케일 밖 값은 포커스 보정 1px 뿐이며 명시함. builder 뼈대의 `Palette` 필드명을 유지하고 스펙 이름과의 대응표를 §2.1 에 두어 두 이름이 섞이지 않게 함.
- 구현 가능성: 그림자·애니메이션·토스트·스피너를 스펙에서 제거하고 Qt 기본 위젯으로 대체(진행 막대, 상태바 메시지, 버튼 라벨 변경). 셀렉터 계약 §13.
- 범위: work-order §5 에 없는 기능 없음. 테마 선택 UI 는 다크 부재로 제외. 취소 버튼은 워커 취소가 범위 밖이라 두지 않음(§15).
- 발견·수정: 검증 페이지의 초록 diff 관습 충돌 → `extra` 를 primary_subtle 로(§5.9). 계정 삭제 다이얼로그 Enter 실수 → 취소를 기본 포커스로(§7).

---

## 15. 미결·선택 사항

- 다크 테마: 없음. 요청 시 `tokens.DARK` 에 `Palette` 를 채우고 `build_qss(DARK)` 로 넘기면 된다.
- 작업 취소 버튼: `requests` 도중 취소가 안정적이지 않아 제외. 필요해지면 검증(subprocess kill)만 먼저.
- `.ico` 생성은 빌드 단계(M4c). SVG 만 디자인 산출물.
- Qt Designer `.ui` 파일: 만들지 않음. 레이아웃이 단순해 코드 레이아웃이 diff 리뷰에 유리.
- `gui/theme/theme.qss`: 사용 안 함(builder 가 `build_qss()` 인라인 생성 방식을 택함). builder 가 삭제해도 된다.
- 스펙 대체안 기록란 (builder 가 추가, 2026-09-16 M4b) — **8건 모두 디자이너 승인 (2026-09-17)**. 조건: #2 는 `#nav` 의 `outline: 0` 제거(§10), #3 은 `NoSelection` 대신 선택·복사 허용(§5.9). 검토 전문은 builder 에게 전달한 Warning 6 / Suggestion 8 목록.
  1. **내비 위젯**: §3 의 `QToolButton[nav]` 대신 `QListWidget#nav` 사용 — `tokens.build_qss` 가 이미 `#nav` 셀렉터로 작성돼 있어 QSS 를 따름. 아이콘 재착색(§12)은 `QIcon.addPixmap(…, Selected)` 로 동일하게 구현.
  2. **포커스 규칙 2개 제거**: `QListWidget#nav:focus::item:selected` 와 `QCheckBox:focus::indicator` 는 Qt 가 위젯 전체 테두리로 해석해 리스트·체크박스 주위에 2px 파란 테두리가 항상 그려짐 → 제거하고 Fusion 기본 포커스 표시 사용 (`tokens.py` 주석).
  3. **DiffView 행 배경**: QSS `::item` 규칙이 있으면 Qt 가 `BackgroundRole` 을 무시 → `QStyledItemDelegate` 로 배경을 직접 칠하고(`widgets._BackgroundDelegate`), 선택 색이 diff 색을 덮지 않도록 `NoSelection`. 첫 불일치 행은 선택 대신 스크롤(가운데)로 표시.
  4. **ResultCard 파일 행 배지**: Qt rich text 는 `<span>` 의 radius/padding 을 그리지 못해 pill 대신 `[생성]`·`[이미 있음]` 대괄호 + 색(`*_text`) 으로 표현. 행마다 QLabel 을 따로 두었음 — QLabel 하나에 `<table>`/`<div>` 를 넣으면 높이 계산이 틀려 잘림.
  5. **저장 페이지 스크롤**: 결과 카드(미리보기 3줄 포함) + 로그가 600px 를 넘는 경우가 있어 저장 페이지도 설정처럼 `QScrollArea` 안에 둠. 로그 최소 80 유지.
  6. **로그 토글 글리프**: `▾/▸` 가 맑은 고딕에 없어 `▼/▶` 사용.
  7. **상태바 진행 메시지**: 워커 progress 를 로그 + `statusBar().showMessage(4s)` 로 그대로 전달 (스펙 §5.5).
  8. **builder QSS 보강** (`gui/app.py::_builder_supplement`): `QFrame#Sidebar`, 드롭 중 카드 테두리 `[state="drop"]`, 미리보기 블록 `QLabel#preview`. 색은 토큰만 사용.
  - 실제 렌더링 캡처: `docs/gui-screenshots/*.png` (offscreen + Windows 글꼴). 디자이너 확인 요청.
  - (없음)
