# M22 다크 모드 · 테마 확장 · 상태 표시 — 빌더 구현 지시서

기준 스펙: `design/design-spec.md` §17 (값·규칙의 단일 출처). 이 문서는 **작업 순서·코드 계약·테스트**만 적는다. 스펙과 다르게 구현해야 하면 코드에 `# 스펙 대체안:` 주석 + §17 끝에 기록 항목 추가.
캡처 기준 해상도 960×680 / 720×480, 12 팔레트(6 테마 × 라이트·다크)를 `docs/gui-screenshots/m22/` 에 저장(골든 아님, 사람이 보는 용도).

## 절대 규칙
- `gui/**/*.py` 에 색 리터럴 금지: `#RRGGBB`, `QColor("…")`/`QColor(r,g,b…)`(알파 변형 `QColor(0,0,0,α)` 토스트 그림자 제외 — 다크는 그림자 안 그림), `Qt.GlobalColor.*`(`transparent` 제외), `rgb(`/`rgba(`, `setStyleSheet(` 안의 색. 색은 `tokens.current().<필드>` 로만. 예외 파일: `gui/theme/tokens.py`(값 정의), `gui/theme/icons/*.svg`(§아이콘 치환 대상 4개 리터럴 + `app.svg`).
- 색을 그리는 시점이 아니라 **저장해 두는 곳**(생성자 캐시·모듈 전역·QIcon/QPixmap/HTML)은 `tokens.version()` 키 캐시이거나 `ThemeBus.changed` 구독자여야 한다.
- 기존 objectName·표시 텍스트·시그널·`set_class` 계약 유지. 테스트는 값 의도를 유지한 채 필요한 것만 수정.
- 모든 애니메이션은 `gui/motion.py` 경유(패널 펼침 포함). 모드 전환 자체는 애니메이션 없음.
- 단계(M22-A~F)마다 `pytest -q` 전체 통과 후 **커밋 분리**.

## M22-A 토큰 구조 · 팔레트 12벌 (`gui/theme/tokens.py`)
1. `Palette` 에 스펙 §17.3 의 신규 필드 추가(기본값 있음): `is_dark`, `sidebar`, `on_primary`, `hover_fill`, `segment_on`, `toggle_knob`, `link`, `image_paper`, `ring_light`, `ring_dark`. `text_3` 라이트 기본값을 `#5E6977` 로.
2. `Theme(key, label, light, dark)`. 생성기를 `_make_light(spec)` / `_make_dark(spec)` 로 분리하고 **스펙 §17.4(공통)·§17.5(테마별 표)의 값을 표 그대로** 코드에 옮긴다. 라이트 주색 계열은 현재 `THEMES` 값 유지, 다크 주색은 §17.5 다크 주색 표(먹색 모노 다크의 `primary_text` 는 `#15181D`).
3. 상태: `_theme_key`, `_color_mode`("light"|"dark"|"system"), `_system_dark`, `_version`. API: `set_theme`, `set_color_mode(mode)`(모르는 값 → "system"), `set_system_dark(bool)`, `is_dark()`, `color_mode()`, `current()`, `version()`. 위 setter 는 값이 실제로 바뀔 때만 `_version += 1`. `LIGHT` = 블루 라이트 고정, `DARK` = 블루 다크(더 이상 `current()` 가로채기 금지). 새 설정 키 상수: `COLOR_MODE_SETTING_KEY = "ui/color_mode"`, 기본 `"system"`.
4. `build_qss(p)` 를 §17.7 / §17.8 대로 수정: 사이드바 `p.sidebar`, 입력 hover `p.hover_fill`, 체크 아이콘 재착색(아래 아이콘 절), QMenu 규칙 추가, 스크롤바 전체 교체, `QAbstractScrollArea`/`corner`/`QComboBox QFrame`/콤보 뷰 스크롤바 마진. `QDialog` 와 `QMainWindow` 배경 분리(다이얼로그 `surface`). `build_statement_css` 에 `a`, 링크·`.imgwrap` 규칙 추가.
5. `gui/theme/qt_palette.py` (신규): `qt_palette(p) -> QPalette`. 역할 매핑 — Window=`bg`, WindowText/Text/ButtonText=`text`, Base=`surface`, AlternateBase=`bg_subtle`, Button=`secondary`, Mid/Dark=`border_strong`, Midlight/Light=`border`, Highlight=`primary`, HighlightedText=`on_primary`, PlaceholderText=`text_placeholder`, ToolTipBase=`toast_bg`, ToolTipText=`toast_text`, Link/LinkVisited=`link`; Disabled 그룹의 Text/ButtonText/WindowText=`text_disabled`.
6. 테스트(`tests/gui/test_gui_theme.py` 확장, 아래 §테스트).
수용: 12 팔레트 전 필드가 유효한 `#RRGGBB`, 대비 표 통과, `current()` 가 테마·모드 조합마다 올바른 팔레트 반환.

