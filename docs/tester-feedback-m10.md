# M10 테스트 결과 → builder 전달 (2026-09-18)

## 1차 (커밋 `00f0842`, 0.6.3) — 통과 770 / 실패 1

**W1. 새 버전 확인이 한 번도 성공한 적 없으면 "하루 동안 재시도하지 않음" 이 동작하지 않음**
- 테스트: `tests/test_update.py::test_check_failure_backs_off_for_a_day_even_without_prior_success`
- 위치: `swea_fetcher/update.py` `check()` — `fresh = latest and checked_at …` 라 캐시에 `latest` 가 없으면 항상 재조회.
- 영향: 오프라인·비공개·차단망에서 모든 CLI 명령이 매번 최대 ~6초(3s×2단계) 지연.
- 제안: `fresh` 판정을 `checked_at` 만으로.

**S1.** non-fast-forward 로 푸시가 거부돼도 로컬 커밋은 남음(설계와 일치) — README/troubleshooting 에 "이미 커밋됨 → pull 시 merge/rebase" 한 줄 권장.
**S2.** `doctor._settings_row` 의 ID 숨김이 ConfigMissing 메시지 형식에 의존 — `test_doctor_settings_row_password_missing_does_not_leak_id` 가 지킴.

## 2차 재검증 (커밋 `4894d34`) — **통과 772 / 실패 0**

- W1: `fresh` 를 `checked_at` 만으로 판정하도록 수정됨 ✔. 회귀 테스트 `test_check_fresh_checked_at_without_latest_is_none_and_no_http` 추가(실패 직후 캐시 상태에서 하루 안 HTTP 0 → 하루 뒤 재조회).
- S1: `docs/troubleshooting.md` 반영 확인 ✔.
- 남은 요청 없음.
