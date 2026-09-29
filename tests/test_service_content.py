"""service 의 지문 경로 (M12): with_content / 이미지 다운로드 / 디스크 캐시 / 루트 무변경. 네트워크 경계는 스텁."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from swea_fetcher import config, content_cache, service
from swea_fetcher.errors import AlreadyExists, NetworkError, SessionExpired
from swea_fetcher.models import ImageRef, ProblemContent
from swea_fetcher.service import FetchOptions
from tests.conftest import CONTEST_PROB_ID, FakeSession

ID = CONTEST_PROB_ID
IN = b"3\n1 2\n"
OUT = b"#1 3\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def stubs(monkeypatch, solver_html):
    st = {"page": (solver_html, "solver"), "calls": [], "images": {}}

    def download(session, url, settings=None):
        st["calls"].append(("download", url))
        if "downType=in" in url:
            return IN
        if "downType=out" in url:
            return OUT
        data = st["images"][url]
        if isinstance(data, Exception):
            raise data
        return data

    monkeypatch.setattr(service.auth, "get_session", lambda settings: FakeSession())
    monkeypatch.setattr(service.client, "fetch_problem_page", lambda s, st_, cid: st["page"])
    monkeypatch.setattr(service.client, "download", download)
    return st


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def _fetch(settings, **kw):
    return service.fetch_problem(settings, ID, "sim", FetchOptions(**kw))


def _with_remote_images(html: str, *srcs: str) -> str:
    return html.replace('<div class="box4">', '<div class="box4">' + "".join(f'<img src="{s}">' for s in srcs), 1)


# --- with_content 옵트인 ------------------------------------------------------------


def test_without_with_content_nothing_content_related_runs(stubs, settings, monkeypatch):
    """CLI 회귀: 기본값이면 지문 파싱·이미지 다운로드·캐시 쓰기가 전혀 없다."""
    monkeypatch.setattr(service.parser, "parse_content", lambda *_: pytest.fail("parse_content 호출 금지"))
    monkeypatch.setattr(service.content_cache, "save", lambda *_a, **_k: pytest.fail("캐시 쓰기 금지"))
    stubs["page"] = (_with_remote_images(stubs["page"][0], "/a.png"), "solver")
    oc = _fetch(settings, cache_content=True)
    assert oc.content is None and oc.result is not None
    assert [c for c in stubs["calls"] if "a.png" in c[1]] == []
    assert not settings.cache_dir.exists()


def test_cli_fetch_options_do_not_enable_content():
    opts = FetchOptions()
    assert opts.with_content is False and opts.cache_content is False


def test_with_content_returns_statement(stubs, settings):
    oc = _fetch(settings, with_content=True)
    assert oc.content is not None and "플레이어는 1번 구역" in oc.content.body_html
    assert oc.result is not None and oc.notices == []


def test_skeleton_only_also_returns_content(stubs, settings):
    oc = _fetch(settings, with_content=True, skeleton_only=True)
    assert oc.content is not None and oc.result is not None


def test_missing_statement_area_adds_notice_and_still_saves(stubs, settings, error_html):
    stubs["page"] = (stubs["page"][0].replace('class="box4"', 'class="other"'), "solver")
    oc = _fetch(settings, with_content=True)
    assert oc.content is None and oc.result is not None
    assert any("지문 영역을 찾지 못했습니다" in n for n in oc.notices)


def test_parse_content_crash_does_not_break_fetch(stubs, settings, monkeypatch):
    def boom(_html):
        raise RuntimeError("예상 밖")

    monkeypatch.setattr(service.parser, "parse_content", boom)
    oc = _fetch(settings, with_content=True)
    assert oc.result is not None and oc.content is None


# --- 이미지 다운로드 -----------------------------------------------------------------


def test_remote_images_downloaded(stubs, settings):
    url = "https://swexpertacademy.com/a.png"
    stubs["page"] = (_with_remote_images(stubs["page"][0], "/a.png"), "solver")
    stubs["images"][url] = PNG
    msgs: list[str] = []
    oc = service.fetch_problem(settings, ID, "sim", FetchOptions(with_content=True), msgs.append)
    ref = oc.content.images["swea-img:0"]
    assert ref.data == PNG and ref.error is None
    assert "지문 이미지 1/1" in msgs


@pytest.mark.parametrize(
    "payload, expect",
    [
        (NetworkError("HTTP 404"), "다운로드 실패"),
        (SessionExpired("HTML 이 왔습니다"), "다운로드 실패"),
        (b"just text", "이미지가 아닌 응답"),
    ],
)
def test_image_failures_are_per_image_and_not_fatal(stubs, settings, payload, expect):
    stubs["page"] = (_with_remote_images(stubs["page"][0], "/a.png", "/b.png"), "solver")
    stubs["images"]["https://swexpertacademy.com/a.png"] = payload
    stubs["images"]["https://swexpertacademy.com/b.png"] = PNG
    oc = _fetch(settings, with_content=True)
    a, b = oc.content.images["swea-img:0"], oc.content.images["swea-img:1"]
    assert a.data is None and expect in a.error
    assert b.data == PNG and b.error is None
    assert oc.result is not None  # fetch 성공은 유지


def test_external_host_image_never_downloaded(stubs, settings):
    stubs["page"] = (_with_remote_images(stubs["page"][0], "http://evil.example.com/t.gif"), "solver")
    oc = _fetch(settings, with_content=True)
    assert oc.content.images["swea-img:0"].error == "외부 이미지 생략"
    assert [c for c in stubs["calls"] if "evil" in c[1]] == []


# --- 루트 무변경 ---------------------------------------------------------------------


def test_save_writes_no_statement_files_under_root(stubs, settings, root_dir):
    _fetch(settings, with_content=True, cache_content=True)
    assert _tree(root_dir) == {"sim", "sim/25730", "sim/25730/input.txt", "sim/25730/output.txt", "sim/25730/25730.py"}


def test_dry_run_leaves_root_unchanged_and_skips_cache(stubs, settings, root_dir):
    before = _tree(root_dir)
    oc = _fetch(settings, with_content=True, cache_content=True, dry_run=True)
    assert oc.result is None and oc.preview is not None and oc.content is not None
    assert _tree(root_dir) == before
    assert not settings.cache_dir.exists()


def test_storage_and_gitops_never_mention_statement_files():
    for mod in ("storage.py", "gitops.py"):
        src = (Path(__file__).parent.parent / "swea_fetcher" / mod).read_text(encoding="utf-8")
        assert "problem.md" not in src and "content_cache" not in src and "ProblemContent" not in src


# --- 디스크 캐시 (P1) ------------------------------------------------------------------


def test_cache_written_only_under_config_dir(stubs, settings, root_dir, config_dir):
    _fetch(settings, with_content=True, cache_content=True)
    f = config_dir / "cache" / "statements" / "25730.json"
    assert f.is_file()
    assert all(root_dir not in p.parents for p in (config_dir / "cache").rglob("*"))
    cached = content_cache.load(settings, 25730)
    assert cached is not None and cached.topic == "sim" and cached.title == "항아리 게임"
    assert "플레이어는 1번 구역" in cached.content.body_html


def test_cache_off_writes_nothing(stubs, settings):
    _fetch(settings, with_content=True, cache_content=False)
    assert not settings.cache_dir.exists()


def test_cache_refused_when_cache_dir_inside_root(stubs, root_dir, config_dir):
    inner = config.Settings(root=root_dir, user_id="u", password="p", config_dir=root_dir / ".cfg")
    (root_dir / ".cfg").mkdir()
    assert content_cache.save(inner, 1, "t", "x", ProblemContent(body_html="<p>a</p>")) is False
    assert not (root_dir / ".cfg" / "cache").exists()


def test_cache_recorded_before_save_so_conflict_still_viewable(stubs, settings):
    _fetch(settings)  # 먼저 저장 (지문 없이)
    with pytest.raises(AlreadyExists):
        _fetch(settings, with_content=True, cache_content=True)
    assert content_cache.has(settings, 25730)


def test_cache_keeps_most_recent_50(settings):
    c = ProblemContent(body_html="<p>x</p>")
    for n in range(1, 52):
        assert content_cache.save(settings, n, "t", f"T{n}", c)
        os.utime(content_cache._file(settings, n), (1_000_000 + n, 1_000_000 + n))  # mtime 을 결정적으로
    files = sorted(p.name for p in content_cache.statements_dir(settings.cache_dir).glob("*.json"))
    assert len(files) == 50
    assert "1.json" not in files and "51.json" in files


def test_cache_roundtrip_with_images(settings):
    c = ProblemContent(limits_html="<ul><li>1초</li></ul>", body_html='<p>a</p><img src="swea-img:0"/>',
                       images={"swea-img:0": ImageRef(data=PNG, alt="그림"), "swea-img:1": ImageRef(url="https://swexpertacademy.com/x.png", error="다운로드 실패")})
    assert content_cache.save(settings, 7, "sim", "제목", c)
    got = content_cache.load(settings, 7).content
    assert got == c


@pytest.mark.parametrize("bad", ["{not json", '{"num": 7}', '{"num":7,"body_html":"x","images":{"a":{"data":"@@@"}}}', "[]"])
def test_corrupt_cache_is_ignored(settings, bad):
    d = content_cache.statements_dir(settings.cache_dir)
    d.mkdir(parents=True)
    (d / "7.json").write_text(bad, encoding="utf-8")
    assert content_cache.load(settings, 7) is None
    assert content_cache.load(settings, 8) is None


def test_clear_only_removes_statement_cache(settings):
    content_cache.save(settings, 1, "t", "x", ProblemContent(body_html="<p>a</p>"))
    other = settings.cache_dir / "keep.txt"
    other.write_text("k")
    assert content_cache.clear(settings.cache_dir) == 1
    assert other.exists() and not content_cache.has(settings, 1)


def test_logout_all_removes_statement_cache(settings, config_dir, fake_keyring):
    content_cache.save(settings, 1, "t", "x", ProblemContent(body_html="<p>a</p>"))
    removed = service.logout(config_dir, all_=True)
    assert "지문 캐시" in removed and not content_cache.has(settings, 1)


def test_cli_fetch_leaves_no_cache(stubs, settings, config_dir):
    """CLI 경로는 FetchOptions 기본값 그대로 → 지문·캐시 없음."""
    service.fetch_problem(settings, ID, "sim", FetchOptions())
    assert not (config_dir / "cache").exists()