## M22-B 적용 파이프라인 · 설정 "화면" 카드 · 위젯 색 출처
1. `gui/theme/bus.py`: `ThemeBus(QObject)` 싱글톤 `bus()`, 신호 `changed`.
2. `gui/theme/appearance.py` (신규, Qt 의존 허용): `detect_system_dark() -> bool`(스펙 §17.2 순서: `styleHints().colorScheme()` → 레지스트리 `AppsUseLightTheme`), `apply_native_scheme(window)`(Qt 6.8 `setColorScheme`, 없으면 DWM ctypes 20 — 모두 try/except 무시), `SystemWatcher`(신호 `colorSchemeChanged` 있으면 연결, 없으면 3초 QTimer 폴링; 모드가 system 일 때만 emit).
3. `MainWindow.apply_theme(key)` → `apply_appearance()` 로 확장(옛 이름은 얇은 래퍼로 유지):
   ```
   setUpdatesEnabled(False)
   tokens.set_theme / set_color_mode / set_system_dark   # 필요한 것만
   app.setPalette(qt_palette(tokens.current()))
   app.setStyleSheet(tokens.build_qss())
   nav 아이콘 갱신, Button.refresh_icon() 전부
   bus().changed.emit()
   apply_native_scheme(self)
   setUpdatesEnabled(True); self.update()
   QSettings 저장(ui/theme, ui/color_mode)
   ```
   기존 "모든 QWidget `update()` 루프" 는 `bus.changed` 구독 + 직접 그리는 위젯은 `update()` 로 대체해도 되지만, 안전하게 마지막에 한 번 유지.
4. `app.py`: 위젯 생성 **전에** `set_color_mode(QSettings ui/color_mode)` + `set_system_dark(detect_system_dark())` + `app.setPalette` + `setStyleSheet`. (첫 프레임 라이트 번쩍임 금지.)
5. `widgets.SegmentedControl`(신규): 3칸 라디오 그룹, 스펙 §17.13. `QAbstractButton` 3개 + `QButtonGroup`, paintEvent 직접 그림(트랙 `surface_alt`, 선택 `segment_on`). `selected_changed(str)` 시그널. 접근성 이름·키보드 §17.13.
6. 설정 "화면" 카드: 행1 세그먼트 → 행2 `ThemeChip` 격자 → 행3 `ReduceMotionToggle`. 선택 시 `MainWindow` 에 신호 `appearance_changed(color_mode, theme_key)`.
7. SVG: 
   - `svg_icon` 기본 색 = `tokens.current().text_2`; 치환 맵 `{ICON_BASE_COLOR→color, "#1A7F37"→success, "#9A6700"→warning, "#FFFFFF"→on_primary}` (`app.svg` 는 호출 경로가 다르므로 제외). 체크 아이콘은 QSS `image: url(check-white.svg)` 이므로 **런타임에 재착색한 SVG 를 임시 파일(캐시 디렉터리 `tempfile`, 이름에 version 포함)로 써서 QSS url 로 연결**하거나, 체크 표시를 `QCheckBox::indicator:checked` 대신 `Checkbox.paintEvent` 로 옮긴다 — 둘 중 단순한 쪽. 파일 방식이면 `build_qss` 가 경로를 받도록 인자 추가(테스트 가능하게 `icon_dir` 주입).
   - 캐시 키 `(name, color, size, dpr, tokens.version())`.
   - 신규 아이콘 11개(16px, viewBox 0 0 16 16, stroke `#424A53`·1.75·round, fill none) — 디자이너 방향: `mode-light`(원 r3 + 8방향 짧은 선), `mode-dark`(초승달), `mode-system`(모니터 사각 + 받침 선), `status-pass`(원 r6.25 + 체크), `status-wrong`(원 + X), `status-timeout`(원 + 시침·분침), `status-runtime`(삼각형 윤곽 + 세로선·점), `status-none`(원 윤곽만), `review`(달력 사각 + 위 두 짧은 선 + 순환 화살표 작게), `check-on-primary`(= check-white 와 같은 모양, 색은 치환). 칩 아이콘은 칩 글자색으로 재착색하므로 모두 기본 스트로크 색 사용.
