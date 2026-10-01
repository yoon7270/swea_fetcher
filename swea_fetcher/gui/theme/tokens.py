"""디자인 토큰 (색·폰트·간격·반경). 값의 출처는 design/design-spec.md §16(M21), §17(M22 다크 모드·테마 확장).

QSS 는 build_qss() 가 토큰으로 생성한다. 테마 6종 × 모드 2(라이트·다크) = 12 팔레트.
위젯 코드에서 색상값을 직접 쓰지 않는다 — 반드시 tokens.current().<field> 를 그리는 시점에 참조한다.
(tests/gui/test_no_hardcoded_colors.py 가 gui/**/*.py 의 색 리터럴을 검사한다.)
셀렉터 규약: objectName(#nav, #log, #diff, #busy) + 동적 속성 class / state (widgets.set_class).

상태: 테마 key + 모드 설정(light|dark|system) + 감지된 시스템 다크 여부 → current() 가 해당 팔레트를 돌려준다.
tokens 는 Qt 를 import 하지 않는다 — 시스템 다크 감지는 gui/theme/appearance.py 가 set_system_dark() 로 주입.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Palette:
    bg: str  # 창·페이지 바닥
    surface: str  # 카드·다이얼로그
    surface_alt: str  # 입력창 채움, 로그 필드, 0단계 잔디, 스켈레톤 기본
    border: str  # 구분선(표 행 등). 카드 외곽선은 없음
    primary: str  # 글자 없는 면: 포커스 링, 진행 막대, 토글 ON, 체크 원, 차트 선택, 스피너
    primary_hover: str  # primary 버튼 hover
    primary_text: str  # primary 버튼 면 위 글자
    accent: str  # 예약 — 새 용도를 만들지 말 것
    success: str  # 아이콘·점
    success_bg: str  # 배너·배지 면
    warning: str
    warning_bg: str
    error: str
    error_bg: str
    text: str  # 1단계 본문
    text_2: str  # 2단계 레이블·보조 설명·로그 본문
    text_3: str  # 3단계 힌트·표 머리글·상태바 — 4.5:1 이상, 이보다 연한 글자 금지 (플레이스홀더·비활성 제외)
    diff_same: str
    diff_changed: str  # = warning_bg
    diff_missing: str  # = error_bg   (기대에만 있는 줄)
    diff_extra: str  # = primary_soft (실제에만 있는 줄 — 초록을 쓰지 않는 이유는 스펙 §5.9)
    # --- 기본값 있음 → 기존 생성 코드 호환 ---
    border_strong: str = "#D1D6DB"  # 스크롤바 핸들, 차트 비선택 막대
    primary_pressed: str = "#1957C2"
    primary_soft: str = "#E8F3FF"  # 내비 선택 알약, info 배너, tonal 버튼, running 배지
    primary_soft_text: str = "#1957C2"  # primary_soft 위 글자
    success_text: str = "#00794A"  # success_bg 위 글자
    warning_text: str = "#8A5100"
    error_text: str = "#C62B38"
    text_disabled: str = "#8B95A1"  # 비활성 컨트롤 글자 (AA 예외)
    # --- M21 ---
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
    # --- M22 (스펙 §17.3) ---
    is_dark: bool = False  # 모드 분기(잔디·그림자 등)
    sidebar: str = "#FFFFFF"  # 사이드바·내비 바닥
    on_primary: str = "#FFFFFF"  # primary 면 위 글리프(체크·토글 손잡이)
    hover_fill: str = "#E5E8EB"  # 입력·행 hover 면
    segment_on: str = "#FFFFFF"  # 세그먼트 컨트롤 선택 칸
    toggle_knob: str = "#FFFFFF"  # 토글 OFF 손잡이
    link: str = "#1957C2"  # 리치 텍스트 링크
    image_paper: str = "#FFFFFF"  # 문제 지문 이미지 뒤 종이색
    ring_light: str = "#FFFFFF"  # 색 선택 패널 SV 핸들 이중 링(임의 색 위라 흑백 고정)
    ring_dark: str = "#0F1720"


# 모드별 1벌 공통 토큰 (스펙 §17.4) — 글자·상태색은 테마와 무관
_COMMON_LIGHT = dict(
    text="#191F28", text_2="#4E5968", text_3="#5B6674", text_placeholder="#8B95A1", text_disabled="#8B95A1",
    control_border="#8B95A1", toggle_off="#B0B8C1", secondary_text="#333D4B", toast_bg="#333D4B", toast_text="#FFFFFF",
    success="#0A9B5E", success_bg="#E6F8F0", success_text="#00794A",
    warning="#D97800", warning_bg="#FFF4E0", warning_text="#8A5100",
    error="#F04452", error_bg="#FFEEEE", error_text="#C62B38", danger_pressed="#FFE3E3",
)
_COMMON_DARK = dict(
    text="#ECEFF3", text_2="#B9C1CD", text_3="#A1AAB6", text_placeholder="#737C8A", text_disabled="#737C8A",
    control_border="#7C8593", toggle_off="#4A515D", secondary_text="#DDE2E9", toast_bg="#ECEFF3", toast_text="#191F28",
    success="#3DD68C", success_bg="#15382A", success_text="#6FE3A8",
    warning="#FFA726", warning_bg="#3D2C12", warning_text="#FFC266",
    error="#FF6B78", error_bg="#3F1D23", error_text="#FF8A94", danger_pressed="#55252D",
)


def _make_light(
    neutral: tuple[str, str, str, str, str, str],
    primary: str, action: str, hover: str, pressed: str, soft: str, soft_hover: str, soft_pressed: str, soft_text: str,
) -> Palette:
    """라이트: neutral = (bg, sidebar, bg_subtle, surface_alt, border, border_strong). surface 는 #FFFFFF 고정 (§17.5)."""
    bg, sidebar, bg_subtle, surface_alt, border, border_strong = neutral
    c = _COMMON_LIGHT
    return Palette(
        bg=bg, surface="#FFFFFF", surface_alt=surface_alt, border=border,
        primary=primary, primary_hover=hover, primary_text="#FFFFFF", accent=primary,
        success=c["success"], success_bg=c["success_bg"], warning=c["warning"], warning_bg=c["warning_bg"],
        error=c["error"], error_bg=c["error_bg"], text=c["text"], text_2=c["text_2"], text_3=c["text_3"],
        diff_same="#FFFFFF", diff_changed=c["warning_bg"], diff_missing=c["error_bg"], diff_extra=soft,
        border_strong=border_strong, primary_pressed=pressed, primary_soft=soft, primary_soft_text=soft_text,
        success_text=c["success_text"], warning_text=c["warning_text"], error_text=c["error_text"],
        text_disabled=c["text_disabled"], bg_subtle=bg_subtle, control_border=c["control_border"],
        text_placeholder=c["text_placeholder"], primary_action=action,
        primary_soft_hover=soft_hover, primary_soft_pressed=soft_pressed,
        secondary=surface_alt, secondary_hover=border, secondary_pressed=border_strong,
        secondary_text=c["secondary_text"], toast_bg=c["toast_bg"], toast_text=c["toast_text"],
        danger_pressed=c["danger_pressed"], toggle_off=c["toggle_off"],
        is_dark=False, sidebar=sidebar, on_primary="#FFFFFF", hover_fill=border, segment_on="#FFFFFF",
        toggle_knob="#FFFFFF", link=soft_text, image_paper="#FFFFFF",
    )


