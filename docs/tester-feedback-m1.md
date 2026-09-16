# M1 테스트 결과 → builder 전달 (2026-09-16)

작성: tester. 대상 커밋: `875d54d` (auth / parser / client / storage / template / config / errors).
테스트 파일: `tests/conftest.py`, `tests/test_{errors,config,parser,template,storage,auth,client}.py` (신규 217개, 네트워크·실제 `~/.swea-fetch` 접근 없음).

## 실행 결과

```
.venv/Scripts/python -m pytest -q
```

**통과 215 / 실패 2 / 스킵 0** (0.7s)

## 실패 항목 (수정 요청)

### Warning

**W1. contestProbId 가 잘못된 URL 에서 `_menuId` 값을 ID 로 반환**
- 테스트: `tests/test_parser.py::test_extract_url_with_invalid_contest_prob_id_must_not_fall_back_to_menu_id` ([test_parser.py:77](../tests/test_parser.py#L77))
- 위치: [swea_fetcher/parser.py:54-76](../swea_fetcher/parser.py#L54-L76) `extract_contest_prob_id`
- 재현:
  ```
  extract_contest_prob_id(".../contestProbDown.do?downType=in&contestProbId=BAD&_menuId=AVtnUz06AA3w6KZN&_menuF=true")
  → 'AVtnUz06AA3w6KZN'   # 기대: InvalidInput
  ```
  `contestProbId=` (빈 값) 도 동일.
- 원인: ① URL 쿼리 분기에서 값이 16자 패턴과 안 맞으면 예외 없이 ③ "문자열 안 유일한 16자 토큰" 으로 흘러가고, Solving Club URL 에는 같은 패턴의 `_menuId` 가 있어 그게 잡힘.
- 제안: `"contestProbId" in s` 분기에서 쿼리에 키가 존재하는데 값이 유효하지 않으면 바로 `InvalidInput` 을 던지고 ②/③ 으로 내려가지 않게 할 것. (링크 복사가 잘려 들어온 경우 엉뚱한 문제를 조회하거나 오해를 부르는 ProblemNotFound 가 뜸)

### Suggestion

**S1. 첨부 `<a>` 에 보이는 파일명이 없으면 숨김 라벨 "다운로드" 가 파일명으로 채워짐**
- 테스트: `tests/test_parser.py::test_attachment_filename_skips_hidden_label_only` ([test_parser.py:282](../tests/test_parser.py#L282))
- 위치: [swea_fetcher/parser.py:120-129](../swea_fetcher/parser.py#L120-L129) `_attachment_filename`
- 원인: span 루프는 `class="hide"` 를 건너뛰지만 마지막 폴백 `a.get_text(strip=True)` 가 숨김 span 텍스트까지 포함.
- 영향: `input_filename` 은 안내 메시지에만 쓰이므로 낮음. 폴백에서 `.hide` 를 제외하거나 빈 문자열을 돌려주면 됨. 판단에 따라 보류 가능.

## 테스트 중 발견한 비실패 관찰 (수정 여부는 판단 요청)

**S2. `--force` 덮어쓰기 도중 실패 시 기존 input/output 이 복구되지 않음**
- [swea_fetcher/storage.py:127-139](../swea_fetcher/storage.py#L127-L139) `_rollback` 은 "이번에 쓴 파일 삭제" 이므로 force 로 기존 `input.txt` 를 덮다가 `output.txt` 에서 실패하면 옛 `input.txt` 도 사라짐. 임시 파일에 쓴 뒤 `os.replace` 로 교체하거나, force 시 백업 후 복원하는 방식을 고려. (assert 로 고정하지 않고 관찰만 기록)

**S3. 프로세스당 로그인 1회 가드와 세션 만료 재로그인의 충돌**
- `auth.get_session` 이 이번 실행에서 새로 로그인한 뒤 곧바로 세션이 만료되면 `client._with_relogin` → `auth.login` 이 `LoginFailed("이 실행에서 이미 로그인을 시도했습니다")` 로 끝남. 설계 의도(잠금 방지)와 맞다면 그대로 두되, 사용자 메시지에 "다시 실행하세요" 안내를 붙이는 것을 제안. M2 E2E 에서 실제 발생 여부 확인 필요.

**S4. `load_settings` 가 `load_dotenv` 로 `os.environ` 을 프로세스 전역에 오염**
- [swea_fetcher/config.py:57-58](../swea_fetcher/config.py#L57-L58). 테스트에서는 autouse 픽스처로 격리했음. `dotenv_values()` 로 읽어 `os.environ` 과 병합하는 방식이면 부작용이 없음. 우선순위 낮음.

**S5. `auth.login` 실패 메시지 포맷**
- [swea_fetcher/auth.py:188-189](../swea_fetcher/auth.py#L188-L189) 매핑에 없는 서버 코드에 `{`/`}` 가 들어오면 `.format(n=...)` 이 KeyError. 실제로 올 가능성은 낮음. `template.format(n=failures)` 를 매핑된 경우에만 적용하면 안전.

**참고.** `pyproject.toml` 의 `swea-fetch = "swea_fetcher.cli:main"` 이 가리키는 `cli.py` 는 아직 없음 (M2 범위로 보임). 현재 테스트 스위트는 cli 를 다루지 않음.

## 재테스트 범위

- W1 수정 후: `pytest tests/test_parser.py` (URL/ID 추출 전체 케이스가 같은 파일에 있음)
- S1 수정 시: 같은 파일
- S2 수정 시: `pytest tests/test_storage.py` (롤백 테스트 3개가 `storage._write` 를 monkeypatch 하므로, 임시파일 방식으로 바꾸면 테스트도 손봐야 함 — tester 에게 알려주면 갱신)
