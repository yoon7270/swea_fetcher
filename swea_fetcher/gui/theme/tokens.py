"""디자인 토큰 (색·폰트·간격·반경). 값의 출처는 design/design-spec.md §16 (M21 토스 스타일 리프레시).

QSS 는 build_qss() 가 토큰으로 생성한다. 라이트 전용(다크는 DARK 를 채우면 활성화 — M21 범위 밖).
위젯 코드에서 색상값을 직접 쓰지 않는다 — 반드시 tokens.current().<field> 를 참조한다 (diff 행 배경, 카드 내부 rich text 등).
셀렉터 규약: objectName(#nav, #log, #diff, #busy) + 동적 속성 class / state (widgets.set_class).

테마(색 조합): THEMES 에 여러 벌. 바뀌는 건 "주색 계열" 필드뿐이고 중립색(바닥·글자·상태색)은 모든 테마가 공유한다.
현재 테마는 set_theme(key) 로 바꾸고 current() 로 읽는다. LIGHT 는 기본 테마(블루) 팔레트 — 하위 호환용 이름.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Palette:
    bg: str  # 창·페이지 바닥
    surface: str  # 카드·사이드바
    surface_alt: str  # 입력창 채움, 로그 필드, 0단계 잔디, 스켈레톤 기본
    border: str  # 구분선(표 행 등). 카드 외곽선은 없음
    primary: str  # 글자 없는 면: 포커스 링, 진행 막대, 토글 ON, 체크 원, 차트 선택, 스피너
    primary_hover: str  # primary 버튼 hover
    primary_text: str  # primary 버튼 면 위 글자 (흰색)
    accent: str  # 예약 — 새 용도를 만들지 말 것
    success: str  # 아이콘·점
    success_bg: str  # 배너·배지 면
    warning: str
    warning_bg: str
    error: str
    error_bg: str
    text: str  # 1단계 본문
    text_2: str  # 2단계 레이블·보조 설명·로그 본문
    text_3: str  # 3단계 힌트·표 머리글·상태바 — bg 위 4.7:1, 이보다 연한 글자 금지 (플레이스홀더·비활성 제외)
    diff_same: str
    diff_changed: str  # = warning_bg
    diff_missing: str  # = error_bg   (기대에만 있는 줄)
    diff_extra: str  # = primary_soft (실제에만 있는 줄 — 초록을 쓰지 않는 이유는 스펙 §5.9)
    # --- 기본값 있음 → 기존 생성 코드 호환 ---
    border_strong: str = "#D1D6DB"  # 스크롤바 핸들, 차트 비선택 막대, 스켈레톤 하이라이트
    primary_pressed: str = "#1957C2"
    primary_soft: str = "#E8F3FF"  # 내비 선택 알약, info 배너, tonal 버튼, running 배지
    primary_soft_text: str = "#1957C2"  # primary_soft 위 글자
    success_text: str = "#00794A"  # success_bg 위 글자
    warning_text: str = "#8A5100"
    error_text: str = "#C62B38"
    text_disabled: str = "#8B95A1"  # 비활성 컨트롤 글자 (AA 예외)
    # --- M21 신규 ---
    bg_subtle: str = "#F9FAFB"  # 표 hover, 카드 안 보조 면, AnswerBrowser 배경
    control_border: str = "#8B95A1"  # 체크박스·라디오 미선택 테두리
    text_placeholder: str = "#8B95A1"  # 플레이스홀더 전용 (AA 예외)
    primary_action: str = "#1F6FE8"  # primary 버튼 면 (primary_text 를 얹어 4.5:1 이상)
    primary_soft_hover: str = "#D3E8FF"
    primary_soft_pressed: str = "#C0DDFF"
    secondary: str = "#F2F4F6"  # 회색 보조 버튼 면 (카드 안 전용)
    secondary_hover: str = "#E5E8EB"
    secondary_pressed: str = "#D1D6DB"
    secondary_text: str = "#333D4B"
    toast_bg: str = "#333D4B"
    toast_text: str = "#FFFFFF"
    danger_pressed: str = "#FFDDDD"  # danger 텍스트 버튼 pressed 면
    toggle_off: str = "#B0B8C1"  # 토글 OFF 트랙 (의미는 손잡이 위치·옆 글자로도 전달)


def _make(
    primary: str, action: str, hover: str, pressed: str, soft: str, soft_hover: str, soft_pressed: str, soft_text: str
) -> Palette:
    """중립색은 공유하고 주색 계열 8개만 받아 Palette 를 만든다."""
    return Palette(
        bg="#F2F4F6",
        surface="#FFFFFF",
        surface_alt="#F2F4F6",
        border="#E5E8EB",
        primary=primary,
        primary_hover=hover,
        primary_text="#FFFFFF",
        accent=primary,
        success="#0A9B5E",
        success_bg="#E6F8F0",
        warning="#D97800",
        warning_bg="#FFF4E0",
        error="#F04452",
        error_bg="#FFEEEE",
        text="#191F28",
        text_2="#4E5968",
        text_3="#636E7C",
        diff_same="#FFFFFF",
        diff_changed="#FFF4E0",
        diff_missing="#FFEEEE",
        diff_extra=soft,
        primary_pressed=pressed,
        primary_soft=soft,
        primary_soft_text=soft_text,
        primary_action=action,
        primary_soft_hover=soft_hover,
        primary_soft_pressed=soft_pressed,
    )


@dataclass(frozen=True)
class Theme:
    key: str  # QSettings `ui/theme` 에 저장되는 값
    label: str  # 설정 화면 표시 이름
    palette: Palette


# 테마 목록 (표시 순서). 모든 테마가 test_gui_theme 의 대비 검증(버튼 면 위 흰 글자 4.5:1 등)을 통과해야 한다.
THEMES: tuple[Theme, ...] = (
    Theme("blue", "토스 블루", _make("#3182F6", "#1F6FE8", "#1B64DA", "#1957C2", "#E8F3FF", "#D3E8FF", "#C0DDFF", "#1957C2")),
    Theme("green", "숲 그린", _make("#16A364", "#0B7A4B", "#096B42", "#075A38", "#E6F8F0", "#D0F1E2", "#BBEAD4", "#065F3A")),
    Theme("purple", "라벤더 퍼플", _make("#7B5CF0", "#6A4BE0", "#5C3FCC", "#4F33B3", "#F0EBFF", "#E3DAFF", "#D6CAFF", "#4B2FB0")),
    Theme("orange", "선셋 오렌지", _make("#E4600F", "#C2410C", "#AE3A0A", "#963208", "#FFF0E5", "#FFE2CC", "#FFD4B3", "#9A3412")),
    Theme("rose", "로즈 핑크", _make("#E5457D", "#C72A62", "#B02256", "#981C49", "#FFEAF1", "#FFD9E6", "#FFC8DB", "#A11D4C")),
    Theme("mono", "먹색 모노", _make("#4E5968", "#333D4B", "#2A3340", "#212933", "#F2F4F6", "#E5E8EB", "#D1D6DB", "#333D4B")),
)
DEFAULT_THEME = "blue"
THEME_SETTING_KEY = "ui/theme"  # QSettings 키

LIGHT = THEMES[0].palette  # 기본 테마(블루) — 하위 호환 이름. 테마가 바뀌어도 이 값은 고정이므로 "현재" 가 필요하면 current()

DARK: Palette | None = None  # 다크는 M21 범위 밖 (스펙 §16.14)

_current_key = DEFAULT_THEME


def theme_keys() -> list[str]:
    return [t.key for t in THEMES]


def get_theme(key: str | None) -> Theme:
    """키로 테마 조회. 모르는 키(손상된 설정 등)는 기본 테마."""
    for t in THEMES:
        if t.key == key:
            return t
    return THEMES[0]


def current() -> Palette:
    """현재 테마의 팔레트. 커스텀 페인팅·rich text 는 그리는 시점에 이걸 읽어야 테마 전환이 즉시 반영된다."""
    return DARK or get_theme(_current_key).palette


def current_theme_key() -> str:
    return get_theme(_current_key).key


def set_theme(key: str | None) -> Theme:
    """현재 테마를 바꾼다 (QSS 재적용은 호출자 몫 — MainWindow.apply_theme). 모르는 키는 기본 테마."""
    global _current_key
    t = get_theme(key)
    _current_key = t.key
    return t


# 글꼴: Pretendard 번들(gui/theme/fonts.py 가 등록, 실패하면 Malgun Gothic 폴백) — 스펙 §16.3
FONT_FAMILY = '"Pretendard", "Malgun Gothic", "Segoe UI", sans-serif'
FONT_MONO = 'Consolas, "Cascadia Mono", "D2Coding", monospace'
# 크기(pt). 96dpi 환산: 9pt=12px, 10pt≈13px, 10.5pt=14px, 12pt=16px, 17pt≈23px, 22pt≈29px
FONT_SIZE_XS = 9  # 배지, 상태바, 표 머리글, 차트 축
FONT_SIZE_SM = 10  # 힌트, 로그, 배너 본문
FONT_SIZE = 10.5  # 본문, 입력, 버튼, 내비
FONT_SIZE_MD = 12  # 카드 제목, 섹션 제목, 앱 이름 (700)
FONT_SIZE_LG = 17  # 페이지 제목 (700)
FONT_SIZE_XL = 22  # 숫자 강조 (700)

SPACE = 8  # 기본 간격 단위(px). 허용 값: 4, 8, 12, 16, 20, 24, 32, 40
RADIUS_SM = 8  # 작은 버튼(sm), 칩, 툴팁
RADIUS_MD = 12  # 입력, 버튼, 내비 알약, 배너, 로그, 토스트
RADIUS = 16  # 카드, 표 컨테이너
RADIUS_PILL = 999  # 배지·토글 (QSS 는 한계가 있어 높이의 절반을 직접 쓴다)
CONTROL_H = 44  # 입력·콤보·버튼 높이
CONTROL_H_LG = 52  # 번호 입력, 페이지 CTA
CONTROL_H_SM = 36  # 배너·표 안 버튼
NAV_ITEM_H = 44
NAV_GAP = 4  # 내비 항목 사이 간격
BTN_GAP = 12  # 나란한 버튼 사이 간격 (전 페이지 통일 — 8~12 중 12)
BTN_GAP_SM = 8  # 배너·표 안 sm 버튼 사이 간격
SIDEBAR_W = 160
PROGRESS_H = 4  # 진행 중 인디케이터(얇은 막대)
WINDOW_DEFAULT = (960, 680)
WINDOW_MIN = (720, 480)
LOG_H_DEFAULT = 140
LOG_H_MIN = 80
MOTION_FAST = 120  # ms — M21-C(모션)에서 사용. 토큰만 먼저 정의
MOTION_BASE = 200
MOTION_EXIT = 150

ICON_DIR = Path(__file__).resolve().parent / "icons"


def _url(path: Path) -> str:
    """QSS url() 용 경로 (슬래시, 따옴표)."""
    return '"' + path.as_posix() + '"'


def build_qss(p: Palette | None = None) -> str:
    """토큰 → QSS. 위젯은 objectName / 동적 속성(class, state)으로 구분한다. 스펙 §16.5 와 1:1.

    Button·Toggle 이 직접 그리는 면은 QSS 에서 투명으로 두고 글자색·패딩·크기만 정한다.
    """
    p = p or current()
    s = SPACE
    check = _url(ICON_DIR / "check-white.svg")
    chevron = _url(ICON_DIR / "chevron-down.svg")
    return f"""