8. 모든 `setStyleSheet(` 제거: `HeatLegend` 칸(→ 직접 그리는 `Swatch`), 설정의 `_swatch_qss`(→ 직접 그리는 `ColorChip`), 복습 카드 상태 글자(→ `QLabel[class="review-status"][state=…]`, QSS 는 §17.12). 이 단계에서 grep 테스트(§테스트)가 통과해야 한다.
9. 직접 그리는 위젯 색 출처는 스펙 §17.9 표대로 점검(대부분 이미 `tokens.current()` 사용). 확인할 점 2곳: `Toggle`(ON 손잡이 `on_primary`, OFF 손잡이 `toggle_knob`, lerp), `Toast`(다크 그림자 생략, 아이콘·글자 `toast_text`). `Skeleton` 하이라이트 `hover_fill`.
10. 리치 텍스트: `ProblemBrowser`/`AnswerBrowser` 에 `_source`(원본 마크다운/HTML)를 보관하고 `refresh_theme()` 구현 — `document().setDefaultStyleSheet(build_statement_css(current()))` → 원본 재설정 → 스크롤 값 복원(`bus.changed` 구독). `LogView` 는 최근 N=500줄 원본 줄을 보관해 `refresh_theme()` 에서 재생성(타임스탬프 span 색은 인라인 금지 — 문서 기본 스타일시트 클래스 `.ts`). 지문 HTML 생성부는 다크일 때 `<img>` 를 `<table class="imgwrap"><tr><td bgcolor="{image_paper}">…</td></tr></table>` 로 감싼다(모드가 바뀌면 원본을 다시 렌더).
11. `DiffView.refresh_theme()`: 기존 아이템의 background/foreground 를 현재 팔레트로 재칠(행 데이터 유지).
수용: 설정에서 모드·테마를 바꾸면 **재시작 없이** 모든 페이지가 즉시 바뀌고, 라이트로 돌아와도 잔존 다크 색(또는 반대)이 없다. grep·대비 테스트 통과.

