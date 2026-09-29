"""mcp_server: SDK 필요 (없으면 건너뜀). 인메모리 클라이언트 + stdio 서브프로세스 스모크. 네트워크·실계정 없음."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

import anyio  # noqa: E402

from swea_fetcher.mcp_server import build_server  # noqa: E402
from swea_fetcher.mcp_tools import SweaTools  # noqa: E402

TOOLS = {"swea_status", "swea_fetch", "swea_preview", "swea_list_topics", "swea_list_recent"}
ALLOWED_ARGS = {"check_login", "problem", "topic", "force", "skeleton_only", "refresh_index", "limit"}
READ_ONLY = TOOLS - {"swea_fetch"}


def _list_tools(tmp_path):
    from mcp.client import Client

    async def run():
        async with Client(build_server(SweaTools(config_dir=tmp_path))) as c:
            return (await c.list_tools()).tools

    return anyio.run(run)


def test_tool_names_schema_and_annotations(tmp_path):
    tools = _list_tools(tmp_path)
    assert {t.name for t in tools} == TOOLS and len(tools) == 5
    for t in tools:
        assert set(t.input_schema.get("properties", {})) <= ALLOWED_ARGS
        assert t.annotations is not None
        assert t.annotations.read_only_hint is (t.name in READ_ONLY)


def test_in_memory_call_roundtrip(tmp_path, monkeypatch, root_dir):
    from mcp.client import Client

    (tmp_path / ".env").write_text(f"SWEA_ROOT={root_dir}\nSWEA_ID=dummy_user\n", encoding="utf-8")
    monkeypatch.setenv("SWEA_PW", "dummy-pw-1234")
    (root_dir / "DFS1").mkdir()

    async def run():
        async with Client(build_server(SweaTools(config_dir=tmp_path))) as c:
            return await c.call_tool("swea_list_topics", {})

    res = anyio.run(run)
    data = res.structured_content
    assert data["ok"] is True and data["topics"] == ["DFS1"]


def test_stdio_subprocess_smoke(tmp_path):
    """설정 없이 기동, initialize -> tools/list. stdout 의 모든 줄이 JSON-RPC 여야 한다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SWEA_")}
    env["PYTHONPATH"] = str(Path(__file__).parents[1])
    env["USERPROFILE"] = env["HOME"] = str(tmp_path)  # 실제 ~/.swea-fetch 를 읽지 않게
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    p = subprocess.run(
        [sys.executable, "-m", "swea_fetcher.mcp_server"],
        input="".join(json.dumps(m) + "\n" for m in msgs).encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=60,
    )
    lines = [ln for ln in p.stdout.decode("utf-8").splitlines() if ln.strip()]
    parsed = [json.loads(ln) for ln in lines]  # JSON 이 아니면 여기서 실패
    assert all(m.get("jsonrpc") == "2.0" for m in parsed)
    by_id = {m["id"]: m for m in parsed if "id" in m}
    assert by_id[1]["result"]["serverInfo"]["name"] == "swea"
    assert {t["name"] for t in by_id[2]["result"]["tools"]} == TOOLS