/* ---------- 기본 ---------- */
QWidget {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}pt; color: {p.text}; }}
QMainWindow, QDialog, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QToolTip {{ background: {p.toast_bg}; color: {p.toast_text}; border: none; border-radius: {RADIUS_SM}px; padding: 6px 10px; font-size: {FONT_SIZE_SM}pt; }}

/* ---------- 텍스트 역할 (굵기는 400 / 700 만) ---------- */
QLabel {{ background: transparent; }}
QLabel[class="title"]   {{ font-size: {FONT_SIZE_LG}pt; font-weight: 700; }}
QLabel[class="section"] {{ font-size: {FONT_SIZE_MD}pt; font-weight: 700; }}
QLabel[class="muted"]   {{ color: {p.text_2}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="hint"]    {{ color: {p.text_3}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="error"]   {{ color: {p.error_text}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="mono"]    {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}pt; }}
QLabel[class="body-2"] {{ color: {p.text_2}; font-size: {FONT_SIZE}pt; }}
QLabel[class="caption"] {{ color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; }}
QLabel[class="metric-value"] {{ font-size: {FONT_SIZE_XL}pt; font-weight: 700; }}
QFrame[class="tile"] {{ background: {p.bg_subtle}; border: none; border-radius: {RADIUS_MD}px; }}
QLabel[class="app-title"] {{ font-size: {FONT_SIZE_MD}pt; font-weight: 700; padding: {s*3}px {s*3}px {s*2}px {s*3}px; }}

/* ---------- 사이드바 내비 (항목·알약은 widgets.NavDelegate 가 그린다 — 알약 슬라이드 §16.7 A2) ---------- */
QFrame#Sidebar {{ background: {p.surface}; border: none; }}
QListWidget#nav {{
    background: {p.surface}; border: none;
    padding: 0 {s}px; min-width: {SIDEBAR_W}px; max-width: {SIDEBAR_W}px; outline: 0;
}}