## M22-C 팝업·스크롤바·메뉴 가장자리 (요구 5)
1. `build_qss` 의 스크롤바·콤보·`QAbstractScrollArea` 블록을 스펙 §17.8(a) 그대로. 기존 `QScrollArea > QWidget > QWidget` 규칙은 유지하되 `QAbstractScrollArea` 일반 규칙을 구체 규칙보다 **앞**에 둔다.
2. `widgets.style_popup(window)`(§17.8(b))와 `widgets.AppMenu`. `widgets` 의 콤보 생성부(또는 `ComboBox` 서브클래스)에서 생성 직후 호출. 앱 안의 `QComboBox(` 직접 생성과 `QMenu(` 직접 생성을 grep 해 모두 교체(예: `history_page._context_menu`). 모듈 상수 `POPUP_TRANSLUCENT = True` 한 곳에서 투명 창 사용을 제어.
3. 12 팔레트에서 캡처 비교(전/후): 주제 콤보 목록, 우클릭 메뉴, 긴 로그 영역 스크롤바, 설정 페이지 세로 스크롤, 표 가로 스크롤.
수용: 스펙 §17.8 검증(트랙 열 픽셀 ≈ `surface`, 모서리 바깥 투명). 스크롤바 핸들 폭이 시각적으로 6px, hover 에 색 변화.

## M22-D 잔디 색 · 색 선택 패널
1. 설정 키: `growth/heat_color` = `"follow"`(기본, 키 없음 포함) | `"#RRGGBB"`. 읽기 함수 `heat_base(settings_value) -> (kind, hex)` 한 곳에 모아 설정 페이지·성장 페이지가 공유(분기 후 `parse_hex`). 기존 키가 hex 면 고정색 유지.
2. `solved.heat_colors(base, bg, dark=False)`: 혼합 비율 `HEAT_MIX_DARK = (0.45, 0.72, 1.0)` 추가, `dark` 에서 사용. `solved.adjust_for_mode(hex, dark)`(휘도 보정, §17.10) 순수 함수 추가. 단위 테스트: 다크에서 0~4단계 휘도가 엄격 증가, 보정 후 휘도 하한/상한.
3. `growth_widgets.heat_palette()` 가 `(surface_alt, surface, is_dark)` 를 돌려주도록 변경하고 `HeatmapWidget.level_colors()`/`HeatLegend` 가 `is_dark` 를 넘긴다. 기준색은 `follow` 면 `tokens.current().primary` — 테마·모드가 바뀌면 `bus.changed` 에서 `HeatmapWidget.base` 재계산 후 `update()`(채움 애니메이션 재생 금지: `_HEAT_INTRO_DONE` 유지).
4. `widgets.ColorPicker`(스펙 §17.11): 하위 위젯 `SVArea`·`HueSlider`(paintEvent 직접 그림, `QImage` 그라디언트는 크기·hue 키 캐시) + HEX `QLineEdit`(검증·3자리 확장). `QColorDialog` import/호출 제거(`settings_page._pick_heat_color` 폐기). 값 변경 신호 `color_committed(str)`(release/Enter/150ms 디바운스) — 설정 페이지가 저장 + `heat_color_changed` emit.
5. 잔디 색 줄: `ColorChip`(원형 32px, 직접 그림, 선택 시 링+체크) · `FollowChip`(알약 36). 선택 상태 전환 규칙 §17.10. 패널 펼침/접힘은 `motion.tween`(높이), 끄면 즉시.
6. `HeatSyncToggle` 행은 코드로 만들되 **기능 연결 전까지 `setVisible(False)`**; 별도 빌더 작업이 연결할 때 보이게.
수용: 기본 설치(키 없음)에서 잔디가 현재 테마 색이고 테마를 바꾸면 따라 바뀐다. 고정색 선택 후엔 테마를 바꿔도 안 바뀌고 [테마 색 따르기]로 복귀. 다크에서 0칸이 카드와 구분되고 1~4단계가 단조롭게 밝아진다. HEX 잘못된 입력은 적용되지 않고 오류 문구.

