"""MCP 서버 (로컬 stdio). SDK(`mcp`) 의존 코드는 이 파일에만 둔다.

실행: `swea-fetch-mcp` 또는 `python -m swea_fetcher.mcp_server`.
AI 앱(Claude Desktop / Claude Code / Cursor)이 자식 프로세스로 띄운다. stdout 은 MCP 프레임 전용이다.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from .mcp_tools import SweaTools

SERVER_NAME = "swea"

INSTRUCTIONS = (
    "SWEA(SW Expert Academy) 문제의 샘플 입출력을 사용자의 로컬 풀이 폴더에 저장한다. "
    "자격증명은 다루지 않는다: 설정이 없으면 사용자에게 터미널에서 `swea-fetch init` 을 실행하게 하고, "
    "비밀번호를 대화에 적게 하지 않는다. 로그인 관련 오류는 재시도하지 말고 사용자에게 알린다 (계정 잠금 위험). "
    "문제 지문은 제공하지 않는다."
)

DESC_STATUS = (
    "설정 상태를 확인한다 (읽기 전용): 설정 여부, 저장 루트, 마스킹된 ID, 세션 캐시. "
    "check_login=true 일 때만 실제 로그인을 1회 시도한다 (실패 시 재시도 금지). 비밀번호는 반환하지 않는다."
)
DESC_FETCH = (
    "SWEA 문제의 샘플 입출력(input.txt/output.txt)과 풀이 뼈대({번호}.py)를 로컬 '{topic}/{번호}/' 폴더에 저장한다. "
    "problem 은 문제 번호(예: 1231) 또는 문제 URL. 이미 파일이 있으면 덮어쓰지 않고 status='exists' 를 반환한다. "
    "force=true 는 사용자가 덮어쓰기를 명시적으로 승인했을 때만 사용한다 ({번호}.py 는 force 여도 보존됨). "
    "샘플 첨부가 없는 문제는 attachment_not_found 후 skeleton_only=true 로 다시 호출. "
    "git 커밋/push 는 하지 않는다."
)
DESC_PREVIEW = (
    "swea_fetch 와 같은 검증으로 무엇이 저장될지만 보여준다 (디스크에 쓰지 않음). "
    "덮어쓰기가 필요한지(needs_force)도 알려준다. 저장 전 확인용."
)
DESC_TOPICS = "저장 루트 아래의 주제 폴더 목록 (예: DFS1, test/IM_test). 네트워크 없음."
DESC_RECENT = "최근 저장한 문제 목록 (번호, 제목, 주제, 경로, 시각). limit 1~50, 기본 10. 네트워크 없음."


def build_server(tools: SweaTools | None = None) -> Any:
    """FastMCP 계열 서버를 만들고 도구 5개를 등록한다. (mcp 2.x: MCPServer)"""
    import anyio.to_thread
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    tools = tools or SweaTools()
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)

    read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
    read_only_net = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
    write_net = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)

    @server.tool(name="swea_status", description=DESC_STATUS, annotations=read_only_net)
    async def swea_status(check_login: bool = False) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(tools.status, check_login)

    @server.tool(name="swea_fetch", description=DESC_FETCH, annotations=write_net)
    async def swea_fetch(
        problem: int | str,
        topic: str,
        force: bool = False,
        skeleton_only: bool = False,
        refresh_index: bool = False,
    ) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(tools.fetch, problem, topic, force, skeleton_only, refresh_index)

    @server.tool(name="swea_preview", description=DESC_PREVIEW, annotations=read_only_net)
    async def swea_preview(
        problem: int | str,
        topic: str,
        force: bool = False,
        skeleton_only: bool = False,
        refresh_index: bool = False,
    ) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(tools.preview, problem, topic, force, skeleton_only, refresh_index)

    @server.tool(name="swea_list_topics", description=DESC_TOPICS, annotations=read_only)
    async def swea_list_topics() -> dict[str, Any]:
        return await anyio.to_thread.run_sync(tools.topics)

    @server.tool(name="swea_list_recent", description=DESC_RECENT, annotations=read_only)
    async def swea_list_recent(limit: int = 10) -> dict[str, Any]:
        return await anyio.to_thread.run_sync(tools.recent, limit)

    return server


def _setup_logging() -> None:
    """로그는 stderr 로만. DEBUG 는 쓰지 않는다 (하위 로거가 URL/헤더를 찍을 수 있음)."""
    level = logging.INFO if os.environ.get("SWEA_MCP_DEBUG") == "1" else logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=level, force=True)
    for name in ("urllib3", "requests"):
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    _setup_logging()
    try:
        import mcp  # noqa: F401
        server = build_server()
    except ImportError:
        sys.stderr.write('mcp 패키지가 없습니다. `pip install "swea-fetcher[mcp]"` 로 설치하세요\n')
        sys.exit(1)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