/* ---------- 진행 막대 (헤더 아래, 진행 중에만 표시) ---------- */
QProgressBar#busy {{ border: none; border-radius: {PROGRESS_H//2}px; background: {p.surface_alt}; min-height: {PROGRESS_H}px; max-height: {PROGRESS_H}px; }}
QProgressBar#busy::chunk {{ background: {p.primary}; border-radius: {PROGRESS_H//2}px; }}

/* ---------- 입력 (무테 채움 + 포커스 시 흰 면·2px 링. 투명 2px 테두리로 두께 확보) ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p.surface_alt}; border: 2px solid transparent; border-radius: {RADIUS_MD}px;
    padding: 0 {s*2-2}px; min-height: {CONTROL_H - 4}px; max-height: {CONTROL_H - 4}px;
    selection-background-color: {p.primary}; selection-color: {p.primary_text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ background: {p.border}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ background: {p.surface}; border: 2px solid {p.primary}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ background: {p.bg_subtle}; color: {p.text_disabled}; }}
QLineEdit[state="invalid"] {{ border: 2px solid {p.error}; }}
QLineEdit[class="mono"] {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_MD}pt; min-height: {CONTROL_H_LG - 4}px; max-height: {CONTROL_H_LG - 4}px; }}
QLineEdit[class="mono"][size="md"] {{ font-size: {FONT_SIZE}pt; min-height: {CONTROL_H - 4}px; max-height: {CONTROL_H - 4}px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 16px; height: 16px; }}
QComboBox QAbstractItemView {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_MD}px; outline: 0; padding: 4px;
    selection-background-color: {p.primary_soft}; selection-color: {p.primary_soft_text};
}}
QComboBox QAbstractItemView::item {{ min-height: 40px; padding: 0 {s}px; border-radius: {RADIUS_SM}px; }}
QPlainTextEdit, QTextEdit {{ background: {p.bg_subtle}; border: none; border-radius: {RADIUS_MD}px; padding: {s*2}px; }}

/* ---------- 체크박스(원형 22px) · 라디오 ---------- */
QCheckBox, QRadioButton {{ spacing: {s}px; min-height: 28px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 18px; height: 18px; border: 2px solid {p.control_border}; border-radius: 11px; background: {p.surface}; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.primary}; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; image: url({check}); }}
QRadioButton::indicator:checked {{ background: {p.surface}; border: 6px solid {p.primary}; width: 10px; height: 10px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {p.text_disabled}; }}

