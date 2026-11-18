"""Query engine: semantic search over the Elasticsearch vector store.

``search(query, top_k)`` returns ranked chunks (text, source_path, score) for a
natural-language query via the LlamaIndex retriever. The query is embedded with
the same model used at ingestion. ``index_name=None`` (the default) keeps the
pre-registry behavior (the global ``SEARCH_INDEX_NAME``); domain-aware callers
pass the index resolved by ``src.search.resolver.resolve_index``.
"""

from __future__ import annotations

from typing import Optional

from llama_index.core import VectorStoreIndex

from .embeddings import get_embed_model
from .vector_store import get_vector_store


def search(query: str, top_k: int = 5, index_name: Optional[str] = None) -> list[dict]:
    """Return ranked chunks for ``query``; ``[]`` when nothing matches."""
    vs = get_vector_store(index_name)
    embed = get_embed_model()
    index = VectorStoreIndex.from_vector_store(vs, embed_model=embed)
    retriever = index.as_retriever(similarity_top_k=top_k)
    nodes = retriever.retrieve(query)
    out: list[dict] = []
    for n in nodes:
        score = getattr(n, "score", None)
        out.append(
            {
                "text": n.get_content(),
                "source_path": n.metadata.get("source_path")
                or n.metadata.get("file_name")
                or "unknown",
                "score": float(score) if score is not None else None,
            }
        )
    return out
