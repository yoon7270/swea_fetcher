# M21 토스 스타일 리프레시 — 빌더 구현 지시서

기준 스펙: `design/design-spec.md` §16 (값·규칙의 단일 출처). 이 문서는 **작업 순서와 코드 계약**만 적는다. 스펙과 다르면 코드에 `# 스펙 대체안:` 주석 + §16 에 항목 추가(§0 규칙).
이전 캡처(before): 위임 때 지정된 `design_before/*.png` — 단계마다 같은 해상도(1100×760)로 after 를 `docs/gui-screenshots/` 에 갱신.

## 절대 규칙
- `.py` 의 색 리터럴·`setStyleSheet` 금지(커스텀 페인팅 위젯도 `tokens.LIGHT` 조회). 신규 팔레트 필드는 **기본값 있는 dataclass 필드**로 추가해 기존 생성 코드 호환.
- 기존 objectName·표시 텍스트·시그널·`set_class` 계약 유지(스펙 §16.10 의 호환 처리 표). 테스트는 값 의도를 유지한 채 필요한 것만 수정.
- 모든 애니메이션은 `gui/motion.py` 경유. QGraphicsDropShadowEffect 금지. QGraphicsOpacityEffect 는 애니 끝에 제거.
- 단계(M21-A~E)마다 `pytest -q` 전체 통과 후 **커밋 분리**.

## M21-A 토큰·QSS·글꼴
1. `gui/theme/tokens.py`: §16.4 표대로 `LIGHT` 값 교체 + 신규 필드(`bg_subtle`, `control_border`, `text_placeholder`, `primary_action`, `primary_soft_hover/_pressed`, `secondary/_hover/_pressed`, `toast_bg`, `toast_text`). 상수: `FONT_SIZE_*`(9/10/10.5/12/17/22), `FONT_SIZE_XL`, 간격 20·40, `RADIUS_SM=8 / RADIUS_MD=12 / RADIUS=16 / RADIUS_PILL=999`, `CONTROL_H=44`, `CONTROL_H_LG=52`, `CONTROL_H_SM=36`, `NAV_ITEM_H=44`, `SIDEBAR_W=160`, `PROGRESS_H=4`, `MOTION_*`.
2. `build_qss` 전면 갱신(§16.5). 규칙: `font-weight` 는 700 만. `Button`·`Toggle` 이 직접 그리는 속성(배경·테두리)은 QSS 에서 `transparent/none` 이고 글자색·패딩·min-size 만 QSS. 입력 포커스는 2px 테두리(+padding 보정 불필요 수준으로 투명 2px 테두리 상시).
3. `build_statement_css`: 본문 14px(위젯 폰트 따름 — 글자 크기 미지정 원칙 유지하되 h1~h3 만 상대 크기), `line-height:150%`, h1 16px / h2 15px / h3 14px 굵게, 코드·표 색 토큰.
4. 글꼴: Pretendard-Regular.otf·Bold.otf·LICENSE 를 `gui/theme/fonts/` 에 **원본 그대로** 배치(공식 릴리스), `gui/theme/fonts.py::load_fonts()` (`app.py` 에서 `QApplication` 생성 직후·QSS 전). `addApplicationFont` 가 -1 이면 로그 1줄 후 계속. `FONT_FAMILY` 갱신(폴백 체인). 용량 실측값을 스펙 §16.3 에 기입.
5. `packaging/swea-fetch-gui.spec` `datas` 에 fonts 폴더 추가. 빌드 후 exe 확인은 M21-E.
6. 위젯 코드는 아직 안 건드린다 — 구조 변경 0 으로 전 화면이 새 모양인지 캡처 확인.

## M21-B 공용 컴포넌트 (`gui/widgets/__init__.py`)
- `Button(QPushButton)`: `paintEvent` 로 면·포커스 링 직접 그림(class→색 매핑은 `Palette` 에서), `set_busy(bool)`, 나머지는 QSS. 페이지의 `QPushButton(` 를 전부 `Button(` 로 치환(`grep -n "QPushButton(" swea_fetcher/gui`). 상태바 배지 등 `link` 도 동일.
- `Toggle(QCheckBox)`: 44×26, 클릭 영역 = 행 전체, `sizeHint`·키보드·포커스 링 포함. 설정 페이지 대상 4개(`GrowthEnabledCheck`, `GrowthCommentCheck`, GitHub 자동 동기화 켜기, `ReduceMotionToggle`)만 교체.
- `Toast(QWidget)` + `MainWindow.notify(msg, kind="success", ms=2400)`: 부모 = 중앙 위젯, `WA_TransparentForMouseEvents` 아님(클릭 닫기), 포커스 거부(`Qt.NoFocus`), 리사이즈 시 재배치, 그림자는 `paintEvent` 3겹. **`statusBar().showMessage` 도 항상 같이 호출**. 현재 성공성 `showMessage` 호출부(`폴더를 열었습니다` 등)를 `notify` 로 교체하되 진행 중 메시지는 그대로.
- `EmptyState(..., icon=None)`, `LogView` 카드화(머리글 행: 토글 + [지우기] `link`), `PageColumn(QWidget)`(`setMaximumWidth(840)` + 가운데 정렬 + 폭 800 미만이면 여백 24/패딩 20 으로 전환 `resizeEvent`).
- QFormLayout 4곳 `setRowWrapPolicy(WrapAllRows)`.
- 정적 상태(모션 없음)로 먼저 완성하고 위젯 단위 테스트 추가(variant 별 class/state, disabled, busy, Toggle 상태, Toast 표시·소거).