/* ---------- 버튼: 면·포커스 링은 widgets.Button 이 그린다. 여기서는 글자색·패딩·크기만 ---------- */
QPushButton {{
    background: transparent; color: {p.secondary_text}; border: none; border-radius: {RADIUS_MD}px;
    padding: 0 {s*2+4}px; min-height: {CONTROL_H}px; max-height: {CONTROL_H}px;
}}
QPushButton:disabled {{ color: {p.text_disabled}; }}
QPushButton[class="primary"] {{ color: {p.primary_text}; font-weight: 700; min-width: 96px; }}
QPushButton[class="primary"]:disabled {{ color: {p.text_disabled}; }}
QPushButton[size="lg"] {{ min-height: {CONTROL_H_LG}px; max-height: {CONTROL_H_LG}px; }}
QPushButton[class="tonal"] {{ color: {p.primary_soft_text}; font-weight: 700; }}
QPushButton[class="tonal"]:disabled {{ color: {p.text_disabled}; }}
QPushButton[class="danger"] {{ color: {p.error_text}; }}
QPushButton[class="danger"]:disabled {{ color: {p.text_disabled}; }}
QPushButton[class="link"] {{ color: {p.primary_soft_text}; padding: 4px {s}px; min-height: 0; max-height: 100px; border-radius: {RADIUS_SM}px; }}
QPushButton[class="link"]:disabled {{ color: {p.text_disabled}; }}
QPushButton[class="sm"], QFrame[class="banner"] QPushButton {{
    min-height: {CONTROL_H_SM}px; max-height: {CONTROL_H_SM}px; padding: 0 {s*2}px; font-size: {FONT_SIZE_SM}pt; border-radius: {RADIUS_SM}px;
}}
QToolButton {{ background: transparent; border: 2px solid transparent; border-radius: {RADIUS_SM}px; color: {p.text_3}; padding: 2px {s}px; min-height: 24px; }}
QToolButton:hover {{ background: {p.secondary}; color: {p.text}; }}
QToolButton:focus {{ border: 2px solid {p.primary}; }}

