"""디자인 토큰 (색·폰트·간격·반경). 값의 출처는 design/design-spec.md §2 — 값을 바꿀 땐 스펙을 먼저 고친다.

QSS 는 build_qss() 가 토큰으로 생성한다. 라이트 1종 기본, 다크는 DARK 를 채우면 활성화.
위젯 코드에서 색상값을 직접 쓰지 않는다 — 반드시 LIGHT.<field> 를 참조한다 (diff 행 배경, 카드 내부 rich text 등).
셀렉터 규약: objectName(#nav, #log, #diff, #busy) + 동적 속성 class / state (widgets.set_class).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str  # 창·페이지 배경
    surface: str  # 카드·입력창·사이드바·테이블 배경
    surface_alt: str  # 로그 영역, 테이블 헤더, hover 배경, 비활성 입력 배경 (스펙: surface_sunken)
    border: str  # 모든 1px 테두리
    primary: str  # 주 버튼, 포커스 링, 진행 막대, 탭 밑줄
    primary_hover: str
    primary_text: str  # primary 배경 위 글자 (흰색)
    accent: str  # 예약 — M4 스펙에서 사용처 없음. 새 용도를 만들지 말 것
    success: str  # 아이콘·단독 글자·배너 테두리
    success_bg: str  # 배너·배지 배경 (스펙: success_subtle)
    warning: str
    warning_bg: str
    error: str  # 스펙: danger
    error_bg: str
    text: str  # 1단계 본문
    text_2: str  # 2단계 레이블·보조 설명·로그 본문 (스펙: text_secondary)
    text_3: str  # 3단계 힌트·플레이스홀더·상태바 (스펙: text_muted) — bg 위 4.8:1, 이보다 연한 글자 금지
    diff_same: str
    diff_changed: str  # = warning_bg
    diff_missing: str  # = error_bg   (기대에만 있는 줄)
    diff_extra: str  # = primary_soft (실제에만 있는 줄 — 초록을 쓰지 않는 이유는 스펙 §5.9)
    # --- 스펙 추가분 (기본값 있음 → 기존 생성 코드 호환) ---
    border_strong: str = "#B9BFC9"  # 입력 hover 테두리, 스크롤바 핸들
    primary_pressed: str = "#164FAD"
    primary_soft: str = "#DDEBFF"  # 선택된 내비, info 배너, running 배지 배경 (스펙: primary_subtle)
    primary_soft_text: str = "#0B4AA8"  # primary_soft 위 글자
    success_text: str = "#116329"  # success_bg 위 글자 (원색 success 를 subtle 위 글자로 쓰지 않는다)
    warning_text: str = "#7D5300"
    error_text: str = "#A40E26"
    text_disabled: str = "#8C959F"  # 비활성 컨트롤 글자 (AA 예외)


LIGHT = Palette(
    bg="#F4F5F7",
    surface="#FFFFFF",
    surface_alt="#EDEFF2",
    border="#D5D9E0",
    primary="#1F6FEB",
    primary_hover="#1A5FD0",
    primary_text="#FFFFFF",
    accent="#1F6FEB",
    success="#1A7F37",
    success_bg="#DAFBE1",
    warning="#9A6700",
    warning_bg="#FFF8C5",
    error="#CF222E",
    error_bg="#FFEBE9",
    text="#1F2328",
    text_2="#424A53",
    text_3="#656D76",
    diff_same="#FFFFFF",
    diff_changed="#FFF8C5",
    diff_missing="#FFEBE9",
    diff_extra="#DDEBFF",
)

DARK: Palette | None = None  # 디자이너가 다크를 만들면 채운다 (M4 범위 밖)

# 글꼴: Windows 기본만 사용, 번들 없음 (스펙 §2.2 결정 근거)
FONT_FAMILY = '"Malgun Gothic", "Segoe UI", sans-serif'
FONT_MONO = 'Consolas, "Cascadia Mono", "D2Coding", monospace'
# 크기(pt). 96dpi 환산: 8pt≈11px, 9pt=12px, 10pt≈13px, 11pt≈15px, 13pt≈17px
FONT_SIZE_XS = 8  # 배지, 상태바, 테이블 헤더
FONT_SIZE_SM = 9  # 보조 설명, 힌트, 로그, diff, 테이블 본문, 배너 본문
FONT_SIZE = 10  # 본문, 입력, 버튼, 내비
FONT_SIZE_MD = 11  # 카드 제목, 섹션 제목, 앱 이름
FONT_SIZE_LG = 13  # 페이지 제목

SPACE = 8  # 기본 간격 단위(px). 허용 값: SPACE//2(4), SPACE(8), 12, SPACE*2(16), SPACE*3(24), SPACE*4(32)
RADIUS = 6  # 카드·배너·로그·테이블
RADIUS_SM = 4  # 입력·버튼·체크박스
CONTROL_H = 32  # 입력·콤보·버튼 높이
CONTROL_H_SM = 28  # 배너 안 버튼, 테이블 행
NAV_ITEM_H = 40
SIDEBAR_W = 148
PROGRESS_H = 3  # 진행 중 인디케이터(얇은 막대)
WINDOW_DEFAULT = (880, 600)
WINDOW_MIN = (720, 480)
LOG_H_DEFAULT = 140
LOG_H_MIN = 80


def build_qss(p: Palette = LIGHT) -> str:
    """토큰 → QSS. 위젯은 objectName / 동적 속성(class, state)으로 구분한다. 스펙 §5·§13 과 1:1."""
    s = SPACE
    return f"""
