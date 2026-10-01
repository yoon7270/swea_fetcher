# swea-fetch GUI 디자인 스펙 (M4)

기준 문서: `docs/m4-work-order.md` §4·§5. 토큰 파일: `swea_fetcher/gui/theme/tokens.py` (이 문서 §2 와 1:1 — `Palette` 필드명은 builder 의 것을 따르고, 스펙 이름과의 대응은 §2.1 표 괄호 참고). QSS: `tokens.build_qss()` 가 생성 (별도 `.qss` 파일 없음). 목업: `design/mockups/index.html` (브라우저로 열기). 아이콘: `design/icons/`.

> **M21 (§16 토스 스타일 리프레시) 이 이 문서의 §1 "그림자·애니메이션 없음", §2 색·글꼴·간격·라운드 값, §3 "페이지 전환 즉시 / 토스트 없음", §5 컴포넌트 치수를 대체한다. 충돌 시 §16 이 우선. §16 에서 언급하지 않은 규칙(셀렉터 계약 §13, 키보드 §10, 오류 매핑 §9, 폼 UX §8)은 그대로 유효.**
>
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
│  │   └─ QListWidget#nav — 항목 6개 (아이콘 20 + 텍스트, h 40, 좌우 padding 12, 항목 간 2px)
│  │         저장 · 문제 · 검증 · 최근 · 성장 · 설정  (M19: 성장은 최근 뒤·설정 앞 — 설정은 마지막에 두는 관례)
│  └─ QStackedWidget  (페이지 6개, 각 QWidget#page)
│        └─ 각 페이지: QVBoxLayout margin 24, spacing 16
│             ├─ 헤더 행: QLabel[class=title] + (우측) 상태 배지/보조 버튼
│             ├─ QProgressBar#busy (h 3, 진행 중에만 visible)   ← 헤더 바로 아래
│             ├─ 배너 슬롯 (QFrame[class=banner][state=…], 없으면 hidden)
│             ├─ 페이지 본문 …
│             └─ (페이지별) 로그 영역
└─ QStatusBar (h 26, surface, border-top)
     ├─ 좌: QLabel[class=login]  "● 로그인됨" (state=ok, success_text) / "○ 세션 없음" (state=none, text_muted) / "○ 설정 없음" (state=none, ConfigMissing 일 때)
     ├─ 중: showMessage() 임시 메시지 (4초 후 자동 소거)
     └─ 우: 루트 경로 QLabel[class=hint], **고정폭 360** 안에서 중간 생략(`elidedText` ElideMiddle), 전체 경로는 툴팁 (permanent 위젯은 Ignored 정책에서 0폭이 되어 고정폭으로 구현 — M4 W6)
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
│   ├─ 대기: EmptyState "실행하면 결과가 여기에 표시됩니다" / "최근 페이지에서 문제를 우클릭 → 검증하기 로도 됩니다"
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
- 클릭 / Enter → 문제 탭에 지문 표시 (M14). 캐시에 있으면 바로, 없으면 지문만 가져와(dry-run + 뼈대만, 저장·덮어쓰기 없음) 캐시에 기록. 문제 탭의 [폴더 열기]·[에디터에서 열기] 는 그 문제 폴더를 대상으로 켜진다. 우클릭 컨텍스트 메뉴: "폴더 열기", "에디터에서 열기", "문제 보기", "검증하기", "SWEA 제출…", "커밋 + 푸시…".
- 헤더 아래 sm `text_muted` 안내 1줄: "클릭 = 문제 보기 · 우클릭 = 에디터·폴더 열기·검증".
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

### 6.5 문제 페이지 (ProblemPage, M12)

**목적**: 가져온 문제의 제한사항·지문을 앱 안에서 읽는다. 내비 두 번째 항목 "문제"(`nav-problem`, Ctrl+2). 지문은 파일로 저장하지 않는다.

```
QWidget#Page (QStackedLayout: 빈 상태 | 본문)
├─ 헤더 HBox: QLabel[class=title] "{번호}. {제목}" (stretch)  Badge(저장됨 success / 미리보기 — 저장 안 됨 idle / 캐시 idle)
├─ ElidedLabel[class=hint] "{주제} · {저장 경로 | 캐시 · 시각}"
├─ 배너 슬롯 (이미지 실패 info / 지문 영역 없음 warning + [저장 탭으로])
├─ 버튼 줄: [폴더 열기] [PyCharm 에서 열기] (저장 성공 때만) ……… [글자 −] [글자 +]
├─ QFrame[class=card] 안 _StatementBrowser (QTextBrowser, 자체 스크롤 — 이중 스크롤 금지, 제한사항 → hr → 본문)
└─ QLabel[class=hint] "지문은 파일로 저장되지 않습니다 (앱 캐시 사용 시 ~/.swea-fetch/cache …)"
빈 상태: EmptyState "아직 가져온 문제가 없습니다" / "저장 탭에서 문제를 가져오면 지문이 여기에 표시됩니다" + [저장 탭으로]
```

- 지문 CSS 는 `tokens.build_statement_css(palette)` 가 Palette 필드(`text` `text_2` `text_3` `border` `surface_alt`, `FONT_MONO`, `SPACE`)로만 만든다. 색 리터럴 금지. 본문 글자 크기는 지정하지 않는다 (위젯 폰트 + zoom, 범위 −3~+8, QSettings `problem/zoom`).
- 표: 1px `border` 격자 + 셀 패딩 4×8, `th` 는 `surface_alt`. `pre/code` 는 `FONT_MONO` + `surface_alt`. 이미지는 뒤에 배경을 깔지 않는다 (다크 도입 시 투명 PNG 대비 재검토).
- 이미지는 뷰포트 폭(−여백)보다 크면 축소, 리사이즈 시 100ms 디바운스로 다시 맞춤. 실패 이미지는 본문에 "[이미지 불러오기 실패: 사유]" (`text_3`).
- 자동 전환: 저장·뼈대 성공 시 문제 탭으로 이동 (설정 "저장 후 문제 탭으로 이동", 기본 ON). 미리보기는 이동하지 않고 결과 카드에 [문제 보기]. 최근 페이지 우클릭 "문제 보기"(캐시 있을 때만 활성), "이미 저장된 문제" 배너의 [문제 보기]는 캐시만 읽는다.
- 설정 페이지 "문제 지문" 카드: 자동 이동 체크박스, "지문 캐시 사용" 체크박스(기본 ON, 최근 50건), [캐시 지우기].

### 6.6 AI 코치 (M17)

**목적**: 제출/검증 결과 직후 AI(Codex / Claude Code CLI)의 평가·힌트·정답 풀이를 받는다. 새 색·간격 토큰 없음.

**코치 바** (`CoachBar`, `QFrame[class=card]`, 검증 탭 배너 아래·폼 카드 위, 결과 직후에만 표시, 새 실행/제출 시작 시 숨김). 세로 배치: 문장 `QLabel[class=muted]`(줄바꿈) → 버튼 줄(secondary, 왼쪽 정렬 — primary 는 페이지당 1개 규칙상 [실행]/[커밋 + 푸시] 에 양보). 720×480 에서 문장이 줄바꿈되어 잘리지 않는다.

| 상태 | 문장 | 버튼 |
|---|---|---|
| Pass | "Pass! 풀이를 AI 에게 평가받을 수 있어요" | [코드 평가 받기] |
| 오답 (< 기준) | "이 문제 오답 {n}회" | [힌트] (전구 아이콘 + 글자) |
| 오답 (≥ 기준, 제안 활성) | "이 문제를 {n}번 틀렸어요. 정답 풀이(설명 + 코드)를 볼까요? 보면 {d}일 뒤 다시 풀기를 권해드려요." | [힌트] [정답 풀이 보기] [다음에](link) |
| 오답 (≥ 기준, 거절함) | "이 문제 오답 {n}회" | [힌트] [정답 풀이 보기] |
| 로컬 검증 실패 | "로컬 검증에 실패했어요 (SWEA 오답 {n}회)" | [힌트] (+ 기준 이상이면 [정답 풀이 보기]) |
| 힌트 진행 | 버튼 "다음 힌트 (2/3)", 3/3 이면 "힌트 (3/3)" 비활성 + 툴팁 | |
| 요청 중 | 모든 코치 버튼 비활성 | |

- 전구 `coach-hint.svg` (16×16, `#424A53`, `svg_icon()` 재착색 규칙 그대로). 이모지 금지. 툴팁 "이 코드에 대한 힌트를 받습니다 (정답 코드는 보여주지 않아요)", `accessibleName` "힌트 받기".
- 정답 풀이 버튼은 오답 기준 미만이면 숨김. [다음에] 는 문장만 끈다 (버튼 유지).

**AI 코치 탭** (결과 탭 위젯의 추가 탭, 다이얼로그·사이드 패널 아님). 요청 시 탭 추가·선택, `stack` 을 결과 영역(1)으로. 로컬 실행 결과가 갱신돼도 이 탭은 남는다.
- 구조 (M18): 상단 줄(종류 제목 `muted` + [취소], 로딩 패널이 있는 동안만) → `QSplitter`(가로; 탭 폭 < 560px 이면 세로로 자동 전환 — 기본 창 880px 에서는 좌우 유지 (세로는 답이 두세 줄만 보임), 바깥 `QScrollArea` 로 720×480 에서도 잘림 없이 스크롤) 안에 엔진별 `EnginePane` → 공통 푸터 `hint` "AI 응답은 틀릴 수 있습니다. 정답 풀이는 {번호}.py 에 저장되지 않습니다." (+ 복습 예정 `hint` 1줄). 단일 모드(자동/GPT/Claude)는 패널 1개가 전폭. 좌 GPT (Codex), 우 Claude (Claude Code) 고정.
- `EnginePane` (`QFrame[class=card]`, objectName `CoachPane_{codex|claude}`, 최소 높이 140): 헤더 줄 = 엔진 이름 `QLabel[class=section]`(objectName `CoachPaneTitle`) + `muted` "{종류} · {시각} · {소요 초}" + 캐시 Badge(idle) + (오른쪽) 재요청 버튼(objectName `CoachPaneRetry`, accessibleName "{GPT|Claude} 다시 받기"). 본문(`CoachPaneBody`)은 상태별 스택, 푸터 줄 = notes `hint` + [코드 복사](정답 풀이만, 패널별).
- 패널 상태 (색만으로 구분하지 않고 글자 병기; 새 색 토큰 없음):

| 상태 | 본문 | 재요청 버튼 |
|---|---|---|
| loading | "{엔진} 에게 묻는 중… 0:12 · 최대 5분" (`muted`, 탭의 1초 타이머 하나가 전부 갱신) | 비활성 |
| done | `AnswerBrowser`(QTextBrowser, 마크다운 `NoHTML`, 링크·리소스 차단, 지문 CSS 재사용, accessibleName "{엔진} 답변") | [다시 받기] (캐시 무시, 이 엔진만) |
| error | `QLabel[class=error]` "오류 · {제목}" + `muted` hint·stderr 끝부분 (선택·복사 가능) | [다시 시도] (이 엔진만) |
| missing | "오류 · {엔진} 를 찾지 못했습니다" + 설치 안내 + [설정으로 이동] | 숨김 |
| cancelled | "취소했습니다" (`muted`) | [다시 받기] |

- 요청 중에는 모든 패널의 재요청 버튼 비활성 (한 번에 요청 1건). 한쪽만 실패해도 다른 쪽 답은 그대로이고 오류는 실패 패널 안에 표시(배너 없음). 두 쪽 모두 실패일 때만 error 배너 "두 엔진 모두 응답하지 못했습니다" + [다시 시도].
- 코치 바 (둘 다 모드): 문장 끝에 "· GPT · Claude 에 각각 1번씩 요청" 을 붙이고 버튼 툴팁에 `DUAL_NOTE` ("…각각 1번씩 요청…각 서비스에서 쓰는 양은 한 곳만 쓸 때와 같습니다") 를 추가. "사용량 2배" 는 각 서비스 한도가 두 배로 줄어든다고 오해되어 쓰지 않는다.
- 동의 다이얼로그: `QMessageBox` (Question) 제목 "AI 에게 코드를 보냅니다", 버튼 [동의하고 보내기] · [취소](기본 포커스, Esc). 엔진(벤더)별 첫 사용 시 1회. 둘 다 모드에서 미동의 엔진이 여럿이면 한 다이얼로그에 모아 1번(엔진 이름 나열 + "각각 1번씩 요청" 고지).

**복습** — 상태바 배지 `QPushButton[class=link]` "복습 {n}개 ↗" (도래한 항목이 있을 때, 클릭 → 최근 탭), 앱 시작 시 임시 메시지 6초. 최근 탭 표 위 `QFrame[class=card]` "복습" (항목 최대 5개: 링크 버튼 "{번호}. {제목}" + 상태 글자 "· 오늘 복습 / N일 지남"(`warning_text`) "/ N일 뒤"(`text_3`) + 행 끝 `QToolButton` [✕], 6개 이상이면 "외 N개"). 색만으로 구분하지 않는다.

**설정 "AI 코치" 카드** (문제 지문 카드 다음, 레이블 열 96): 엔진 콤보(자동 (Codex 우선)/GPT (Codex)/Claude (Claude Code)/GPT & Claude (둘 다)) — 둘 다 선택 시 콤보 아래 `hint` "요청 1건마다 GPT 와 Claude 구독 사용량이 각각 소모되고, 답이 2개 표시됩니다." (objectName `AiBothHint`), 감지 상태 + [다시 감지] (환경변수 API 키 경고·설치 안내·"둘 다 모드는 설치된 쪽만 실행합니다" 는 `hint` 줄), [연결 테스트] (둘 다 모드는 엔진별 결과를 한 배너에: 전부 성공 success · 일부 실패 warning · 전부 실패 error), 오답 기준 스핀(1~20 " 회"), 복습 스핀(1~30 " 일"), [AI 전송 동의 초기화], [AI 기록 지우기](확인창), 안내 `hint` 한 줄.

### 6.7 성장 페이지 (GrowthPage, M19)

**목적**: AI 코치 응답의 분류 태그와 제출 결과로 만든 **주간 리포트**를 보여준다 ("어떤 방향이 좋아졌는지"). 내비 다섯 번째 "성장"(`nav-growth`, Ctrl+5). 새 색·간격 토큰 없음. 항상 "AI 분류 기반 참고용" 을 표시한다.

전체가 `QScrollArea`(NoFrame) 안 — 720×480 에서 잘림 없이 스크롤(가로 스크롤 없음: 값·이름 라벨은 줄바꿈 허용). 위에서 아래로:

1. **배너 슬롯** (`Banner`, 0~1개): 성장 꺼짐(info + [설정으로 이동]) / 코멘트 동의 필요(info, "집계 숫자와 분류 이름만 {엔진} 으로 보냅니다(코드·지문·문제 번호 제외)" + [동의하고 코멘트 받기]). 앱 시작 시 모달 없음.
2. **리포트 헤더 카드** (`GrowthHeader`): "2026-09-21 ~ 09-27"(`section`) + Badge `진행 중`(idle) / `확정`(success) / `새 리포트`(running = info 색, 미확인일 때만) → 한 줄 아래 `hint` "AI 분류 기반 참고용" → 머리글(`muted`; 기준 주가 없으면 "첫 기록이에요. 다음 주부터 변화를 비교해 드려요") → 섹션 라벨 `section` "좋아진 점"(최대 3) / "지켜볼 점"(최대 2) / "꾸준히 지적되는 약점" + 항목 `muted` "· {문장}" → 진행 중이면 `hint` "월요일에 확정돼요".
3. **AI 코멘트 카드** (`GrowthCommentCard`): 제목 "AI 코멘트" + `hint` "{엔진 짧은 이름} · {시각}". 상태:

| 상태 (`comment_state`) | 본문 | 버튼 |
|---|---|---|
| done | `AnswerBrowser`(내용 높이에 맞춰 72~240px) | [다시 받기] |
| loading | "코멘트 작성 중…" | [취소] |
| in_progress | "주가 끝나면 자동으로 만들어져요" (확정 리포트가 아직 없으면 "첫 주가 끝나면 리포트가 만들어져요") | 없음 |
| skipped_low_data | "이 주는 기록이 적어 코멘트를 생략했어요" | 없음 |
| skipped_backlog | "밀린 주라 통계만 만들었어요" | [코멘트 받기] |
| failed | "코멘트를 만들지 못했어요 — {오류 제목}" | [다시 받기] |
| pending | "코멘트를 곧 자동으로 만들어요" | [코멘트 받기] |
| comment_off | "주간 AI 코멘트 자동 생성이 꺼져 있어요. …" | [코멘트 받기] (수동은 가능) |
| no_engine | "AI 엔진을 찾지 못해 코멘트를 만들지 못했어요" | [설정으로 이동] |
| (needs_consent) | 위 상태 문구 뒤에 " · 동의가 필요해요" + 배너 슬롯의 [동의하고 코멘트 받기] | |

4. **지표 카드** "이번 주 숫자" (`GrowthMetrics`): `BarChart`(최근 8주 Pass 문제 수, 선택 주 강조, 높이 120) + 지표 행 5개(Pass 문제 / 첫 시도 Pass 비율 / Pass 전 평균 오답 / 시간초과 비중 / 힌트·정답 풀이 사용). 행 = 이름(고정 132) · 값(`section`, 고정 112, 줄바꿈) · 변화(`hint`, "▲ 좋아짐 · 지난 기록 대비 +20%p" / "▼ 지켜볼 점 · …" / "변화 없음" / "비교 불가" — 화살표 글리프 + 글자 병기) · `SparkLine`(96×24, 8주).
5. **강점·약점 카드** "강점·약점 변화" (`GrowthCategories`): "자주 지적된 점(약점)" / "잘한 점(강점)" 각 최대 5행. 행 = 카테고리 이름(132) · 막대(`RateBar`, 높이 8, 길이는 응답당 평균 강도/3) + 값 글자 "점수 4 · 분류 4건 중" · 변화 글자(150) · `SparkLine`. 이번 주 분류가 3건 미만이면 "AI 코치를 더 사용하면 변화가 보여요 (이번 주 분류 {n}건)" 로 대체.
6. **지난 리포트 카드** (`GrowthHistory`): `QListWidget#GrowthReportList`(높이 120~220), 첫 행 "이번 주 (진행 중)", 그 뒤 최신순 최대 52개 "09-21 ~ 09-27 · Pass 5 · 좋아진 점 2" (미확인은 앞에 "새 · "). 선택 → 카드 갱신 + 맨 위로 스크롤. 기본 선택 = 가장 최근 확정 리포트(없으면 진행 중). 확정 리포트가 화면에 표시되는 순간 확인 처리(상태바 배지 갱신).

빈 상태(`GrowthEmpty`, EmptyState): "아직 기록이 없어요" / "문제를 제출하거나 AI 코치에서 평가·힌트를 받으면 쌓여요." 꺼짐 상태(`GrowthOff`): "성장 기록이 꺼져 있어요" + [설정으로 이동] (+ 배너).

**차트 위젯** (`gui/growth_widgets.py`, QPainter, 외부 라이브러리 없음, 색은 `tokens.LIGHT` 조회만):
- `BarChart`: 높이 120 고정, 막대 폭 ≤ 40·최소 6, 선택 주 `primary` + 굵은 라벨 / 나머지 `border_strong`, 값 0 은 2px 기준선만, 막대 위 숫자(`text_2`), x 라벨 "09-21"(`text_3`, 좁으면 격 주 생략). accessibleName "주별 Pass 문제 수" + accessibleDescription/툴팁 "09-21: 5, 09-28: 3 …".
- `SparkLine`: 96×24, `text_3` 1.5px 선, None 은 선을 끊고 점 생략, 마지막 점만 `primary` 원, 유효 값이 2개 미만이면 "-". accessibleDescription "{이름}: 첫값 → 끝값 (낮을수록 좋음)".
- 값·변화는 항상 옆 글자에도 있어 색·길이만으로 의미를 전달하지 않는다.

**설정 "성장 기록" 카드** (AI 코치 카드 다음): 체크박스 "성장 기록 사용"(`GrowthEnabledCheck`) + `hint`, 체크박스 "주간 AI 코멘트 자동 생성"(`GrowthCommentCheck`, 성장 기록이 꺼지면 비활성) + `hint`, "풀이 잔디 색" 행(§6.8), [성장 기록 지우기](확인창 "성장 리포트·분류 기록·풀이 잔디가 삭제됩니다") + `hint` "기록은 ~/.swea-fetch/coach/profile 에만 있고 GitHub 로 올라가지 않습니다". 저장은 즉시 `.env`.

**알림**: 상태바 배지 `QPushButton[class=link]#GrowthBadge` "새 성장 리포트 ↗"(2개 이상 "새 성장 리포트 {n}개 ↗", 클릭 → 성장 탭), 앱 시작 메시지 6초(복습이 있으면 "복습 {n}개 · 새 성장 리포트 — 최근/성장 탭에서 확인" 한 메시지), AI 코치 탭 푸터 아래 `muted` 팁 한 줄 `#GrowthTip` ("성장 팁 · 최근 3번 연속 '{이름}' 이(가) 지적됐어요. {팁}"). 토스트 없음.

### 6.8 풀이 잔디 (M20, 성장 탭 맨 위 카드 `#GrowthHeat`)

GitHub contribution 그래프처럼 하루에 Pass 한 문제 수를 칸으로 채운다. 성장 기록이 꺼져 있으면 카드는 숨기고(기존 꺼짐 안내만), 기록도 하지 않는다.

- **구성** (위 → 아래): 제목 `section` "지난 1년간 N문제 해결"(`#GrowthHeatTitle`) → `HeatmapWidget`(`#Heatmap`) → `HeatLegend`(`#HeatLegend`, 오른쪽 정렬 "적게 ▢▢▢▢▢ 많이") → `hint` 한 줄(첫 클릭 전만) → 선택한 날 제목(`#GrowthDayTitle`, "2026-09-30 (수) · 3문제" / 0문제 "… · 이날은 푼 문제가 없어요") → 문제 목록 `QListWidget#GrowthDayList`.
- **격자**: 53주 × 7일, 열 = 주, 행 = 요일, **일요일 시작**(GitHub 와 동일), 마지막 열이 오늘이 든 주, 미래 칸은 그리지 않는다. 칸 gap 3px, 모서리 2px. 왼쪽 요일 라벨 "월·수·금"(`text_3`, XS), 위 월 라벨 "9월"(월이 바뀌는 첫 열, 앞 라벨과 겹치면 생략).
- **칸 크기·좁은 창**: 폭에 맞춰 8~13px. 8px 로도 53주가 안 들어가면 **오른쪽 정렬로 오래된 주부터 자른다**(최신 주가 항상 보임, 최소 6주). 가로 스크롤 없음(720x480 규칙). 제목의 N 은 잘려도 1년 전체 기준. 높이는 칸 크기에 맞춰 조정(`setFixedHeight`).
- **농도**: 0칸은 `surface_alt`, 1~4단계는 **기준색 하나를 카드 배경(`surface`) 쪽으로 섞어** 만든다(기준색 비율 30 / 50 / 75 / 100%, 4단계 = 기준색). 하루 Pass 수 → 단계는 고정 임계값 **1 / 2 / 3 / 4+** (하루 5문제 넘게 푸는 사람은 드물어 GitHub 식 분포 기반보다 적게 푸는 사용자도 진해지는 보람이 있다). 임계값·비율은 `solved.HEAT_STEPS` / `HEAT_MIX` 한 곳. 다크 팔레트(`tokens.DARK`)가 생기면 그쪽 `surface`·`surface_alt` 로 자동 전환.
- **강조**: 오늘 칸은 `text` 1.5px 테두리, 선택한 칸은 `primary` 2px 테두리(오늘이면 안쪽에 겹침). 색으로만 의미를 전달하지 않는다 — 문제 수는 툴팁·접근성 설명·선택 목록 글자에 있다.
- **상호작용**: hover 툴팁 "2026-09-30 (수) · 3문제"(0 이면 "0문제"), 칸 위에서 손가락 커서. 칸 클릭 → 아래 목록("{번호} · {제목} · {주제} · SWEA|로컬", 최대 6줄 높이, 가로 스크롤 없음·말줄임), 목록 항목 클릭/Enter → `problem_requested(topic, num)` → `MainWindow._open_recent_problem`(최근 탭과 같은 흐름: 캐시 있으면 즉시, 없으면 지문만 가져오기).
- **집계**: Pass 한 문제 = 앱으로 낸 SWEA 제출 Pass(`SWEA`) + 로컬 검증 통과(`로컬`, 샘플 출력 일치; CLI `check` 와 GUI 검증 모두). 같은 날 같은 문제는 1번(둘 다 있으면 SWEA 로 표시). 날짜는 로컬 날짜.
- **색 설정**: 설정 "성장 기록" 카드 안 "풀이 잔디 색" 행 — 프리셋 원형 칩 5개(초록 `#2DA44E` 기본 · 파랑 · 보라 · 주황 · 분홍, 선택은 3px `text` 테두리) + [직접 고르기](`QColorDialog`; 프리셋이 아닌 색이면 버튼 왼쪽에 그 색 띠). QSettings `growth/heat_color`("#RRGGBB", 잘못된 값은 기본 초록), 변경 즉시 성장 탭에 반영(`heat_color_changed` 신호).
- **저장**: `~/.swea-fetch/coach/profile/solved.json` (`{"v":1,"days":{"YYYY-MM-DD":[{num,topic,title,via,at}]}}`, 400일 보관, 코드·지문 원문 없음, 루트 안이면 쓰기 거부). [성장 기록 지우기]·[AI 기록 지우기]·`logout --all` 이 함께 지운다. 첫 로드 때 기존 기록에서 백필(growth submit Pass 120일 + AI 코치 기록의 마지막 Pass) — 로컬 검증 과거 기록은 없어 불가. 백필은 1회(`coach/solved_backfilled` 표식; [성장 기록 지우기] 뒤에 되살아나지 않게 `profile/` 밖).

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
| `AiEngineMissing` | warning | AI 엔진을 찾지 못했습니다 (본문 = 설치 안내) | [설정으로 이동] | — |
| `AiRunFailed` / `AiTimeout` | error | {엔진} 실행 실패 (코드 N) / 응답이 300초를 넘어 중단 (본문 = hint + stderr 끝) | [다시 시도] (`coach-retry`) | — |
| 예상 밖 `Exception` | error | 내부 오류: {type} | [로그 보기] (로그 펼치고 스크롤) | — |

`AlreadyExists`·`AttachmentNotFound` 는 "실패"가 아니라 "선택이 필요한 상황"이므로 warning 이다. 배너의 재실행 버튼은 폼의 체크박스 상태도 함께 바꾼다 (덮어쓰기 체크 on) — 사용자가 무엇이 달라졌는지 보게.

조치 버튼 키 (구현 `Banner.action_clicked(key)`): `force` 덮어쓰고 다시 저장 · `skeleton` 뼈대만 저장 · `refresh` 색인 새로고침 후 재시도 · `retry` 다시 시도 · `settings` 설정으로 이동 · `fetch` 저장 페이지로 · `log` 로그 보기. 배너당 최대 2개 ("이미 저장된 문제" 만 [에디터에서 열기]·[문제 보기]·[덮어쓰고 다시 저장] 3개, `editor`·`view` 키), 본문 아래 오른쪽 정렬 행.

---

## 10. 키보드·접근성

- 탭 순서(저장): 번호 → 주제 → 덮어쓰기 → 뼈대만 → 색인 → [저장] → [미리보기] → 결과 카드 버튼 → 로그 토글. 내비는 Ctrl+1~6 (Tab 순서에서는 맨 앞). M19 로 성장이 Ctrl+5, 설정이 Ctrl+6.
- 단축키: Enter = 저장(번호·주제 입력에서), Ctrl+Enter = 미리보기, Esc(저장 페이지) = **배너가 보이면 배너 닫기, 아니면 로그 지우기** (배너는 포커스를 받지 않으므로 표시 여부로 판단), F5 = 최근 새로고침, Ctrl+, = 설정, Ctrl+1~6 = 페이지 (순서: 저장·문제·검증·최근·성장·설정).
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
| `nav-growth.svg` | 내비 "성장" (축 + 상승 꺾은선) | M19 |
| `nav-settings.svg` | 내비 "설정" (슬라이더 3줄) | |
| `status-success.svg` / `status-error.svg` / `status-warning.svg` | 배너·카드 상태 아이콘, 채움형 | 색은 각 시맨틱 원색 + 흰 글리프 |
| `app.svg` | 앱 아이콘 (primary 둥근 사각 + 흰 트레이 화살표) | `.ico` 는 빌드 단계에서 생성: `python -c "from PIL import Image; ..."` 또는 `cairosvg` — 256/48/32/16 포함. 저장소에 `design/icons/app.ico` 로 커밋 (바이너리 ~50KB 허용) |
| `coach-hint.svg` | AI 코치 [힌트] 버튼 전구 (16×16) | M17 |
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

---

## 16. M21 토스 스타일 리프레시

**요청**: "전체적인 디자인이나 애니메이션을 개선, 토스(Toss) 앱 같은 깔끔한 UI". 기존 규칙은 §1~§15 가 유효하되 값·치수는 이 절이 덮어쓴다. 토스의 **브랜드 자산(로고·아이콘·일러스트)은 쓰지 않고** 시각 원칙(여백·위계·무테 카드·큰 숫자·부드러운 동작)만 참고한다.

### 16.1 방향 (한 문장)

**"회색 바닥 위에 흰 카드 한 장씩, 한 화면에 질문 하나·행동 하나"** — 테두리 대신 면의 명도 차(`#F2F4F6` 바닥 / `#FFFFFF` 카드)로 층을 만들고, 굵은 큰 제목과 큰 숫자로 위계를 만들며, 상태 변화는 120~250ms 짧은 ease-out 으로 알린다.

근거 (바뀌는 이유)
- 현재는 모든 박스가 1px 테두리 + 6px 라운드라 "카드 안의 카드 안의 박스"(검증 탭 AI 코치 패널)가 겹쳐 보이고, 글자 위계가 크기 3단계(13/15/17px)뿐이라 어디부터 읽을지 모호하다.
- 이 앱의 핵심 장면은 "번호 입력 → 저장" 한 동작(3~10초)이다. 토스식 "큰 입력 + 큰 CTA 하나"가 그대로 맞는다. 밀도가 필요한 곳(로그, 설정, diff)은 카드 안에서 유지한다.
- 사용자(= 이 앱 주인)의 직접 요청. 단, 접근성(AA)은 양보하지 않는다 — 토스 원색 `#3182F6` 위 흰 글자는 3.7:1 이라 **글자가 얹히는 버튼은 한 단계 진한 `primary_action` 을 쓴다**(§16.2 결정 D1).

### 16.2 결정 요약

| # | 결정 | 이유 |
|---|---|---|
| D1 | 주색 이원화: `primary #3182F6`(글자 없는 면·링·차트·토글) + `primary_action #1F6FE8`(흰 글자가 얹히는 버튼 면, 4.66:1) | AA. 정확히 토스 파랑을 버튼에도 쓰려면 버튼 글자를 17pt bold 이상(큰 글자 3:1)으로 키워야 해 비현실적. 시각 차이는 미미 |
| D2 | **Pretendard 번들** (Regular 400 + Bold 700, 원본 무수정) — §16.3 | 한글 가독성·숫자 모양이 토스 느낌의 절반. Malgun Gothic 은 폴백으로 유지 |
| D3 | 카드 그림자 **사용 안 함** (무테 + 명도 차). 그림자는 토스트만, `paintEvent` 로 직접 그림 | QSS 는 box-shadow 미지원, `QGraphicsDropShadowEffect` 는 자식 글자를 래스터화(ClearType→회색조)해 흐려지고 스크롤 영역에서 느림 |
| D4 | 라이트 전용 유지. 다크는 **이번 범위 밖** (토큰 이름만 대비) — §16.14 | 팔레트 2벌 검증·캡처가 마일스톤 하나 분량. 새 위젯이 색을 `Palette` 에서만 읽게 해 두면 나중에 `DARK` 만 채우면 됨 |
| D5 | 내비 선택 = 둥근 알약 배경이 **슬라이드 이동** (색 띠·밑줄 아님) | 토스식 + 애니메이션 요구. 모션 off 면 즉시 이동 |
| D6 | 즉시 반영되는 "켜기/끄기" 체크박스 → **토글 스위치**, 폼의 일회성 옵션은 **원형 체크박스** 유지 | 토글 = "지금 상태가 바뀐다", 체크 = "이번 실행에만 적용" 의미 구분 |
| D7 | 성공·확인 알림 = **토스트** 신설. 오류·선택 필요·결과 = 기존 **배너 유지**(조치 버튼이 있으므로). §3 "토스트 없음" 폐기 | 토스트는 사라지므로 조치가 필요한 정보에 부적합 |
| D8 | 동작 줄이기: OS 설정(Windows 애니메이션 효과) 자동 존중 + 설정 체크박스 + 환경변수. 테스트는 기본 off | §16.9 |
| D9 | 풀이 잔디 기본색은 **초록 유지** (파랑으로 바꾸지 않음) | "잔디"=초록이라는 은유, 기존 사용자 저장값·테스트 보존. 파랑은 기존 프리셋에 있음 |
| D10 | 창 기본 880×600 / 최소 720×480 유지. 사이드바 148→**160** | 컨트롤이 커져 폭 여유가 줄어 최소 증가분만 |

### 16.3 글꼴

**결정: Pretendard 번들 (Regular 400 · Bold 700 두 파일).** 이전 §2.2 의 "번들 안 함" 결정을 폐기한다.

| 항목 | 내용 |
|---|---|
| 라이선스 | SIL OFL 1.1. 앱에 번들·재배포 허용(폰트 단독 판매만 금지). 조건: 라이선스 전문 동봉, **원본 무수정**(서브셋·이름 변경 금지 — Reserved Font Name 때문. 구현 시 저장소 `LICENSE.txt` 로 RFN 문구 재확인) |
| 용량 | 정적 OTF 1개 약 1.5~2MB → 2개 약 3~4MB (구현 시 실측해 이 문서에 기입). 현재 onefile exe 의 PySide6 본체 대비 한 자리 % 증가 |
| 왜 전체 글리프 | 문제 지문·AI 답변이 임의 한글을 렌더링하므로 완성형 11,172자 필요 → GOV/서브셋 불가 |
| 왜 2웨이트 | Windows·Qt 에서 SemiBold 가 별도 패밀리명("Pretendard SemiBold")으로 등록돼 `font-weight:600` 이 안 먹는 사례가 있다. 400/700 만 쓰면 Malgun 과 같은 선택 로직이라 안전. 가변(Variable) 폰트도 같은 이유로 제외 |
| 위치 | `swea_fetcher/gui/theme/fonts/Pretendard-Regular.otf`, `Pretendard-Bold.otf`, `Pretendard-LICENSE.txt` |
| 로딩 | `gui/theme/fonts.py::load_fonts()` — `QApplication` 생성 직후·QSS 적용 전, `QFontDatabase.addApplicationFont`. 실패해도 예외 없이 로그 한 줄 후 폴백(앱은 계속 동작) |
| 폴백 체인 | `FONT_FAMILY = '"Pretendard", "Malgun Gothic", "Segoe UI", sans-serif'` — 롤백 = 폰트 파일·로딩 호출 제거만 |
| PyInstaller | `packaging/swea-fetch-gui.spec` 의 `datas` 에 `(str(PKG/"gui"/"theme"/"fonts"), "swea_fetcher/gui/theme/fonts")` 추가 (아이콘과 같은 방식, `Path(__file__).parent` 기준 경로가 onefile 에서도 동작). 빌드 후 exe 에서 한글 렌더·두 웨이트 차이 육안 확인 |
| 고정폭 | 변경 없음 (Consolas 등). 한글 문장 mono 금지 규칙(§2.2) 유지 |
| 가중치 규칙 | 400 / 700 두 개뿐. QSS 에서 `font-weight: 600` 금지 → `700` 또는 생략 |
| 숫자 정렬 | Qt 6 QSS 에 `tnum` 지정 수단이 없다. 카운트업·타이머 라벨은 **우측 정렬 + 최소 폭 고정**(예: 4자리 폭)으로 흔들림 방지 |

### 16.4 디자인 토큰 (LIGHT, `tokens.py` 갱신값)

**색** (`Palette` 필드명 유지, 신규 필드는 기본값 부여해 기존 생성 코드 호환)

| 토큰 (필드) | 값 | 용도 |
|---|---|---|
| `bg` | `#F2F4F6` | 창·페이지 바닥 (토스 grey100) |
| `bg_subtle` (신규) | `#F9FAFB` | 표 hover, 카드 안 보조 면, AnswerBrowser 배경 |
| `surface` | `#FFFFFF` | 카드·사이드바 |
| `surface_alt` | `#F2F4F6` | 입력창 채움, 로그 필드, 표 머리글 없음, 0단계 잔디, 스켈레톤 기본 |
| `border` | `#E5E8EB` | 구분선(표 행, 카드 내 divider)만. 카드 외곽선은 **없음** |
| `border_strong` | `#D1D6DB` | 스크롤바 핸들, 차트 비선택 막대, 스켈레톤 하이라이트 |
| `control_border` (신규) | `#8B95A1` | 체크박스·라디오 미선택 테두리(2px) |
| `text` | `#191F28` | 제목·본문 1단계 |
| `text_2` | `#4E5968` | 2단계: 레이블, 보조 설명, 로그 본문 |
| `text_3` | `#636E7C` | 3단계: 힌트, 표 머리글, 상태바. **토스 `#8B95A1` 대신** (아래 대비표: `#8B95A1` 는 회색 바닥 위 2.7:1 로 AA 불가) |
| `text_placeholder` (신규) · `text_disabled` | `#8B95A1` | 플레이스홀더·비활성·장식 글자 전용 (AA 예외 — 모든 입력은 위에 보이는 레이블이 있어 플레이스홀더는 예시일 뿐) |
| `primary` | `#3182F6` | 포커스 링, 진행 막대, 토글 ON, 체크 원, 차트 선택, 스피너 (글자 없는 면) |
| `primary_action` (신규) | `#1F6FE8` | primary 버튼 면 (흰 글자 4.66:1) |
| `primary_hover` / `primary_pressed` | `#1B64DA` / `#1957C2` | primary 버튼 hover/pressed |
| `primary_text` | `#FFFFFF` | primary 버튼 글자 |
| `primary_soft` / `primary_soft_text` | `#E8F3FF` / `#1957C2` | 내비 선택 알약, info 배너, tonal 버튼, running 배지 (5.9:1) |
| `primary_soft_hover` / `_pressed` (신규) | `#D3E8FF` / `#C0DDFF` | tonal 버튼 |
| `secondary` / `_hover` / `_pressed` (신규) | `#F2F4F6` / `#E5E8EB` / `#D1D6DB` | 회색 보조 버튼 (글자 `#333D4B`, 9.9:1). **카드 안에서만** 사용 — 바닥(`bg`) 위에서는 같은 색이라 안 보이므로 tonal/link 사용 |
| `success` / `_bg` / `_text` | `#0A9B5E` / `#E6F8F0` / `#00794A` | 아이콘·점 / 배너·배지 면 / 면 위 글자 |
| `warning` / `_bg` / `_text` | `#D97800` / `#FFF4E0` / `#8A5100` | 〃 |
| `error` / `_bg` / `_text` | `#F04452` / `#FFEEEE` / `#C62B38` | 〃 (invalid 입력 2px 테두리는 `error`) |
| `toast_bg` / `toast_text` (신규) | `#333D4B` / `#FFFFFF` | 토스트·툴팁 (11:1) |
| `diff_*` | same `#FFFFFF` / changed = `warning_bg` / missing = `error_bg` / extra = `primary_soft` | 기존 규칙 유지 |

대비 검증 (계산값, WCAG AA 4.5:1 글자 / 3:1 그래픽)

| 조합 | 비율 | 판정 |
|---|---|---|
| `text` on `surface` / on `bg` | 16.6 / 14.9 | OK |
| `text_2` on `surface` / `bg` | 7.1 / 6.4 | OK |
| `text_3 #636E7C` on `surface` / `bg` | 5.2 / 4.7 | OK (가장 약한 조합 — 이보다 연한 글자 금지) |
| (참고) 토스 `#8B95A1` on `bg` | 2.7 | **불가** → `text_placeholder` 전용 |
| `primary_text` on `primary_action` | 4.66 | OK |
| (참고) 흰 글자 on `#3182F6` | 3.7 | 글자 불가, 그래픽 OK |
| `primary` 링/면 on `surface` | 3.7 | 그래픽 3:1 OK |
| `primary_soft_text` on `primary_soft` | 5.9 | OK |
| `success_text` on `success_bg` / `warning_text` on `warning_bg` / `error_text` on `error_bg` | 5.0 / 5.9 / 4.9 | OK |
| 토스트 `toast_text` on `toast_bg` | 11 | OK |
| 입력 채움 `surface_alt` on `surface` 경계 | 1.1 | **수용된 예외** — 레이블이 항상 보이고, 포커스 시 2px `primary`(3.7) 링, 오류 시 `error` 링 + 문구 |
| 토글 OFF 트랙 `#B0B8C1`, 체크 원 | — | 의미는 손잡이 위치·체크 글리프·옆 레이블로도 전달 (색 단독 아님) |

**글꼴 크기·굵기** (pt, 96dpi px 환산)

| 토큰 | pt (px) | 굵기 | 용도 |
|---|---|---|---|
| `FONT_SIZE_XS` | 9 (12) | 400 | 배지(700), 상태바, 표 머리글, 차트 축 |
| `FONT_SIZE_SM` | 10 (13) | 400 | 힌트, 로그, 배너 본문, 표 본문 보조 |
| `FONT_SIZE` | 10.5 (14) | 400 | 본문, 입력, 버튼, 내비, 표 본문 |
| `FONT_SIZE_MD` | 12 (16) | 700 | 카드 제목, 섹션 제목, 앱 이름, 큰 입력(번호) 글자 |
| `FONT_SIZE_LG` | 17 (≈23) | 700 | 페이지 제목 |
| `FONT_SIZE_XL` (신규) | 22 (≈29) | 700 | 숫자 강조(잔디 N문제, 지표 값, 리포트 주간 Pass) |

굵기는 400 / 700 두 값만. 본문 줄 간격은 지문·AI 답변 CSS 에서 `line-height:150%`(Qt rich text 지원 부분집합), 일반 라벨은 Qt 기본.

**간격 (4 스케일 확장)**: 4 · 8 · 12 · 16 · 20 · 24 · 32 · 40. (`SPACE`=8 의 배수 + `SPACE*5/2`=20, `SPACE*5`=40 허용 — 20·40 이 신규)

| 용도 | 값 |
|---|---|
| 페이지 좌우·상단 여백 | 32 (너비 < 800 이면 24) / 하단 24 |
| 페이지 제목 ↔ 첫 카드 | 24 |
| 카드 ↔ 카드 | 16 |
| 카드 내부 패딩 | 24 (너비 < 800 이면 20) |
| 섹션 제목(밖) ↔ 카드 | 12, 섹션 ↔ 섹션 32 |
| 폼 행 ↔ 행 | 20, 레이블 ↔ 입력 8 (레이블은 입력 **위**) |
| 버튼 사이 | 8 (CTA 줄) |
| 내용 최대 폭(`PageColumn`) | 840, 가운데 정렬 (저장·검증·성장·설정). 최근·문제 페이지는 전폭 |

**라운드·선·그림자**

| 토큰 | 값 | 용도 |
|---|---|---|
| `RADIUS_SM` | 8 | 작은 버튼(sm), 칩, 툴팁, 표 행 hover, 배지 내부 막대 |
| `RADIUS_MD` | 12 | 입력, 버튼, 내비 알약, 배너, 로그 필드, AnswerBrowser, 토스트 |
| `RADIUS` (카드) | 16 | 카드, 표 컨테이너, 탭 pane 안 패널 |
| `RADIUS_PILL` | 999 | 배지, 토글, 원형 체크(반지름 11) |
| 잔디 칸 | 3 | (기존 2) |
| 테두리 | 카드·버튼·입력 **없음**. 구분선 1px `border`. 포커스 링 2px `primary`(입력·버튼), 체크박스·토글은 외곽 2px `primary` 링 |
| 그림자 | 카드 없음. 토스트만 `paintEvent` 로 3겹 둥근 사각(alpha 10/6/3%, 확장 4/10/18px, y오프셋 6). QGraphicsDropShadowEffect **금지** |

**컨트롤 크기**

| 토큰 | px |
|---|---|
| `CONTROL_H` (입력·기본 버튼) | 44 |
| `CONTROL_H_LG` (신규: 번호 입력, 페이지 CTA) | 52 |
| `CONTROL_H_SM` (배너·표 안 버튼) | 36 |
| `NAV_ITEM_H` | 44 (항목 사이 gap 4, 알약 좌우 8 마진) |
| `SIDEBAR_W` | 160 |
| 표 행 높이 | 52 (최근), 44 (diff) |
| 상태바 높이 | 32 |
| `PROGRESS_H` | 4 (라운드 2) |
| 토글 | 44×26, 손잡이 20 |
| 원형 체크/라디오 | 22 |
| 아이콘 | 내비 20, 인라인 16, 빈 상태 원형 배경 64 (아이콘 28) |

최소 클릭 대상: 어떤 컨트롤도 높이 36 미만 금지(아이콘 전용 28×28 예외 유지).

### 16.5 컴포넌트별 변경

공통: 위젯 코드에 색 리터럴·`setStyleSheet` 금지(§13) 유지. 새 커스텀 페인팅 위젯(`Button`, `Toggle`, `Toast`, `Spinner`, `Skeleton`)도 색은 `tokens.LIGHT`(나중엔 현재 팔레트)에서만 읽는다.

**앱 셸·사이드 내비**
- 사이드바: `surface`, **우측 border 제거**(바닥 `bg` 와의 명도 차로 분리). 앱 이름 `md` 700, 패딩 24/24/16/24.
- 항목: 높이 44, 아이콘 20 + 글자 `base`, 좌우 패딩 12, 알약 라운드 12, 비선택 글자 `text_2` / 아이콘 `text_2`, hover 배경 `secondary`(#F2F4F6) · 글자 `text`.
- 선택: 알약 배경 `primary_soft`, 글자·아이콘 `primary_soft_text` 700. **알약은 이동한다**(§16.7 A2): `NavDelegate` 가 항목 사각형과 "움직이는 알약 사각형"의 교집합을 칠한다(항목 간 gap 은 항목 rect 안 투명 여백으로 처리해 이동 중 끊기지 않게). 모션 off 면 즉시 현재 항목에 칠함.
- 키보드 포커스: Fusion 점선 유지가 아니라 **2px `primary` 라운드 12 링**을 델리게이트가 그림(`State_HasFocus` 일 때, 마우스 선택 시엔 안 그림). §10 "outline 0 금지" 의도(포커스 위치 가시)는 동일.

**버튼** — `widgets.Button(QPushButton)` 서브클래스로 교체(기존 `QPushButton(` 생성부 치환; `QPushButton` 상속이라 테스트의 `findChildren(QPushButton)`·클릭 시뮬레이션은 영향 없음). 배경·포커스 링은 `paintEvent` 가 직접 그려 **hover/pressed 색 보간과 pressed 축소**를 가능하게 하고, 글자·아이콘·패딩·최소 크기는 QSS 가 담당(QSS 에서는 `background: transparent; border: none`).

| class | 높이 | 면(default / hover / pressed) | 글자 | 비고 |
|---|---|---|---|---|
| `primary` | 52(`lg` 페이지 CTA) 또는 44 | `primary_action` / `primary_hover` / `primary_pressed` | `primary_text` 700 | 페이지당 1개 규칙 유지. 최소 폭 96, 저장 CTA 는 가로로 늘어남(stretch 2 : 보조 1) |
| (기본) secondary | 44 | `secondary` / `_hover` / `_pressed` | `#333D4B` | 카드 안 전용 |
| `tonal` (신규) | 44 | `primary_soft` / `_hover` / `_pressed` | `primary_soft_text` 700 | 바닥 위 버튼, AI 코치 제안 버튼([코드 평가 받기], [힌트], [정답 풀이 보기]) |
| `danger` | 44 | `error_bg`(저면 투명 → hover 시 `error_bg`) | `error_text` | 텍스트형 위험 버튼. pressed `#FFDDDD` |
| `link` | 자동 | 투명 / `secondary` / `secondary_hover` | `primary_soft_text` | 라운드 8, 패딩 4×8 |
| `sm` | 36 | 위 variant 에 동일 | `sm` 크기 | 배너 안 버튼, 표 안 |
| disabled | — | primary: `border` `#E5E8EB`, 그 외 `bg_subtle` | `text_disabled` | primary disabled 도 면 유지(사라지지 않음) |
| busy | — | 비활성 + 왼쪽 `Spinner`(16px, 글자색) + 기존 "저장 중…" 라벨 | | `Button.set_busy(bool)` |

- 라운드 12(sm 은 8). 포커스 링 2px `primary`, 면에서 2px 바깥(오프셋)으로 그려 크기 유지(QSS padding 1px 보정 불필요 → §13 의 보정 규칙 폐기).
- pressed: 면이 중심 기준 **0.97 배 축소**(그림만, 위젯 영역 불변), release 시 복귀.

**입력 (QLineEdit/QComboBox/QSpinBox)**
- 채움 `surface_alt`, 테두리 없음(투명 2px 로 두께 확보), 라운드 12, 높이 44, 글자 `base`, 좌우 패딩 16, 플레이스홀더 `text_placeholder`.
- hover: 채움 `#E5E8EB`. focus: 채움 `surface`(흰) + 2px `primary` 테두리 (카드 안에서 떠 보임). invalid: 2px `error` 테두리 + 하단 `error` 문구(§8 유지, 문구는 `error_text`). disabled: 채움 `bg_subtle`, 글자 `text_disabled`.
- 번호 입력 `QLineEdit[class="mono"]`: 높이 52, 글자 `md`(mono 유지). 레이블은 입력 **위**(QFormLayout `WrapAllRows` — 폼 레이아웃 구조는 유지하고 정책만 변경).
- 콤보 팝업: 흰 배경, 라운드 12, 항목 높이 40, 선택 `primary_soft`, 테두리 없음.

**체크박스·토글·라디오**
- 폼의 일회성 옵션(덮어쓰기·뼈대만·색인 새로고침, 비밀번호 표시): 원형 체크 22px — 미선택 2px `control_border` 테두리 흰 면, 선택 `primary` 채움 + 흰 체크(`check-white.svg`), 글자 `base`, 간격 8.
- **토글** (`widgets.Toggle(QCheckBox)` 서브클래스, 기존 objectName·`toggled`·`isChecked` 유지): 설정 페이지의 즉시 저장 옵션(성장 기록 사용, 주간 AI 코멘트 자동 생성, GitHub 자동 동기화 켜기, 동작 줄이기). 행 = 글자(왼쪽) + 스위치(오른쪽, 44×26 · OFF 트랙 `#B0B8C1`, ON 트랙 `primary`, 흰 손잡이 20). 손잡이 이동 180ms(§16.7). 키보드 Space, 포커스 2px 링.
- 라디오(범위): 원형 22px 동일 문법(선택 시 안쪽 흰 점 8px + 면 `primary`). 시점 같은 다중 선택은 체크박스.

**카드 (`QFrame[class=card]`)**: 면 `surface`, 테두리 **없음**, 라운드 16, 패딩 24. 드롭 상태(`state=drop`)는 2px `primary` 테두리 + 면 `primary_soft`. 카드 안 카드 금지 — 하위 패널은 `surface_alt`/`bg_subtle` 면 + 라운드 12(테두리 없음).

**배너 (Banner, 유지)**: 테두리 제거, 면 `*_bg`(info = `primary_soft`), 라운드 12, 패딩 16, 아이콘 20 + 제목 `base` 700 `*_text` + 본문 `sm` `text_2`, 조치 버튼 `sm`(secondary 대신 면 `surface` 흰 + 글자 `*_text`, hover `bg_subtle`). 닫기 ✕ 는 `QToolButton` 28×28. 등장 = 페이드 180ms(§16.7).

**토스트 (신설 `widgets.Toast`)**
- 용도: 끝난 일의 확인(폴더를 열었습니다, 로그를 지웠습니다, 복사했어요, 설정을 저장했어요 등 현재 `statusBar().showMessage` 로 내던 성공성 메시지). **오류·선택 필요·결과는 토스트 금지**(배너/카드).
- 모양: 중앙 창 하단 중앙, 상태바 위 24px 띄움, 면 `toast_bg`, 글자 `toast_text` `base`, 라운드 16, 패딩 14×20, 최대 폭 480(넘으면 elide), 선택적 왼쪽 상태 아이콘 16(success 아이콘 흰색). 그림자 §16.4.
- 동작: 한 번에 1개(새 메시지는 기존 것을 즉시 교체), 표시 2400ms(경고성은 4000), 클릭하면 닫힘, 포커스를 가져가지 않음. 등장/퇴장 §16.7.
- API: `MainWindow.notify(message, kind="success", ms=2400)` — **토스트와 함께 기존 `statusBar().showMessage(message, ms)` 도 그대로 호출**한다(스크린리더 접근·기존 테스트 호환). 진행 중 메시지("지문 가져오는 중…")는 토스트 없이 상태바만.

**배지**: pill(999), 패딩 4×10, `xs` 700, 면/글자는 `*_bg`/`*_text`, idle = `surface_alt`/`text_2`. 항상 글자 포함(§10).

**표 (최근 탭, QTableWidget)**: 컨테이너 면 `surface` 라운드 16 무테(바깥 padding 8). 머리글: 면 투명, 글자 `text_3` `xs` 700, 하단 구분선 없음, 높이 36. 행 높이 52, 구분선 1px `border`(좌우 16 안쪽 인셋은 QSS 로 불가 → 전폭 선 허용), hover `bg_subtle`, 선택 `primary_soft`, 번호 열 700. "새로고침"은 바닥 위이므로 `tonal` 으로. "복습" 카드 항목은 행 형태(링크 버튼 + 상태 글자)·✕ 유지. 안내 한 줄("클릭 = …")은 표 **아래** `hint` 로 이동하지 않고 제목 아래 유지(레이아웃 불변).

**탭 (QTabWidget, 검증 결과)**: 탭 바 = 글자만(`base`), 비선택 `text_3`, 선택 `text` 700 + 하단 3px `text` 밑줄(라운드 2), hover `text_2`. **pane 은 면 투명·테두리 없음**(현재 흰 외곽이 EnginePane 카드와 이중 박스를 만듦 — 가장 눈에 띄는 개선점). 탭 사이 gap 20.

**로그 영역 (LogView)**: 로그 전체를 카드(`class=card`, 패딩 16)로 감싸고, 머리글 행 = 토글 "▼ 로그"(`md`) + 오른쪽 텍스트형 "지우기"(`link`, `sm`). 본문 `QPlainTextEdit#log` 는 면 `surface_alt`, 테두리 없음, 라운드 12, 패딩 16, `sm` `text_2`, 줄 간격 150%. 비었을 때 안내 "진행 로그가 여기에 표시됩니다" 는 `text_placeholder`가 아니라 `text_3`. 기본 높이 140(변경 없음).

**상태바**: 면 `bg`(바닥과 동일), 상단 border 제거, 높이 32, 글자 `xs` `text_3`. 로그인 점 라벨: ● `success`(점)+ "로그인됨" `success_text` / ○ `text_3`. 경로 라벨은 그대로. 복습·성장 배지(`link`)는 `tonal` pill 형(`primary_soft`, 라운드 999, 높이 24).

**코치 바 (CoachBar)**: 카드(무테). 문장 `base` `text`(기존 muted → 본문 승격), 버튼은 `tonal`. 문장 앞 16px 전구/체크 아이콘은 추가하지 않는다(범위 밖).

**코치 답변 패널 (EnginePane)**: 카드(무테 16). 머리글 = 엔진 이름 `md` 700 + 메타 `xs` `text_3` + 캐시 배지, 오른쪽 `sm` secondary [다시 받기]. 본문 `AnswerBrowser`: 면 `bg_subtle`, 테두리 없음, 라운드 12, 패딩 16(두 번째 카드 안 박스 대신 **면 구분**). 답변 CSS(`build_statement_css`): h1 `md`(16px) 700, h2 `base`+ 700 15px, h3 14px 700, 본문 14px·`line-height:150%`, 코드 블록 면 `surface_alt` 라운드 불가 → 면+패딩만, 표 테두리 `border`. 로딩 패널은 §16.7 의 스켈레톤.

**성장 탭**
- 풀이 잔디 카드: 제목 한 줄에 숫자 강조 — "지난 1년간 **178**문제 해결" 에서 숫자만 `xl` 700 `primary_soft_text`, 나머지 `md` 700 `text`(한 라벨에 rich text 한 줄, `#GrowthHeatTitle` 유지, 접근성 이름은 평문). 격자 칸 라운드 3, gap 3, 0단계 `surface_alt`, 요일·월 라벨 `xs` `text_3`. 오늘 칸 테두리 1.5px `text`, 선택 칸 2px `primary`(기존 유지). 범례 `xs`.
- 리포트 헤더 카드: 주간 범위 `md` 700, 오른쪽 배지. 그 아래 **큰 숫자 줄**: "Pass N문제"(N `xl` 700) + 변화 `sm`("▲ 지난 주보다 +2" `success_text` / "▼ …" `warning_text` / 글자 병기 유지). "좋아진 점/지켜볼 점/약점" 섹션 라벨 `base` 700, 항목은 "·" 대신 6px `*` 색 점 + `base` `text_2`(색 점 + 글자 두 가지로 의미 전달).
- AI 코멘트 카드: 제목 `md` 700 + `xs` 메타. 본문 `AnswerBrowser`(위 규칙). 상태 문구는 `text_2`.
- 지표 카드 "이번 주 숫자": **타일 그리드**가 목표 — 2열(< 560px 1열) 타일(면 `bg_subtle`, 라운드 12, 패딩 16): 이름 `sm` `text_3` → 값 `xl` 700 → 변화 `xs` 글자+화살표 → `SparkLine`(우하단 96×24). `BarChart` 는 타일 위 전폭(높이 120→140), 막대 위쪽 모서리 라운드 4, 비선택 `border_strong`, 선택 `primary`. 구현 부담이 크면 **대체안**: 기존 행 레이아웃 유지 + 값 라벨만 `xl`→`md` 700 으로(구조 변경 0). 기존 테스트가 행 구조에 의존하므로 builder 가 판단(§16.11 M21-D 단계에서 결정, 기준 문서에 기록).
- 강점·약점 카드: `RateBar` 높이 8→10, 라운드 5, 트랙 `surface_alt`, 막대 `primary`(약점은 `warning`, 강점은 `success` — 이름 옆에 "약점/강점" 소제목이 이미 있어 색 단독 아님).
- 지난 리포트 목록(`QListWidget`): 면 투명, 항목 높이 48, 라운드 12 hover `bg_subtle`·선택 `primary_soft`.

**설정 페이지**: `PageColumn`(최대 840) 안에서 섹션 구조 유지(계정/검증/GitHub 연동/문제 지문/AI 코치/성장 기록 + **신설 "화면" 카드**). 섹션 제목(카드 밖)은 `md` 700 `text`, 카드 패딩 24, 필드는 레이블 위·입력 아래(`WrapAllRows`), 설명 `hint` 입력 아래 4px. 각 섹션의 주 행동 1개만 `primary`(계정의 [저장 후 로그인 확인]), 나머지 secondary. 즉시 저장 옵션은 **행 단위 토글**(글자 + hint 2줄 왼쪽, 스위치 오른쪽) — 행 사이 구분선 1px `border`. [성장 기록 지우기]·[AI 기록 지우기]·[계정 정보 삭제]는 `danger` 텍스트형을 카드 맨 아래 "위험 영역" 소제목 아래에 모은다(스펙 §7 확인 다이얼로그 불변).
- **신설 "화면" 카드** (맨 아래, 성장 기록 카드 다음): 토글 "동작 줄이기" (`ReduceMotionToggle`) + hint "화면 전환·버튼 효과 같은 움직임을 끕니다. Windows 의 '애니메이션 효과'가 꺼져 있으면 이 설정과 관계없이 항상 꺼집니다." QSettings `ui/reduce_motion`(bool, 기본 False). 변경 즉시 적용(`motion.set_user_reduce(bool)`).

**빈 상태 (EmptyState)**: 선택적 `icon` 인자 추가 — 64px 원(면 `primary_soft`) 안 28px 아이콘(`primary_soft_text` 재착색), 제목 `md` 700 `text`(기존 `empty-title` 를 `md`+700 으로), 본문 `sm` `text_3`, CTA 는 `primary`(있을 때 한 개). 아이콘 인자는 선택이라 기존 호출 불변. 문제 페이지는 `nav-problem`(= nav-fetch 계열 문서 아이콘) 재사용.

**스크롤바**: 폭 8, 핸들 `border_strong` 라운드 4(hover `text_placeholder`), 트랙 투명, 화살표 없음. **툴팁**: 면 `toast_bg`, 글자 `toast_text`, 라운드 8, 패딩 6×10.

**다이얼로그**: `QMessageBox` 면 `surface`, 버튼은 `Button` 규칙(높이 44, 최소 폭 88, 기본 포커스 규칙 §7 유지). 위 규칙 외 변경 없음.

### 16.6 페이지별 before / after

| 페이지 | before | after |
|---|---|---|
| 저장 | 테두리 카드, 레이블 좌측 열 96, 32px 컨트롤, 작은 체크박스 3개, 작은 [저장]/[미리보기], 로그가 바닥 회색에 묻힘 | 제목 `lg` + 단축키 안내는 제목 아래 `hint`. 흰 카드 1장: **레이블 위** · 번호 입력 52px(큰 글자) · 주제 입력 44 + 힌트 · 원형 체크 3개 한 줄 · CTA 줄 [저장](primary 52, stretch 2) [미리보기](secondary, stretch 1). 로그는 별도 흰 카드(머리글 + 회색 필드). 결과 카드·배너는 등장 페이드 |
| 문제 | 중앙 텍스트 + 흰 버튼 | 64px 원형 아이콘 + 굵은 제목 + 회색 본문 + primary [저장 탭으로]. 지문 보기 모드는 카드 안 본문 `base` 줄 간격 150%, 제목 `lg` |
| 검증 | 코치 바·폼 카드·탭 모두 1px 테두리, 탭 pane 이중 박스, 패널 제목 텍스트가 테두리에 붙음 | 코치 바 카드(tonal 버튼) → 폼 카드(주제/번호 입력 44, [실행] primary 44, [SWEA 제출] secondary) → 밑줄 탭, **pane 투명**, EnginePane 카드 2장 나란히(무테). < 800 에서 [실행]·[SWEA 제출]은 둘째 줄로 |
| 최근 | 테두리 표, 소형 [새로고침] 아웃라인 | 제목 행 오른쪽 tonal [새로고침]. 흰 표 컨테이너 라운드 16, 행 52, 머리글 회색 소형 글자, 복습 카드 상단 |
| 성장 | 잔디 카드는 있으나 숫자·제목이 작아 위계 없음, 모든 카드 테두리 | 잔디 카드 제목에 큰 숫자, 칸 라운드 3, 리포트 헤더에 큰 Pass 숫자, 지표 타일(또는 대체안), 막대 차트 라운드 모서리. 모든 카드 무테 흰색 |
| 설정 | 한 줄 길이 100% 로 늘어난 입력, 구분 약한 섹션, 체크박스 다수 | 최대 폭 840 가운데, 레이블 위 입력, 토글 행, 위험 영역 분리, 신설 "화면" 카드(동작 줄이기) |
| 공통 | 흰 사이드바 + 우측 선, 선택 = 연파랑 직사각 | 선 없음, 알약 슬라이드, 하단 상태바 선 없음 |

### 16.7 애니메이션

원칙: **의미 있는 변화에만**(위치 이동·등장·완료·로딩), 장식용 반복 금지. 모든 애니메이션은 `gui/motion.py`(신규, Qt 만 사용) 헬퍼를 통해 만들고, 위젯 코드는 `QPropertyAnimation` 을 직접 쓰지 않는다 — 그래야 끄는 지점이 한 곳이다.

| 토큰 | 값 |
|---|---|
| `MOTION_FAST` | 120ms (hover 색, 토글 손잡이 일부) |
| `MOTION_BASE` | 200ms (페이지, 내비 알약, 등장) |
| `MOTION_EXIT` | 150ms (퇴장) |
| `MOTION_NUMBER` | 600ms (카운트업만 예외) |
| `MOTION_HEAT` | 700ms (잔디 전체) |
| 진입 이징 | `QEasingCurve.OutCubic` (토스풍 감속) |
| 퇴장 이징 | `InCubic` |
| 눌림 | `OutQuad` 80ms 축소 / 120ms 복귀 |

| # | 대상 | 동작 | 구현 | 시간·이징 |
|---|---|---|---|---|
| A1 | 페이지 전환 | 새 페이지 불투명도 0→1 + 아래 8px→0 슬라이드(이전 페이지는 즉시 숨김; 교차 페이드 없음 — 느려 보임) | `motion.fade_slide_in(page)` — `QGraphicsOpacityEffect` + `pos` 애니메이션, **끝나면 효과 제거**(`setGraphicsEffect(None)`, 글자 ClearType 복원)·`layout().activate()` 로 위치 확정. 연타 시 진행 중인 것을 즉시 끝상태로 | 200ms OutCubic |
| A2 | 내비 알약 이동 | 선택 알약이 이전 항목 → 새 항목으로 이동(+높이 유지) | `NavDelegate` + `QVariantAnimation`(알약 사각형 y), 각 프레임 `viewport().update()` | 200ms OutCubic |
| A3 | 버튼 hover | 면 색 보간 | `Button` 의 `QVariantAnimation`(0→1)로 `QColor` 선형 보간 후 `update()` | 120ms OutCubic |
| A4 | 버튼 press | 0.97 배 축소 후 복귀 | 〃 (`painter.scale` 중심 기준) | 80ms / 120ms |
| A5 | 카드·배너·결과 등장 | 불투명도 0→1 (이동 없음 — 레이아웃 소유 위젯은 pos 이동 시 충돌) | `motion.fade_in(widget)` (효과 후 제거). 대상: 저장 결과 카드, 배너 show, 코치 바, EnginePane 상태 전환, 성장 리포트 카드(리포트 선택 변경 시) | 180ms OutCubic |
| A6 | 토스트 | 등장: 불투명도 0→1 + 아래 12px→0, 퇴장: 0으로 + 아래 8px | `Toast` 자체 `QPropertyAnimation`(`windowOpacity` 대신 자체 `_opacity` 프로퍼티 + `move`) | 200ms OutCubic / 150ms InCubic |
| A7 | 토글 | 손잡이 x 이동 + 트랙 색 보간 | `Toggle` 의 `QVariantAnimation` | 180ms OutCubic |
| A8 | 진행 — 스피너 | 버튼 busy 시 16px 호 회전 | `Spinner`(QPainter `drawArc`, `QVariantAnimation` 0→360 loop, 선형) | 900ms/회전. **보이지 않으면 정지**(`hideEvent`·창 비활성/최소화) |
| A9 | 진행 — 스켈레톤 | AI 코치 로딩 패널(기존 "묻는 중… 0:12 · 최대 5분" 텍스트 라벨은 **그대로 유지**) 아래 회색 막대 3줄(100%/92%/64% 폭, 높이 14, 라운드 7)에 하이라이트가 좌→우로 스침 | `Skeleton`(QPainter 그라디언트 `surface_alt`→`border`→`surface_alt`) | 1200ms 루프 선형, 보일 때만 |
| A10 | 진행 — 막대 | 기존 `QProgressBar#busy` 4px 유지 (Qt 기본 무한 막대) | QSS 만 | — |
| A11 | 잔디 채움 | 열(주)이 왼쪽→오른쪽으로 차례로 불투명도 0→1(열마다 지연 ≤ 450ms, 열당 250ms). 성장 탭에 **처음 들어올 때 1회**(앱 실행당), 데이터 갱신·hover·칸 선택에서는 재생 안 함 | `HeatmapWidget._reveal` 프로퍼티 + 전체 `update()` (칸 371개, 부담 작음) | 총 700ms OutCubic |
| A12 | 숫자 카운트업 | 이전 표시값(없으면 0)→목표값. 대상: 잔디 제목 N, 리포트 Pass 수, 지표 값(정수/퍼센트 포맷 콜백). 탭 진입 후 값이 **바뀐 경우에만**, 소수는 포맷 후 표시 | `motion.count_up(label, to, fmt)` — **`accessibleName`·`toolTip` 은 즉시 최종값**, 표시 텍스트만 보간. 우측 정렬 최소 폭 고정 | 600ms OutCubic |
| A13 | 차트 막대 | 높이 0→목표, 막대마다 지연 30ms | `BarChart._grow` | 400ms OutCubic |

**성능 기준**
- 동시에 `QGraphicsOpacityEffect` 가 걸린 위젯은 최대 1개(페이지 전환 진행 중 하위 fade_in 은 생략). 종료 시 반드시 효과 제거.
- 1100×760 에서 프레임당 페인트 ≤ 16ms 목표. `motion.MotionGuard` 가 애니메이션 중 연속 3프레임이 50ms 를 넘으면 그 세션 동안 모션을 자동 비활성(원격 데스크톱·소프트웨어 렌더링 방어). 원격 세션(`GetSystemMetrics(SM_REMOTESESSION)`)은 시작부터 off.
- 무한 반복(A8·A9)은 위젯이 보이고 창이 활성일 때만. 유휴 시 타이머 0개(CPU 0%).
- 대형 위젯(`QTextBrowser`·표)에는 효과를 걸지 않는다 — 대신 **페이지 단위**로만(A1) 짧게. 지문 보기 페이지처럼 효과가 깨지는 경우(`QTextBrowser` 이미지 로드 중) A1 생략 가능.
- 시작 직후 첫 페이지 표시, `restore` 된 창 크기 복원 중에는 애니메이션 없음.

### 16.8 모션 구현 위치

헬퍼는 `swea_fetcher/gui/motion.py` 한 파일: `motion_enabled()`, `set_user_reduce(bool)`, `fade_in(w)`, `fade_slide_in(w)`, `count_up(label, to, fmt)`, `MotionGuard`, 토큰 상수(`MOTION_*`). 커스텀 위젯(`Button`·`Toggle`·`Toast`·`Spinner`·`Skeleton`)은 이 모듈의 `motion_enabled()` 만 조회한다. 애니메이션 객체는 대상 위젯을 부모로 두어 위젯 파괴 시 함께 정리한다.

### 16.9 동작 줄이기 · 테스트 안정성

`motion.motion_enabled()` 는 아래 중 **하나라도 해당하면 False** (우선순위 위→아래):

1. 환경변수 `SWEA_GUI_MOTION` = `off` / `0` / `false` → False. `on` / `1` → (아래 2·3·4 를 무시하고) True — 모션 자체를 테스트하는 테스트 전용.
2. `QT_QPA_PLATFORM == "offscreen"` (conftest 가 실수로 env 를 빠뜨려도 안전망).
3. 사용자 설정 `QSettings("swea-fetch","gui")/ui/reduce_motion` = true (설정 "화면" 카드 토글).
4. OS: Windows `SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION=0x1042)` 가 0 (설정 > 접근성 > 시각 효과 > 애니메이션 효과 끔) 또는 원격 세션. 호출 실패 시 True(켬)로 간주하지 않고 **무시**(= 다른 조건만 따름).
5. `MotionGuard` 가 성능 문제로 세션 비활성화.

False 일 때 헬퍼의 계약: **애니메이션 객체를 만들지 않고 즉시 최종 상태를 적용**한다(`fade_in` → 불투명 그대로, `count_up` → 최종 텍스트, `Toast.show` → 즉시 표시·`QTimer` 로 소거만, 잔디 `_reveal=1`, 내비 알약 즉시, 스피너·스켈레톤은 **정지 상태 정적 그림**(스피너 3/4 호, 스켈레톤 기본색 막대)). 따라서 테스트에서 `qtbot.wait` 로 애니메이션을 기다릴 필요가 없다.

- `tests/gui/conftest.py`: `os.environ.setdefault("SWEA_GUI_MOTION", "off")` 를 `QApplication` 생성 전에 추가(기존 `QT_QPA_PLATFORM` 줄 옆).
- 신규 `tests/gui/test_motion.py`: `monkeypatch.setenv("SWEA_GUI_MOTION","on")` 로 (a) off 일 때 헬퍼가 `QVariantAnimation` 을 만들지 않음, (b) `fade_in` 후 `graphicsEffect() is None`, (c) `count_up` 이 끝나면 라벨 텍스트 = 최종값·`accessibleName` 은 시작 즉시 최종값, (d) 연타 시 진행 중 애니메이션이 끝상태로 점프, (e) 설정 토글이 `motion_enabled()` 에 반영, (f) 무한 애니메이션이 `hide()` 후 정지.
- 접근성: 모션이 꺼져도 정보 손실 없어야 한다(내비 선택은 알약 색, 결과는 즉시 표시).

### 16.10 구조 변경 목록 (테스트 영향 최소화 기준)

QSS·토큰만으로 끝나는 변경이 기본이다. 위젯 구조가 바뀌는 항목은 아래뿐이며 **모두 objectName·텍스트·시그널을 유지**한다.

| # | 변경 | 호환 처리 |
|---|---|---|
| S1 | `QPushButton(` → `widgets.Button(`(서브클래스) | `isinstance(…, QPushButton)` 유지 |
| S2 | 일부 `QCheckBox` → `widgets.Toggle`(서브클래스, 설정 페이지 4개) | `GrowthEnabledCheck` 등 objectName·`isChecked/setChecked/toggled` 유지 |
| S3 | `PageColumn`(최대 폭 840 컨테이너)으로 페이지 본문 감쌈 (저장·검증·성장·설정) | 기존 위젯 객체는 그대로 자식, `findChild` 로 찾으므로 영향 없음. `QScrollArea` 안/밖 위치만 확인 |
| S4 | 내비 `NavDelegate` 추가 | `QListWidget#nav` 그대로, `currentRow` 계약 불변 |
| S5 | `Toast` 위젯·`MainWindow.notify` 신설 | `statusBar().showMessage` 도 계속 호출 |
| S6 | `LogView` 를 카드로 감싸고 머리글 행 정리 | 내부 `QPlainTextEdit#log`·토글·[지우기] objectName 유지 |
| S7 | `EmptyState(icon=None)` 인자 추가 | 기존 호출 불변 |
| S8 | 설정 "화면" 카드·`ReduceMotionToggle` 신설 | 신규라 영향 없음 |
| S9 | `QFormLayout.setRowWrapPolicy(WrapAllRows)` | 필드 위젯 순서·objectName 불변. 레이블 위젯의 `setBuddy`는 유지 |
| S10 | (성장) 지표 행 → 타일 그리드 | **선택**. 테스트가 행 구조(고정 폭 132/112, 개수 5)를 단언하면 대체안(값 글자만 키움) 채택 |
| S11 | `fonts.py` 신설, `FONT_FAMILY` 갱신 | 글꼴 폭이 달라 텍스트 폭 단언이 있는 테스트가 있으면 조정 |

폰트 크기 증가(10→10.5pt, 컨트롤 32→44)로 720×480 에서 내용이 넘칠 수 있다: **저장·설정은 `QScrollArea`(이미 있음)로 스크롤 허용**, 이전 §11 의 "최소 720×480 에서 설정 제외 스크롤 없이" 규칙은 **저장 페이지도 제외**하는 것으로 완화(로그 접힘 시 번호·주제·CTA 는 스크롤 없이 보이게). 검증 페이지는 < 800 에서 [실행]·[SWEA 제출] 줄바꿈.

### 16.11 구현 순서 (마일스톤)

각 단계 끝에 `pytest -q`(전체 1368) 통과 + 해당 화면 캡처를 `docs/gui-screenshots/` 에 갱신. 단계 사이 **커밋을 분리**(롤백 용이).

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| M21-A 토큰·QSS·글꼴 | `tokens.py`(Palette 신규 필드·상수·`build_qss` 전면 갱신·`build_statement_css`), `fonts.py`+폰트 파일+라이선스, spec `datas`, 이 문서 §2 와 동기화 | 구조 변경 없이 모든 화면이 새 색·라운드·글꼴로 렌더, 기존 테스트 통과, 한글 글꼴 로드 확인 |
| M21-B 공용 컴포넌트 | `Button`·`Toggle`·`EmptyState(icon)`·`Banner`·`Badge`·`LogView` 카드화·`PageColumn`·탭/표 QSS·`Toast`(정적 표시)·`notify` | 위젯 단위 테스트(상태·variant), 모션 없이 정적으로 완성 |
| M21-C 모션 | `motion.py`(헬퍼·`motion_enabled`·`MotionGuard`) + conftest 환경변수 + `Button` 색 보간/눌림, `Toggle`, `Toast` 애니, 내비 알약(A2), 페이지 전환(A1), A5 등장, `Spinner`·`Skeleton` | `test_motion.py`, 모션 off 에서 기존 전 테스트 통과, 설정 "동작 줄이기" |
| M21-D 페이지 | 저장→검증→최근→문제→성장(잔디 A11, 카운트업 A12, 차트 A13, 타일 결정)→설정(토글 행·위험 영역·"화면" 카드) | 페이지별 before/after 캡처 6장, §16.12 수용 기준 중 해당 항목 |
| M21-E 마감 | 720×480·1100×760·150% DPI 점검, 대비·키보드 점검, 번들 exe 확인(폰트 포함), `design-spec.md` §2·§3·§5 본문을 §16 과 합쳐 정리(중복 제거), 디자이너 정합성 검토(모드 2) 요청 | 수동 체크리스트 전부 체크, 성능 기준 측정 기록 |

### 16.12 수용 기준 · 수동 검증 체크리스트

수용 기준
1. 모든 화면에서 카드 외곽 1px 테두리가 없고(구분선 제외) 카드 안 카드 이중 박스가 없다. 위젯 코드에 색 리터럴 0(`grep -nE '#[0-9A-Fa-f]{6}' swea_fetcher/gui --include=*.py` 는 `tokens.py` 밖에서 0건).
2. 대비표(§16.4)의 모든 글자 조합이 구현값과 일치 — `text_3` 보다 연한 글자는 `text_placeholder`/disabled 외에 없다.
3. 모든 애니메이션이 `motion.py` 경유, `motion_enabled()==False` 에서 즉시 최종 상태, 기존 테스트 전체(1368) 통과 + 신규 모션 테스트 통과.
4. 키보드만으로 전 기능 조작 가능, 모든 포커스 가능 위젯에서 포커스 링 가시(§10 불변).
5. 720×480 에서 가로 스크롤 없음, 텍스트 잘림 없음(스크롤 허용 페이지는 §16.10).
6. 앱 실행 유휴 상태 CPU ≈ 0%(무한 애니메이션 없음).
7. onefile exe 에서 Pretendard 로 렌더(폰트 파일 누락 시에도 Malgun 폴백으로 앱 실행).

수동 체크리스트
- [ ] 저장 페이지: 번호 입력 52px 큰 글자·레이블 위, [저장] 가로로 넓음, Enter/Ctrl+Enter/Esc 동작 불변
- [ ] 저장 성공 → 결과 카드 페이드 등장, 토스트 아님(결과는 카드). 폴더 열기 → 토스트 + 상태바 메시지
- [ ] 내비 클릭 → 알약 슬라이드 200ms, 연타해도 튀지 않음, Ctrl+1~6 동일
- [ ] 페이지 전환 후 글자가 흐리지 않다(효과 제거 확인, 확대해서 ClearType)
- [ ] 버튼 hover 색 부드럽게, 누르면 살짝 줄었다 복귀, 비활성은 반응 없음, busy 시 스피너
- [ ] 입력 포커스 흰 면 + 파란 링, invalid 빨간 링 + 오류 문구(색 단독 아님)
- [ ] 설정: 토글 4개 키보드(Space)·마우스, 상태가 즉시 `.env`/QSettings 반영, "동작 줄이기" 켜면 이후 전환 모두 즉시
- [ ] Windows 설정에서 "애니메이션 효과" 끄고 앱 재실행 → 모션 없음(앱 설정과 무관)
- [ ] 검증 → AI 코치 탭: 탭 pane 이중 박스 없음, 로딩 시 스켈레톤 + 기존 텍스트, 완료 시 페이드
- [ ] 최근: 행 52px, hover·선택 색, 복습 카드, 새로고침 tonal
- [ ] 성장: 처음 진입 시 잔디 채움·숫자 카운트업 1회, 재진입/hover/칸 선택에서는 재생 없음, 요일·월 라벨 겹침 없음
- [ ] 720×480 / 880×600 / 1100×760 / 150% DPI 에서 저장·검증·성장·설정 캡처 확인
- [ ] 화면 낭독기(Narrator) 에서 토스트 메시지가 상태바 경로로 전달됨
- [ ] 고대비 모드(Windows)에서 글자 가독성 확인(문제 있으면 R8 과 함께 기록)

### 16.13 리스크

| # | 리스크 | 대응 |
|---|---|---|
| R1 | QSS 는 box-shadow·transition·transform 미지원 | 그림자는 토스트만 직접 그림, 전환·보간·축소는 `Button`/`Toggle` 페인팅 + `QVariantAnimation` 으로 대체. QSS 로 못 하는 것을 QSS 로 흉내 내지 않는다 |
| R2 | `QGraphicsDropShadowEffect` 성능·흐림 | 카드에 사용 금지(D3). 리뷰에서 발견 시 Critical |
| R3 | `QGraphicsOpacityEffect` 가 큰 페이지를 래스터화(글자 회색조, 프레임 저하), 자식 `QComboBox` 팝업·`QTextBrowser` 와 충돌 | 효과는 200ms 동안만, 끝나면 제거, 동시 1개, `MotionGuard` 자동 off |
| R4 | Pretendard 가 PyInstaller onefile 에서 못 찾음·SemiBold 이름 문제 | 2웨이트(400/700) 고정, `addApplicationFont` 반환값 검사, 폴백 체인, M21-E 에서 exe 실측 |
| R5 | 폰트·컨트롤 확대로 720×480 에서 넘침, 기존 테스트의 크기/위치 단언 깨짐 | 스크롤 허용 범위 §16.10, 해당 테스트만 수정(값 의도 유지), 구조 단언은 S10 대체안으로 회피 |
| R6 | 알약 슬라이드(델리게이트)가 QSS 선택 렌더와 충돌, 키보드 포커스 표시 누락 | A2 구현이 불안정하면 **대체안**: 선택 항목 배경만 즉시 전환(슬라이드 생략) — 나머지 모션과 독립이라 단계 M21-C 에서 따로 판단해 이 문서에 기록 |
| R7 | 토스 파랑 `#3182F6` 와 `primary_action` 이 한 화면에 섞여 어색 | 링·토글·차트는 `primary`, 글자 얹힌 면만 `primary_action`. 두 색 차이를 캡처로 확인 후 불만이면 사용자에게 "버튼 글자 크기 키우고 `#3182F6` 로 통일" 옵션 제시(AA 하향 감수 필요) |
| R8 | 입력창 무테 채움(경계 대비 1.1:1) 접근성 | 수용된 예외(§16.4), 레이블·링·문구로 보완. 사용자가 불편하면 1px `border_strong` 추가 |
| R9 | 사용 기록 호환: 사용자가 이미 고른 잔디색(`growth/heat_color`)·창 크기 | 변경 없음(D9, D10) |

### 16.14 다크 모드 판단

**이번 범위 밖.** 이유: 토스풍 정체성은 라이트의 "회색 바닥 + 흰 카드" 명도 차에 있어 다크는 별도 디자인(카드 elevation 을 명도로 재정의)이 필요하고, 팔레트·대비·캡처 검증이 한 마일스톤 분량이다. **대비책**: (1) 새 커스텀 위젯은 색을 `Palette` 에서만 읽는다(Toast·Button·Toggle·Spinner·Skeleton·Heatmap·차트), (2) 신규 토큰은 의미 이름(`bg_subtle`·`toast_bg`·`secondary`…)이라 `DARK` 에 값만 채우면 되며, (3) `DARK` 가 채워지기 전엔 `build_qss(DARK)` 호출 경로를 만들지 않는다.

  - M19 성장 페이지 대체안 (builder, 새 토큰 없음): ① "새 리포트" 배지는 Badge 상태 `info` 가 없어 `running`(primary_soft, 같은 색)으로 표시. ② 약점·강점 비율은 100% 를 넘을 수 있어(강도 합 ÷ 분류 건수) % 대신 "응답당 강도 2.0 → 1.0" 문장과 "점수 N · 분류 M건 중" 값으로 표시, 막대 길이는 응답당 평균 강도/3. ③ "AI 분류 기반 참고용" 은 720px 에서 헤더가 가로로 넘치지 않도록 제목 줄 아래 한 줄로 배치. ④ `design/icons/nav-growth.svg` 는 디자이너 산출물 위치에 builder 가 임시로 만든 것 — 디자이너 검토 요청.
  - (없음)

### 16.15 M21 1단계 구현 기록 (builder) — 사용자 결정·스펙 대체안

사용자 결정(스펙보다 우선)
- **테마(색 조합) 6종 + 설정 변경**: D1 의 파랑은 기본 테마 "토스 블루" 로 유지하고 `tokens.THEMES` 에 5종 추가(숲 그린·라벤더 퍼플·선셋 오렌지·로즈 핑크·먹색 모노). 바뀌는 건 주색 계열 8개(`primary`·`primary_action`·`primary_hover/_pressed`·`primary_soft`·`primary_soft_hover/_pressed`·`primary_soft_text`, `accent`·`diff_extra` 따라감)뿐, 중립·상태색은 공유. 기준 = **버튼 면(`primary_action`) 위 흰 글자 4.5:1 이상**, `primary_soft_text` on `primary_soft` 4.5:1 이상, `primary`(글자 없는 면) on `surface` 3:1 이상 — `tests/gui/test_gui_theme.py` 로 고정. 선택은 즉시 전체 QSS 재적용(`MainWindow.apply_theme`), QSettings `ui/theme`(key). 모르는 key 는 기본 테마. 풀이 잔디 색(`growth/heat_color`)은 별개 설정 유지. 커스텀 페인팅·rich text 는 `tokens.current()`(현재 팔레트)에서 읽는다 — `tokens.LIGHT` 는 기본 테마 고정값(하위 호환 이름).
- **창 기본 크기 960×680** (D10 의 880×600 대체, 최소 720×480 유지, 저장된 geometry 가 있으면 그대로).
- 글꼴 Pretendard 는 공식 릴리스 v1.3.9 의 `public/static/Pretendard-Regular.otf`·`Pretendard-Bold.otf`(각 약 1.5MB, 합계 약 3.0MB)와 `LICENSE.txt` 를 무수정으로 번들.

스펙 대체안·보류
- 설정 "화면" 카드: 이번 단계는 **테마 칩 6개**만. 동작 줄이기 토글(`ReduceMotionToggle`)은 모션 단계(M21-C)에서 함께 추가한다(동작하지 않는 스위치를 먼저 보이지 않기 위해). 카드 위치는 성장 기록 카드 바로 다음.
- 테마 칩(`widgets.ThemeChip`): 150×44, 해당 테마의 `primary_action` 색 원 + 이름, 선택 시 그 테마의 `primary_soft` 면 + 2px `primary` 링. 3열 격자.
- `Toggle` 적용은 3개(`GrowthEnabledCheck`·`GrowthCommentCheck`·GitHub 자동 동기화 켜기) — 4번째는 위 사유로 보류.
- 큰 CTA 높이 52 는 class 가 `primary` 와 겹칠 수 없어 `size="lg"` 동적 속성으로 분리(QSS `QPushButton[size="lg"]`). 페이지 적용은 M21-D.
- 콤보 팝업은 흰 바탕에 떠 있어 1px `border` 테두리를 유지(§16.5 "테두리 없음" 의 예외).
- 라디오 선택 표시는 에셋 없이 6px 주색 테두리 + 흰 중심(링 모양)으로 구현. 체크 표시는 `check-white.svg`(QSS `image`).
- 내비 알약 슬라이드(A2)는 M21-C. 지금은 QSS `::item:selected` 정적 배경(내비 항목 높이 44 + 사이 간격 4).
- `PageColumn`·`EmptyState(icon)`·`Toast`·`notify` 는 컴포넌트만 완성했고 페이지 적용(S3·S7 호출부)은 M21-D. 단, 성공성 `status_message`(문구가 "~했습니다/켰습니다/껐습니다/지웠습니다/열었습니다/바꿨습니다" 로 끝나거나 "저장 완료" 로 시작)는 `MainWindow._on_page_message` 가 `notify` 로 보내고 그 외는 상태바만.
- 폼 줄바꿈 정책(S9)은 해당 레이아웃이 QFormLayout 이 아니라 QGridLayout 이어서(`git_dialog` 만 QFormLayout) 페이지 재배치와 함께 M21-D 에서 처리.
- Pretendard 에는 `✕ ▼ ▶ ● ○ ↗ − ≠ …` 글리프가 없어(`QRawFont.supportsCharacter` 확인) 시스템 폴백 글꼴로 그려진다 — Windows 에서 모양·세로 정렬을 M21-E 에서 확인.


### 16.16 M21 2단계 구현 기록 (builder) — 모션·페이지·마감

모션 (구현값)
- `gui/motion.py`: `motion_enabled()`(§16.9 순서), `tween`/`loop`/`fade_in`/`fade_slide_in`/`count_up`/`finish_now`, `MotionGuard`(유한 애니메이션 프레임 간격 50ms 초과 연속 3회 → 세션 동안 off, 무한 반복은 제외). 꺼짐 = 애니메이션 객체 0개·즉시 최종 상태. `tests/gui/conftest.py` 가 `SWEA_GUI_MOTION=off` 기본, `tests/gui/test_motion.py` 가 켜서 시작·종료 상태만 검증.
- 스펙 대체안: (1) 버튼 눌림 0.97 축소는 **면만** 축소(글자는 QSS 가 그려 스케일 불가). (2) 스피너 색은 글자색이 아니라 `primary` (회색 비활성 면 위에서 보이게). (3) 내비 항목은 `NavDelegate` 가 아이콘·글자까지 직접 그림(QSS `::item` 은 패딩 외 제거). (4) 토스트 등장/퇴장은 위젯 이동이 아니라 paintEvent 의 투명도·y 오프셋. (5) 모션 on 이어도 창이 활성이 아니면 스피너·스켈레톤은 멈춤(`applicationStateChanged`).
- 지표 타일(S10): `metric_box` 를 QGridLayout 으로 바꿔 **타일 그리드 채택**(2열, 카드 폭 560 미만 1열). `count()`/`itemAt(i).widget()` 계약과 `MetricRow_*`·`.change`·`.spark` 유지. 값이 숫자 하나("3문제", "85%")일 때만 카운트업, 복합 값("힌트 2 · 정답 풀이 0")은 md 700 정적.
- `BarChart` 높이 120→140 (테스트 갱신). 성장 제목 `#GrowthHeatTitle` 은 rich text 라 `text()` 대신 `accessibleName()` 이 평문 — 테스트 갱신.
- 검증 페이지: `QScrollArea` 로 감싸 720×480 에서도 코치 바+결과가 겹치지 않고 스크롤(결과 영역 최소 220). 번호 입력은 이 줄에서만 44px(`size="md"`).
- EnginePane 머리글: 제목 아래에 메타(`코드 평가 · 14:02 · 16.2초`) — `ElidedLabel.set_parts` 가 좁으면 시각부터 빼고 그래도 안 되면 오른쪽 말줄임. 가운데 말줄임 금지.
- 글리프: `✕ ▼ ▶ ● ○ ↗ ⟳ ⚠` → SVG(`close`·`caret-down/right`·`arrow-up-right`·`sync`) 또는 `StatusDot`. 상태바 문구는 "로그인됨"/"세션 없음"/"설정 없음"(점은 그림), 배지 문구에서 "↗" 제거(아이콘).
- 버튼 간격 토큰 `BTN_GAP=12`, `BTN_GAP_SM=8`. 설정 "위험 영역" 카드에 세션 삭제·계정 삭제(danger)·AI 기록 지우기·성장 기록 지우기를 모음. `ReduceMotionToggle` 은 QSettings `ui/reduce_motion`.
- 번들: `packaging/swea-fetch-gui.spec` 가 `qsvg.dll`·`qsvgicon.dll` 을 binaries 로 명시.
- 마감 검토: 지연 시작·일시 정지 모션도 교체 시 끝값과 정리 콜백을 적용하고, 취소된 지연 타이머는 재시작하지 않는다. 모션 off 전환 후 같은 키를 요청하면 이전 모션을 먼저 종료한다. 회귀 테스트 2건 추가.
- 2026-10-01 검증: main 전체 1,433개 테스트 통과. 960×680·720×480 캡처와 150% offscreen 캡처 레이아웃 확인. 실제 exe 자가진단 exit 0, Pretendard Regular/Bold·SVG 아이콘·MainWindow 초기화 확인(로그인 네트워크 검증은 하지 않음). 빌드 PATH의 외부 `icuuc.dll` 충돌은 System32 우선 검색으로 수정. Narrator·고대비·실사용 프레임 성능 검증은 미실시.

---

## 17. M22 다크 모드 · 테마 확장 · 상태 표시

구현 지시서(순서·테스트·체크리스트)는 `docs/handoff-designer-m22-dark.md`. 이 절은 **값과 규칙의 단일 출처**다. §16.14(다크 범위 밖)는 이 절로 대체된다.

### 17.1 방향과 결정 요약

방향 한 문장: **"토스의 '바닥 < 카드' 명도 차 구조를 어두운 쪽으로 그대로 뒤집고(바닥이 가장 어둡고 카드가 한 단계 밝다), 테마 색은 버튼·선택면뿐 아니라 바닥·사이드바·hover 면에 5~8% 틴트로 번지게 한다."** 이유: 사용자가 "테마가 버튼 색만 바꾼다"고 느꼈고, 다크는 그림자 없이 명도 단계만으로 층을 만들어야 §16 의 무테·무그림자 규칙이 유지된다.

| # | 결정 | 이유 |
|---|---|---|
| E1 | 화면 모드 3종: 라이트 / 다크 / **시스템 따르기(기본)**. QSettings `ui/color_mode` = `light`·`dark`·`system`. 테마(`ui/theme`)와 직교 — 6테마 × 2모드 = 12 팔레트 | 요구 1·2 |
| E2 | 전환은 **즉시**(재시작 없음, 크로스페이드 없음). 시스템 따르기는 OS 앱 모드 변경도 즉시 반영 | 요구 1 |
| E3 | 라이트의 중립색(바닥·사이드바·hover)도 테마별 틴트로 바꾼다. **카드 면은 라이트에서 `#FFFFFF` 유지** (흰 면의 틴트는 보이지 않고 글자 대비만 깎는다). 카드 면 틴트는 다크에서 적용 | 요구 2, 과하지 않게 |
| E4 | 글자색(`text`·`text_2`·`text_3`)은 **모드별 1벌, 테마와 무관**. 상태색(success/warning/error)도 모드별 1벌 | 대비 보증을 12팔레트에서 반복 계산하지 않기 위해 |
| E5 | 다크의 버튼 면은 라이트의 "hover 색"을 기본으로, 라이트의 "기본 색"을 hover 로 쓴다(밝아지는 hover). 면 위 글자는 흰색 유지, 4.5:1 이상 | 다크에서 hover 가 어두워지면 눌린 것처럼 보임 |
| E6 | 먹색 모노 다크만 예외: 버튼 면이 **밝은 회색 + 어두운 글자**(`primary_text` 가 모드·테마별 토큰) | 어두운 면 위 어두운 버튼은 보이지 않음 |
| E7 | 잔디 색 기본 = **테마 색 따르기**. 저장 키 `growth/heat_color` 가 없거나 `"follow"` 면 따르기, `"#RRGGBB"` 면 고정색. 기존 저장값은 그대로 고정색으로 유지 | 요구 3. 이전 버전은 사용자가 칩을 누를 때만 키를 쓰므로 키 없음 = 한 번도 안 골랐음 |
| E8 | 색 선택은 QColorDialog 대신 **설정 카드 안에서 펼쳐지는 인라인 패널**(HSV 사각형 + 색상 슬라이더 + HEX 입력). 별도 창·팝업 없음 | 팝업 창은 가장자리 회색 문제를 재현하고 다크 대응 부담이 큼 |
| E9 | 최근 탭 상태 = **왼쪽 3px 색 띠 + 아이콘·글자가 든 상태 칩** 새 첫 열. 복습 예정은 제목 칸 오른쪽의 별도 작은 태그 | 요구 4, 색만으로 전달 금지 |
| E10 | 회색 가장자리 원인은 3곳(팝업 컨테이너 창·스크롤바 트랙 서브컨트롤·QAbstractScrollArea 코너/뷰포트)이며 QSS + 팝업 창 속성 + 앱 QPalette 를 함께 적용 | 요구 5, §17.8 |
| E11 | 사용자 확인 필요 결정 없음. 아래 기본값으로 진행하고 어긋나면 값만 바꾼다: 모드 기본 시스템 따르기, 로컬 검증 실패는 기록이 없어 "미제출"로 표시(§17.12), 잔디 저장소 동기화 토글은 빌더 기능 완성 전까지 숨김 | |

### 17.2 모드 해석과 시스템 감지

- 유효 모드 `is_dark` = `color_mode == "dark"` 또는 (`"system"` 이고 OS 앱 모드가 다크).
- 감지 순서: ① `QGuiApplication.styleHints().colorScheme()` (Qt 6.5+, `Qt.ColorScheme.Dark`) → ② 값이 `Unknown` 이거나 속성이 없으면 레지스트리 `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize` 의 `AppsUseLightTheme`(0 = 다크, 읽기 실패 = 라이트).
- 변경 감지: `styleHints().colorSchemeChanged` 신호(있을 때). 없으면 모드가 system 인 동안 3초 `QTimer` 로 ②를 폴링. 신호/폴링 모두 모드가 system 일 때만 반응.
- 강제 모드일 때 네이티브 요소(타이틀 바·시스템 메뉴·네이티브 다이얼로그)를 앱 선택에 맞춘다: Qt 6.8+ 는 `styleHints().setColorScheme(Light|Dark)`, system 이면 `Unknown`(OS 따름). 없으면 창 핸들에 DWM `DWMWA_USE_IMMERSIVE_DARK_MODE`(20) 를 ctypes 로 설정(실패 무시).
- 한계(수용): `QFileDialog` 네이티브 창은 OS 설정을 따른다. 사용자가 앱 모드와 OS 앱 모드를 다르게 두면 파일 대화상자만 다른 모드로 보일 수 있다 — 설정 화면 힌트에 쓰지 않는다(드문 경우).

### 17.3 토큰 구조 변경 (`tokens.py`)

- `Theme` = `key`, `label`, `light: Palette`, `dark: Palette` (기존 `palette` 는 `light` 의 별칭으로 유지).
- 전역 상태: 테마 key + 모드 설정 + 해석된 `is_dark`. API: `set_theme(key)`, `set_color_mode(mode)`, `set_system_dark(bool)`(감지 결과 주입 — tokens 는 Qt 를 import 하지 않는다), `is_dark()`, `color_mode()`, `current()`(= 현재 테마의 해당 모드 팔레트), `version()`(위 셋이 바뀔 때마다 증가하는 정수 — 캐시 키).
- `LIGHT` 는 블루 라이트로 고정(하위 호환). `DARK` 는 블루 다크 팔레트로 채운다(더 이상 `current()` 를 가로채지 않음).
- 신규 `Palette` 필드(모두 기본값 있음, 기본값은 블루 라이트 값):

| 필드 | 용도 | 라이트 | 다크 |
|---|---|---|---|
| `is_dark: bool` | 모드 분기(잔디·로고 등) | False | True |
| `sidebar` | 사이드바·내비 바닥 (§17.5 표) | 테마별 | 테마별 |
| `on_primary` | `primary` 면 위 글리프(체크·토글 손잡이·선택 칸 아이콘) | `#FFFFFF` | `#0F1720` |
| `hover_fill` | 입력·행 hover 면 | = `border` | = `secondary_hover` |
| `segment_on` | 세그먼트 컨트롤 선택 칸 | `#FFFFFF` | = `secondary_hover` |
| `toggle_knob` | 토글 OFF 손잡이 | `#FFFFFF` | `#C9D0DA` |
| `link` | 리치 텍스트 링크 | = `primary_soft_text` | = `primary_soft_text` |
| `image_paper` | 문제 지문 이미지 뒤 종이색 | `#FFFFFF` | `#FFFFFF` |
| `ring_light` / `ring_dark` | 색 선택 패널 SV 핸들 이중 링(임의 색 위라 흑백 고정) | `#FFFFFF` / `#0F1720` | 동일 |
| (별도 필드 없음) | 상태 칩은 기존 `*_bg`/`*_text`, 위치·일정 점은 `success`/`warning` 사용 | | |

- `primary_text`(= `primary_action` 면 위 글자)는 `Palette` 기존 필드지만 값이 모드·테마별로 달라질 수 있다(먹색 모노 다크 `#15181D`).
- `text_3` 라이트 값을 `#636E7C` → **`#5E6977`** 로 올린다(틴트 바닥 위 여유 확보, bg 위 약 5.0:1).
- 신규 함수 `build_qpalette(p) -> dict[str,str]` 대신 Qt 쪽 `gui/theme/qt_palette.py` 가 `QPalette` 를 만든다(§17.8).

### 17.4 공통 중립·글자·상태 토큰 (모드별 1벌)

| 토큰 | 라이트 | 다크 |
|---|---|---|
| `text` | `#191F28` | `#ECEFF3` |
| `text_2` | `#4E5968` | `#B9C1CD` |
| `text_3` | `#5E6977` | `#A1AAB6` |
| `text_placeholder` = `text_disabled` | `#8B95A1` | `#737C8A` |
| `control_border` | `#8B95A1` | `#7C8593` |
| `toggle_off` | `#B0B8C1` | `#4A515D` |
| `secondary_text` | `#333D4B` | `#DDE2E9` |
| `toast_bg` / `toast_text` | `#333D4B` / `#FFFFFF` | `#ECEFF3` / `#191F28` (역전 — 툴팁도 같음) |
| `success` / `success_bg` / `success_text` | `#0A9B5E` / `#E6F8F0` / `#00794A` | `#3DD68C` / `#15382A` / `#6FE3A8` |
| `warning` / `warning_bg` / `warning_text` | `#D97800` / `#FFF4E0` / `#8A5100` | `#FFA726` / `#3D2C12` / `#FFC266` |
| `error` / `error_bg` / `error_text` | `#F04452` / `#FFEEEE` / `#C62B38` | `#FF6B78` / `#3F1D23` / `#FF8A94` |
| `danger_pressed` | `#FFDDDD` | `#55252D` |
| `diff_changed` / `diff_missing` | = `warning_bg` / = `error_bg` | 동일 규칙 |
| `diff_same` / `diff_extra` | = `surface` / = `primary_soft` | 동일 규칙 |

### 17.5 테마 × 모드 토큰 표

**라이트** — 규칙: `secondary` = `surface_alt`, `secondary_hover` = `border`, `secondary_pressed` = `border_strong`, `surface` = `#FFFFFF`.

| 테마 | bg | sidebar | bg_subtle | surface_alt | border | border_strong |
|---|---|---|---|---|---|---|
| 토스 블루 | `#F2F4F6` | `#FFFFFF` | `#F9FAFB` | `#F2F4F6` | `#E5E8EB` | `#D1D6DB` |
| 숲 그린 | `#F0F5F2` | `#FAFDFB` | `#F7FAF8` | `#F0F5F2` | `#E1E9E4` | `#CBD6CE` |
| 라벤더 퍼플 | `#F3F2F8` | `#FCFBFF` | `#F9F8FC` | `#F3F2F8` | `#E6E4EF` | `#D2CFE0` |
| 선셋 오렌지 | `#F7F3F0` | `#FFFCFA` | `#FBF9F7` | `#F7F3F0` | `#EBE5E0` | `#D8D0C8` |
| 로즈 핑크 | `#F8F2F4` | `#FFFBFC` | `#FCF8F9` | `#F8F2F4` | `#EDE4E8` | `#DACFD4` |
| 먹색 모노 | `#F2F2F3` | `#FFFFFF` | `#F8F8F9` | `#F2F2F3` | `#E4E4E6` | `#D0D0D4` |

라이트의 주색 계열 8개(`primary`, `primary_action`, `primary_hover`, `primary_pressed`, `primary_soft`, `primary_soft_hover`, `primary_soft_pressed`, `primary_soft_text`)는 §16 / 현재 `THEMES` 값 그대로. `primary_text` `#FFFFFF`, `on_primary` `#FFFFFF`.

**다크** — 규칙: `surface` 가 `bg` 보다 한 단계 밝고, `sidebar` 는 둘 사이. `secondary` = `surface_alt`.

| 테마 | bg | sidebar | surface | bg_subtle | surface_alt = secondary | secondary_hover | secondary_pressed | border | border_strong |
|---|---|---|---|---|---|---|---|---|---|
| 토스 블루 | `#14171C` | `#191C22` | `#1E222A` | `#242A33` | `#29303A` | `#333B47` | `#3D4655` | `#2E3541` | `#444E5C` |
| 숲 그린 | `#121714` | `#171D19` | `#1C231F` | `#232B26` | `#28322C` | `#323E36` | `#3C4A41` | `#2C372F` | `#415046` |
| 라벤더 퍼플 | `#16151C` | `#1B1A23` | `#201F29` | `#262432` | `#2C2A38` | `#363445` | `#413E53` | `#302E3E` | `#484560` |
| 선셋 오렌지 | `#1A1613` | `#201B17` | `#251F1B` | `#2D2621` | `#332B25` | `#3E352E` | `#4A4038` | `#382F28` | `#54483E` |
| 로즈 핑크 | `#1A1417` | `#201A1D` | `#251E22` | `#2D2529` | `#332A2F` | `#3E3439` | `#4A3F45` | `#382E34` | `#54454D` |
| 먹색 모노 | `#121212` | `#181818` | `#1E1E1F` | `#252527` | `#2A2A2C` | `#343436` | `#3F3F42` | `#313133` | `#4A4A4E` |

**다크 주색 계열** (`primary` = 글자 없는 면: 링·진행·토글 ON·차트 선택·스피너. `action/hover/pressed` = 버튼 면, 위 글자 `primary_text`. `soft*` = 내비 알약·tonal 버튼·info 배너·선택 행·`diff_extra`, 위 글자 `soft_text`):

| 테마 | primary | primary_action | primary_hover | primary_pressed | primary_text | soft | soft_hover | soft_pressed | soft_text |
|---|---|---|---|---|---|---|---|---|---|
| 토스 블루 | `#4C94FF` | `#1B64DA` | `#1F6FE8` | `#1957C2` | `#FFFFFF` | `#1C3560` | `#223F6E` | `#28497C` | `#8FBBFF` |
| 숲 그린 | `#2FBF7F` | `#096B42` | `#0B7A4B` | `#075A38` | `#FFFFFF` | `#17382B` | `#1D4636` | `#245640` | `#7BE0B0` |
| 라벤더 퍼플 | `#9B83FF` | `#5C3FCC` | `#6A4BE0` | `#4F33B3` | `#FFFFFF` | `#2D2559` | `#372E6C` | `#413680` | `#C4B5FF` |
| 선셋 오렌지 | `#FF8A3D` | `#AE3A0A` | `#C2410C` | `#963208` | `#FFFFFF` | `#43271A` | `#55311F` | `#683D25` | `#FFB27A` |
| 로즈 핑크 | `#FF6B9A` | `#B02256` | `#C72A62` | `#981C49` | `#FFFFFF` | `#45202F` | `#572A3C` | `#6A3449` | `#FF9DBF` |
| 먹색 모노 | `#AEB6C2` | `#E6E9EE` | `#D3D8DF` | `#BEC5CE` | `#15181D` | `#33363D` | `#3C4048` | `#474B54` | `#E3E7ED` |

(`accent` = `primary`, `on_primary` = `#0F1720` 전 테마. 다크 버튼 면과 `soft` 계열은 위 규칙 E5 에 따라 라이트 hover/기본 값을 맞바꾼 것.) 틴트 강도: 라이트 bg 는 중립 회색 대비 채널 차 약 2~5, 다크 bg/surface 는 테마 hue 로 채널 차 약 3~8 — 테마를 바꾸면 사이드바·바닥이 눈에 띄게 달라지되 "색칠된" 느낌은 아니다.

### 17.6 대비 표 (WCAG, 자동 테스트 대상)

`ratio(fg, bg)` 가 아래 하한 이상이어야 한다. 아래 수치는 설계 시 계산한 근사 하한이며 **정답은 테스트**다(미달 값은 해당 색의 명도를 2~4% 조정). 모든 12 팔레트에 적용.

| 쌍 | 하한 | 비고 |
|---|---|---|
| `text` on `bg`, `surface`, `surface_alt`, `bg_subtle`, `primary_soft` | 7:1 | 실제 라이트 ≥ 14, 다크 ≥ 10 |
| `text_2` on `bg`, `surface`, `surface_alt` | 4.5:1 | 라이트 ≥ 6, 다크 ≥ 7 |
| `text_3` on `bg`, `surface`, `surface_alt`, `hover_fill`(secondary_hover) | 4.5:1 | 라이트 ≥ 4.9, 다크 최저 ≈ 4.8(hover 면 위) |
| `primary_text` on `primary_action`, `primary_hover`, `primary_pressed` | 4.5:1 | 라이트 hover 는 더 진해 ≥ 5.2, 다크 ≥ 4.6 |
| `primary_soft_text` on `soft`, `soft_hover`, `soft_pressed` | 4.5:1 | 다크 최저 ≈ 4.6(블루 pressed) |
| `success_text` on `success_bg`, `warning_text` on `warning_bg`, `error_text` on `error_bg` (+ `danger_pressed`) | 4.5:1 | 다크 ≥ 6.6 |
| `secondary_text` on `secondary`, `secondary_hover`, `secondary_pressed` | 4.5:1 | |
| `toast_text` on `toast_bg` | 7:1 | 14 |
| `link` on `bg_subtle`, `surface` | 4.5:1 | |
| `primary` on `surface`, `bg` (포커스 링·토글 ON·진행 막대·차트 선택 = UI 3:1) | 3:1 | 라이트 ≥ 3.2(모노 ≥ 7), 다크 ≥ 5 |
| `on_primary` on `primary` (체크·손잡이 글리프) | 3:1 | 라이트 최저 3.25, 다크 ≥ 6 |
| `control_border` on `surface` (체크박스 테두리 UI) | 3:1 | 라이트 3.3, 다크 ≈ 4.3 |
| `error`·`success`·`warning` on `surface` (점·아이콘) | 3:1 | 아이콘은 글자 병기 |
| `text_disabled`·`text_placeholder` on `surface_alt` | 예외(AA 면제) 단 다크 3:1 | 다크 ≈ 3.1 |
| 면 구분(`surface` vs `bg`, 선택 알약 vs `sidebar`) | 비텍스트 — 의무 없음 | 의미는 글자색·2px `primary` 띠·아이콘이 함께 전달 |

`primary_action` 면 자체와 `surface` 의 대비(1.4.11)는 버튼 안에 글자가 있어 면제(다크 퍼플·그린 버튼 면은 3:1 미만일 수 있음 — 수용).

### 17.7 컴포넌트별 다크 규칙 (QSS 변경·추가분)

`build_qss(p)` 는 모드를 모르고 팔레트만 읽는다(분기 금지). 아래는 §16.5 대비 **바뀌는 줄**이다.

- 사이드바: `QFrame#Sidebar`, `QListWidget#nav` 배경 `p.sidebar`(기존 `surface`). 내비 알약·글자·아이콘 색은 기존 토큰(`primary_soft`, `primary_soft_text`, 2px `primary` 띠).
- 입력: hover 배경 `p.hover_fill`(기존 `p.border`). 나머지 동일. 다크에서 채움은 `surface_alt`(카드보다 밝음), 포커스 시 `surface` + 2px `primary` 링.
- 체크박스·라디오: 체크 아이콘은 `check-white.svg` 대신 **`on_primary` 로 재착색**한 아이콘(§17.9 SVG 규칙). 미선택 테두리 `control_border`.
- 토글: ON 트랙 `primary`, ON 손잡이 `on_primary`, OFF 트랙 `toggle_off`, OFF 손잡이 `toggle_knob`. 손잡이 색은 t(0~1) 로 보간.
- 버튼: 면 계산은 기존 `Button` 이 `p.*` 로 하므로 팔레트만 바뀌면 됨. 비활성 면 `p.border`, 글자 `text_disabled`. 면 위 글자는 QSS `primary_text`.
- 표: 선택 `primary_soft`+`text`, hover `hover_fill` 대신 **`bg_subtle`**(행 단위, 기존 유지), 행 구분선 `border`. 머리글 `text_3`.
- 로그/코드/diff: `QPlainTextEdit#log` 배경 `surface_alt`, 글자 `text_2`. `DiffView` 행 배경 = `diff_*`(§17.4), 글자 `text`; `…` 같은 보조 글자 `text_3`; 변경 표시 글자 `warning_text`. 다크의 `diff_extra` 는 `primary_soft`(파랑 계열 틴트) — 초록을 쓰지 않는 이유(§5.9)는 동일.
- 배너·배지: `*_bg` 면 + `*_text` 글자. 배너 아이콘은 `success`/`warning`/`error`/`primary` 색으로 재착색(§17.9).
- 툴팁: `toast_bg`/`toast_text` (다크 = 밝은 면 + 어두운 글자). 토스트도 동일. 토스트 외곽 그림자는 §16 대로 라이트에서만 `QColor(0,0,0,α)` — 다크는 그림자를 그리지 않는다(`p.is_dark`).
- 메뉴 (신규, 현재 QSS 없음): 
  `QMenu { background: surface; border: 1px solid border; border-radius: 12px; padding: 6px; }`
  `QMenu::item { padding: 8px 16px 8px 12px; border-radius: 8px; min-width: 140px; color: text; }`
  `QMenu::item:selected { background: primary_soft; color: primary_soft_text; }`
  `QMenu::item:disabled { color: text_disabled; }` `QMenu::separator { height: 1px; background: border; margin: 4px 8px; }`
  팝업 창 속성은 §17.8 의 `AppMenu` 헬퍼.
- 다이얼로그: `QMessageBox`·`QDialog` 배경 `surface`(기존 `QDialog` 가 `bg` 로 묶여 있으면 카드 안 다이얼로그를 `surface` 로 분리). QMessageBox 버튼은 기존 Button 규칙.
- 탭(검증 결과): 선택 글자·밑줄 `text`, 비선택 `text_3`. 상태바 `bg` 바닥 + `text_3`.
- 스크롤바·콤보 팝업: §17.8.
- 지문 뷰어 `QTextBrowser`: 바닥 `bg_subtle`(AnswerBrowser)/`surface`(지문), 글자 `text`. 지문·AI 답변 CSS 는 `build_statement_css(p)` 가 그대로 팔레트를 읽는다. 추가 규칙 3줄: `a { color: {p.link}; }`, `blockquote { color: text_2; }`(기존), 인라인 코드·`pre` 배경 `surface_alt` 에 글자 `text`. **이미지**: SWEA 지문 이미지는 투명 배경 + 검은 선인 경우가 많아 다크에서 사라진다 → 지문 HTML 생성부가 이미지를 `<table class="imgwrap"><tr><td bgcolor="{p.image_paper}">` 로 감싼다(다크일 때만, 둥근 모서리는 못 줌). 표 `th` 배경 `surface_alt`, 테두리 `border`. 샘플 입출력 `pre.sample` 은 기존 규칙.
- 색 있는 인라인 `style="color:…"`·`<font color>` 금지. 리치 텍스트 색은 CSS 클래스(`.ts`·`.imgfail`·`.sample-more` 등)로만 주고 문서의 `defaultStyleSheet` 에 정의한다.

### 17.8 팝업·스크롤바 가장자리 회색 제거 (요구 5)

**원인**
1. 콤보 팝업은 `QComboBoxPrivateContainer`(최상위 팝업 창 + QFrame)가 감싼다. 이 컨테이너는 QSS 규칙이 없어 앱 `QPalette.Window`(Fusion 기본 회색)로 칠해지고, 안쪽 `QAbstractItemView` 는 radius 12 + padding 4 라서 **둥근 모서리 바깥·4px 패딩 틈·스크롤바 둘레**에 회색이 비친다.
2. `QScrollBar:vertical { background: transparent }` 만 있고 `::add-page` / `::sub-page`(핸들 위·아래 트랙)와 `::up-arrow`/`::down-arrow`·`::corner` 를 스타일하지 않아 Fusion 이 트랙을 팔레트(`Mid`/`Window`)로 그린다. 핸들 옆 연한 띠가 그것이다(캡처 8번).
3. `QScrollArea > QWidget > QWidget` 규칙은 뷰포트 자식만 칠하고 코너 위젯과 `Base` 팔레트로 칠하는 뷰포트는 남아, 다크에서는 하얀·회색 사각형이 튄다.

**해결 (3단 병행 — 하나만 적용하면 재발)**
- (a) QSS 추가·교체:
```
QAbstractScrollArea { background: transparent; border: none; }          /* 구체 규칙(QTableWidget 등)보다 앞에 */
QAbstractScrollArea::corner { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; border: none; width: 10px; margin: 2px 2px 2px 0; }
QScrollBar:horizontal { background: transparent; border: none; height: 10px; margin: 0 2px 2px 2px; }
QScrollBar::handle:vertical { background: {border_strong}; border-radius: 3px; min-height: 28px; margin: 0 1px; }   /* 폭 6px 로 보임 */
QScrollBar::handle:horizontal { background: {border_strong}; border-radius: 3px; min-width: 28px; margin: 1px 0; }
QScrollBar::handle:hover { background: {text_placeholder}; }   QScrollBar::handle:pressed { background: {text_3}; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; border: none; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; width: 0; height: 0; }
QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow { background: none; width: 0; height: 0; }
QComboBox QFrame { background: transparent; border: none; }              /* 팝업 컨테이너 */
QComboBox QAbstractItemView { background: {surface}; border: 1px solid {border}; border-radius: 12px; padding: 4px; outline: 0; selection-background-color: {primary_soft}; selection-color: {primary_soft_text}; }
QComboBox QAbstractItemView QScrollBar:vertical { margin: 10px 3px 10px 0; }   /* 둥근 모서리 안쪽으로 */
```
  (기존 `margin: 0`·`width: 8px` 는 위 값으로 대체. 핸들 시각 폭은 6px 로 유지해 기존과 같은 얇음.)
- (b) 코드(위젯 팩토리): `widgets.style_popup(window)` = `setWindowFlag(Qt.FramelessWindowHint)`, `setWindowFlag(Qt.NoDropShadowWindowHint)`, `setAttribute(Qt.WA_TranslucentBackground)`. 모든 콤보 생성 직후 `style_popup(combo.view().window())` 와 `combo.view().viewport().setAutoFillBackground(False)`, `combo.view().setFrameShape(QFrame.NoFrame)`. 모든 `QMenu` 는 `widgets.AppMenu`(생성자에서 `style_popup(self)` 호출)로 교체. 플래그 변경은 창이 처음 보이기 전에만 한다.
- (c) 앱 `QPalette`(§17.9 `qt_palette`): `Window=bg`, `Base=surface`, `AlternateBase=bg_subtle`, `Button=secondary`, `Mid=border_strong`, `Midlight=border`, `Dark=border_strong`, `Window` 가 비치는 모든 곳이 앱 색이 되게 한다. 테마·모드 전환마다 갱신.
- 검증: `combo.view().window().grab()` 의 스크롤바 트랙 열 픽셀이 `surface` 와 ±2 이내, 둥근 모서리 바깥 픽셀 alpha 0(투명 창일 때). 12 팔레트 전부.

### 17.9 QPainter 위젯 · 아이콘 · 캐시 색 출처 규칙

**규칙**: 색은 `paintEvent`/`paint`(델리게이트)가 그리는 시점에 `tokens.current().<필드>` 로 읽는다. 생성자·모듈 전역에 색을 저장하지 않는다. 캐시(QPixmap·QIcon·QBrush·HTML)는 **`tokens.version()` 을 키에 포함**하거나 `ThemeBus.changed` 에서 재생성한다. `.py` 에 `#RRGGBB`·`QColor("#…")`·`Qt.GlobalColor`(`transparent` 제외)·`rgb(`·`setStyleSheet(f"…color…")` 금지.

| 위젯 | 칠하는 요소 → 토큰 |
|---|---|
| `Button`(면) | 기존 `p.*` 조회 유지(§16.5). 포커스 링 `primary` 2px |
| `Toggle` | §17.7 |
| `NavDelegate` | 알약 `primary_soft`(hover `secondary`), 글자 선택 `primary_soft_text`/hover `text`/기본 `text_2`, 선택 띠 `primary` 2px, 비활성 `text_disabled` |
| `ThemeChip` | 칩은 **선택 중인 모드 기준** 해당 테마의 `primary_action` 점 + 이름 `text`, 선택 시 그 테마 `primary_soft` 면 + 2px `primary` 링(그 테마 `primary`). 팔레트는 `theme.light`/`theme.dark` 중 현재 모드 것 |
| `Spinner` | `primary` (회색 비활성 면 위에서 보임) |
| `Skeleton` | 기본 `surface_alt`, 반짝이는 하이라이트 `hover_fill` (라이트 = `border`, 다크 = `secondary_hover`) |
| `BarChart` | 축·눈금선 `border`, 축 글자 `text_3`, 선택 막대 `primary`, 비선택 `border_strong`, 강조 값 글자 `text`, 비강조 `text_2` |
| `Sparkline` | 선 `text_3` 1.5px, 끝점 `primary` |
| `MetricBar`(진행·강도) | 트랙 `surface_alt`, 채움 `primary`/`warning`/`success` |
| `StatusDot` | success/warning/error/`text_3`(미연결 윤곽) |
| `HeatmapWidget` | §17.10. 요일·월 글자 `text_3`, 오늘 테두리 `text` 1.5px, 선택 `primary` 2px |
| `Toast` | §17.7 |
| `DiffView` 행 | §17.7 |
| `EmptyState`·배너 아이콘 | SVG 재착색: 아이콘 색은 `text_3`(빈 상태)·상태색(배너) |

**SVG 재착색**: `svg_icon(name, color=None, size)` 의 기본색은 `tokens.current().text_2`(기존 `#424A53` 문자열 치환 유지, 치환 대상 = `ICON_BASE_COLOR`). 추가 치환 맵(해당 SVG 만 영향): `#1A7F37`→`success`, `#9A6700`→`warning`, 아이콘 내부 흰 글리프 `#FFFFFF`→`on_primary`(체크·상태 아이콘 안쪽). `app.svg`(앱 로고)는 치환 제외. 결과 `QIcon`/`QPixmap` 은 `(name, color, size, devicePixelRatio, tokens.version())` 키의 딕셔너리 캐시.

**`ThemeBus`** (`gui/theme/bus.py`): `QObject` 싱글톤, 신호 `changed()`. `MainWindow.apply_appearance()` 가 모든 적용(QSS·QPalette) 후 마지막에 emit. 구독 대상(캐시를 가진 위젯, `refresh_theme()` 구현): 내비 아이콘, `Button`(글자 옆 아이콘), `EmptyState`, `Banner`(아이콘), `ProblemBrowser`/`AnswerBrowser`(문서 CSS), `LogView`(타임스탬프 span 재생성), 최근 표(칩 델리게이트·전경색), `DiffView`(행 색), 복습 카드(상태 글자 색 → 클래스), `HeatLegend`(칸 색), 설정 칩들(`ThemeChip`·잔디 칩·색 패널), 성장 페이지(잔디 기준색·막대·스파크라인)이다.

### 17.10 잔디 색

- **모드 인식 농도**: 0단계 = `surface_alt`. 1~3단계 = 기준색을 카드 `surface` 에서 섞는 비율, 4단계 = 기준색을 배경 반대쪽(라이트 검정 / 다크 흰색)으로 30% 민 색.
  - 라이트: 혼합 (0.35, 0.65, 1.0) — 현행 유지.
  - **다크: (0.45, 0.72, 1.0)** — 어두운 바닥에서 1단계가 0단계와 구분되도록 올림(블루 기준 명도 L 0단계 0.03 → 0.09 → 0.17 → 0.30 → 0.46 단조 증가).
  - `solved.heat_colors(base, bg, dark: bool = False)` 에 `dark` 인자 추가(기본값으로 호환). `bg` 는 카드 `surface`.
- **기준색 결정**: 설정 `follow` → `tokens.current().primary` (라이트는 테마의 `primary`, 다크는 밝은 다크 `primary`). 고정색 → 저장 hex 를 모드 보정해 사용.
- **모드 보정(표시 전용, 저장값 불변)**: 다크에서 기준색 상대 휘도 < 0.20 이면 흰색 쪽으로 5%씩 섞어 0.20 이상으로. 라이트에서 > 0.60 이면 검정 쪽으로 5%씩 섞어 0.60 이하로. 툴팁·접근성 이름에는 저장 hex.
- **칩**: 설정 → 성장 기록 카드의 잔디 색 줄(기존 위치):
  `[● 테마 색 따르기]` (알약 칩 높이 36, 현재 `primary` 점 16px + 글자, 선택 시 `primary_soft` 면 + 2px `primary` 링 + 체크 아이콘) · 프리셋 5색 원형 칩 32px(기존 24 에서 키움, 사이 간격 8) · `[직접 고르기]`(그라디언트 링 아이콘 있는 원형 칩 32px; 고정색이 프리셋이 아닐 때는 그 색 원형 칩이 자리를 대신하고 같은 이름).
  선택 표시: 2px `text` 링 + 칩 중앙 `on_primary` 체크(색만으로 선택을 알리지 않음). 프리셋 칩 색은 현재 모드의 보정 후 색. 접근성 이름 "풀이 잔디 색: 초록, 선택됨".
- 프리셋 목록은 `solved.HEAT_PRESETS` 유지(초록·파랑·보라·주황·분홍).
- **마이그레이션**: 키 없음 → follow. 키 있음(`#RRGGBB`) → 고정색 그대로(이미 직접 고른 사용자 존중). `parse_hex` 는 `"follow"` 를 모르므로 호출 전에 분기.
- "잔디 기록을 풀이 저장소에 함께 저장" 토글(`HeatSyncToggle`, `.env` `SWEA_SOLVED_SYNC`, 비어 있으면 루트가 git 저장소+원격일 때 ON 표시, M23 에서 활성화): 성장 기록 카드 잔디 색 줄 아래 한 줄(`_toggle_row`). 힌트 "여러 PC 에서 같은 잔디를 보려면 켜세요. 번호·제목·주제·날짜만 저장소에 올라갑니다(지문·코드 없음). …". 성장 기록이 꺼지면 비활성. 저장소가 아니거나 `.gitignore` 가 `.swea-fetch/` 를 무시하면 아래 `HeatSyncNote` 힌트 한 줄로 안내.

### 17.11 잔디 색 선택 패널 (인라인, `widgets.ColorPicker`)

- 위치: 잔디 색 줄 바로 아래에서 `[직접 고르기]` 로 펼침/접힘(높이 트윈 `MOTION_BASE`, 동작 줄이기면 즉시). 카드 안 `QFrame[class="tile"]`(`bg_subtle` 면, radius 12, 패딩 16). 너비는 카드 폭에 맞추되 내용은 최대 320px 왼쪽 정렬.
- 구성(위→아래, 간격 12):
```
ColorPickerPanel (tile)
├─ 제목 줄: "색 직접 고르기" (section 12pt 700)                       [닫기 ✕ 24px 아이콘 버튼, 이름 "색 선택 닫기"]
├─ SVArea   폭 100% (최대 288) × 높이 144, radius 8
│     가로 = 채도 0→100%, 세로 = 명도 100→0%. 현재 색 위치에 지름 14px 링(2px `ring_light` 외곽 + 1px `ring_dark` 안쪽선 — 임의 색 위라 흑백 이중선)
├─ HueSlider 폭 100% × 높이 16 (트랙 radius 8, 색상환 무지개), 손잡이 지름 20 링
├─ 입력 줄:  [미리보기 28×28 원] [HEX 입력 "#2DA44E" 폭 120, mono, 높이 44→36 sm]   [적용됨 ✓ 힌트]
│     오류 시 입력 2px `error` 링 + 아래 한 줄 "색 코드는 #과 영문·숫자 6자리예요 (예: #2DA44E)"(error 클래스)
├─ 미리보기 줄: 잔디 범례와 같은 5칸(0~4단계, 현재 모드 기준 계산) + "적게 … 많이"
└─ 하단 버튼 줄(우측 정렬, 간격 8): [테마 색 따르기로 되돌리기](link) 
```
- 동작: 색 이동 중에는 패널 안 미리보기만 갱신, **놓을 때(마우스 release)·HEX Enter/포커스 아웃·키보드 이동 150ms 디바운스** 에 설정 저장 + `heat_color_changed` emit(성장 탭이 즉시 갱신). 확인/취소 버튼 없음(즉시 적용, 되돌리기 링크로 복구).
- HEX 입력: `#` 자동 보충, 3자리 확장(`#abc`→`#AABBCC`), 대소문자 무시, 잘못된 값은 적용하지 않고 오류 표시, 유효하면 SV·Hue 위치 동기화.
- 키보드: SVArea 포커스 시 ←→ 채도 ±1%, ↑↓ 명도 ±1%(Shift 10%), HueSlider ←→ ±1°(Shift 10°), Tab 순서 SVArea → Hue → HEX → 되돌리기 → 닫기. 접근성 이름 "채도·명도 영역", "색상 슬라이더 0~360", "HEX 색 코드". 포커스 링 `primary` 2px(오프셋 2).
- 한국어 문구 전부 패널 안에 둠(영문 컴포넌트 없음). 다크 대응: 패널 면 `bg_subtle`, 글자 `text`/`text_3`, SV/Hue 의 그라디언트는 색 자체이므로 모드와 무관.
- 터치 타깃: SVArea·Hue·칩 모두 짧은 변 ≥ 16px 이나 포인터 입력 위젯이므로 44px 규칙은 칩(36/32 + 주변 8 간격)에 한해 "가까운 근사"를 수용하고, 표시 중복 입력 수단으로 HEX 입력을 제공한다.

### 17.12 최근 탭 상태 표시

**표 구조 (5열)**: `상태`(128) · `번호`(72) · `제목`(Stretch, 최소 140) · `주제`(112) · `저장 시각`(124). 창 너비로 표 폭이 640 미만이면 `주제` 열 숨김(툴팁에 주제 포함). 행 높이 36 유지.

**상태 판정 규칙** (`service.problem_status(...)` 순수 함수, 문제 번호 단위):
입력: `rec = coach.get_record(num)`(없을 수 있음: `last_result`, `last_submit_at`), `solved_latest` = `solved.load` 를 번호로 모아 가장 늦은 항목(`at`, `via`), `review` = `service.review_items` 중 같은 번호.
1. `solved_latest` 가 있고 (`rec` 가 없거나, `rec.last_result != "pass"` 이면서 `solved_latest.at` ≥ `rec.last_submit_at`, 또는 `rec.last_result == "pass"`) → **Pass**. 세부: `via == "swea"` → "SWEA Pass", `local` → "로컬 Pass"(툴팁에만).
2. 아니면 `rec.last_result` 가 `wrong` → **오답**, `timeout` → **시간 초과**, `runtime_error` → **런타임 오류**.
3. `rec.last_result == "pass"` 인데 solved 기록이 없으면(400일 경과·백필 누락) → **Pass**.
4. 그 외(기록 없음) → **미제출**("아직 제출·검증하지 않음"). 로컬 검증이 실패한 기록은 저장되지 않으므로 이 경우에도 미제출로 보인다 — 후속 개선 후보(별도 빌더 작업).
5. 복습 태그는 상태와 독립: `review.overdue_days >= 0` → "복습 오늘"/"복습 N일 지남"(warning 톤), `< 0` → "복습 N일 뒤"(중립 톤). 상태 칩과 겹칠 수 있다.
6. 한 문제가 표에 번호 중복으로 올 수 있으면(주제 다름) 번호만으로 조회 — 기존 `records.json` 키 규칙과 동일.

**시각**

| 상태 | 칩 면 | 칩 글자·아이콘 | 왼쪽 띠 3px | 아이콘(16px SVG, 선 1.75) | 칩 글자 |
|---|---|---|---|---|---|
| Pass | `success_bg` | `success_text` | `success` | 원 안 체크 `status-pass` | "Pass" |
| 오답 | `error_bg` | `error_text` | `error` | 원 안 X `status-wrong` | "오답" |
| 시간 초과 | `warning_bg` | `warning_text` | `warning` | 시계 `status-timeout` | "시간 초과" |
| 런타임 오류 | `error_bg` | `error_text` | `error` | 삼각 느낌표 `status-runtime` | "런타임 오류" |
| 미제출 | `surface_alt` | `text_2` | 없음 | 빈 원 `status-none` (점선 아님, 1.75 선) | "미제출" |

- 칩: 높이 22, radius 11, 아이콘 14px + 간격 4 + 글자 9pt 700, 좌우 패딩 6/8. 칩 왼쪽 시작 x = 18, 왼쪽 띠는 x = 8 의 3×(행 높이 −16) 둥근 막대. 구분은 **아이콘 모양 + 글자 + 색** 3중(색각 이상 대응: 오답/런타임은 같은 색 계열이지만 아이콘·글자가 다르다).
- 복습 태그: 제목 칸 오른쪽 끝, 높이 20, radius 10, 아이콘 `review`(달력+화살표 12px) + 9pt 700 글자. 도래 = `warning_bg`/`warning_text`, 예정 = `surface_alt`/`text_2`. 제목은 태그 폭 + 8 만큼 줄여 말줄임(오른쪽 `…`).
- 행 hover = `bg_subtle`, 선택 = `primary_soft`(칩 색은 그대로). 칩·띠는 `StatusDelegate` 가 그림(QSS 아님). 위젯을 셀에 넣지 않는다(20행 × 위젯 비용·접근성).
- 접근성: 첫 열 `QTableWidgetItem` 텍스트 = 칩 글자("Pass" 등), `setToolTip("1226번 · Pass(SWEA) · 마지막 제출 09-30 14:44 · 복습 2일 뒤")`, 행 전체 접근성 설명 "1226번 문제, Pass, 복습 2일 뒤".
- 표 위 요약 한 줄(선택): 기존 `count_label` 자리에 "Pass 12 · 오답 3 · 시간 초과 1 · 미제출 4" (hint 클래스). 20개 미만이어도 표시.
- 복습 카드의 "· N일 지남" 글자는 `setStyleSheet(f"color:…")` 대신 `QLabel[class="review-status"][state="due"|"upcoming"]` QSS(due `warning_text`, upcoming `text_3`)로 바꾼다.
- 다크: 칩 색은 §17.4 의 다크 `*_bg`/`*_text`, 띠는 다크 `success`/`error`/`warning`, 미제출 칩 `surface_alt`/`text_2` — 별도 규칙 없음.
- 빈 상태·로딩: 기존 EmptyState 유지. 상태 조회 실패(파일 손상)는 모든 행 "미제출" 이 아니라 **칩을 숨기고**(첫 열 빈칸) 표는 정상 표시 — 상태는 부가 정보.

### 17.13 설정 "화면" 카드

기존 카드(테마 칩 6 + 동작 줄이기)를 다음 순서로 확장한다. 카드 제목 "화면".
```
화면 (card)
├─ 행1  "화면 모드"                      [☀ 라이트 | ☾ 다크 | ▣ 시스템 따르기]  (SegmentedControl, 높이 44)
│       힌트: "시스템 따르기는 Windows 설정의 앱 모드를 따라가요."
├─ divider
├─ 행2  "테마 색"  (ThemeChip 3열 격자, 현재 모드 색으로 표시)
├─ divider
└─ 행3  "동작 줄이기" Toggle (기존)
```
- `SegmentedControl`: 트랙 `surface_alt` radius 12, 안쪽 패딩 4, 칸 radius 8, 선택 칸 `segment_on` + `text` 700, 비선택 `text_2`, hover `hover_fill`. 칸 최소 폭 96, 높이 36(트랙 44). 키보드: 좌우 화살표 이동·Space/Enter 선택, 포커스 링 2px `primary`. 라디오 그룹으로 접근성 노출(이름 "화면 모드: 다크, 선택됨"). 아이콘(sun/moon/monitor)은 16px, 선택 시 글자와 같은 색. 720px 너비에서 칸 아이콘을 숨기고 글자만.
- 선택 즉시 `MainWindow.apply_appearance()`. 시스템 따르기 상태에서 OS 모드가 바뀌어도 반영.
- 테마 칩 격자는 모드가 바뀌면 칩 색도 즉시 새 모드 값으로 다시 그린다.

### 17.14 전환 시 재적용 절차 (요약, 상세는 handoff)

1. `tokens.set_theme/set_color_mode/set_system_dark` → `version` 증가.
2. `app.setPalette(qt_palette(current()))` → `app.setStyleSheet(build_qss())` (한 번만, `setUpdatesEnabled(False)` 로 감싸 깜빡임 방지).
3. 아이콘 캐시 무효화(version 키) → 내비·Button·EmptyState·Banner 재설정.
4. `ThemeBus.changed.emit()` → QTextBrowser 문서 CSS 교체 + 원본 재렌더(스크롤 위치 보존), 로그 재생성, 표·diff 재칠, 잔디·차트 `update()`.
5. 네이티브 타이틀 바·`QStyleHints` 색 구성표 갱신.
6. 설정 저장(`ui/color_mode`, `ui/theme`). 시작 시에는 위젯 생성 **전에** 모드·테마를 해석해 첫 프레임부터 올바른 색(라이트 번쩍임 금지).

### 17.15 접근성 · 일관성 자기검토 결과

- 대비: §17.6 표를 12 팔레트에 자동 테스트. 색만으로 의미를 전하는 곳 없음(상태 칩 = 아이콘+글자, 선택 = 링+체크, 모드 = 아이콘+글자).
- 포커스: 라이트/다크 모두 `primary` 2px 링(≥ 3:1 on `surface`·`bg` — §17.6). 다크 `primary` 가 `soft` 면 위에서도 ≥ 4:1.
- 범위: 새 기능 UI 는 요청된 4개(모드 세그먼트, 색 패널, 상태 칩·태그, 동기화 토글 자리)뿐. 모드 빠른 전환 버튼 등 추가 UI 없음.
- 일관성: 모든 새 색은 팔레트 토큰, 간격은 기존 스케일(4·8·12·16), radius 는 8·12·16·pill.
- 참고: 13번 캡처(선택 내비 굵은 글씨)는 메인에서 힌팅 끔으로 해결됨 — 이 절의 영향 없음.

### 17.16 리스크

| # | 리스크 | 대응 |
|---|---|---|
| X1 | Fusion 이 일부 위젯(QSpinBox 화살표, QAbstractItemView 코너)을 팔레트로 그려 다크에서 흰 사각형 | `qt_palette` 전 역할 지정 + 캡처 휴리스틱 테스트(§handoff) |
| X2 | `QComboBox QFrame` 규칙이 컨테이너에 안 먹음(Qt 버전차) | 코드 `style_popup` + `viewport().setAutoFillBackground(False)` 병행. 캡처로 확인 |
| X3 | 투명 팝업 창이 일부 환경(원격 데스크톱·offscreen)에서 검게 보임 | `WA_TranslucentBackground` 는 팝업에만, 실패 시 radius 0 폴백 플래그 `POPUP_TRANSLUCENT=False` 한 곳에서 끔 |
| X4 | 다크 지문 이미지 | `image_paper` 흰 종이(둥근 모서리 불가 수용) |
| X5 | 다크 3색 퍼플·그린 버튼 면이 `surface` 와 대비 3:1 미만 | 글자 포함 컨트롤이라 면제(§17.6 각주), 필요하면 1px `primary` 테두리 옵션 |
| X6 | 시스템 감지 신호 누락 | 3초 폴링 폴백 |
| X7 | 12 팔레트 틴트가 "칙칙/촌스럽다" | 값만 `tokens.py` 표에서 조정(구조 변경 없음). 사용자가 싫어하면 라이트 틴트를 half 로 |


### 17.17 구현 기록 (builder) — 스펙 대체안

- **값 조정 (대비 표 자동 테스트 결과)**: 라이트 `text_3` `#5E6977` → `#5B6674`(hover_fill 위 4.5:1 미달 해결), `danger_pressed` `#FFDDDD` → `#FFE3E3`(error_text 4.5:1), 숲 그린 라이트 `primary` `#16A364` → `#14995E`(bg 위 3:1). 나머지는 표 그대로.
- **번호 열 폭** 72 → 84: 항목 좌우 패딩 16×2 를 빼면 5자리 번호가 말줄임됨.
- **SVG 리터럴**: 지시서의 4개에 `#CF222E`(error 아이콘)와 콤보 화살표 `#656D76`(text_3 로 재착색) 추가. 치환표는 `tokens.icon_recolor_pairs`.
- **`#RRGGBB` 검사 예외**: 앱 전체 QSS 적용 `app.setStyleSheet(` 는 허용(위젯 `setStyleSheet(` 만 금지). 토스트 그림자 `QColor(0,0,0,α)` 는 `# noqa-color`.
- 체크 표시(체크박스)는 QSS `image:` 에 재착색 SVG 임시 파일(`tempdir/swea_fetcher_icons`, 파일명에 색 포함)을 연결하는 방식. 색 칩의 체크는 직접 그림.
- 상태 판정·`problem_statuses` 는 `service.py`. 상태 조회 실패는 빈 dict(칩 숨김).
- 잔디 동기화 토글(`HeatSyncToggle`)은 행 전체를 숨김 상태로 만들어 둠(기능 연결 전).
- 알려진 한계: AI 답변 표의 격자선 색은 Qt 마크다운 표가 CSS border-color 를 무시해 다크에서 밝은 회색으로 보임.
