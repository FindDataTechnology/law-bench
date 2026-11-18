"""Elasticsearch vector store wiring + dimension-mismatch guard.

The index mapping declares a ``dense_vector`` field whose ``dims`` is locked to
``EMBEDDING_DIMS`` (2048). On init we read the existing index mapping and refuse
to write if its dims differ from the configured value - swapping the embedding
model requires an explicit reindex (drop + re-ingest).
"""

from __future__ import annotations

from typing import Optional

from llama_index.vector_stores.elasticsearch import ElasticsearchStore

from src.settings import (
    ConfigError,
    EMBEDDING_DIMS,
    ES_PASSWORD,
    ES_URL,
    ES_USER,
    SEARCH_INDEX_NAME,
)


def get_vector_store(index_name: Optional[str] = None) -> ElasticsearchStore:
    """Build the ElasticsearchStore, after asserting the index dims match.

    ``index_name=None`` (the default) keeps the pre-registry behavior: the
    global ``SEARCH_INDEX_NAME`` constant is used. Domain-aware callers pass
    the index resolved by ``src.search.resolver.resolve_index``.
    """
    if not ES_URL:
        raise ConfigError("elastic_search_host is not set.")
    resolved = index_name if index_name is not None else SEARCH_INDEX_NAME
    _check_dims(resolved)
    return ElasticsearchStore(
        index_name=resolved,
        es_url=ES_URL,
        es_user=ES_USER,
        es_password=ES_PASSWORD,
    )


def _check_dims(index_name: Optional[str] = None) -> None:
    """Raise if the existing ES index dims != ``EMBEDDING_DIMS``.

    ``index_name=None`` falls back to the global ``SEARCH_INDEX_NAME``.
    """
    from elasticsearch import Elasticsearch

    if index_name is None:
        index_name = SEARCH_INDEX_NAME
    es = Elasticsearch(ES_URL, basic_auth=(ES_USER, ES_PASSWORD))
    try:
        if not es.indices.exists(index=index_name):
            return  # will be created with the correct dims on first insert
        mapping = es.indices.get_mapping(index=index_name)
        props = mapping[index_name]["mappings"]["properties"]
        # LlamaIndex ElasticsearchStore uses 'embedding' as the vector field.
        vec_field = props.get("embedding") or props.get("vector") or {}
        dims = vec_field.get("dims")
        if dims is not None and dims != EMBEDDING_DIMS:
            raise ConfigError(
                f"Elasticsearch index {index_name!r} has dims={dims}; "
                f"expected {EMBEDDING_DIMS}. Drop the index and re-ingest to "
                f"change the embedding model."
            )
    finally:
        es.close()
