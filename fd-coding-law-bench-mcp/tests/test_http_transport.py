"""Hermetic tests for the streamable-HTTP transport + shared-token guard.

No DB / LLM / external network: tool listing never touches ``src.*``, and the
HTTP tests drive the ASGI app in memory (``httpx.ASGITransport``) with the
real FastMCP client stack, so no socket is bound.
"""

from __future__ import annotations

import httpx
import pytest

from fd_coding_law_bench_mcp.server import (
    _TokenGuard,
    _extract_access_token,
    main,
    mcp,
)

TOKEN = "hermetic-shared-token"


# ---------------------------------------------------------------------------
# Transport selection (main)


def _run_with(monkeypatch, **env):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(mcp, "run", fake_run)
    for key in ("MCP_HTTP_TRANSPORT", "MCP_HTTP_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return calls


def test_stdio_is_the_default_transport(monkeypatch):
    calls = _run_with(monkeypatch)
    main()
    assert calls


def test_stdio_explicit(monkeypatch):
    calls = _run_with(monkeypatch, MCP_HTTP_TRANSPORT="stdio")
    main()
    assert calls


def test_http_without_token_refuses_to_start(monkeypatch):
    _run_with(monkeypatch, MCP_HTTP_TRANSPORT="http")
    with pytest.raises(SystemExit, match="MCP_HTTP_TOKEN"):
        main()


def test_http_blank_token_refuses_to_start(monkeypatch):
    _run_with(monkeypatch, MCP_HTTP_TRANSPORT="http", MCP_HTTP_TOKEN="   ")
    with pytest.raises(SystemExit, match="MCP_HTTP_TOKEN"):
        main()


def test_http_unsupported_transport_value(monkeypatch):
    _run_with(monkeypatch, MCP_HTTP_TRANSPORT="websocket")
    with pytest.raises(SystemExit, match="Unsupported MCP_HTTP_TRANSPORT"):
        main()


# ---------------------------------------------------------------------------
# Header extraction


def _headers(**kv: str) -> list[tuple[bytes, bytes]]:
    return [(k.lower().encode(), v.encode()) for k, v in kv.items()]


def test_extract_bearer_header():
    assert _extract_access_token(_headers(Authorization=f"Bearer {TOKEN}")) == TOKEN


def test_extract_api_key_header():
    assert _extract_access_token(_headers(**{"X-API-Key": TOKEN})) == TOKEN


def test_extract_bearer_wins_over_api_key():
    hdrs = _headers(Authorization=f"Bearer {TOKEN}", **{"X-API-Key": "other"})
    assert _extract_access_token(hdrs) == TOKEN


def test_extract_malformed_bearer_falls_back_to_api_key():
    hdrs = _headers(Authorization="Basic dXNlcjpwYXNz", **{"X-API-Key": TOKEN})
    assert _extract_access_token(hdrs) == TOKEN


def test_extract_no_headers():
    assert _extract_access_token([]) is None


# ---------------------------------------------------------------------------
# Guard ASGI behavior (dummy downstream app records invocation)


class _DummyApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True


def _http_scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {"type": "http", "method": "GET", "path": "/mcp", "headers": headers}


def _capture_send():
    messages = []

    async def send(message):
        messages.append(message)

    return messages, send


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_guard_rejects_missing_token_before_dispatch():
    dummy = _DummyApp()
    messages, send = _capture_send()
    await _TokenGuard(dummy, TOKEN)(_http_scope([]), _receive, send)
    assert not dummy.called
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_guard_rejects_wrong_token_before_dispatch():
    dummy = _DummyApp()
    messages, send = _capture_send()
    scope = _http_scope(_headers(Authorization="Bearer wrong-token"))
    await _TokenGuard(dummy, TOKEN)(scope, _receive, send)
    assert not dummy.called
    assert messages[0]["status"] == 401


@pytest.mark.asyncio
async def test_guard_forwards_valid_bearer_token():
    dummy = _DummyApp()
    _, send = _capture_send()
    scope = _http_scope(_headers(Authorization=f"Bearer {TOKEN}"))
    await _TokenGuard(dummy, TOKEN)(scope, _receive, send)
    assert dummy.called


@pytest.mark.asyncio
async def test_guard_forwards_valid_api_key_header():
    dummy = _DummyApp()
    _, send = _capture_send()
    scope = _http_scope(_headers(**{"X-API-Key": TOKEN}))
    await _TokenGuard(dummy, TOKEN)(scope, _receive, send)
    assert dummy.called


@pytest.mark.asyncio
async def test_guard_passes_non_http_scopes_through():
    dummy = _DummyApp()
    _, send = _capture_send()
    await _TokenGuard(dummy, TOKEN)({"type": "lifespan"}, _receive, send)
    assert dummy.called


# ---------------------------------------------------------------------------
# Protocol-level: the HTTP app advertises exactly the stdio tool set


async def _list_tools_via_memory_client() -> set[str]:
    from fastmcp import Client

    async with Client(mcp) as client:
        return {tool.name for tool in await client.list_tools()}


async def _list_tools_via_http_asgi(token: str) -> set[str]:
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    wrapped = _TokenGuard(
        mcp.http_app(transport="http", json_response=True, stateless_http=True),
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
    # The in-memory ASGI transport never runs the app's lifespan, and the
    # streamable-HTTP session manager refuses requests before its startup
    # runs — enter it explicitly around the client session.
    async with starlette_app.router.lifespan_context(starlette_app):
        async with Client(transport) as client:
            return {tool.name for tool in await client.list_tools()}


@pytest.mark.asyncio
async def test_http_advertises_the_stdio_tool_set():
    stdio_tools = await _list_tools_via_memory_client()
    assert stdio_tools, "stdio registration must not be empty"
    http_tools = await _list_tools_via_http_asgi(TOKEN)
    assert http_tools == stdio_tools