def _make_dark(
    neutral: tuple[str, str, str, str, str, str, str, str, str],
    primary: str, action: str, hover: str, pressed: str, primary_text: str,
    soft: str, soft_hover: str, soft_pressed: str, soft_text: str,
) -> Palette:
    """다크: neutral = (bg, sidebar, surface, bg_subtle, surface_alt, secondary_hover, secondary_pressed, border, border_strong)."""
    bg, sidebar, surface, bg_subtle, surface_alt, sec_hover, sec_pressed, border, border_strong = neutral
    c = _COMMON_DARK
    return Palette(
        bg=bg, surface=surface, surface_alt=surface_alt, border=border,
        primary=primary, primary_hover=hover, primary_text=primary_text, accent=primary,
        success=c["success"], success_bg=c["success_bg"], warning=c["warning"], warning_bg=c["warning_bg"],
        error=c["error"], error_bg=c["error_bg"], text=c["text"], text_2=c["text_2"], text_3=c["text_3"],
        diff_same=surface, diff_changed=c["warning_bg"], diff_missing=c["error_bg"], diff_extra=soft,
        border_strong=border_strong, primary_pressed=pressed, primary_soft=soft, primary_soft_text=soft_text,
        success_text=c["success_text"], warning_text=c["warning_text"], error_text=c["error_text"],
        text_disabled=c["text_disabled"], bg_subtle=bg_subtle, control_border=c["control_border"],
        text_placeholder=c["text_placeholder"], primary_action=action,
        primary_soft_hover=soft_hover, primary_soft_pressed=soft_pressed,
        secondary=surface_alt, secondary_hover=sec_hover, secondary_pressed=sec_pressed,
        secondary_text=c["secondary_text"], toast_bg=c["toast_bg"], toast_text=c["toast_text"],
        danger_pressed=c["danger_pressed"], toggle_off=c["toggle_off"],
        is_dark=True, sidebar=sidebar, on_primary="#0F1720", hover_fill=sec_hover, segment_on=sec_hover,
        toggle_knob="#C9D0DA", link=soft_text, image_paper="#FFFFFF",
    )