/* ---------- 카드 (무테 + 명도 차) ---------- */
QFrame[class="card"] {{ background: {p.surface}; border: none; border-radius: {RADIUS}px; }}
QFrame[class="card"][state="drop"] {{ background: {p.primary_soft}; border: 2px solid {p.primary}; }}

QFrame[class="divider"] {{ background: {p.border}; border: none; min-height: 1px; max-height: 1px; }}

/* ---------- 배너 (아이콘 + 제목 + 본문 + 조치 버튼 + 닫기) ---------- */
QFrame[class="banner"] {{ border-radius: {RADIUS_MD}px; border: none; }}
QFrame[class="banner"][state="error"]   {{ background: {p.error_bg}; }}
QFrame[class="banner"][state="success"] {{ background: {p.success_bg}; }}
QFrame[class="banner"][state="warning"] {{ background: {p.warning_bg}; }}
QFrame[class="banner"][state="info"]    {{ background: {p.primary_soft}; }}
QFrame[class="banner"] QLabel {{ background: transparent; }}
QFrame[class="banner"][state="error"]   QLabel[class="banner-title"] {{ color: {p.error_text}; font-weight: 700; }}
QFrame[class="banner"][state="success"] QLabel[class="banner-title"] {{ color: {p.success_text}; font-weight: 700; }}
QFrame[class="banner"][state="warning"] QLabel[class="banner-title"] {{ color: {p.warning_text}; font-weight: 700; }}
QFrame[class="banner"][state="info"]    QLabel[class="banner-title"] {{ color: {p.primary_soft_text}; font-weight: 700; }}
QFrame[class="banner"] QLabel[class="muted"] {{ color: {p.text_2}; }}
QFrame[class="banner"] QToolButton {{ color: {p.text_2}; min-width: 24px; }}
QFrame[class="banner"][state="error"]   QPushButton {{ color: {p.error_text}; }}
QFrame[class="banner"][state="success"] QPushButton {{ color: {p.success_text}; }}
QFrame[class="banner"][state="warning"] QPushButton {{ color: {p.warning_text}; }}
QFrame[class="banner"][state="info"]    QPushButton {{ color: {p.primary_soft_text}; }}

/* ---------- 상태 배지 (항상 텍스트 포함) ---------- */
QLabel[class="badge"] {{ border-radius: 11px; padding: 4px {s+2}px; font-weight: 700; font-size: {FONT_SIZE_XS}pt; min-height: 14px; }}
QLabel[class="badge"][state="success"] {{ background: {p.success_bg}; color: {p.success_text}; }}
QLabel[class="badge"][state="error"]   {{ background: {p.error_bg};   color: {p.error_text}; }}
QLabel[class="badge"][state="warning"] {{ background: {p.warning_bg}; color: {p.warning_text}; }}
QLabel[class="badge"][state="running"] {{ background: {p.primary_soft}; color: {p.primary_soft_text}; }}
QLabel[class="badge"][state="idle"]    {{ background: {p.surface_alt}; color: {p.text_2}; }}

/* ---------- 로그 / 코드 ---------- */
QPlainTextEdit#log {{
    background: {p.surface_alt}; border: none; border-radius: {RADIUS_MD}px;
    font-family: {FONT_FAMILY}; font-size: {FONT_SIZE_SM}pt; color: {p.text_2}; padding: {s*2}px;
}}
/* (builder, W1) 로그 본문은 한국어 문장이라 UI 글꼴. 타임스탬프만 코드에서 mono span (§5.8) */

/* ---------- 목록 (성장 탭의 지난 리포트 등) ---------- */
QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ min-height: 48px; padding: 0 {s*2}px; border-radius: {RADIUS_MD}px; }}
QListWidget::item:hover {{ background: {p.bg_subtle}; }}
QListWidget::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}

