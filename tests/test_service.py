"""service: CLI/GUI 공용 파이프라인. auth/client/lookup 경계만 스텁하고 parser/storage 는 실제로 돈다."""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from dotenv import dotenv_values

from swea_fetcher import config, service
from swea_fetcher.errors import AlreadyExists, AttachmentNotFound, InvalidInput, LoginFailed, NetworkError, ProblemNotFound
from swea_fetcher.service import FetchOptions
from tests.conftest import CONTEST_PROB_ID, DUMMY_ID, FakeSession

ID = CONTEST_PROB_ID
IN = b"3\n1 2\n3 4\n5 6\n"
OUT = b"#1 3\n#2 7\n#3 11\n"


@pytest.fixture
def stubs(monkeypatch, solver_html):
    """네트워크 경계 스텁. 기본: 세션 OK, solver 페이지, 첨부 IN/OUT."""
    st = {
        "session": FakeSession(),
        "page": (solver_html, "solver"),
        "downloads": {"in": IN, "out": OUT},
        "lookup": {},  # num -> id
        "calls": [],
    }

    def get_session(settings):
        st["calls"].append("get_session")
        return st["session"]

    def fetch_page(session, settings, cid):
        st["calls"].append(("fetch_page", cid))
        page = st["page"]
        if isinstance(page, Exception):
            raise page
        return page

    def download(session, url, settings=None):
        st["calls"].append(("download", url))
        key = "in" if "downType=in" in url else "out"
        data = st["downloads"][key]
        if isinstance(data, Exception):
            raise data
        return data

    def find_by_number(session, settings, num, refresh=False):
        st["calls"].append(("lookup", num, refresh))
        if num in st["lookup"]:
            return st["lookup"][num]
        raise InvalidInput(f"문제 번호 {num} 을(를) 찾지 못했습니다")

    monkeypatch.setattr(service.auth, "get_session", get_session)
    monkeypatch.setattr(service.client, "fetch_problem_page", fetch_page)
    monkeypatch.setattr(service.client, "download", download)
    monkeypatch.setattr(service.lookup, "find_by_number", find_by_number)
    return st


# =============================================================================
# resolve_topic / preview_text
# =============================================================================


def test_resolve_topic_exact(root_dir):
    (root_dir / "BFS").mkdir()
    assert service.resolve_topic(root_dir, " BFS ") == ("BFS", [])


def test_resolve_topic_case_insensitive_uses_existing(root_dir):
    (root_dir / "BFS").mkdir()
    topic, notices = service.resolve_topic(root_dir, "bfs")
    assert topic == "BFS"
    assert len(notices) == 1 and "BFS" in notices[0] and "bfs" in notices[0]


def test_resolve_topic_similar_only_notifies(root_dir):
    (root_dir / "Queue").mkdir()
    topic, notices = service.resolve_topic(root_dir, "Queues")
    assert topic == "Queues"
    assert len(notices) == 1 and "Queue" in notices[0]


def test_resolve_topic_new_and_hidden_dirs_ignored(root_dir):
    (root_dir / ".git").mkdir()
    assert service.resolve_topic(root_dir, ".git") == (".git", [])  # 숨김 폴더는 후보에서 제외되므로 안내 없음
    assert service.resolve_topic(root_dir, "Stack") == ("Stack", [])


def test_resolve_topic_missing_root(tmp_path):
    assert service.resolve_topic(tmp_path / "nope", "x") == ("x", [])


def test_preview_text():
    assert service.preview_text(None) == ""
    assert service.preview_text(b"1\r\n2\r\n") == "1 / 2"
    assert service.preview_text(b"1\n2\n3\n4\n") == "1 / 2 / 3 ..."
    long = service.preview_text(b"x" * 100)
    assert len(long) == service.PREVIEW_CHARS and long.endswith("...")
    assert service.preview_text(b"  a  \n") == "a"


# =============================================================================
# fetch_problem — 정상
# =============================================================================


def test_fetch_by_url_saves_files(settings, stubs):
    progress: list[str] = []
    oc = service.fetch_problem(settings, f"https://swexpertacademy.com/x?contestProbId={ID}", "sim", progress=progress.append)
    assert oc.info.num == 25730 and oc.info.title == "항아리 게임"
    assert oc.topic == "sim" and oc.notices == [] and oc.preview is None
    d = oc.result.problem_dir
    assert d == (settings.root / "sim" / "25730").resolve()
    assert (d / "input.txt").read_bytes() == IN and (d / "output.txt").read_bytes() == OUT
    assert (d / "25730.py").read_text(encoding="utf-8").startswith("# 25730. 항아리 게임")
    assert stubs["calls"][:2] == ["get_session", ("fetch_page", ID)]
    assert any("저장 완료" in m for m in progress)


