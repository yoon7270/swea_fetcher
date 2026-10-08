"""에디터에서 열기 (M13): .py 기본 앱을 판별하고, VS Code 는 가상 데스크톱 전환 없이 현재 데스크톱에 연다.

원리: os.startfile 은 이미 떠 있는 에디터 창으로 파일을 넘기는데, 그 창이 다른 가상 데스크톱에 있으면 Windows 가
그 데스크톱으로 화면을 전환한다. VS Code 는 현재 데스크톱에 같은 문제 폴더 창이 있으면 거기로, 없으면 --new-window 로 연다.
PyCharm/기본 앱은 창 위치를 제어할 방법이 없어 (문서화된 API 부재) 경고만 알리고 os.startfile 로 연다.

Qt 비의존. ctypes 만 사용 (새 의존성 없음), 문서화된 IVirtualDesktopManager 만 쓴다.
Windows 에서 판별/열거/실행 중 어떤 예외가 나도 os.startfile 로 폴백한다. 로그에는 경로와 판별 결과만 남긴다.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Callable

log = logging.getLogger("swea_fetcher.opener")

EDITOR_CHOICES = ("auto", "vscode", "pycharm", "default")
_LABELS = {"vscode": "VS Code", "pycharm": "PyCharm", "default": "기본 연결 프로그램"}
_VSCODE_EXES = ("code.exe", "code - insiders.exe")

_ASSOCSTR_EXECUTABLE = 2
_S_OK = 0
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_CLSID_VDM = "{aa509086-5ca9-4c25-8f95-589d3c07b48a}"  # VirtualDesktopManager
_IID_VDM = "{a5cd92ff-29be-454c-8d04-d82879fb3f1b}"  # IVirtualDesktopManager
_PYCHARM_WARNING = "다른 가상 데스크톱의 PyCharm 창으로 전환될 수 있습니다 (SWEA_EDITOR=vscode 사용 또는 PyCharm 을 현재 데스크톱에서 실행)"


@dataclass(frozen=True)
class OpenResult:
    ok: bool
    kind: str  # "vscode" | "pycharm" | "default"
    note: str = ""  # 상태 메시지용 (경고 등). 없으면 ""


# --- 판별 ---------------------------------------------------------------------------


def _assoc_exe() -> str | None:
    """`.py` 를 여는 실제 실행파일 경로 (AssocQueryStringW, UserChoice 반영). 실패 시 None."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    fn = ctypes.WinDLL("shlwapi").AssocQueryStringW
    fn.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = ctypes.HRESULT
    size = wintypes.DWORD(0)
    try:
        fn(0, _ASSOCSTR_EXECUTABLE, ".py", None, None, ctypes.byref(size))  # 필요한 길이 조회 (S_FALSE)
    except OSError:
        return None
    if size.value == 0:
        return None
    buf = ctypes.create_unicode_buffer(size.value)
    fn(0, _ASSOCSTR_EXECUTABLE, ".py", None, buf, ctypes.byref(size))
    return buf.value or None


def _kind_of_exe(exe_name: str) -> str:
    name = exe_name.lower()
    if name in _VSCODE_EXES:
        return "vscode"
    if name.startswith("pycharm"):
        return "pycharm"
    return "default"


def normalize_setting(setting: str | None) -> str:
    s = (setting or "").strip().lower()
    return s if s in EDITOR_CHOICES else "auto"


def detect_editor(setting: str | None = "auto") -> str:
    """열릴 에디터 종류. 강제값(vscode/pycharm/default)이 auto 보다 우선. 판별 실패는 "default"."""
    s = normalize_setting(setting)
    if s != "auto":
        return s
    try:
        exe = _assoc_exe()
    except Exception as e:  # noqa: BLE001 — ctypes 오류 등 전부 default 로
        log.debug("기본 앱 조회 실패: %s", e)
        return "default"
    return _kind_of_exe(PureWindowsPath(exe).name) if exe else "default"


def editor_label(kind: str) -> str:
    return _LABELS.get(kind, _LABELS["default"])


def editor_tooltip(setting: str | None = "auto") -> str:
    return f"열릴 프로그램: {editor_label(detect_editor(setting))}"


# --- 가상 데스크톱 / 창 열거 (Windows, ctypes) ------------------------------------------