/* ---------- 테이블 (최근 목록, diff) ---------- */
QTableWidget, QTableView {{
    background: {p.surface}; border: none; border-radius: {RADIUS}px;
    gridline-color: transparent; outline: 0;
    selection-background-color: {p.primary_soft}; selection-color: {p.text};
}}
QTableWidget::item, QTableView::item {{ padding: 0 {s*2}px; border-bottom: 1px solid {p.border}; }}
QTableWidget::item:hover, QTableView::item:hover {{ background: {p.bg_subtle}; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}
QTableWidget#diff {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_SM}pt; }}
QHeaderView {{ background: {p.surface}; border: none; }}
QHeaderView::section {{
    background: transparent; border: none;
    padding: {s//2}px {s*2}px; color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; font-weight: 700; min-height: 28px;
}}

/* ---------- 탭 (검증 결과): 글자만 + 선택 밑줄. pane 은 투명 ---------- */
QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}
QTabBar::tab {{ background: transparent; color: {p.text_3}; padding: {s}px 2px {s}px 2px; margin-right: {s*5//2}px; border: none; border-bottom: 3px solid transparent; }}
QTabBar::tab:hover {{ color: {p.text_2}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 3px solid {p.text}; font-weight: 700; }}

/* ---------- 상태바 ---------- */
QStatusBar {{ background: {p.bg}; border: none; color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; min-height: 32px; }}
QStatusBar::item {{ border: none; }}
QLabel[class="login"][state="ok"]   {{ color: {p.success_text}; font-size: {FONT_SIZE_XS}pt; padding-left: 14px; }}
QLabel[class="login"][state="none"] {{ color: {p.text_3}; font-size: {FONT_SIZE_XS}pt; padding-left: 14px; }}

/* ---------- 빈 상태 ---------- */
QLabel[class="empty-title"] {{ color: {p.text}; font-size: {FONT_SIZE_MD}pt; font-weight: 700; }}
QLabel[class="empty-body"]  {{ color: {p.text_3}; font-size: {FONT_SIZE_SM}pt; }}

/* ---------- 스크롤바 (얇게) ---------- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_placeholder}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {p.text_placeholder}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* ---------- 다이얼로그 ---------- */
QMessageBox {{ background: {p.surface}; }}
QMessageBox QLabel {{ min-width: 320px; }}
QMessageBox QPushButton {{ min-width: 88px; }}
QLabel#preview {{ background: {p.surface_alt}; color: {p.text_2}; border-radius: {RADIUS_SM}px; }}
"""


def build_statement_css(p: Palette | None = None) -> str:
    """문제 지문·AI 답변(QTextBrowser 문서)용 스타일시트. Qt rich text 가 지원하는 CSS 부분집합만 쓴다.

    본문 글자 크기는 지정하지 않는다 — 위젯 폰트를 따라야 확대/축소(zoom)가 먹는다. 제목만 상대 크기(스펙 §16.5).
    """
    p = p or current()
    return f"""
body {{ color: {p.text}; line-height: 150%; }}
p {{ margin-top: 0; margin-bottom: {SPACE}px; line-height: 150%; }}
ul, ol {{ margin-top: 0; margin-bottom: {SPACE}px; }}
li {{ margin-bottom: {SPACE // 2}px; line-height: 150%; }}
h1, h2, h3, h4, h5, h6 {{ color: {p.text}; font-weight: 700; margin-top: {SPACE * 2}px; margin-bottom: {SPACE // 2}px; }}
h1 {{ font-size: 16px; }}
h2 {{ font-size: 15px; }}
h3, h4, h5, h6 {{ font-size: 14px; }}
pre, code {{ font-family: {FONT_MONO}; background-color: {p.surface_alt}; color: {p.text}; }}
pre {{ margin-top: 0; margin-bottom: {SPACE}px; }}
blockquote {{ color: {p.text_2}; }}
table {{ border-collapse: collapse; border-width: 1px; border-style: solid; border-color: {p.border}; }}
th, td {{ border-width: 1px; border-style: solid; border-color: {p.border}; padding: {SPACE // 2}px {SPACE}px; }}
th {{ background-color: {p.surface_alt}; }}
hr {{ background-color: {p.border}; }}
.limits {{ color: {p.text_2}; }}
.imgfail {{ color: {p.text_3}; }}
table.samples {{ border-width: 0; margin-top: {SPACE}px; }}
table.samples th {{ text-align: left; }}
table.samples td {{ vertical-align: top; }}
pre.sample {{ white-space: pre-wrap; margin-bottom: 0; }}
.sample-more {{ color: {p.text_3}; }}
"""
