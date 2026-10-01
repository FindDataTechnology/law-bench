"""Embedding client: OpenRouter (OpenAI-compatible ``/embeddings`` endpoint).

Uses ``nvidia/nemotron-3-embed-1b:free`` (L2-normalized, 2048-dim). Ingestion
and query share the same model. ``verify_dimensions`` embeds a probe and asserts
the configured dimension so a wrong model/dim fails fast rather than corrupting
the Elasticsearch index.

A custom ``BaseEmbedding`` subclass calls the endpoint via httpx (the OpenAI
client library returns "no embedding data" for OpenRouter's ``:free`` embedding
models, but the raw HTTP call works - so we bypass the library).
"""

from __future__ import annotations

from typing import Any

import httpx
from llama_index.core.embeddings import BaseEmbedding
from pydantic import Field

from src.settings import (
    ConfigError,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    OPENROUTER_API_BASE,
    OPENROUTER_API_KEY,
)

_embed: "OpenRouterEmbedding | None" = None


class OpenRouterEmbedding(BaseEmbedding):
    """Calls OpenRouter's OpenAI-compatible /embeddings endpoint via httpx."""

    api_base: str = OPENROUTER_API_BASE
    api_key: str = OPENROUTER_API_KEY
    model_name: str = EMBEDDING_MODEL
    dims: int = EMBEDDING_DIMS

    def _post(self, texts: list[str]) -> list[list[float]]:
        resp = httpx.post(
            f"{self.api_base}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model_name, "input": list(texts)},
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        if not data:
            raise ConfigError(
                f"OpenRouter returned no embedding data for model {self.model_name!r}."
            )
        return [d["embedding"] for d in data]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._post([query])[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._post([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._post(texts)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._get_text_embeddings(texts)


def get_embed_model() -> OpenRouterEmbedding:
    """Return a process-wide cached ``OpenRouterEmbedding``."""
    global _embed
    if _embed is None:
        if not OPENROUTER_API_KEY:
            raise ConfigError("OPENROUTER_API_KEY is not set.")
        _embed = OpenRouterEmbedding()
    return _embed


def verify_dimensions() -> int:
    """Embed a probe and assert it is ``EMBEDDING_DIMS``-dimensional.

    The Elasticsearch ``dense_vector`` field is locked to one dimension; a
    mismatched model would fail at index time with a confusing error, so we fail
    fast here with a clear message.
    """
    vec = get_embed_model().get_text_embedding("dimension probe 保密义务")
    if len(vec) != EMBEDDING_DIMS:
        raise ConfigError(
            f"Embedding model {EMBEDDING_MODEL!r} returned {len(vec)} dims; "
            f"expected {EMBEDDING_DIMS} (the ES index is locked to this). "
            f"Change EMBEDDING_MODEL/EMBEDDING_DIMS and reindex."
        )
    return len(vec)
