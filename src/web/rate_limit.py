"""In-process token-bucket rate limiter for the public API pod.

A dependency-light per-caller throttle: no Redis, no external state — just a
process-local dict of token buckets keyed by the caller's API-key prefix (or
the client IP for anonymous requests). Each bucket refills at
``RATE_LIMIT_RPS`` tokens/sec up to ``RATE_LIMIT_BURST`` capacity; every request
consumes one token; an empty bucket yields ``429 Too Many Requests`` with a
``Retry-After`` header (whole seconds until the next token is available).

Gated behind ``RATE_LIMIT_ENABLED`` (env, default ``"0"``) so the middleware is
active on the public pod and dormant on the origin: when unset/``"0"``,
:func:`add_rate_limit_middleware` returns without registering anything, so the
origin's request path is byte-for-byte unchanged. This is the *fallback*
posture — a gateway-level limiter (Caddy ``rate_limit`` / Nginx ``limit_req``)
in front of the pod is the preferred production shape (see
``docs/public-api-deploy.md``); the in-process limiter exists for the
no-gateway case so an abusive caller is never unthrottled even bare-metal.

``/healthz`` is exempt (task 6.4): liveness/readiness probes must not be 429'd,
or k8s would restart a healthy pod.

The limiter is installed as the outermost HTTP middleware (added after the
locale middleware), so it runs *before* auth — an invalid-credential caller
still consumes a token, which is the desired abuse posture (a cred-spray is
throttled regardless of whether the creds would have validated).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.settings import (
    RATE_LIMIT_BURST,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_MAX_BUCKETS,
    RATE_LIMIT_RPS,
)

# The liveness/readiness probe path is exempt from throttling so a healthy pod
# is never restarted by its own rate limit.
_EXEMPT_PATH = "/healthz"


class _Bucket:
    """One caller's token-bucket state (mutable, guarded by the limiter's lock)."""

    __slots__ = ("tokens", "last")

    def __init__(self, tokens: float, last: float) -> None:
        self.tokens = tokens
        self.last = last


class TokenBucketLimiter:
    """Thread-safe in-memory token-bucket rate limiter.

    Each distinct caller id (``"k:<key-prefix>"`` or ``"i:<ip>"``) gets an
    independent bucket, created lazily on first sight. The map is **bounded**:
    when it reaches ``max_buckets`` the coldest entries are dropped (see
    ``_evict_locked``). The earlier version never evicted, on the theory that
    the working set is "bounded by the number of distinct callers, which is
    small" — true for honest traffic and false for exactly the traffic this
    limiter exists for: one bot sending a fresh ``X-API-Key`` per request grows
    the dict without limit, because this middleware runs *before* auth by
    design and never rejects an unknown key.
    

    Settings are read from the :mod:`src.settings` module globals at
    construction time (when ``rps``/``burst`` are not passed), so tests that
    monkeypatch ``src.web.rate_limit.RATE_LIMIT_*`` before constructing the app
    see their values take effect.
    """

    def __init__(
        self,
        rps: Optional[float] = None,
        burst: Optional[int] = None,
        max_buckets: Optional[int] = None,
    ) -> None:
        # Clamp away zero/negative so a misconfigured env never divides-by-zero
        # or admits an unbounded burst.
        self._rps = max(float(rps) if rps is not None else RATE_LIMIT_RPS, 1e-6)
        self._burst = max(int(burst) if burst is not None else RATE_LIMIT_BURST, 1)
        self._buckets: dict[str, _Bucket] = {}
        # Hard ceiling on tracked callers. Eviction prefers buckets that have
        # refilled to full (dropping one loses nothing — a full bucket is
        # indistinguishable from a never-seen caller) and only falls back to the
        # stalest entry when every bucket is active. Without that ordering an
        # attacker could flush their *own* exhausted bucket by flooding fresh
        # keys, which would turn the memory fix into a new bypass.
        self._max_buckets = max(
            int(max_buckets) if max_buckets is not None else RATE_LIMIT_MAX_BUCKETS,
            1,
        )
        self._lock = threading.Lock()

    def allow(self, caller: str) -> tuple[bool, int]:
        """Consume one token for ``caller``; return ``(allowed, retry_after_s)``.

        ``retry_after_s`` is ``0`` when the request is allowed; otherwise the
        whole-second ceiling of the time until the next token refills, for the
        ``Retry-After`` response header. Uses ``time.monotonic`` so the refill
        math is immune to wall-clock adjustments.
        """
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(caller)
            if b is None:
                if len(self._buckets) >= self._max_buckets:
                    self._evict_locked(now)
                # First sight of this caller: start with a full bucket so the
                # very first request is never 429'd (no warm-up penalty).
                b = _Bucket(float(self._burst), now)
                self._buckets[caller] = b
            else:
                # Refill: accrue tokens for elapsed wall-time, capped at burst.
                elapsed = max(0.0, now - b.last)
                b.tokens = min(self._burst, b.tokens + elapsed * self._rps)
                b.last = now
            if b.tokens >= 1.0:
                b.tokens -= 1.0
                return True, 0
            # Empty: seconds until one token is available, rounded up to a whole
            # second (the Retry-After header is an integer count of seconds).
            deficit = 1.0 - b.tokens
            return False, max(1, math.ceil(deficit / self._rps))


    def _evict_locked(self, now: float) -> None:
        """Drop the buckets that are closest to full, so a key-flood cannot grow the map.

        Ordering matters more than the eviction itself. A bucket at (or near)
        full is indistinguishable from a never-seen caller — dropping it changes
        no decision. An *empty* bucket is a caller currently being throttled;
        dropping it hands them a fresh full bucket, i.e. turns the memory fix
        into a bypass. So sort by remaining tokens, largest first.

        (An earlier draft evicted the stalest ``last`` instead. That was wrong in
        the direction that matters: the caller being throttled is often the one
        seen longest ago, so a flood would evict exactly that bucket.)

        Frees ~10% of the ceiling per call, so the cost is amortised across
        inserts rather than paid on every request.
        """
        target = max(1, self._max_buckets // 10)
        ordered = sorted(
            self._buckets.items(),
            key=lambda kv: (-kv[1].tokens, kv[1].last),
        )
        for key, _bucket in ordered[:target]:
            del self._buckets[key]

def _caller_id(request: Request) -> str:
    """Identify the caller for rate-limit keying.

    Prefer the API-key prefix (first 16 chars of ``X-API-Key``) so a legitimate
    keyed caller is throttled per-key, not per-IP — multiple callers behind one
    NAT would otherwise share an IP bucket and unfairly trip each other's limit.

    Falls back to the client IP when no key is presented. For the forwarded
    case we take the **last** hop, not the first:

        客户端伪造成    X-Forwarded-For: 1.2.3.4
        代理追加真实源 → X-Forwarded-For: 1.2.3.4, <真实源>

    前面那层代理（cheap1 的雷池 nginx）用的是 ``$proxy_add_x_forwarded_for``，
    即**追加**语义。所以 ``split(",")[0]`` 取到的正是客户端自己写的假值——
    每次请求换一个假 IP 就是一批新桶，速率限制形同不存在，而且还会把桶表灌满、
    触发淘汰把别人正在限流的桶挤掉（审计 03 §7）。取 ``[-1]`` 才是离我们最近、
    由我们自己代理写入的那一跳，客户端改不了。

    前提：前面确实只有一层可信代理且用追加语义。将来加层或改成覆盖语义时，
    这条要跟着调（那时应改为"信任前 N 跳"或按可信网段白名单解析）。
    """
    key = request.headers.get("X-API-Key", "")
    if key:
        return f"k:{key[:16]}"
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            return f"i:{hops[-1]}"
    client = request.client.host if request.client else "unknown"
    return f"i:{client}"


def add_rate_limit_middleware(
    app: FastAPI,
    limiter: Optional[TokenBucketLimiter] = None,
) -> None:
    """Install the in-process rate-limit middleware on ``app``.

    No-op when ``RATE_LIMIT_ENABLED`` is unset/``"0"`` (the origin default) — the
    function returns without registering anything, so the origin's request path
    is unchanged. When enabled, a :class:`TokenBucketLimiter` is installed as
    an HTTP middleware; over-limit callers get ``429`` + ``Retry-After`` while
    ``/healthz`` stays exempt. An explicit ``limiter`` may be passed for tests
    that want a tiny bucket independent of the env defaults.
    """
    # An explicit ``limiter`` means the caller (tests, or a deliberate override)
    # wants the middleware ON regardless of the env gate; only the no-limiter
    # production path is gated by ``RATE_LIMIT_ENABLED`` (dormant on the origin).
    if limiter is None and not RATE_LIMIT_ENABLED:
        return
    lim = limiter or TokenBucketLimiter()

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # noqa: ANN001
        # Probe path is exempt: never 429 a readiness check.
        if request.url.path == _EXEMPT_PATH:
            return await call_next(request)
        ok, retry = lim.allow(_caller_id(request))
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"error": "rate limit exceeded", "retry_after": retry},
                headers={"Retry-After": str(retry)},
            )
        return await call_next(request)
