"""HTTP client for the law-api gateway.

Endpoints (gateway contract, see docs/law-catalog-runbook.md §法语义检索):
  POST /v1/search      {query, top_k, ...}   -> ranked chunks, each carrying
                          law_id / title / chunk_text / law_status
  GET  /v1/laws/{id}   assembled full text + law_status

Responses are normalized defensively: hits may be flat or nest their fields
under ``payload`` (the gateway's chunk payloads mirror the JSONL export
shape). ``law_id`` values are treated as OPAQUE STRINGS everywhere — the
JSONL/Qdrant layer uses string ids and numeric coercion is a known trap.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import httpx

from src.settings import (
    LAW_API_BASE_URL,
    LAW_API_KEY,
    LAW_API_MIN_INTERVAL,
    LAW_SEARCH_ENABLED,
)

logger = logging.getLogger("law_api")

# The gateway's key-auth plugin expects the key in this header.
_KEY_HEADER = "apikey"

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Shared httpx client + pacing state (law-api is rate-limited at 10 r/s; we
# pace ourselves instead of reacting to 429s).
_lock = threading.Lock()
_client: Optional[httpx.Client] = None
_last_request_at = 0.0


def enabled() -> bool:
    """True when the law search feature is on (switch AND key)."""
    return bool(LAW_SEARCH_ENABLED and LAW_API_KEY)


def _get_client() -> httpx.Client:
    global _client
    with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(base_url=LAW_API_BASE_URL.rstrip("/"), timeout=_TIMEOUT)
        return _client


def _auth_headers() -> dict:
    """Per-request auth header — survives key rotation and test-injected clients."""
    return {_KEY_HEADER: LAW_API_KEY} if LAW_API_KEY else {}


def _pace() -> None:
    """Enforce the configured minimum interval between law-api requests."""
    global _last_request_at
    with _lock:
        wait = LAW_API_MIN_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _log_http_failure(op: str, resp: Optional[httpx.Response], err: Optional[Exception]) -> None:
    if err is not None:
        logger.error("law-api %s failed: %s: %s", op, type(err).__name__, err)
        return
    snippet = (resp.text or "")[:200] if resp is not None else ""
    logger.error("law-api %s returned HTTP %s: %s", op, resp.status_code if resp else "?", snippet)


def _merge_hit(hit: dict) -> dict:
    """Accept flat hits or payload-nested hits (both seen in the gateway)."""
    payload = hit.get("payload") if isinstance(hit.get("payload"), dict) else {}
    return {**hit, **payload}


def search(query: str, top_k: int = 5, client: Optional[httpx.Client] = None) -> list[dict]:
    """Semantic search over the 法规库 corpus.

    Returns normalized hits: ``{law_id (str), title, chunk_text, law_status,
    score}`` — ``[]`` when disabled or on any failure.
    """
    if not enabled():
        return []
    c = client or _get_client()
    _pace()
    try:
        resp = c.post("/search", json={"query": query, "top_k": top_k}, headers=_auth_headers())
    except Exception as err:  # noqa: BLE001 - degradation contract
        _log_http_failure("search", None, err)
        return []
    if resp.status_code != 200:
        _log_http_failure("search", resp, None)
        return []
    try:
        body = resp.json()
        raw_hits = body.get("hits", body.get("results", body if isinstance(body, list) else []))
        hits = [_merge_hit(h) for h in raw_hits]
        return [
            {
                "law_id": str(h.get("law_id")) if h.get("law_id") is not None else None,
                "title": h.get("title"),
                "chunk_text": h.get("chunk_text") or h.get("text") or "",
                "law_status": h.get("law_status") or h.get("status"),
                "score": h.get("score"),
            }
            for h in hits
        ]
    except Exception as err:  # noqa: BLE001 - unexpected payload shape
        _log_http_failure("search parse", resp, err)
        return []


_FULL_TEXT_KEYS = ("content", "full_text", "text", "body")
_STATUS_KEYS = ("law_status", "status")


def get_law(law_id: str, client: Optional[httpx.Client] = None) -> Optional[dict]:
    """Fetch a law's assembled full text by its (opaque string) id.

    Returns ``{law_id (str), title, status, full_text}`` or ``None`` on any
    failure. ``law_id`` is never coerced to a number.
    """
    if not enabled():
        return None
    c = client or _get_client()
    _pace()
    try:
        resp = c.get(f"/laws/{law_id}", headers=_auth_headers())
    except Exception as err:  # noqa: BLE001
        _log_http_failure(f"laws/{law_id}", None, err)
        return None
    if resp.status_code != 200:
        _log_http_failure(f"laws/{law_id}", resp, None)
        return None
    try:
        body = resp.json()
        if isinstance(body, dict) and isinstance(body.get("law"), dict):
            body = body["law"]
        full_text = next((body[k] for k in _FULL_TEXT_KEYS if body.get(k)), None)
        if not full_text:
            raise ValueError(f"no full-text field in response keys {list(body)}")
        return {
            "law_id": str(body.get("law_id", law_id)),
            "title": body.get("title"),
            "status": next((body[k] for k in _STATUS_KEYS if body.get(k)), None),
            "full_text": full_text,
        }
    except Exception as err:  # noqa: BLE001
        _log_http_failure(f"laws/{law_id} parse", resp, err)
        return None


# Fixed probe query for the enable-time smoke check (D6): this query is known
# to hit 婚姻家庭编解释（一）第42条 in the v2 collection.
_SMOKE_QUERY = "民法典 离婚后子女抚养费"
_SMOKE_MUST_INCLUDE = "抚养"


def smoke(client: Optional[httpx.Client] = None) -> bool:
    """One fixed search through the whole chain (auth + gateway + retrieval).

    Called once per process before the first real use; a failure logs ERROR
    and keeps the feature degraded for this process (never blocks startup).
    """
    hits = search(_SMOKE_QUERY, top_k=3, client=client)
    ok = any(_SMOKE_MUST_INCLUDE in (h.get("chunk_text") or "") for h in hits)
    if not ok:
        logger.error(
            "law-api smoke check failed: query %r returned %d hits without %r — "
            "law search stays degraded for this process",
            _SMOKE_QUERY, len(hits), _SMOKE_MUST_INCLUDE,
        )
    else:
        logger.info("law-api smoke check passed (%d hits)", len(hits))
    return ok


# Process-wide first-use smoke (design D6): the crew tool calls this before its
# first real query. A failed check degrades law search for the whole process —
# better "" than silently-wrong statute context. Thread-safe: crew agents can
# run concurrently. Kept here (not in tool.py) so it is testable without the
# crewai dependency.
_smoke_lock = threading.Lock()
_smoke_state = {"done": False, "ok": False}


def reset_first_use_smoke() -> None:
    """Test hook: forget the cached verdict so the next call re-smokes."""
    with _smoke_lock:
        _smoke_state.update(done=False, ok=False)


def first_use_smoke() -> bool:
    """Run :func:`smoke` once per process; cache the verdict."""
    with _smoke_lock:
        if not _smoke_state["done"]:
            _smoke_state["ok"] = smoke()
            _smoke_state["done"] = True
        return _smoke_state["ok"]