## M21-C 모션 (`gui/motion.py`)
- API 는 스펙 §16.8. `motion_enabled()` 판정 순서는 §16.9 그대로(env → offscreen → QSettings `ui/reduce_motion` → OS(ctypes `SystemParametersInfoW(0x1042, …)`, 원격 세션 `GetSystemMetrics(0x1000)`; Windows 가 아니거나 실패 시 무시) → `MotionGuard`).
- off 일 때 **애니메이션 객체 생성 금지, 즉시 최종 상태**. 스피너·스켈레톤은 정적 그림.
- `tests/gui/conftest.py`: `QApplication` 생성 전에 `os.environ.setdefault("SWEA_GUI_MOTION", "off")`.
- 적용: A3·A4(Button), A7(Toggle), A6(Toast), A2(NavDelegate — 불안정하면 즉시 전환 대체안 + 스펙 기록), A1(`MainWindow` 가 `stack.setCurrentIndex` 직후 `fade_slide_in`; 시작 복원 시에는 호출 안 함, 연타 시 이전 애니 즉시 종료), A5(Banner.show, ResultCard, CoachBar, EnginePane 상태 전환), A8(Spinner → Button busy), A9(Skeleton → 코치 로딩 패널, 기존 텍스트 라벨 유지).
- 설정 "화면" 카드와 `motion.set_user_reduce` 연결(`ui/reduce_motion`).
- `tests/gui/test_motion.py`: 스펙 §16.9 의 (a)~(f).

## M21-D 페이지
순서: 저장 → 검증 → 최근 → 문제 → 성장 → 설정. 각 페이지의 after 레이아웃은 스펙 §16.5·§16.6. 주의:
- 검증: 탭 pane 투명, `AnswerBrowser` 면 `bg_subtle`, 폼 줄 < 800 에서 줄바꿈.
- 성장: `HeatmapWidget` 의 `_reveal`(A11, 앱 실행당 최초 1회 플래그), 제목 rich text 의 숫자 `xl`(접근성 이름은 평문, `#GrowthHeatTitle` 유지), `BarChart._grow`(A13), 숫자 `count_up`(A12, 값이 바뀐 경우만). 지표 타일(S10)은 먼저 기존 테스트가 행 구조를 단언하는지 확인(`grep -n "GrowthMetrics" tests`) 후 타일 vs 대체안 결정, **결정을 스펙 §16.5 에 기록**.
- 설정: 즉시 저장 옵션을 토글 행으로, 위험 버튼(danger 텍스트형) 영역 분리, "화면" 카드 신설.
- 폰트 폭이 달라지므로 텍스트 폭에 의존하는 테스트가 있으면 의도를 유지해 수정.

## M21-E 마감
- 720×480 / 880×600 / 1100×760 / 150% DPI 캡처, §16.12 수용 기준·체크리스트 수행, 성능(유휴 CPU, 전환 프레임) 기록.
- onefile exe 빌드(`pyinstaller packaging\swea-fetch-gui.spec --noconfirm`) → 한글 렌더·Pretendard 두 웨이트·모션 동작 확인, 폰트 파일 제거 시 폴백 실행 확인.
- `design/design-spec.md` §2·§3·§5 본문을 §16 과 합쳐 정리(상충 문구 삭제).
- 디자이너 **모드 2 정합성 검토** 요청(변경된 UI 파일 목록 전달).

## 열린 질문 (사용자 확인 필요 시)
1. 버튼 색을 정확히 토스 파랑 `#3182F6` 로 통일할까? (흰 글자 3.7:1 → AA 미달, 글자 키우기 필요) — 기본 답: `primary_action #1F6FE8` 유지.
2. 창 기본 크기를 960×680 으로 키울까? (현재 880×600 유지 — 컨트롤이 커져 여유가 줄어듦.)