def test_fetch_by_number_uses_lookup(settings, stubs):
    stubs["lookup"][25730] = ID
    oc = service.fetch_problem(settings, "25730", "sim", FetchOptions(refresh_index=True))
    assert ("lookup", 25730, True) in stubs["calls"]
    assert ("fetch_page", ID) in stubs["calls"]
    assert oc.result is not None


def test_fetch_by_bare_id(settings, stubs):
    service.fetch_problem(settings, ID, "sim")
    assert ("fetch_page", ID) in stubs["calls"]
    assert not any(isinstance(c, tuple) and c[0] == "lookup" for c in stubs["calls"])


def test_fetch_uses_existing_topic_case_insensitively(settings, stubs):
    (settings.root / "SIM").mkdir()
    oc = service.fetch_problem(settings, ID, "sim")
    assert oc.topic == "SIM"
    assert len(oc.notices) == 1
    assert (settings.root / "SIM" / "25730" / "input.txt").exists()


def test_fetch_num_override_replaces_page_number(settings, stubs, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="swea_fetcher.service"):
        oc = service.fetch_problem(settings, ID, "sim", FetchOptions(num_override=999))
    assert oc.info.num == 999
    assert (settings.root / "sim" / "999" / "999.py").exists()
    assert any("999" in r.getMessage() for r in caplog.records)


def test_fetch_num_override_when_page_has_no_number(settings, stubs, club_html):
    stubs["page"] = (club_html, "detail")
    oc = service.fetch_problem(settings, ID, "sim", FetchOptions(num_override=25730))
    assert oc.info.num == 25730 and oc.result is not None


def test_fetch_no_number_and_no_override(settings, stubs, club_html):
    stubs["page"] = (club_html, "detail")
    with pytest.raises(InvalidInput, match="--num"):
        service.fetch_problem(settings, ID, "sim")
    assert not (settings.root / "sim").exists()


def test_fetch_force_overwrites(settings, stubs):
    service.fetch_problem(settings, ID, "sim")
    stubs["downloads"] = {"in": b"new-in\n", "out": b"new-out\n"}
    with pytest.raises(AlreadyExists):
        service.fetch_problem(settings, ID, "sim")
    oc = service.fetch_problem(settings, ID, "sim", FetchOptions(force=True))
    assert (oc.result.problem_dir / "input.txt").read_bytes() == b"new-in\n"
    assert [p.name for p in oc.result.skipped] == ["25730.py"]


# =============================================================================
# fetch_problem — skeleton_only / dry_run
# =============================================================================


def test_fetch_skeleton_only_skips_download(settings, stubs):
    stubs["page"] = ("<html><h3 class='problem_title'>1234. A+B</h3></html>", "solver")  # 첨부 없음
    oc = service.fetch_problem(settings, ID, "sim", FetchOptions(skeleton_only=True))
    assert not any(isinstance(c, tuple) and c[0] == "download" for c in stubs["calls"])
    d = oc.result.problem_dir
    assert (d / "input.txt").read_bytes() == b"" and (d / "1234.py").exists() and not (d / "output.txt").exists()


def test_fetch_without_attachments_and_without_skeleton_flag_fails(settings, stubs):
    stubs["page"] = ("<html><h3 class='problem_title'>1234. A+B</h3></html>", "solver")
    with pytest.raises(AttachmentNotFound):
        service.fetch_problem(settings, ID, "sim")


def test_fetch_dry_run_downloads_but_writes_nothing(settings, stubs):
    oc = service.fetch_problem(settings, ID, "sim", FetchOptions(dry_run=True))
    assert oc.result is None
    assert not (settings.root / "sim").exists()
    pv = oc.preview
    assert pv["problem_dir"] == (settings.root / "sim" / "25730").resolve()
    assert pv["needs_force"] is False
    names = [(f.name, f.action) for f in pv["files"]]
    assert names == [("input.txt", "create"), ("output.txt", "create"), ("25730.py", "create")]
    fin = pv["files"][0]
    assert fin.source == "input7_sample.txt" and fin.size == len(IN) and fin.preview == "3 / 1 2 / 3 4 ..."


