# M13 핸드오프: 에디터에서 열기 + 가상 데스크톱 전환 방지

작성: planner / 대상: builder, tester. 코드 미수정 (설계만).

## 1. 문제와 목표
- 라벨이 "PyCharm 에서 열기" 지만 실제로는 사용자 기본 앱(VS Code)이 열린다 -> 라벨을 에디터 무관하게 변경.
- 핵심: 멀티 가상 데스크톱 사용 중 열기 동작이 다른 데스크톱으로 화면 전환을 일으킨다. 현재 데스크톱에 머물게 한다.
- 원인: os.startfile 이 이미 실행 중인 에디터 인스턴스에 파일을 넘기고, 그 창이 다른 데스크톱에 있으면 Windows 가 활성화하며 데스크톱을 전환.

## 2. 결정 사항
| 항목 | 결정 |
|---|---|
| 라벨 | "에디터에서 열기" (3곳 동일). 툴팁: "열릴 프로그램: VS Code" (판별 결과 표시, 판별 불가 시 "기본 연결 프로그램") |
| 에디터 선택 | 환경설정 `SWEA_EDITOR` = `auto`(기본) / `vscode` / `pycharm` / `default`. auto 는 .py 기본 앱 조회 결과로 결정. 설정 화면 콤보는 P1 (P0 는 .env/환경변수만) |
| 판별 방법 | ctypes `shlwapi.AssocQueryStringW(ASSOCF_NONE, ASSOCSTR_EXECUTABLE, ".py")` -> 실행파일 경로. UserChoice(사용자 기본 앱)를 반영하므로 `assoc` 값이 아니라 실제 열릴 프로그램이 나옴. 파일명 소문자 비교: `code.exe`/`code - insiders.exe` -> vscode, `pycharm64.exe`/`pycharm*.exe` -> pycharm, 그 외 -> default |
| 데스크톱 판별 | ctypes 로 문서화된 `IVirtualDesktopManager`(CLSID aa509086-5ca9-4c25-8f95-589d3c07b48a, IID a5cd92ff-29be-454c-8d04-d82879fb3f1b)의 `IsWindowOnCurrentVirtualDesktop` 만 사용. 비공개 Internal 인터페이스 사용 금지. comtypes/pywin32 미도입 (새 의존성 0) |
| 폴더 열기 | 기존 os.startfile 유지. 수동 검증에서 전환이 재현될 때만 후속 조치 (7절) |

## 3. 열기 전략

### 3.1 VS Code (전환 방지 가능)
1. `Code.exe` 경로는 AssocQueryString 결과 사용 (없으면 `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe`, 그다음 `shutil.which("code")`). `.cmd` 는 셸 경유라 지양, Code.exe 를 직접 `subprocess.Popen([exe, ...])` (shell=False, 인자 리스트).
2. EnumWindows 로 visible + 제목 비어있지 않음 + 프로세스 이미지가 Code.exe(QueryFullProcessImageNameW) 인 최상위 창 수집 -> 각각 IsWindowOnCurrentVirtualDesktop.
3. 분기:
   - 현재 데스크톱에 제목이 문제 폴더명(예: `1234`)을 포함하는 VS Code 창이 있다 -> `Code.exe <문제폴더> -g <파일>` (같은 폴더 창으로 전달, 그 창은 현재 데스크톱이므로 전환 없음).
   - 그 외(다른 데스크톱에만 있거나 아예 없음) -> `Code.exe --new-window <문제폴더> -g <파일>`. 새 창은 현재 데스크톱에 생성.
4. `--reuse-window` 는 사용하지 않는다: "마지막 활성 창"이 다른 데스크톱이면 그대로 전환되기 때문.
5. 제목 매칭은 휴리스틱이므로 실패해도 결과는 "새 창 1개 추가" 로 안전. 데스크톱 API 호출이 예외/실패하면 "현재 데스크톱 창 없음"으로 간주 -> `--new-window`.
6. 트레이드오프: 매칭 실패 시 창이 늘어난다. 허용 (전환보다 낫다).