/* ---------- 기본 ---------- */
QWidget {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}pt; color: {p.text}; }}
QMainWindow, QDialog, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QToolTip {{ background: {p.text}; color: {p.surface}; border: none; padding: {s//2}px {s}px; font-size: {FONT_SIZE_SM}pt; }}

/* ---------- 텍스트 역할 ---------- */
QLabel {{ background: transparent; }}
QLabel[class="title"]   {{ font-size: {FONT_SIZE_LG}pt; font-weight: 600; }}
QLabel[class="section"] {{ font-size: {FONT_SIZE_MD}pt; font-weight: 600; }}
QLabel[class="muted"]   {{ color: {p.text_2}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="hint"]    {{ color: {p.text_3}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="error"]   {{ color: {p.error_text}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="mono"]    {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="app-title"] {{ font-size: {FONT_SIZE_MD}pt; font-weight: 600; padding: {s*2}px {s*2}px {s+4}px {s*2}px; }}

/* ---------- 사이드바 내비 ---------- */
QListWidget#nav {{
    background: {p.surface}; border: none; border-right: 1px solid {p.border};
    padding: 0 {s}px; min-width: {SIDEBAR_W}px; max-width: {SIDEBAR_W}px;
}}
QListWidget#nav::item {{
    min-height: {NAV_ITEM_H}px; padding: 0 {s+4}px; margin: 1px 0;
    border-radius: {RADIUS_SM}px; color: {p.text_2};
}}
QListWidget#nav::item:hover    {{ background: {p.surface_alt}; color: {p.text}; }}
QListWidget#nav::item:selected {{ background: {p.primary_soft}; color: {p.primary_soft_text}; font-weight: 600; }}
/* (builder) `#nav:focus::item:selected` 는 Qt 가 리스트 전체 테두리로 해석해 제거 — 선택 항목 배경으로 충분 */

/* ---------- 진행 막대 (헤더 아래, 진행 중에만 표시) ---------- */
QProgressBar#busy {{ border: none; background: {p.surface_alt}; min-height: {PROGRESS_H}px; max-height: {PROGRESS_H}px; }}
QProgressBar#busy::chunk {{ background: {p.primary}; }}

/* ---------- 입력 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_SM}px;
    padding: 0 {s}px; min-height: {CONTROL_H - 2}px; max-height: {CONTROL_H - 2}px;
    selection-background-color: {p.primary}; selection-color: {p.primary_text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {p.border_strong}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 2px solid {p.primary}; padding: 0 {s-1}px; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ background: {p.surface_alt}; color: {p.text_disabled}; }}
QLineEdit[state="invalid"] {{ border: 2px solid {p.error}; padding: 0 {s-1}px; }}
QLineEdit[class="mono"] {{ font-family: {FONT_MONO}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {p.surface}; border: 1px solid {p.border}; outline: 0;
    selection-background-color: {p.primary_soft}; selection-color: {p.text};
}}
QPlainTextEdit, QTextEdit {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS}px; padding: {s}px; }}

QCheckBox {{ spacing: {s}px; min-height: 24px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {p.border_strong}; border-radius: {RADIUS_SM}px; background: {p.surface}; }}
QCheckBox::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; }}
/* (builder) `QCheckBox:focus::indicator` 는 체크박스 전체 테두리로 해석돼 제거 — Fusion 기본 포커스 표시 사용 */
QCheckBox:disabled {{ color: {p.text_disabled}; }}

/* ---------- 버튼 ---------- */
QPushButton {{
    background: {p.surface}; color: {p.text}; border: 1px solid {p.border}; border-radius: {RADIUS_SM}px;
    padding: 0 {s*2}px; min-height: {CONTROL_H - 2}px; max-height: {CONTROL_H - 2}px;
}}
QPushButton:hover   {{ background: {p.surface_alt}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:focus   {{ border: 2px solid {p.primary}; padding: 0 {s*2-1}px; }}
QPushButton:disabled {{ color: {p.text_disabled}; background: {p.surface_alt}; border-color: {p.border}; }}
QPushButton[class="primary"] {{ background: {p.primary}; color: {p.primary_text}; border-color: {p.primary}; font-weight: 600; min-width: 96px; }}
QPushButton[class="primary"]:hover   {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton[class="primary"]:pressed {{ background: {p.primary_pressed}; }}
QPushButton[class="primary"]:focus   {{ border: 2px solid {p.primary_pressed}; }}
QPushButton[class="primary"]:disabled {{ background: {p.border_strong}; border-color: {p.border_strong}; color: {p.surface}; }}
QPushButton[class="danger"] {{ color: {p.error}; }}
QPushButton[class="danger"]:hover {{ background: {p.error_bg}; border-color: {p.error}; }}
QPushButton[class="danger"]:focus {{ border: 2px solid {p.error}; }}
QPushButton[class="link"] {{ border: none; background: transparent; color: {p.primary_soft_text}; padding: 2px {s//2}px; min-height: 0; }}
QPushButton[class="link"]:hover {{ background: {p.surface_alt}; }}
QPushButton[class="sm"], QFrame[class="banner"] QPushButton {{
    min-height: {CONTROL_H_SM - 2}px; max-height: {CONTROL_H_SM - 2}px; padding: 0 {s+4}px; font-size: {FONT_SIZE_SM}pt;
}}
QToolButton {{ background: transparent; border: none; border-radius: {RADIUS_SM}px; color: {p.text_3}; padding: {s//2}px {s}px; min-height: 24px; }}
QToolButton:hover {{ background: {p.surface_alt}; color: {p.text}; }}
QToolButton:focus {{ border: 2px solid {p.primary}; }}

/* ---------- 카드 ---------- */
QFrame[class="card"] {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS}px; }}

/* ---------- 배너 (아이콘 + 제목 + 본문 + 조치 버튼 + 닫기) ---------- */
QFrame[class="banner"] {{ border-radius: {RADIUS}px; border: 1px solid {p.border}; }}
QFrame[class="banner"][state="error"]   {{ background: {p.error_bg};   border-color: {p.error}; }}
QFrame[class="banner"][state="success"] {{ background: {p.success_bg}; border-color: {p.success}; }}
QFrame[class="banner"][state="warning"] {{ background: {p.warning_bg}; border-color: {p.warning}; }}
QFrame[class="banner"][state="info"]    {{ background: {p.primary_soft}; border-color: {p.primary}; }}
QFrame[class="banner"] QLabel {{ background: transparent; }}
QFrame[class="banner"][state="error"]   QLabel[class="banner-title"] {{ color: {p.error_text}; font-weight: 600; }}
QFrame[class="banner"][state="success"] QLabel[class="banner-title"] {{ color: {p.success_text}; font-weight: 600; }}
QFrame[class="banner"][state="warning"] QLabel[class="banner-title"] {{ color: {p.warning_text}; font-weight: 600; }}
QFrame[class="banner"][state="info"]    QLabel[class="banner-title"] {{ color: {p.primary_soft_text}; font-weight: 600; }}
QFrame[class="banner"] QLabel[class="muted"] {{ color: {p.text_2}; }}
QFrame[class="banner"] QToolButton {{ color: {p.text_2}; min-width: 24px; }}

/* ---------- 상태 배지 (항상 텍스트 포함) ---------- */
QLabel[class="badge"] {{ border-radius: 10px; padding: 2px {s}px; font-weight: 600; font-size: {FONT_SIZE_XS}pt; min-height: 16px; }}
QLabel[class="badge"][state="success"] {{ background: {p.success_bg}; color: {p.success_text}; }}
QLabel[class="badge"][state="error"]   {{ background: {p.error_bg};   color: {p.error_text}; }}
QLabel[class="badge"][state="warning"] {{ background: {p.warning_bg}; color: {p.warning_text}; }}
QLabel[class="badge"][state="running"] {{ background: {p.primary_soft}; color: {p.primary_soft_text}; }}
QLabel[class="badge"][state="idle"]    {{ background: {p.surface_alt}; color: {p.text_2}; }}

/* ---------- 로그 / 코드 ---------- */
QPlainTextEdit#log {{
    background: {p.surface_alt}; border: 1px solid {p.border}; border-radius: {RADIUS}px;
    font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_SM}pt; color: {p.text_2}; padding: {s}px;
}}
/* (builder, W1) 로그 본문은 한국어 문장이라 UI 글꼴. 타임스탬프만 코드에서 mono span (§5.8) */

/* ---------- 테이블 (최근 목록, diff) ---------- */
QTableWidget, QTableView {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS}px;
    gridline-color: transparent; outline: 0;
    selection-background-color: {p.primary_soft}; selection-color: {p.text};
}}
QTableWidget::item, QTableView::item {{ padding: 0 {s}px; border-bottom: 1px solid {p.surface_alt}; }}
QTableWidget::item:hover, QTableView::item:hover {{ background: {p.surface_alt}; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QTableWidget#diff {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}pt; }}
QHeaderView::section {{
    background: {p.surface_alt}; border: none; border-bottom: 1px solid {p.border};
    padding: {s//2}px {s}px; color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; font-weight: 600; min-height: 22px;
}}

/* ---------- 탭 (검증 결과) ---------- */
QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: {RADIUS}px; background: {p.surface}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p.text_3}; padding: {s}px {s+4}px; border: none; border-bottom: 2px solid transparent; font-size: {FONT_SIZE_SM}pt; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.primary}; font-weight: 600; }}

/* ---------- 상태바 ---------- */
QStatusBar {{ background: {p.surface}; border-top: 1px solid {p.border}; color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; min-height: 26px; }}
QStatusBar::item {{ border: none; }}
QLabel[class="login"][state="ok"]   {{ color: {p.success_text}; font-size: {FONT_SIZE_XS}pt; }}
QLabel[class="login"][state="none"] {{ color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; }}

/* ---------- 빈 상태 ---------- */
QLabel[class="empty-title"] {{ color: {p.text_2}; font-size: {FONT_SIZE_MD}pt; }}
QLabel[class="empty-body"]  {{ color: {p.text_3}; font-size: {FONT_SIZE_SM}pt; }}

/* ---------- 스크롤바 (얇게) ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------- 다이얼로그 ---------- */
QMessageBox {{ background: {p.surface}; }}
QMessageBox QLabel {{ min-width: 320px; }}
/* ---------- builder 보강 (S7: app.py 에서 병합) ---------- */
QFrame#Sidebar {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
QListWidget#nav {{ border-right: none; }}
QFrame[class="card"][state="drop"] {{ border: 2px solid {p.primary}; }}
QLabel#preview {{ background: {p.surface_alt}; color: {p.text_2}; border-radius: {RADIUS_SM}px; }}
"""
