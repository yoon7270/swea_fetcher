# builder → designer 전달 (M4 GUI 구현 검토 요청, 2026-09-17)

대상: `design/design-spec.md` 와 구현 화면의 일치 확인. 구현 `swea_fetcher/gui/`, 태그 `v0.3.1`.

## 1. 확인해 주실 것

1. **캡처 vs 스펙**: `docs/gui-screenshots/` 9장 (offscreen + Windows 글꼴로 렌더). 실제 창은 `swea-fetch-gui` 로 띄우면 됩니다.
   - `1-settings-first-run` / `2-settings-saved` — §6.4, §4.1
   - `3a-fetch-running` / `3b-fetch-success` / `3c-fetch-preview` / `3d-fetch-already-exists` — §6.1 상태 4종
   - `4-check-fail` / `4b-check-pass` — §6.2, §5.9 diff
   - `5-history` — §6.3
2. **대체안 8건 승인** — 스펙 §15 "대체안 기록란"에 적어 두었습니다. 요약:

| # | 스펙 | 구현 | 이유 |
|---|---|---|---|
| 1 | §3 내비 `QToolButton[nav]` | `QListWidget#nav` | `tokens.build_qss` 가 `#nav` 셀렉터로 작성돼 있어 QSS 를 따름. 아이콘 재착색(§12)은 동일 |
| 2 | `#nav:focus::item:selected`, `QCheckBox:focus::indicator` 포커스 링 | 두 규칙 제거, Fusion 기본 포커스 | Qt 가 위젯 **전체** 테두리로 해석해 리스트·체크박스에 파란 테두리가 상시 표시됨 |
| 3 | §5.9 diff 행 배경 `BackgroundRole` | 커스텀 델리게이트로 직접 칠함, 선택 비활성 | QSS `::item` 규칙이 있으면 Qt 가 `BackgroundRole` 을 무시. 선택색이 diff 색을 덮음 |
| 4 | §5.10 파일 행 배지(pill) | `[생성]`·`[이미 있음]` 대괄호 + `*_text` 색 | Qt rich text 는 `<span>` radius/padding 미지원. 행마다 QLabel 분리(`<table>` 높이 계산 오류) |
| 5 | §11 높이 < 560 로그 접힘 | 저장 페이지 전체를 `QScrollArea` 로 | 결과 카드(미리보기 3줄) + 로그가 600px 를 넘어 겹침. 로그 최소 80 유지 |
| 6 | §5.8 토글 `▾/▸` | `▼/▶` | 맑은 고딕에 글리프 없음 |
| 7 | §5.5 진행 메시지 | 로그 + 상태바 `showMessage(4s)` | 스펙대로 |
| 8 | — | builder QSS 보강 (`gui/app.py::_builder_supplement`) | `#Sidebar`, 드롭 중 카드 테두리, 미리보기 블록 `#preview`. 색은 토큰만 |

3. **아이콘**: `design/icons/*.svg` 를 `gui/theme/icons/` 로 복사해 사용. `app.ico` 는 `packaging/make_ico.py` 로 SVG 에서 생성(256~16px) — 확인 부탁.

## 2. 구현이 스펙에서 확장한 것 (스펙에 추가 기록 요청)

- 검증 페이지 드롭: `.py` 뿐 아니라 **`{번호}` 폴더** 드롭도 허용. 잘못 놓으면 경고 배너에 "놓은 항목: …" 표시. (사용자가 입력창 위에 놓아 텍스트로 들어간 사고가 있어 자식 입력창의 드롭 수용을 껐음)
- 미리보기 카드의 [이대로 저장] 은 충돌이 있으면 라벨이 [덮어쓰고 저장] 으로 바뀜 (§6.1 미리보기 상태와 동일).
- 배너 조치 버튼 키: `force` / `skeleton` / `refresh` / `retry` / `settings` / `fetch` / `log` (§9 매핑 구현).

## 3. 알고 있는 표시 차이 (수정 여부 판단 요청)

- 고정폭 글꼴(`Consolas`) 영역의 한글(예: 결과 카드 "원본", "뼈대 생성")이 offscreen 캡처에서 작게 보임 — 실제 Windows 에선 맑은 고딕으로 폴백되나, `FONT_MONO` 에 한글 지원 고정폭(`D2Coding` 번들?)을 넣을지 결정 필요.
- 배지 텍스트가 mono 영역 안에 있어 §5.7 pill 과 시각적으로 다름 (#4).
- 다크 테마 없음 (`tokens.DARK = None`).

## 4. 수정 요청 방법

- 색·간격·글꼴: `swea_fetcher/gui/theme/tokens.py` 만 수정 (`Palette` 값 / `build_qss`). 위젯 코드에 색상값 없음.
- 문구: 각 페이지 파일의 문자열 (`gui/pages/*.py`). 배너 문구는 `errors.py` 의 `default_hint`.
- 변경 후 확인: `QT_QPA_FONTDIR=C:/Windows/Fonts` 로 캡처 스크립트를 돌리면 `docs/gui-screenshots/` 가 갱신됩니다 (builder 에게 요청하면 바로 재생성).