@dataclass(frozen=True)
class Theme:
    key: str  # QSettings `ui/theme` 에 저장되는 값
    label: str  # 설정 화면 표시 이름
    light: Palette
    dark: Palette

    @property
    def palette(self) -> Palette:  # 하위 호환 — 라이트
        return self.light


# 테마 목록 (표시 순서). 값은 스펙 §17.5 표 그대로. 모든 팔레트가 test_gui_theme 의 대비 표(§17.6)를 통과해야 한다.
THEMES: tuple[Theme, ...] = (
    Theme(
        "blue", "오션 블루",
        _make_light(("#F2F4F6", "#FFFFFF", "#F9FAFB", "#F2F4F6", "#E5E8EB", "#D1D6DB"),
                    "#3182F6", "#1F6FE8", "#1B64DA", "#1957C2", "#E8F3FF", "#D3E8FF", "#C0DDFF", "#1957C2"),
        _make_dark(("#14171C", "#191C22", "#1E222A", "#242A33", "#29303A", "#333B47", "#3D4655", "#2E3541", "#444E5C"),
                   "#4C94FF", "#1B64DA", "#1F6FE8", "#1957C2", "#FFFFFF", "#1C3560", "#223F6E", "#28497C", "#8FBBFF"),
    ),
    Theme(
        "green", "숲 그린",
        _make_light(("#F0F5F2", "#FAFDFB", "#F7FAF8", "#F0F5F2", "#E1E9E4", "#CBD6CE"),
                    "#14995E", "#0B7A4B", "#096B42", "#075A38", "#E6F8F0", "#D0F1E2", "#BBEAD4", "#065F3A"),
        _make_dark(("#121714", "#171D19", "#1C231F", "#232B26", "#28322C", "#323E36", "#3C4A41", "#2C372F", "#415046"),
                   "#2FBF7F", "#096B42", "#0B7A4B", "#075A38", "#FFFFFF", "#17382B", "#1D4636", "#245640", "#7BE0B0"),
    ),
    Theme(
        "purple", "라벤더 퍼플",
        _make_light(("#F3F2F8", "#FCFBFF", "#F9F8FC", "#F3F2F8", "#E6E4EF", "#D2CFE0"),
                    "#7B5CF0", "#6A4BE0", "#5C3FCC", "#4F33B3", "#F0EBFF", "#E3DAFF", "#D6CAFF", "#4B2FB0"),
        _make_dark(("#16151C", "#1B1A23", "#201F29", "#262432", "#2C2A38", "#363445", "#413E53", "#302E3E", "#484560"),
                   "#9B83FF", "#5C3FCC", "#6A4BE0", "#4F33B3", "#FFFFFF", "#2D2559", "#372E6C", "#413680", "#C4B5FF"),
    ),
    Theme(
        "orange", "선셋 오렌지",
        _make_light(("#F7F3F0", "#FFFCFA", "#FBF9F7", "#F7F3F0", "#EBE5E0", "#D8D0C8"),
                    "#E4600F", "#C2410C", "#AE3A0A", "#963208", "#FFF0E5", "#FFE2CC", "#FFD4B3", "#9A3412"),
        _make_dark(("#1A1613", "#201B17", "#251F1B", "#2D2621", "#332B25", "#3E352E", "#4A4038", "#382F28", "#54483E"),
                   "#FF8A3D", "#AE3A0A", "#C2410C", "#963208", "#FFFFFF", "#43271A", "#55311F", "#683D25", "#FFB27A"),
    ),
    Theme(
        "rose", "로즈 핑크",
        _make_light(("#F8F2F4", "#FFFBFC", "#FCF8F9", "#F8F2F4", "#EDE4E8", "#DACFD4"),
                    "#E5457D", "#C72A62", "#B02256", "#981C49", "#FFEAF1", "#FFD9E6", "#FFC8DB", "#A11D4C"),
        _make_dark(("#1A1417", "#201A1D", "#251E22", "#2D2529", "#332A2F", "#3E3439", "#4A3F45", "#382E34", "#54454D"),
                   "#FF6B9A", "#B02256", "#C72A62", "#981C49", "#FFFFFF", "#45202F", "#572A3C", "#6A3449", "#FF9DBF"),
    ),
    Theme(
        "mono", "먹색 모노",
        _make_light(("#F2F2F3", "#FFFFFF", "#F8F8F9", "#F2F2F3", "#E4E4E6", "#D0D0D4"),
                    "#4E5968", "#333D4B", "#2A3340", "#212933", "#F2F4F6", "#E5E8EB", "#D1D6DB", "#333D4B"),
        _make_dark(("#121212", "#181818", "#1E1E1F", "#252527", "#2A2A2C", "#343436", "#3F3F42", "#313133", "#4A4A4E"),
                   "#AEB6C2", "#E6E9EE", "#D3D8DF", "#BEC5CE", "#15181D", "#33363D", "#3C4048", "#474B54", "#E3E7ED"),
    ),
)
DEFAULT_THEME = "blue"
THEME_SETTING_KEY = "ui/theme"  # QSettings 키
COLOR_MODE_SETTING_KEY = "ui/color_mode"  # QSettings 키: light | dark | system
DEFAULT_COLOR_MODE = "system"
COLOR_MODES = ("light", "dark", "system")

