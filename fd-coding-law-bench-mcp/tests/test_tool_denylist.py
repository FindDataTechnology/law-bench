"""Hermetic tests for ``MCP_TOOL_DENYLIST`` tool exclusion.

No DB / LLM / external network: denylist behavior is exercised on scratch
FastMCP servers (never on the shared module-level ``mcp``, whose registry is
mutated destructively and is asserted complete by other test modules), plus a
read-only check that the production denylist names still exist.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastmcp import Client, FastMCP

from fd_coding_law_bench_mcp.server import (
    _TokenGuard,
    apply_tool_denylist,
    main,
    mcp,
)

#: Exactly the denylist the assistant-facing deployment runs with.
ASSISTANT_DENYLIST = "clause_delete,rubric_delete,criterion_delete,prompt_delete"

TOKEN = "hermetic-shared-token"


def _scratch_server() -> FastMCP:
    s = FastMCP("scratch")

    @s.tool
    def alpha() -> str:
        return "a"

    @s.tool
    def beta() -> str:
        return "b"

    return s


def _listed_sync(server: FastMCP) -> set[str]:
    async def _list() -> set[str]:
        async with Client(server) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(_list())


# ---------------------------------------------------------------------------
# apply_tool_denylist


def test_unset_denylist_is_a_noop(monkeypatch):
    monkeypatch.delenv("MCP_TOOL_DENYLIST", raising=False)
    server = _scratch_server()
    assert apply_tool_denylist(server) == set()
    assert _listed_sync(server) == {"alpha", "beta"}


def test_blank_denylist_is_a_noop(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", " , ")
    server = _scratch_server()
    assert apply_tool_denylist(server) == set()
    assert _listed_sync(server) == {"alpha", "beta"}


def test_denylist_removes_named_tools_from_listing(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "beta")
    server = _scratch_server()
    assert apply_tool_denylist(server) == {"beta"}
    assert _listed_sync(server) == {"alpha"}


def test_denylist_tolerates_whitespace(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", " beta , alpha ")
    server = _scratch_server()
    assert apply_tool_denylist(server) == {"alpha", "beta"}
    assert _listed_sync(server) == set()


@pytest.mark.asyncio
async def test_removed_tool_is_not_invocable(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "beta")
    server = _scratch_server()
    apply_tool_denylist(server)
    async with Client(server) as client:
        with pytest.raises(Exception, match="(?i)unknown tool"):
            await client.call_tool("beta", {})


def test_unknown_denylist_entry_fails_loud(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "alpha,ghost_tool")
    server = _scratch_server()
    with pytest.raises(SystemExit, match="ghost_tool"):
        apply_tool_denylist(server)


def test_main_applies_the_denylist(monkeypatch):
    """``main`` wires the denylist in before transport dispatch (stdio path)."""
    calls = []
    monkeypatch.setattr(
        "fd_coding_law_bench_mcp.server.apply_tool_denylist",
        lambda server=None: calls.append(server) or set(),
    )
    monkeypatch.setattr(mcp, "run", lambda *a, **k: None)
    monkeypatch.delenv("MCP_HTTP_TRANSPORT", raising=False)
    monkeypatch.delenv("MCP_TOOL_DENYLIST", raising=False)
    main()
    assert calls == [None]  # called once; the function resolves None -> mcp


# ---------------------------------------------------------------------------
# The production denylist must track the real toolset (rename-rot guard)


@pytest.mark.asyncio
async def test_assistant_denylist_names_all_exist():
    registered = {tool.name for tool in await mcp.local_provider.list_tools()}
    missing = set(ASSISTANT_DENYLIST.split(",")) - registered
    assert not missing, f"denylist references tools that no longer exist: {missing}"


# ---------------------------------------------------------------------------
# HTTP transport: the denylisted app still authenticates and still hides tools


async def _list_tools_via_http_asgi(server: FastMCP, token: str) -> set[str]:
    from fastmcp.client.transports import StreamableHttpTransport

    wrapped = _TokenGuard(
        server.http_app(transport="http", json_response=True, stateless_http=True),
        token,
    )
    starlette_app = wrapped.app

    def factory(**kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=wrapped),
            base_url="http://lawbench-mcp.test",
            **kwargs,
        )

    transport = StreamableHttpTransport(
        "http://lawbench-mcp.test/mcp",
        headers={"X-API-Key": token},
        httpx_client_factory=factory,
    )
    # In-memory ASGI never runs the app's lifespan; enter it explicitly so the
    # streamable-HTTP session manager accepts requests.
    async with starlette_app.router.lifespan_context(starlette_app):
        async with Client(transport) as client:
            return {tool.name for tool in await client.list_tools()}


@pytest.mark.asyncio
async def test_http_app_with_denylist_hides_tools(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "beta")
    server = _scratch_server()
    apply_tool_denylist(server)
    http_tools = await _list_tools_via_http_asgi(server, TOKEN)
    assert http_tools == {"alpha"}


@pytest.mark.asyncio
async def test_http_app_still_rejects_missing_token(monkeypatch):
    """Direct ASGI probe: no token -> 401 from the guard, app never reached."""
    monkeypatch.setenv("MCP_TOOL_DENYLIST", "beta")
    server = _scratch_server()
    apply_tool_denylist(server)
    wrapped = _TokenGuard(server.http_app(transport="http"), TOKEN)

    messages: list[dict] = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/mcp", "headers": []}
    await wrapped(scope, receive, send)
    assert messages[0]["status"] == 401