### 3.2 PyCharm (부분 대응, 한계 명시)
- `pycharm64.exe <파일>` 은 실행 중인 인스턴스로 IPC 전달 후 그 프로젝트 프레임을 활성화한다. 창 위치를 제어할 공식 방법이 없고, 자기 프로세스가 아닌 창을 다른 데스크톱에서 옮기는 문서화된 API 도 없다. 따라서 전환을 완전 차단할 수 없다.
- 처리: 열기 전 PyCharm 창 열거 -> 현재 데스크톱에 없고 다른 데스크톱에만 있으면 "다른 가상 데스크톱의 PyCharm 창으로 전환될 수 있습니다" 를 상태 메시지로만 알리고(막지 않음, 확인창 금지) 그대로 실행. 실행 방식은 기존 os.startfile 과 동일하게 유지 (인자 규약 미검증 상태에서 CLI 직접 호출 금지).
- README/도움말에 "데스크톱 전환을 피하려면 SWEA_EDITOR=vscode 사용 또는 PyCharm 을 현재 데스크톱에서 실행" 한 줄 기재.

### 3.3 default (알 수 없는 앱)
- 기존 os.startfile 그대로. 한계 동일, 별도 처리 없음.

### 3.4 폴백/플랫폼
- 비 Windows: 기존 `xdg-open` 경로 유지, 데스크톱 로직/ctypes.windll 접근 전부 `sys.platform == "win32"` 가드 (import 시점 에러 없어야 함).
- Windows 에서 판별/열거/Popen 중 어떤 예외(OSError, AttributeError, ctypes 오류 포함)든 잡아 로그(debug) 후 `os.startfile` 폴백. 최종 실패만 False 반환.
- 반환은 기존 bool 호환 유지 + 툴팁/상태 메시지용으로 판별 결과 조회 함수 별도 제공.

## 4. 변경 파일
| 파일 | 변경 |
|---|---|
| `swea_fetcher/opener.py` (신규, Qt 비의존) | `detect_editor(setting) -> "vscode"\|"pycharm"\|"default"`, `editor_label(kind) -> str`, `open_in_editor(problem_dir, file, setting="auto") -> OpenResult(ok, kind, note)`, 내부 `_assoc_exe()`, `_windows_of(exe_name)`, `_on_current_desktop(hwnd)` (ctypes, 지연 초기화, 실패 시 None) |
| `swea_fetcher/config.py` | `Settings.editor: str = "auto"` (SWEA_EDITOR, 허용값 외는 auto + 경고). 시크릿 아님 |
| `swea_fetcher/gui/widgets/__init__.py` | `open_with_default_app` 유지(호환), `open_in_explorer` 유지. 신규 `open_in_editor` 재노출 |
| `gui/pages/fetch_page.py`(167,437,444), `problem_page.py`(177,286,293), `history_page.py`(145) | 라벨 "에디터에서 열기", 툴팁에 `editor_label`, 호출을 `open_in_editor(problem_dir, py)` 로 교체 |
| `README`/`docs/troubleshooting.md` | SWEA_EDITOR 설명, PyCharm 한계 |
| `tests/test_opener.py` (신규) | 5절 |

## 5. 수용 기준
- AC1: 3곳 라벨이 "에디터에서 열기", 툴팁에 실제 열릴 프로그램명.
- AC2: auto 에서 이 PC(.py 기본 앱 VS Code)는 vscode 로 판별.
- AC3: VS Code 가 다른 데스크톱에만 떠 있어도 버튼 클릭 시 화면 전환 없이 현재 데스크톱에 새 VS Code 창이 뜬다.
- AC4: 현재 데스크톱에 해당 문제 폴더 창이 있으면 새 창을 만들지 않고 그 창에 파일이 열린다.
- AC5: 데스크톱 API/조회 실패 시에도 파일은 열린다 (os.startfile 폴백), 앱이 죽지 않는다.
- AC6: PyCharm 판별 시 다른 데스크톱 전환 가능성을 상태 메시지로 알리고 열기는 진행.
- AC7: 비 Windows 에서 import/실행 오류 없음. 새 pip 의존성 없음. 경로 인자에 셸 메타문자가 있어도 셸 해석되지 않음(shell=False).
- AC8: 로그에 파일 내용/자격증명 없음 (경로와 판별 결과만).

