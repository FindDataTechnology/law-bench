"""Tests for the in-process token-bucket rate limiter (OpenSpec task 3.3).

Two levels of coverage:

- **Unit** (minimal FastAPI + an injected tiny limiter): an over-limit caller
  receives ``429`` with a ``Retry-After`` header and a ``retry_after`` body
  field; an under-limit caller receives ``200``. A *different* caller is NOT
  throttled by the first caller's exhaustion (per-caller bucket), and
  ``/healthz`` is exempt even when the bucket is empty. The limiter is
  injected directly via the ``limiter`` parameter so the test does not depend
  on env defaults (``RATE_LIMIT_ENABLED`` is off in the test env).

- **Integration** (real ``create_public_app`` with the rate-limit module
  globals monkeypatched on + a tiny rps/burst): a valid API key's first
  request passes both auth and the limiter (``200``); the same key's
  immediate second request is throttled to ``429`` with ``Retry-After`` —
  confirming the middleware is wired into the public factory and that
  legitimate under-limit traffic is not broken. The limiter runs *before*
  auth (outermost middleware), so an over-limit caller is throttled regardless
  of whether the key would have validated.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.web.auth import apikey
from src.web.deps import get_db
from src.web.public_app import create_public_app
from src.web.rate_limit import TokenBucketLimiter, add_rate_limit_middleware


def _tiny_app() -> FastAPI:
    """Minimal FastAPI app with an injected tiny limiter (burst=1, ~0 rps).

    No auth — the limiter is the only gate. ``/healthz`` is included to verify
    the probe-path exemption. The limiter is passed explicitly so the
    ``RATE_LIMIT_ENABLED`` env gate is bypassed (the test runs with it off).
    """
    app = FastAPI()

    @app.get("/ping", include_in_schema=False)
    async def _ping():
        return {"ok": True}

    @app.get("/healthz", include_in_schema=False)
    async def _hz():
        return JSONResponse({"status": "ok"})

    # burst=1 + rps=0.01 -> the 2nd immediate request from the same caller is
    # always over-limit (the bucket cannot refill a whole token in time).
    add_rate_limit_middleware(app, limiter=TokenBucketLimiter(rps=0.01, burst=1))
    return app


def test_under_limit_200_over_limit_429_with_retry_after():
    """Core assertion: under-limit -> 200, over-limit -> 429 + Retry-After."""
    client = TestClient(_tiny_app())
    headers = {"X-API-Key": "lbk_testcaller01"}  # 17 chars; prefix = first 16

    r1 = client.get("/ping", headers=headers)
    assert r1.status_code == 200, r1.text

    r2 = client.get("/ping", headers=headers)
    assert r2.status_code == 429, r2.text
    # Retry-After header (case-insensitive) is a whole-second count.
    lower_headers = {k.lower(): v for k, v in r2.headers.items()}
    assert "retry-after" in lower_headers
    assert int(lower_headers["retry-after"]) >= 1
    # Body carries the machine-readable hint too.
    body = r2.json()
    assert body["retry_after"] >= 1
    assert "rate limit exceeded" in body["error"]


def test_per_caller_isolation():
    """Caller A exhausting the bucket does NOT throttle caller B."""
    client = TestClient(_tiny_app())
    a = {"X-API-Key": "lbk_callerA0000001"}
    b = {"X-API-Key": "lbk_callerB0000001"}

    # Exhaust caller A's bucket (burst=1: first ok, second over).
    assert client.get("/ping", headers=a).status_code == 200
    assert client.get("/ping", headers=a).status_code == 429

    # Caller B has its own bucket -> still 200.
    assert client.get("/ping", headers=b).status_code == 200


def test_healthz_exempt_when_over_limit():
    """The liveness/readiness probe path is never 429'd (task 6.4)."""
    client = TestClient(_tiny_app())
    headers = {"X-API-Key": "lbk_probe00000001"}

    # Exhaust the bucket on /ping.
    assert client.get("/ping", headers=headers).status_code == 200
    assert client.get("/ping", headers=headers).status_code == 429

    # /healthz is exempt even though the caller's bucket is empty.
    assert client.get("/healthz", headers=headers).status_code == 200
    # ...and still exempt with no key at all (anonymous probe).
    assert client.get("/healthz").status_code == 200


def test_public_app_throttles_repeat_valid_key(monkeypatch, seeded_db):
    """Integration: the wired-in limiter throttles a valid key's 2nd request.

    The limiter is constructed inside ``create_public_app()`` from the
    ``src.web.rate_limit`` module globals, so we monkeypatch
    ``RATE_LIMIT_ENABLED``/``RPS``/``BURST`` on that module BEFORE constructing
    the app. A valid key's first request passes auth + limiter (200); the
    second (same caller bucket, now empty) is throttled to 429 + Retry-After
    before auth even runs.

    ``create_key`` is a direct DB call (not an HTTP request) so it does not
    consume a limiter token; the first ``client.get`` is the limiter's first
    sight of this caller. The key resolves via the shared session-DB connection
    established by ``seeded_db`` (same pattern as test_apikey_readonly's HTTP
    tests).
    """
    import src.web.rate_limit as rl

    monkeypatch.setattr(rl, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rl, "RATE_LIMIT_RPS", 0.01)
    monkeypatch.setattr(rl, "RATE_LIMIT_BURST", 1)

    app = create_public_app()
    app.dependency_overrides[get_db] = lambda: seeded_db
    with TestClient(app) as client:
        plaintext = apikey.create_key("rl-user", "rate-int", ["*"])
        headers = {"X-API-Key": plaintext}

        r1 = client.get("/api/contracts/sale", headers=headers)
        assert r1.status_code == 200, r1.text

        r2 = client.get("/api/contracts/sale", headers=headers)
        assert r2.status_code == 429, r2.text
        lower_headers = {k.lower(): v for k, v in r2.headers.items()}
        assert "retry-after" in lower_headers
        assert int(lower_headers["retry-after"]) >= 1
        assert r2.json()["retry_after"] >= 1
