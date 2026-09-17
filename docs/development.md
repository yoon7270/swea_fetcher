# 개발자용

## 구조

```
swea_fetcher/
├── cli.py          진입점: fetch(기본) / init / logout / check / doctor
├── service.py      CLI·GUI 공용 파이프라인 (fetch_problem, list_topics, list_recent, write_env, logout)
├── auth.py         로그인 (AJAX JSON), 세션 캐시, 잠금 가드
├── client.py       HTTP (호스트 화이트리스트, 재시도, utf-8 강제, 302 → SessionExpired)
├── lookup.py       문제 번호 → contestProbId (공개 목록 → User Problem → Solving Club 상자, 캐시)
├── parser.py       HTML → ProblemInfo. 선택자 상수는 파일 상단 (SEL_*, TITLE_RE)
├── storage.py      경로 계산·중첩 주제 검증·저장·롤백
├── checker.py      풀이 실행 + output.txt 행 단위 비교, 인터프리터 탐색(resolve_python)
├── doctor.py       진단 정보 (CLI doctor / GUI [진단 정보 복사])
├── update.py       새 버전 확인 (GitHub Releases, 하루 1회 캐시)
├── config.py       Settings, .env, keyring (Windows 자격 증명 관리자)
├── errors.py       예외 계층 + 종료 코드 + 힌트
└── gui/            PySide6: app.py, main_window.py, workers.py(QThread), pages/, widgets/, theme/tokens.py(QSS)
packaging/          PyInstaller spec, 런처, 아이콘 생성
design/             디자인 스펙·아이콘·목업
docs/               페이지 구조 조사(swea-page-notes.md), 전달 문서, 스크린샷
tests/              pytest + pytest-qt (491+). fixtures/ 는 계정 정보를 DUMMY_* 로 치환한 실제 페이지
```

## 설치·테스트

```powershell
python -m venv .venv
```

```powershell
.\.venv\Scripts\Activate.ps1
```

```powershell
pip install -e ".[dev,gui]"
```

```powershell
pytest
```

- 테스트는 네트워크·자격 증명·레지스트리를 건드리지 않습니다 (`tests/conftest.py` 의 `FakeSession`, `FakeKeyring`, tmp `CONFIG_DIR`). GUI 테스트는 offscreen.
- 한글이 깨지면 `$env:PYTHONUTF8=1`.

## 사이트 구조가 바뀌었을 때

1. [swea-page-notes.md](swea-page-notes.md) 에서 어떤 페이지의 어떤 요소를 읽는지 확인
2. `swea_fetcher/parser.py` 상단 상수(`SEL_SOLVER_TITLE`, `SEL_CLUB_TITLE`, `SEL_ATTACH`, `TITLE_RE`) 수정
3. 새 페이지를 `tests/fixtures/` 에 저장할 때는 **닉네임(`span.name`)·`userInformationPopup('…')` 키·클럽 ID 를 반드시 `DUMMY_*` 로 치환**하고 커밋 전에 확인:

```powershell
git diff --cached | Select-String -Pattern "SESSION=|SWEA_PW=|userInformationPopup\('A"
```

## 버전 올리기·Release

1. `swea_fetcher/__init__.py` 의 `__version__` (pyproject 는 여기서 읽음) + `CHANGELOG.md`
2. 커밋 → 태그 `vX.Y.Z` → 푸시
3. exe 빌드 후 Release 에 첨부:

```powershell
pip install pyinstaller pillow
```

```powershell
python packaging\make_ico.py
```

```powershell
pyinstaller packaging\swea-fetch-gui.spec --noconfirm
```

```powershell
Get-FileHash dist\swea-fetch-gui.exe -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLower()) *swea-fetch-gui.exe" } | Set-Content dist\swea-fetch-gui.exe.sha256
```

```powershell
gh release create vX.Y.Z dist\swea-fetch-gui.exe dist\swea-fetch-gui.exe.sha256 --title "vX.Y.Z" --notes-file <CHANGELOG 발췌>
```

- `dist/`·`build/` 는 커밋하지 않습니다
- exe 자가진단 (창 없이 frozen·keyring·설정·인터프리터 확인):

```powershell
$env:SWEA_FETCH_SELFTEST="$env:TEMP\swea_selftest.txt"; .\dist\swea-fetch-gui.exe; Get-Content $env:SWEA_FETCH_SELFTEST
```

- 백신 오탐이 잦으면 `packaging\swea-fetch-gui.spec` 의 `ONEFILE = False` 로 폴더형 빌드
- 새 버전 알림(`update.py`)은 Release 의 태그 이름(`vX.Y.Z`)을 현재 `__version__` 과 비교합니다 — 태그를 빼먹으면 알림이 가지 않습니다

## 역할 분담 문서

- 구성안·마일스톤: `../docs/project-plan.md` (저장소 밖)
- 전달 문서: `docs/handoff-*.md`, 테스터 피드백: `docs/tester-feedback-*.md`
- 디자인: `design/design-spec.md` (QSS 계약은 `gui/theme/tokens.py` 가 기준)