LIGHT = THEMES[0].light  # 하위 호환 — 블루 라이트 고정
DARK = THEMES[0].dark  # 블루 다크 (current() 를 가로채지 않는다)

_theme_key = DEFAULT_THEME
_color_mode = DEFAULT_COLOR_MODE
_system_dark = False
_version = 0


def theme_keys() -> list[str]:
    return [t.key for t in THEMES]


def get_theme(key: str | None) -> Theme:
    """키로 테마 조회. 모르는 키(손상된 설정 등)는 기본 테마."""
    for t in THEMES:
        if t.key == key:
            return t
    return THEMES[0]


def normalize_color_mode(mode: object) -> str:
    """모르는 값(손상된 설정 등)은 'system'."""
    return mode if isinstance(mode, str) and mode in COLOR_MODES else DEFAULT_COLOR_MODE


def is_dark() -> bool:
    """유효 모드가 다크인가 (dark 이거나 system 이면서 OS 가 다크)."""
    return _color_mode == "dark" or (_color_mode == "system" and _system_dark)


def color_mode() -> str:
    return _color_mode


def version() -> int:
    """테마·모드·시스템 다크가 실제로 바뀔 때마다 증가 — 캐시 키."""
    return _version


def current() -> Palette:
    """현재 테마·모드의 팔레트. 커스텀 페인팅·rich text 는 그리는 시점에 이걸 읽어야 전환이 즉시 반영된다."""
    t = get_theme(_theme_key)
    return t.dark if is_dark() else t.light


def current_theme_key() -> str:
    return get_theme(_theme_key).key


def set_theme(key: str | None) -> Theme:
    """현재 테마를 바꾼다 (QSS 재적용은 호출자 몫 — MainWindow.apply_appearance). 모르는 키는 기본 테마."""
    global _theme_key, _version
    t = get_theme(key)
    if t.key != _theme_key:
        _theme_key = t.key
        _version += 1
    return t


def set_color_mode(mode: str | None) -> str:
    """화면 모드(light|dark|system). 모르는 값은 system. 값이 바뀔 때만 version 증가."""
    global _color_mode, _version
    m = normalize_color_mode(mode)
    if m != _color_mode:
        _color_mode = m
        _version += 1
    return m


def set_system_dark(value: bool) -> None:
    """OS 앱 모드 감지 결과 주입 (tokens 는 Qt 를 모른다). 실제 값이 바뀔 때만 version 증가."""
    global _system_dark, _version
    v = bool(value)
    if v != _system_dark:
        _system_dark = v
        _version += 1


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