## M22-E 최근 탭 상태 표시
1. `service.py`(또는 `status.py`)에 순수 함수 `problem_status(rec, solved_latest, review) -> ProblemStatus(key, label, detail, review_tag)` 와 조회 함수 `problem_statuses(settings, nums)`(1회에 `solved.load` + `coach._load_records` + `review_items` 읽어 번호별 dict) — 스펙 §17.12 판정 1~6. UI 스레드에서 호출하되 파일 3개 읽기뿐(20행) — 예외는 삼키고 빈 dict(상태 칩 숨김).
2. `history_page`: 5열(`상태`·번호·제목·주제·저장 시각), 열 너비 §17.12, 폭 640 미만 `주제` 숨김(`resizeEvent`), `StatusDelegate`(칩·띠·복습 태그를 paint; `Qt.UserRole+1` = 상태 key, `+2` = 복습 태그 `(text, tone)`), 첫 열 아이템 텍스트·툴팁·접근성 설명 §17.12. `__import__("PySide6.QtGui"…)` 해킹 제거(전경색 `QColor(p.text_3)` 정식 import).
3. 복습 카드 상태 글자를 클래스 방식으로(§M22-B-8).
4. `count_label` 위치에 상태 요약(선택, 칩 순서 Pass·오답·시간 초과·런타임 오류·미제출 중 0 인 것 생략).
5. `bus.changed` → 표 `viewport().update()`(델리게이트가 매번 토큰을 읽음).
수용: 각 상태가 라이트·다크에서 칩 텍스트·아이콘·띠로 구분되고, 흑백 변환 캡처에서도 상태를 읽을 수 있다. 테스트: 판정 함수 표 기반 파라미터 테스트(아래).

## M22-F 마감
1. 12 팔레트 × 페이지 5개(저장·검증·최근·문제·성장·설정 — 6) 캡처, 다이얼로그(MessageBox·git_dialog)·토스트·배너 4종·배지 5종·콤보 팝업·메뉴 캡처.
2. 이 문서 §수동 체크리스트 수행, 결과와 스펙 대체안을 `design/design-spec.md` §17 끝 `17.17 구현 기록`에 기록.
3. 실제 exe 자가진단, 다크 모드에서 SVG 아이콘·Pretendard 확인.

## 테스트 방법