def test_fetch_dry_run_reports_conflicts(settings, stubs):
    service.fetch_problem(settings, ID, "sim")
    pv = service.fetch_problem(settings, ID, "sim", FetchOptions(dry_run=True)).preview
    assert pv["needs_force"] is True
    assert [(f.name, f.action) for f in pv["files"]] == [("input.txt", "conflict"), ("output.txt", "conflict"), ("25730.py", "keep")]
    pv2 = service.fetch_problem(settings, ID, "sim", FetchOptions(dry_run=True, force=True)).preview
    assert pv2["needs_force"] is False
    assert [f.action for f in pv2["files"]] == ["overwrite", "overwrite", "keep"]


def test_fetch_dry_run_skeleton_only(settings, stubs):
    pv = service.fetch_problem(settings, ID, "sim", FetchOptions(dry_run=True, skeleton_only=True)).preview
    assert [(f.name, f.action) for f in pv["files"]] == [("input.txt", "create_empty"), ("25730.py", "create")]


def test_fetch_dry_run_bad_topic_is_invalid_input(settings, stubs):
    with pytest.raises(InvalidInput):
        service.fetch_problem(settings, ID, "a/b", FetchOptions(dry_run=True))


# =============================================================================
# fetch_problem — 에러
# =============================================================================


@pytest.mark.parametrize("target", ["", "   ", None])
def test_fetch_empty_target(settings, stubs, target):
    with pytest.raises(InvalidInput):
        service.fetch_problem(settings, target, "sim")
    assert stubs["calls"] == []


@pytest.mark.parametrize("topic", ["", "  ", None])
def test_fetch_empty_topic(settings, stubs, topic):
    with pytest.raises(InvalidInput):
        service.fetch_problem(settings, ID, topic)
    assert stubs["calls"] == []


def test_fetch_bad_target_before_login(settings, stubs):
    with pytest.raises(InvalidInput):
        service.fetch_problem(settings, "not-an-id", "sim")
    assert stubs["calls"] == []


def test_fetch_bad_topic_is_invalid_input(settings, stubs):
    with pytest.raises(InvalidInput, match="문자"):
        service.fetch_problem(settings, ID, "a:b")


def test_fetch_lookup_failure_propagates(settings, stubs):
    with pytest.raises(InvalidInput, match="99999"):
        service.fetch_problem(settings, "99999", "sim")


@pytest.mark.parametrize("exc", [ProblemNotFound("nf"), NetworkError("net"), LoginFailed("lf")])
def test_fetch_page_errors_propagate_unchanged(settings, stubs, exc):
    stubs["page"] = exc
    with pytest.raises(type(exc)):
        service.fetch_problem(settings, ID, "sim")
    assert not (settings.root / "sim").exists()


def test_fetch_download_error_writes_nothing(settings, stubs):
    stubs["downloads"]["out"] = NetworkError("dl")
    with pytest.raises(NetworkError):
        service.fetch_problem(settings, ID, "sim")
    assert not (settings.root / "sim").exists()


def test_fetch_login_error_propagates(settings, monkeypatch):
    def bad(settings):
        raise LoginFailed("nope")

    monkeypatch.setattr(service.auth, "get_session", bad)
    with pytest.raises(LoginFailed):
        service.fetch_problem(settings, ID, "sim")


# =============================================================================
# verify_login / is_session_cached
# =============================================================================


def test_verify_login(settings, stubs):
    msgs: list[str] = []
    out = service.verify_login(settings, msgs.append)
    assert DUMMY_ID in out and "get_session" in stubs["calls"]
    assert msgs[-1] == out


def test_is_session_cached(settings):
    assert service.is_session_cached(settings) is False
    settings.session_file.write_text("{}")
    assert service.is_session_cached(settings) is True


# =============================================================================
# list_topics / list_recent / read_skeleton_title
# =============================================================================


def test_list_topics(settings):
    for n in ("b", "a", ".hidden"):
        (settings.root / n).mkdir()
    (settings.root / "file.txt").write_text("")
    assert service.list_topics(settings) == ["a", "b"]
    assert service.list_topics(settings.root) == ["a", "b"]
    assert service.list_topics(settings.root / "nope") == []


def test_read_skeleton_title(tmp_path):
    p = tmp_path / "1.py"
    p.write_text("# 25730. 항아리 게임\nimport sys\n", encoding="utf-8")
    assert service.read_skeleton_title(p) == "항아리 게임"
    p.write_text("# 25730.\n", encoding="utf-8")
    assert service.read_skeleton_title(p) is None
    p.write_text("print(1)\n", encoding="utf-8")
    assert service.read_skeleton_title(p) is None
    assert service.read_skeleton_title(tmp_path / "missing.py") is None


