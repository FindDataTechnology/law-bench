"""Admin-assistant chat proxy: ``/copilotkit`` -> the CopilotKit runtime.

The floating assistant's browser island talks to this same-origin route with
the workbench session cookie; this module is the ONLY public path to the
runtime (change ``add-admin-copilot-assistant``). The whole router is gated by
``require_scope("admin")`` — unauthenticated requests 401 and non-admin
sessions 403 before anything is forwarded, so the runtime itself can stay
ClusterIP-only behind no auth of its own.

Forwarding is streaming (``aiter_raw``), not buffered: CopilotKit speaks a
streaming GraphQL protocol and tool loops (e.g. ``compare_run``) can run for
minutes, so read/write timeouts are raised accordingly. Request cookies and
credentials are stripped — the runtime trusts nothing about the caller; the
scope check above is the entire gate.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from ..auth.deps import require_scope
from ...settings import COPILOT_RUNTIME_URL

router = APIRouter(tags=["assistant"], dependencies=[Depends(require_scope("admin"))])

# compare_run / contract generation over chat can legitimately run for many
# minutes; the proxy must not cut a live stream.
_TIMEOUT = httpx.Timeout(connect=10.0, read=900.0, write=900.0, pool=10.0)

# Connection-scoped headers must not cross the proxy boundary (RFC 9110 §7.6.1)
# plus the workbench's own credentials, which are meaningless to the runtime.
_DROPPED_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "trailer",
    "upgrade",
    "cookie",
    "authorization",
    "x-api-key",
}
_DROPPED_RESPONSE_HEADERS = {
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
}


def _build_client() -> httpx.AsyncClient:
    """Factory so tests can swap in an ``httpx.MockTransport``-based client."""
    return httpx.AsyncClient(timeout=_TIMEOUT)


def _forward_headers(request: Request) -> dict[str, str]:
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _DROPPED_REQUEST_HEADERS
    }


def _response_headers(upstream: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() not in _DROPPED_RESPONSE_HEADERS
    }


async def _cleanup(upstream: httpx.Response, client: httpx.AsyncClient) -> None:
    await upstream.aclose()
    await client.aclose()


@router.api_route(
    "/copilotkit",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    response_model=None,
)
@router.api_route(
    "/copilotkit/{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    response_model=None,
)
async def copilot_proxy(request: Request, rest: str = "") -> StreamingResponse | JSONResponse:
    """Stream the request to the runtime and its response back, unbuffered."""
    if not COPILOT_RUNTIME_URL:
        return JSONResponse(
            status_code=503,
            content={"error": "assistant runtime not configured (COPILOT_RUNTIME_URL unset)"},
        )
    target = f"{COPILOT_RUNTIME_URL}/copilotkit"
    if rest:
        target = f"{target}/{rest}"

    client = _build_client()
    upstream_request = client.build_request(
        request.method,
        target,
        headers=_forward_headers(request),
        content=await request.body(),
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"error": f"assistant runtime unreachable: {exc}"},
        )
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=_response_headers(upstream),
        background=BackgroundTask(_cleanup, upstream, client),
    )