def _windows_of(match: Callable[[str], bool]) -> list[tuple[int, str]]:
    """보이는 최상위 창 중 프로세스 이미지 파일명(소문자)이 match 를 만족하는 것의 (hwnd, 제목)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    found: list[tuple[int, str]] = []
    exe_cache: dict[int, str] = {}

    def image_name(pid: int) -> str:
        if pid not in exe_cache:
            name = ""
            h = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    n = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                        name = Path(buf.value).name.lower()
                finally:
                    kernel32.CloseHandle(h)
            exe_cache[pid] = name
        return exe_cache[pid]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(512)
            if not user32.GetWindowTextW(hwnd, buf, 512) or not buf.value:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if match(image_name(pid.value)):
                found.append((int(hwnd), buf.value))
        except Exception:  # noqa: BLE001 — 콜백에서 예외가 새면 안 된다
            pass
        return True

    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows(cb, 0)
    return found


_vdm = None  # 지연 초기화된 IVirtualDesktopManager 포인터 (c_void_p)


def _get_vdm():
    """IVirtualDesktopManager COM 객체 생성 (프로세스당 1회 캐시). 실패 시 예외."""
    global _vdm
    if _vdm is not None:
        return _vdm
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    ole32 = ctypes.OleDLL("ole32")
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]
    ole32.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
    clsid, iid = GUID(), GUID()
    ole32.CLSIDFromString(_CLSID_VDM, ctypes.byref(clsid))
    ole32.CLSIDFromString(_IID_VDM, ctypes.byref(iid))
    ptr = ctypes.c_void_p()
    try:
        ole32.CoInitialize(None)  # 이미 초기화돼 있으면 S_FALSE/무시
    except OSError:
        pass
    ole32.CoCreateInstance(ctypes.byref(clsid), None, 23, ctypes.byref(iid), ctypes.byref(ptr))  # CLSCTX_ALL
    if not ptr.value:
        raise OSError("IVirtualDesktopManager 생성 실패")
    _vdm = ptr
    return _vdm


def _on_current_desktop(hwnd: int) -> bool | None:
    """창이 현재 가상 데스크톱에 있는지. 판별 불가(COM 오류 등)면 None."""
    try:
        import ctypes
        from ctypes import wintypes

        vdm = _get_vdm()
        vtbl = ctypes.cast(ctypes.cast(vdm, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, ctypes.POINTER(wintypes.BOOL))
        is_on_current = proto(vtbl[3])  # IUnknown 3개 다음 첫 메서드: IsWindowOnCurrentVirtualDesktop
        out = wintypes.BOOL(0)
        is_on_current(vdm, hwnd, ctypes.byref(out))
        return bool(out.value)
    except Exception as e:  # noqa: BLE001
        log.debug("가상 데스크톱 판별 실패: %s", e)
        return None


# --- 열기 -----------------------------------------------------------------------------


def _vscode_exe() -> str | None:
    """Code.exe 경로: 기본 앱 조회 → %LOCALAPPDATA% 기본 설치 → PATH 의 code.exe. (.cmd 는 셸 경유라 쓰지 않는다)"""
    try:
        exe = _assoc_exe()
    except Exception:  # noqa: BLE001
        exe = None
    if exe and Path(exe).name.lower() in _VSCODE_EXES and Path(exe).is_file():
        return exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cand = Path(local) / "Programs" / "Microsoft VS Code" / "Code.exe"
        if cand.is_file():
            return str(cand)
    return shutil.which("code.exe")


def _is_vscode(image: str) -> bool:
    return image in _VSCODE_EXES


def _folder_windows(folder_name: str) -> tuple[bool, bool]:
    """제목이 폴더명을 포함하는 VS Code 창이 (현재 데스크톱에 있는가, 다른 데스크톱에만 있을 수 있는가).
    판별 불가(None)는 다른 데스크톱 쪽으로 친다 — 폴더를 넘기면 그 창으로 전환될 수 있으므로."""
    here = elsewhere = False
    for hwnd, title in _windows_of(_is_vscode):
        if folder_name in title:
            if _on_current_desktop(hwnd) is True:
                here = True
            else:
                elsewhere = True
    return here, elsewhere


def _open_vscode(problem_dir: Path, file: Path) -> None:
    exe = _vscode_exe()
    if not exe:
        raise OSError("Code.exe 를 찾지 못했습니다")
    try:
        here, elsewhere = _folder_windows(problem_dir.name)
    except Exception as e:  # noqa: BLE001
        log.debug("VS Code 창 열거 실패: %s", e)
        here, elsewhere = False, False
    if here:
        args = [exe, str(problem_dir), "-g", str(file)]
    elif elsewhere:
        # VS Code 는 같은 폴더 창을 새로 만들지 않고 기존 창을 활성화한다 → 폴더 없이 파일만 새 창으로
        args = [exe, "--new-window", "-g", str(file)]
    else:
        args = [exe, "--new-window", str(problem_dir), "-g", str(file)]
    log.debug("VS Code 열기: here=%s elsewhere=%s file=%s", here, elsewhere, file)
    subprocess.Popen(args)  # noqa: S603 — shell=False, 인자 리스트


def _pycharm_other_desktop_only() -> bool:
    """PyCharm 창이 있는데 현재 데스크톱에는 하나도 없으면 True (전환 가능성). 판별 불가는 False."""
    wins = _windows_of(lambda image: image.startswith("pycharm"))
    return bool(wins) and not any(_on_current_desktop(h) is True for h, _ in wins)


def _explorer_window_here(folder_name: str) -> int | None:
    """현재 가상 데스크톱에서 제목이 "{폴더명} - ..." 인 탐색기 창(CabinetWClass) hwnd. 없으면 None."""
    import ctypes

    user32 = ctypes.WinDLL("user32")
    for hwnd, title in _windows_of(lambda image: image == "explorer.exe"):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "CabinetWClass" and title.startswith(f"{folder_name} - ") and _on_current_desktop(hwnd) is True:
            return hwnd
    return None


def _activate(hwnd: int) -> bool:
    import ctypes

    user32 = ctypes.WinDLL("user32")
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    return bool(user32.SetForegroundWindow(hwnd))


def open_folder(path: Path) -> bool:
    """폴더를 탐색기로 연다. 실패는 False.

    os.startfile 은 Windows 11 에서 폴더를 기존 탐색기 창의 새 탭으로 열 수 있고, 그 창이 다른 가상 데스크톱에 있으면
    화면이 전환된다. 현재 데스크톱에 같은 폴더 창이 있으면 그 창을 앞으로, 없으면 `explorer /n,` 으로 새 창을 연다
    (실측: 새 창은 현재 데스크톱에 뜨고 전환 없음).
    """
    if sys.platform == "win32":
        try:
            hwnd = _explorer_window_here(path.name)
            if hwnd and _activate(hwnd):
                return True
            subprocess.Popen(["explorer.exe", "/n,", str(path)])  # noqa: S603, S607 — shell=False
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("탐색기 새 창 열기 실패, os.startfile 로 폴백: %s", e)
    try:
        _startfile(path)
        return True
    except OSError as e:
        log.debug("폴더 열기 실패: %s (%s)", path, e)
        return False


def _startfile(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603, S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603, S607


def _mac_app(setting: str | None) -> str | None:
    """macOS: 열 앱 이름. auto 면 VS Code → PyCharm 순으로 설치된 것, 없으면 None (기본 앱)."""
    s = normalize_setting(setting)
    names = {"vscode": "Visual Studio Code", "pycharm": "PyCharm"}
    if s == "default":
        return None
    cands = [names[s]] if s in names else list(names.values())
    for n in cands:
        for base in ("/Applications", str(Path.home() / "Applications")):
            if (Path(base) / f"{n}.app").exists():
                return n
    return None


def open_in_editor(problem_dir: Path, file: Path, setting: str | None = "auto") -> OpenResult:
    """풀이 파일을 에디터로 연다. 실패는 os.startfile 폴백, 최종 실패만 ok=False."""
    kind = "default"
    note = ""
    if sys.platform == "darwin":
        app = _mac_app(setting)
        try:
            if app:
                subprocess.Popen(["open", "-a", app, str(file)])  # noqa: S603, S607
                return OpenResult(True, "vscode" if app == "Visual Studio Code" else "pycharm")
        except OSError as e:
            log.debug("에디터 열기 실패, 기본 앱으로 폴백: %s", e)
    if sys.platform == "win32":
        try:
            kind = detect_editor(setting)
            if kind == "vscode":
                _open_vscode(problem_dir, file)
                return OpenResult(True, kind)
            if kind == "pycharm":
                try:
                    if _pycharm_other_desktop_only():
                        note = _PYCHARM_WARNING
                except Exception as e:  # noqa: BLE001
                    log.debug("PyCharm 창 열거 실패: %s", e)
        except Exception as e:  # noqa: BLE001 — 판별/열거/실행 어떤 실패든 폴백
            log.debug("에디터 열기 실패, os.startfile 로 폴백: %s", e)
    try:
        _startfile(file)
        return OpenResult(True, kind, note)
    except OSError as e:
        log.debug("열기 실패: %s (%s)", file, e)
        return OpenResult(False, kind)