## 6. 테스트 (모킹만, 실제 창 조작/프로세스 실행 금지)
- `detect_editor`: `_assoc_exe` 를 monkeypatch -> Code.exe / pycharm64.exe / notepad.exe / None / 예외 -> 기대 kind. setting 강제값이 auto 보다 우선. 잘못된 값 -> auto.
- `open_in_editor` vscode: `subprocess.Popen`, `_windows_of`, `_on_current_desktop` 모킹.
  - 현재 데스크톱에 폴더명 포함 창 있음 -> 인자에 `--new-window` 없음, `-g` 포함.
  - 창 없음 / 다른 데스크톱에만 있음 -> `--new-window` 포함.
  - `_on_current_desktop` 예외/None -> `--new-window`.
  - Popen OSError -> `os.startfile`(모킹) 폴백 호출, ok 결과.
  - 인자가 리스트이고 shell 미사용.
- pycharm: 다른 데스크톱에만 창 -> note 에 경고, startfile 호출.
- 비 Windows: `sys.platform` 패치 -> xdg-open 경로, windll 미접근.
- 라벨/툴팁: `editor_label` 반환값 테스트. Settings 로딩: SWEA_EDITOR 값 파싱.
- 전체 테스트 스위트 회귀 통과.

## 7. 수동 검증 (tester, 사용자 PC)
1. 데스크톱 1: 이 앱 실행. 데스크톱 2: VS Code 로 다른 폴더 열어둠. 데스크톱 1 에서 "에디터에서 열기" -> 전환 없이 데스크톱 1 에 새 창 확인 (AC3).
2. 같은 문제를 다시 클릭 -> 새 창이 늘지 않고 기존 창에 열림 (AC4). 늘어나면 창 제목 형식 확인 후 매칭 규칙 보정하도록 보고.
3. 데스크톱 2 에만 그 문제 폴더 창이 있는 상태에서 클릭 -> 데스크톱 1 에 새 창, 전환 없음.
4. SWEA_EDITOR=pycharm 상태에서 다른 데스크톱의 PyCharm 이 있을 때 경고 메시지 표시 및 동작 관찰 (전환 여부 기록).
5. "폴더 열기": 같은 폴더의 탐색기 창을 다른 데스크톱에 열어둔 채 클릭 -> 전환 여부 확인. 전환되면 후속 이슈로 보고 (대안: `explorer.exe` 를 `/n,` 인자로 새 창 강제; 현 범위에서는 미구현).
6. 라벨/툴팁 3곳 확인, VS Code 완전 종료 상태에서도 정상 열림.

## 8. 리스크
- 창 제목 매칭 휴리스틱(VS Code 제목 형식/설정 `window.title` 변경) -> 실패해도 새 창으로 안전 저하.
- `--new-window` 가 같은 폴더가 이미 다른 데스크톱 창에 열려 있을 때 그 창을 재활용해 전환시킬 가능성: VS Code 버전별 동작이라 미확정 -> 수동 검증 3번이 판정 기준. 재현되면 사용자에게 보고하고 대안(임시 `--user-data-dir` 등은 과설계이므로 제외, 한계로 문서화) 결정.
- PyCharm/기본 앱은 전환 완전 차단 불가 (문서화된 API 부재) - 알림으로 대체.
- ctypes COM vtable 호출 오류 가능성 -> 모든 호출 try/except, 실패 시 폴백.
- 비공개 API 미사용이므로 Windows 업데이트에 의한 파손 위험 낮음.