_icon_tmp: Path | None = None
ICON_BASE_COLOR = "#424A53"  # 디자이너 SVG 의 스트로크 색 (= 라이트 text_2). 재착색은 이 문자열 치환으로


def themed_icon_path(name: str, mapping: dict[str, str], icon_dir: Path | None = None) -> Path:
    """SVG 의 색 리터럴을 치환한 사본을 캐시 디렉터리에 써서 경로를 돌려준다 (QSS `url()` 용 — QSS 는 색을 못 바꾼다).

    파일명에 치환 색이 들어가 팔레트가 같으면 같은 파일을 재사용한다. 실패하면 원본 경로(색만 틀림).
    """
    import tempfile

    global _icon_tmp
    src = ICON_DIR / f"{name}.svg"
    try:
        base = icon_dir
        if base is None:
            if _icon_tmp is None:
                _icon_tmp = Path(tempfile.gettempdir()) / "swea_fetcher_icons"
            base = _icon_tmp
        base.mkdir(parents=True, exist_ok=True)
        tag = "".join(v.lstrip("#") for v in mapping.values())
        dst = base / f"{name}-{tag}.svg"
        if not dst.is_file():
            text = src.read_text(encoding="utf-8")
            for old, new in mapping.items():
                text = text.replace(old, new)
            dst.write_text(text, encoding="utf-8")
        return dst
    except OSError:
        return src


def icon_recolor_pairs(p: Palette) -> tuple[tuple[str, str], ...]:
    """SVG 안의 색 리터럴 → 팔레트 색 치환표 (스펙 §17.9). 기본 스트로크는 호출자가 따로 치환하므로 상태 아이콘 3색 + 흰 글리프만."""
    return (("#1A7F37", p.success), ("#9A6700", p.warning), ("#CF222E", p.error), ("#FFFFFF", p.on_primary))


CHEVRON_COLOR = "#656D76"  # chevron-down.svg 의 원래 스트로크 색 (콤보 화살표) — QSS 에서 text_3 로 재착색