자동(`tests/gui/`):
1. **대비**: `test_gui_theme.py` 에 `CONTRAST_PAIRS`(스펙 §17.6 표의 (전경 필드, 배경 필드 목록, 하한))을 정의하고 `THEMES × (light, dark)` 파라미터화. 상대 휘도·대비 계산 함수는 테스트 안에 구현(외부 의존 없음). 실패 메시지에 `테마/모드/쌍/실제값` 포함.
2. **구조**: 12 팔레트 모든 필드 `^#[0-9A-F]{6}$`; 라이트와 다크의 `bg` 휘도 관계(다크 < 라이트), 다크에서 `bg < sidebar < surface < surface_alt` 휘도 단조(`bg_subtle` 은 surface 와 alt 사이); `current()` 가 `set_color_mode("dark")`/`set_system_dark` 조합에 맞게 선택; `version()` 증가.
3. **QSS**: 12 팔레트에 `build_qss(p)` 가 예외 없이 생성되고 `None`·`{`·`}` 미치환 문자열이 없으며, **다크 QSS 에 라이트 `bg` 값이 나오지 않는다**(라이트 전용 하드코딩 누수 탐지: 다크 QSS 안의 모든 `#RRGGBB` ⊆ 다크 팔레트 값 ∪ 아이콘 경로 제외).
4. **하드코딩 색 grep**(`tests/gui/test_no_hardcoded_colors.py`): `swea_fetcher/gui/**/*.py`(tokens.py 제외) 소스를 정규식으로 검사 — `#[0-9A-Fa-f]{6}\b`, `QColor\(\s*["']`, `QColor\(\s*\d`(토스트 그림자 허용 목록 1곳 라인 지정 대신 `# noqa-color` 주석 필수), `Qt\.GlobalColor\.(?!transparent)`, `setStyleSheet\(`(허용: 없음), `rgba?\(`. 실패 시 `파일:라인` 출력. SVG 는 허용 리터럴 집합만 검사.
5. **전환 재적용**: 오프스크린 `MainWindow` 에서 라이트→다크→라이트로 `apply_appearance` 후 (a) `app.styleSheet()` 가 해당 모드 팔레트 값으로 생성된 것과 같음, (b) `AnswerBrowser.document().defaultStyleSheet()` 에 `current().text` 값이 있음, (c) 내비 아이콘 픽셀의 한 점이 해당 모드 `text_2` 계열, (d) 표·diff 아이템 전경색이 새 팔레트 값.
6. **팝업·스크롤바 회색**: 콤보 뷰 `viewport`/스크롤바 영역 `grab()` 샘플 픽셀이 `surface` 와 ±2(12 팔레트). QMenu `grab()` 의 가장자리 안쪽 1px 외 영역이 `surface`.
7. **흰 면 누수 휴리스틱**: 다크 12 팔레트에서 각 페이지 `grab()` 의 (휘도 > 0.60) 픽셀 비율 < 12%(글자·아이콘 제외 큰 흰 사각형 탐지). 한 번 측정 후 여유를 둔 임계값으로 고정.
8. **잔디**: `adjust_for_mode`·`heat_colors(dark=True)` 단위 테스트(단조·보정·hex 대소문자), 설정 키 마이그레이션(키 없음 → follow, hex → 고정, 쓰레기 값 → follow), 테마 변경 시 follow 기준색 갱신.
9. **상태 판정**(`tests/test_problem_status.py`, GUI 불필요): 표 기반 — (rec 없음·solved 없음 → none), (rec wrong·solved 없음 → wrong), (rec wrong·solved.at ≥ submit_at → pass), (rec timeout·solved.at < submit_at → timeout), (rec pass·solved 없음 → pass), (rec runtime_error → runtime_error), 복습 태그 도래/예정/없음 조합, 파일 손상 → 빈 dict(예외 없음).
10. **델리게이트**: `StatusDelegate.paint` 를 `QImage` 에 그려 5개 상태 칩 영역의 대표 픽셀이 `*_bg`, 띠 픽셀이 상태색(라이트·다크).
11. **세그먼트·패널**: `SegmentedControl` 키보드 이동·선택 시그널, `ColorPicker` HEX 검증(유효/3자리/오류)·Enter 로 `color_committed`. `QColorDialog` 가 소스에 없음(grep).
12. 기존 1,433개 테스트: 모든 GUI 테스트 conftest 는 `SWEA_GUI_MOTION=off` 유지, 모드는 `light` 고정(`set_color_mode("light")` 픽스처)으로 기존 값 단정이 흔들리지 않게 한다.

수동(캡처 기반): 아래 체크리스트.

## 마일스톤

| 단계 | 내용 | 커밋 | 예상 |
|---|---|---|---|
| M22-A | 토큰 구조·12 팔레트·qt_palette·대비/구조 테스트 | 1 | 0.5~1일 |
| M22-B | 적용 파이프라인·세그먼트·설정 카드·SVG·리치 텍스트·grep 테스트 | 1~2 | 1~1.5일 |
| M22-C | 팝업·스크롤바·메뉴 회색 제거 | 1 | 0.5일 |
| M22-D | 잔디 follow·다크 농도·색 선택 패널 | 1 | 1일 |
| M22-E | 최근 탭 상태 판정·델리게이트 | 1 | 0.5~1일 |
| M22-F | 캡처·체크리스트·기록·exe 확인 | 1 | 0.5일 |

순서 의존: A → B → (C, D, E 는 서로 독립, B 이후) → F. 사용자 검토가 필요하면 B 후 다크 캡처를 먼저 보여준다(색 값은 `tokens.py` 표만 바꾸면 조정됨).

## 수용 기준

