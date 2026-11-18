"""Per-library embedding routing: pick the model that built the library.

A library's vectors were produced by **one specific model**. Querying with any
other model does not error — it silently returns worse neighbours, which is the
worst kind of bug because the page still looks fine. ``libraries.dims`` is not
enough to identify that model: the fleet currently holds two *different*
1024-dim spaces:

- ``Qwen/Qwen3-Embedding-0.6B`` — the law corpus in Qdrant (364,916 chunks),
  served in-cluster by ``law-rag/embedding-svc``;
- ``Qwen/Qwen3-Embedding-8B`` — the text engine's ``fd_text`` verticals,
  served by the gateway **with** ``dimensions=1024`` (MRL truncation). Without
  the ``dimensions`` field the same model answers in 4096 dims, which is a
  different space again.

Both facts were measured on 2026-11-08 by re-embedding a stored chunk and
comparing against the vector already in the store:

===========  ==========================================  =========
store        call                                        cosine
===========  ==========================================  =========
Qdrant law   ``POST /embed`` (0.6B, in-cluster)          0.999894
``fd_text``  gateway 8B, ``dimensions=1024``            0.999864
``fd_text``  gateway 8B, no ``dimensions`` (4096 dims)  0.500971
===========  ==========================================  =========

So routing keys on the **model name** (plus the truncation rule), never on dims.

Providers are resolved lazily and cached per ``(model, dims)``; a missing
credential raises ``ConfigError`` at call time rather than returning a
plausible-looking wrong vector.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

import httpx

from src.settings import (
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    ConfigError,
)

#: HTTP seam. Tests replace it to state the wire protocol without a network.
_http_post = httpx.post

#: In-cluster embedder (Qwen3-Embedding-0.6B, 1024 dims). Taken from the
#: deployment because a ClusterIP is not stable across cluster rebuilds; the
#: service name is the stable part.
LOCAL_EMBED_URL_ENV = "LIBRARY_EMBED_LOCAL_URL"
_DEFAULT_LOCAL_URL = "http://embedding-svc.law-rag.svc.cluster.local:6100"

#: Gateway embedder for models this app does not host itself (8B, MRL-truncated).
GATEWAY_BASE_ENV = "LIBRARY_EMBED_GATEWAY_BASE"
GATEWAY_KEY_ENV = "LIBRARY_EMBED_GATEWAY_KEY"
_DEFAULT_GATEWAY_BASE = "https://router.finddatatech.cloud/v1"

#: Models served by the in-cluster service. Everything else that names a real
#: model goes through the OpenAI-compatible gateway.
LOCAL_MODELS = ("Qwen/Qwen3-Embedding-0.6B",)

#: Models that are MRL-trained: ``dims`` must be requested explicitly, otherwise
#: the gateway answers at the model's native width.
MRL_MODELS = ("Qwen/Qwen3-Embedding-8B",)


class Embedder:
    """A callable ``list[str] -> list[list[float]]`` with its identity attached.

    ``space`` is the string worth comparing when someone asks "can these two
    libraries be searched together?" — equal dims is *not* that answer.
    """

    def __init__(self, model: str, dims: int, fn: Callable[[list[str]], list[list[float]]],
                 provider: str):
        self.model = model
        self.dims = dims
        self.provider = provider
        self._fn = fn

    @property
    def space(self) -> str:
        return f"{self.provider}:{self.model}@{self.dims}"

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vecs = self._fn(list(texts))
        for v in vecs:
            if len(v) != self.dims:
                # Never hand back a vector from another space: this is the guard
                # that turns silent degradation into a loud failure.
                raise ConfigError(
                    f"embedder {self.space!r} returned {len(v)} dims; expected {self.dims}. "
                    "The model and the library disagree — refusing to search."
                )
        return vecs

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<Embedder {self.space}>"


_cache: dict[tuple[str, int], Embedder] = {}


def _local(model: str, dims: int) -> Embedder:
    url = os.environ.get(LOCAL_EMBED_URL_ENV, _DEFAULT_LOCAL_URL).rstrip("/")

    def _call(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        # The service accepts 1..64 inputs per request.
        for i in range(0, len(texts), 64):
            resp = _http_post(
                f"{url}/embed", json={"input": texts[i : i + 64]}, timeout=120.0
            )
            resp.raise_for_status()
            out.extend(resp.json().get("embeddings") or [])
        return out

    return Embedder(model, dims, _call, "local")


def _gateway(model: str, dims: int) -> Embedder:
    base = os.environ.get(GATEWAY_BASE_ENV, _DEFAULT_GATEWAY_BASE).rstrip("/")
    key = os.environ.get(GATEWAY_KEY_ENV, "")

    def _call(texts: list[str]) -> list[list[float]]:
        if not key:
            raise ConfigError(
                f"embedding model {model!r} is served by the gateway; "
                f"{GATEWAY_KEY_ENV} is not set"
            )
        body: dict[str, Any] = {"model": model, "input": list(texts)}
        if model in MRL_MODELS:
            # Explicit truncation: without it the gateway answers in the model's
            # native width and the vectors are not comparable to the library.
            body["dimensions"] = dims
        resp = _http_post(
            f"{base}/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json=body,
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if not data:
            raise ConfigError(f"gateway returned no embedding data for {model!r}")
        return [d["embedding"] for d in data]

    return Embedder(model, dims, _call, "gateway")


def _legacy(model: str, dims: int) -> Embedder:
    """The bench's own 2048-dim OpenRouter embedder (owned libraries)."""
    from src.search.embeddings import get_embed_model

    client = get_embed_model()

    def _call(texts: list[str]) -> list[list[float]]:
        return client.get_text_embedding_batch(texts)

    return Embedder(model, dims, _call, "openrouter")


def embedder_for(model: Optional[str], dims: int) -> Embedder:
    """Resolve the embedder that owns ``(model, dims)``.

    An empty ``model`` means "the embedded default" — the bench's own embedder,
    which is what every library created before per-library models existed uses.
    """
    model = (model or "").strip()
    if not model:
        model = EMBEDDING_MODEL
        if dims != EMBEDDING_DIMS:
            # A library with no model and a non-default width cannot be satisfied
            # by the default embedder; guessing would corrupt its space.
            raise ConfigError(
                f"library declares dims={dims} but no embedding_model; "
                f"the default embedder is {EMBEDDING_MODEL!r} at {EMBEDDING_DIMS} dims"
            )
    key = (model, int(dims))
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if model in LOCAL_MODELS:
        emb = _local(model, dims)
    elif model == EMBEDDING_MODEL:
        emb = _legacy(model, dims)
    else:
        emb = _gateway(model, dims)
    _cache[key] = emb
    return emb


def embedder_for_library(lib: dict) -> Embedder:
    """The embedder a library's own vectors were built with."""
    return embedder_for(lib.get("embedding_model"), int(lib.get("dims") or EMBEDDING_DIMS))


def clear_cache() -> None:
    """Drop cached embedders (tests change env between cases)."""
    _cache.clear()
