"""문제별 Python 시간 제한 (M25): 지문 파싱 · 기록 · 조회 · 검증 타임아웃 · logout."""

from __future__ import annotations

import pytest

from swea_fetcher import checker, content_cache, service, time_limits
from swea_fetcher.models import ProblemContent

LIMITS = "<ul><li>시간 : 10개 테스트케이스를 합쳐서 C++의 경우 1초 / Java의 경우 2초 / Python의 경우 4초</li><li>메모리 : 힙, 정적 메모리 합쳐서 256MB 이내, 스택 메모리 1MB 이내</li></ul>"


@pytest.mark.parametrize(
    ("html", "want"),
    [
        (LIMITS, 4.0),
        ("<li>시간 : 30개 테스트케이스를 합쳐서 Python의 경우 10초</li>", 10.0),
        ("<li>시간 : 10개 테스트케이스를 합쳐서 C의 경우 1초 / Java의 경우 1.5초 / Python의 경우 3초</li>", 3.0),
        ("<li>시간 : 10개 테스트케이스를 합쳐서 Python : 2.5초</li>", 2.5),
        ("<li>시간 : 2초</li><li>메모리 : 256MB</li>", 2.0),  # Python 표기가 없고 값이 하나뿐이면 그 값
        ("<li>시간 : C의 경우 1초 / Java의 경우 2초</li>", None),  # Python 이 없고 값이 여러 개면 모름
        ("<li>메모리 : 256MB</li>", None),
        ("", None),
        ("<li>시간 : Python의 경우 0초</li>", None),
        ("<li>시간 : Python의 경우 9999초</li>", None),
    ],
)
def test_parse_python_limit(html, want):
    assert time_limits.parse_python_limit(html) == want


def test_remember_lookup_and_clear(settings):
    assert time_limits.lookup(settings, 1234) is None
    assert time_limits.remember(settings, 1234, LIMITS) == 4.0
    assert time_limits.lookup(settings, 1234) == 4.0
    assert (settings.config_dir / time_limits.FILE).exists() and not settings.cache_dir.exists()  # 지문 캐시 폴더에는 쓰지 않는다
    assert time_limits.remember(settings, 99, "<li>메모리</li>") is None and time_limits.lookup(settings, 99) is None
    assert time_limits.clear(settings.config_dir) == 1 and time_limits.lookup(settings, 1234) is None


def test_lookup_falls_back_to_statement_cache(settings):
    content_cache.save(settings, 777, "sim", "x", ProblemContent(limits_html=LIMITS, body_html="<p>a</p>"))
    assert time_limits.lookup(settings, 777) == 4.0


def test_corrupt_file_is_ignored(settings):
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    (settings.config_dir / time_limits.FILE).write_text("{oops", encoding="utf-8")
    assert time_limits.lookup(settings, 1) is None
    assert time_limits.remember(settings, 1, LIMITS) == 4.0 and time_limits.lookup(settings, 1) == 4.0


def test_check_timeout_uses_problem_limit_else_default(settings):
    d = settings.root / "sim" / "1234"
    assert service.check_timeout(settings, d) == (checker.DEFAULT_TIMEOUT, False)
    time_limits.remember(settings, 1234, LIMITS)
    assert service.check_timeout(settings, d) == (4.0, True)
    assert service.check_timeout(settings, settings.root / "sim" / "notes") == (checker.DEFAULT_TIMEOUT, False)


def test_check_problem_passes_problem_limit_to_checker(settings, monkeypatch):
    seen = []
    monkeypatch.setattr(checker, "run_and_compare", lambda d, s, t, **k: seen.append(t) or checker.CheckResult(False, "", "", "", 0.0, False, []))
    d = settings.root / "sim" / "1234"
    time_limits.remember(settings, 1234, LIMITS)
    service.check_problem(settings, d)
    service.check_problem(settings, d, timeout=7.0)  # CLI --timeout 처럼 직접 주면 그 값
    assert seen == [4.0, 7.0]


def test_logout_all_removes_time_limits(settings, monkeypatch):
    time_limits.remember(settings, 1234, LIMITS)
    removed = service.logout(settings.config_dir, all_=True)
    assert "시간 제한 기록" in removed and time_limits.lookup(settings, 1234) is None