def _make_problem(root: Path, topic: str, num: int, title: str | None, mtime: float) -> Path:
    d = root / topic / str(num)
    d.mkdir(parents=True)
    py = d / f"{num}.py"
    py.write_text(f"# {num}. {title}\n" if title else "", encoding="utf-8")
    (d / "input.txt").write_text("x")
    for p in (d, py, d / "input.txt"):
        os.utime(p, (mtime, mtime))
    return d


def test_list_recent_sorted_by_mtime_and_limited(settings):
    base = time.time() - 10_000
    _make_problem(settings.root, "sim", 1, "old", base)
    _make_problem(settings.root, "bfs", 2, "mid", base + 100)
    _make_problem(settings.root, "sim", 3, None, base + 200)
    (settings.root / "sim" / "notes").mkdir()  # 숫자 아닌 폴더 무시
    (settings.root / "sim" / "4").write_text("file, not dir")
    items = service.list_recent(settings)
    assert [(i.num, i.topic, i.title) for i in items] == [(3, "sim", None), (2, "bfs", "mid"), (1, "sim", "old")]
    assert items[0].path == settings.root / "sim" / "3"
    assert items[0].saved_at > items[1].saved_at
    assert [i.num for i in service.list_recent(settings.root, limit=2)] == [3, 2]


def test_list_recent_empty(settings):
    assert service.list_recent(settings) == []


# =============================================================================
# write_env / quote_env / logout
# =============================================================================


@pytest.mark.parametrize(
    "value",
    ["plain", "C:\\Users\\me\\Desktop\\swea", "C:/with space/x", "has#hash", "a=b", 'q"uote', "it's", " lead", "한글 경로"],
)
def test_quote_env_roundtrips_through_dotenv(tmp_path, value):
    f = tmp_path / ".env"
    f.write_text(f"K={service.quote_env(value)}\n", encoding="utf-8")
    assert dotenv_values(f)["K"] == value


def test_write_env_roundtrip(config_dir, root_dir, fake_keyring):
    env = service.write_env(config_dir / "deep", root_dir, f" {DUMMY_ID} ", "in.txt", "out.txt")
    assert env == config_dir / "deep" / ".env"
    v = config.read_env_file(config_dir / "deep")
    assert v == {"SWEA_ROOT": str(root_dir), "SWEA_ID": DUMMY_ID, "SWEA_INPUT_NAME": "in.txt", "SWEA_OUTPUT_NAME": "out.txt"}
    assert "SWEA_PW" not in env.read_text(encoding="utf-8")
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = "pw"
    s = config.load_settings(config_dir / "deep")
    assert (s.root, s.user_id, s.input_name) == (root_dir, DUMMY_ID, "in.txt")


def test_write_env_overwrites_and_drops_old_password_line(config_dir, root_dir):
    (config_dir / ".env").write_text("SWEA_PW=plain\nSWEA_ROOT=old\n", encoding="utf-8")
    service.write_env(config_dir, root_dir, DUMMY_ID)
    assert "SWEA_PW" not in (config_dir / ".env").read_text(encoding="utf-8")


def test_logout_session_only(config_dir, fake_keyring):
    (config_dir / "session.json").write_text("{}")
    (config_dir / "login_state.json").write_text("{}")
    (config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n")
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = "pw"
    removed = service.logout(config_dir)
    assert removed == ["session.json", "login_state.json"]
    assert (config_dir / ".env").exists() and fake_keyring.store


def test_logout_all_removes_env_and_credential(config_dir, fake_keyring):
    (config_dir / "session.json").write_text("{}")
    (config_dir / ".env").write_text(f"SWEA_ID={DUMMY_ID}\n")
    fake_keyring.store[(config.KEYRING_SERVICE, DUMMY_ID)] = "pw"
    removed = service.logout(config_dir, all_=True)
    assert removed == [f"자격 증명({DUMMY_ID})", "session.json", ".env"]
    assert fake_keyring.store == {} and not (config_dir / ".env").exists()


def test_logout_nothing_to_remove(config_dir):
    assert service.logout(config_dir, all_=True) == []


def test_logout_all_without_env_skips_keyring(config_dir, fake_keyring):
    service.logout(config_dir, all_=True)
    assert fake_keyring.calls == []