1. 설정 "화면" 카드에서 라이트/다크/시스템 따르기를 고르면 즉시(재시작 없이) 전 화면이 전환되고, 값은 재시작 후에도 유지된다. 시스템 따르기에서 Windows 앱 모드를 바꾸면 앱이 따라 바뀐다.
2. 6 테마 × 2 모드 모두에서 §17.6 대비 테스트 통과, 모든 화면에서 라이트 전용 또는 다크 전용 잔존 색 없음(grep·캡처).
3. 테마를 바꾸면 버튼·탭뿐 아니라 바닥·사이드바·hover·선택면 색조가 바뀐다(라이트 블루 vs 숲 그린 캡처에서 바닥/사이드바가 육안 구분). 텍스트는 어느 팔레트에서도 4.5:1 이상.
4. 잔디 기본이 "테마 색 따르기"이고 테마·모드 변경에 따라간다. 고정색 선택·복귀 가능. 기본 QColorDialog 는 쓰이지 않고 색 패널은 한국어이며 다크 대응.
5. 최근 탭에서 문제별 상태(Pass/오답/시간 초과/런타임 오류/미제출)와 복습 태그가 칩·띠·아이콘·글자로 보이고 판정 규칙 테스트가 통과.
6. 콤보 팝업·메뉴·스크롤바 가장자리에 회색 띠·모서리가 없다(라이트·다크 12 팔레트).
7. 지문 뷰어·AI 답변·로그·diff·코드 영역이 다크에서 읽기 쉽고 이미지가 사라지지 않는다.
8. 전체 pytest 통과, 모션 off 테스트 기본 유지.

## 수동 체크리스트 (라이트·다크 각각, 최소 블루·그린·모노는 필수, 나머지는 훑기)
- [ ] 저장 페이지: 헤더·입력 포커스 링·히어로 카드·진행 막대·토스트·배너 4종
- [ ] 검증 페이지: 번호 입력, 코치 바, 탭 밑줄, diff 표 4색 행, 로그, 코드 영역, 스피너·스켈레톤
- [ ] 최근 페이지: 상태 칩 5종, 띠, 복습 태그 2종, hover·선택 행, 우클릭 메뉴, 640 미만에서 주제 열 숨김
- [ ] 문제 페이지: 지문(본문·표·인라인 코드·링크·이미지), 샘플 입출력, 확대/축소
- [ ] AI 코치: 답변 마크다운(제목·목록·코드·인용·표), 로딩·에러·빈 상태
- [ ] 성장 페이지: 잔디(0~4단계·오늘·선택 테두리·월/요일 라벨·범례), 막대·스파크라인·지표 타일, 리포트 목록
- [ ] 설정: 세그먼트 3칸(키보드 포함), 테마 칩 6, 잔디 색 줄·패널(HEX 오류·되돌리기), 토글 ON/OFF, 위험 영역 danger 버튼
- [ ] 콤보 팝업(주제), 메뉴, 툴팁, MessageBox, git 다이얼로그, 파일 대화상자(네이티브, 앱 모드와 달라도 무시)
- [ ] 스크롤바: 세로(페이지·표·로그·콤보)·가로 — 트랙 회색 없음, hover/drag 색
- [ ] 내비: 선택 알약·hover·아이콘 색(선택 시 `primary_soft_text`), 비활성
- [ ] 모드 전환 중 깜빡임·잔상 없음, 전환 직후 스크롤 위치·입력 내용 유지, 시작 직후 첫 프레임이 이미 올바른 모드
- [ ] 150% DPI·720×480 에서 칩·세그먼트·패널이 잘리지 않음
- [ ] 흑백(채도 0) 캡처에서도 상태 칩 의미가 구분됨

## 열린 질문 (기본값으로 진행, 확인 불필요)
- 모드 기본값 = 시스템 따르기. 첫 실행 사용자 Windows 가 다크면 바로 다크로 시작한다.
- 로컬 검증 실패는 기록이 없어 "미제출"로 보인다. 필요하면 후속으로 `solved`/records 에 실패 기록을 남기는 별도 작업.
- 라이트 카드 면 틴트 없음(스펙 E3). 더 강한 테마 느낌을 원하면 라이트 `bg`·`sidebar` 의 채널 차만 키운다.