def build_qss(p: Palette | None = None, icon_dir: Path | None = None) -> str:
    """토큰 → QSS. 위젯은 objectName / 동적 속성(class, state)으로 구분한다. 스펙 §16.5 · §17.7 · §17.8.

    Button·Toggle 이 직접 그리는 면은 QSS 에서 투명으로 두고 글자색·패딩·크기만 정한다.
    build_qss 는 모드를 모른다 — 팔레트만 읽는다. 체크·콤보 화살표 아이콘은 팔레트 색으로 재착색한 사본을 쓴다.
    icon_dir: 재착색 SVG 를 쓸 디렉터리 (테스트 주입용, 기본은 임시 폴더).
    """
    p = p or current()
    s = SPACE
    check = _url(themed_icon_path("check-white", {"#FFFFFF": p.on_primary}, icon_dir))
    chevron = _url(themed_icon_path("chevron-down", {CHEVRON_COLOR: p.text_3}, icon_dir))
    return f"""
/* ---------- 기본 ---------- */
QWidget {{ font-family: {FONT_FAMILY}; font-size: {FONT_SIZE}pt; color: {p.text}; }}
QAbstractScrollArea {{ background: transparent; border: none; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QDialog {{ background: {p.surface}; }}
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
QFrame#Sidebar {{ background: {p.sidebar}; border: none; }}
QListWidget#nav {{
    background: {p.sidebar}; border: none;
    padding: 0 {s}px; min-width: {SIDEBAR_W - 2*s}px; max-width: {SIDEBAR_W - 2*s}px; outline: 0;  /* 폭은 padding 제외 — 합계가 사이드바 폭과 같아야 오른쪽이 안 잘린다 */
}}

/* ---------- 진행 막대 (헤더 아래, 진행 중에만 표시) ---------- */
QProgressBar#busy {{ border: none; border-radius: {PROGRESS_H//2}px; background: {p.surface_alt}; min-height: {PROGRESS_H}px; max-height: {PROGRESS_H}px; }}
QProgressBar#busy::chunk {{ background: {p.primary}; border-radius: {PROGRESS_H//2}px; }}

/* ---------- 입력 (무테 채움 + 포커스 시 흰 면·2px 링. 투명 2px 테두리로 두께 확보) ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p.surface_alt}; border: 2px solid transparent; border-radius: {RADIUS_MD}px;
    padding: 0 {s*2-2}px; min-height: {CONTROL_H - 4}px; max-height: {CONTROL_H - 4}px;
    selection-background-color: {p.primary}; selection-color: {p.on_primary};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ background: {p.hover_fill}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ background: {p.surface}; border: 2px solid {p.primary}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ background: {p.bg_subtle}; color: {p.text_disabled}; }}
QLineEdit[state="invalid"] {{ border: 2px solid {p.error}; }}
QLineEdit[class="mono"] {{ font-family: {FONT_MONO}; font-size: {FONT_SIZE_MD}pt; min-height: {CONTROL_H_LG - 4}px; max-height: {CONTROL_H_LG - 4}px; }}
QLineEdit[class="mono"][size="md"] {{ font-size: {FONT_SIZE}pt; min-height: {CONTROL_H - 4}px; max-height: {CONTROL_H - 4}px; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 16px; height: 16px; }}
QComboBox QFrame {{ background: transparent; border: none; }}
QComboBox QAbstractItemView {{
    background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_MD}px; outline: 0; padding: 4px;
    selection-background-color: {p.primary_soft}; selection-color: {p.primary_soft_text};
}}
QComboBox QAbstractItemView QScrollBar:vertical {{ margin: 10px 3px 10px 0; }}
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

/* ---------- 스크롤바 (얇게, 트랙은 완전 투명 — 스펙 §17.8) ---------- */
QScrollBar:vertical {{ background: transparent; border: none; width: 10px; margin: 2px 2px 2px 0; }}
QScrollBar:horizontal {{ background: transparent; border: none; height: 10px; margin: 0 2px 2px 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 3px; min-height: 28px; margin: 0 1px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 3px; min-width: 28px; margin: 1px 0; }}
QScrollBar::handle:hover {{ background: {p.text_placeholder}; }}
QScrollBar::handle:pressed {{ background: {p.text_3}; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; }}
QScrollBar::add-line, QScrollBar::sub-line {{ background: none; border: none; width: 0; height: 0; }}
QScrollBar::up-arrow, QScrollBar::down-arrow, QScrollBar::left-arrow, QScrollBar::right-arrow {{ background: none; width: 0; height: 0; }}

/* ---------- 메뉴 (우클릭 등 — 팝업 창 속성은 widgets.AppMenu) ---------- */
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: {RADIUS_MD}px; padding: 6px; }}
QMenu::item {{ padding: 8px 16px 8px 12px; border-radius: {RADIUS_SM}px; min-width: 140px; color: {p.text}; background: transparent; }}
QMenu::item:selected {{ background: {p.primary_soft}; color: {p.primary_soft_text}; }}
QMenu::item:disabled {{ color: {p.text_disabled}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}

/* ---------- 다이얼로그 ---------- */
QMessageBox {{ background: {p.surface}; }}
QLabel[class="review-status"][state="due"] {{ color: {p.warning_text}; }}
QLabel[class="review-status"][state="upcoming"] {{ color: {p.text_3}; }}
QMessageBox QLabel {{ min-width: 320px; }}
QMessageBox QPushButton {{ min-width: 88px; }}
QLabel#preview {{ background: {p.surface_alt}; color: {p.text_2}; border-radius: {RADIUS_SM}px; }}
"""


def build_log_css(p: Palette | None = None) -> str:
    """LogView(QPlainTextEdit) 문서 기본 스타일시트 — 인라인 style 대신 클래스로 색을 준다 (스펙 §17.7)."""
    p = p or current()
    return f"""
.ts {{ font-family: {FONT_MONO}; }}
.err {{ color: {p.error_text}; }}
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
a {{ color: {p.link}; }}
.ts {{ color: {p.text_3}; font-family: {FONT_MONO}; }}
table.imgwrap {{ border-width: 0; margin-top: 0; margin-bottom: {SPACE}px; }}
table.imgwrap td {{ border-width: 0; padding: {SPACE // 2}px; }}
.limits {{ color: {p.text_2}; }}
.imgfail {{ color: {p.text_3}; }}
table.samples {{ border-width: 0; margin-top: {SPACE}px; }}
table.samples th {{ text-align: left; }}
table.samples td {{ vertical-align: top; }}
pre.sample {{ white-space: pre-wrap; margin-bottom: 0; }}
.sample-more {{ color: {p.text_3}; }}
"""
