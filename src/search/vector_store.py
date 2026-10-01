"""Elasticsearch vector store wiring + dimension-mismatch guard.

The index mapping declares a ``dense_vector`` field whose ``dims`` is locked to
``EMBEDDING_DIMS`` (2048). On init we read the existing index mapping and refuse
to write if its dims differ from the configured value - swapping the embedding
model requires an explicit reindex (drop + re-ingest).
"""

from __future__ import annotations

from llama_index.vector_stores.elasticsearch import ElasticsearchStore

from src.settings import (
    ConfigError,
    EMBEDDING_DIMS,
    ES_PASSWORD,
    ES_URL,
    ES_USER,
    SEARCH_INDEX_NAME,
)


def get_vector_store() -> ElasticsearchStore:
    """Build the ElasticsearchStore, after asserting the index dims match."""
    if not ES_URL:
        raise ConfigError("elastic_search_host is not set.")
    _check_dims()
    return ElasticsearchStore(
        index_name=SEARCH_INDEX_NAME,
        es_url=ES_URL,
        es_user=ES_USER,
        es_password=ES_PASSWORD,
    )


def _check_dims() -> None:
    """Raise if the existing ES index dims != ``EMBEDDING_DIMS``."""
    from elasticsearch import Elasticsearch

    es = Elasticsearch(ES_URL, basic_auth=(ES_USER, ES_PASSWORD))
    try:
        if not es.indices.exists(index=SEARCH_INDEX_NAME):
            return  # will be created with the correct dims on first insert
        mapping = es.indices.get_mapping(index=SEARCH_INDEX_NAME)
        props = mapping[SEARCH_INDEX_NAME]["mappings"]["properties"]
        # LlamaIndex ElasticsearchStore uses 'embedding' as the vector field.
        vec_field = props.get("embedding") or props.get("vector") or {}
        dims = vec_field.get("dims")
        if dims is not None and dims != EMBEDDING_DIMS:
            raise ConfigError(
                f"Elasticsearch index {SEARCH_INDEX_NAME!r} has dims={dims}; "
                f"expected {EMBEDDING_DIMS}. Drop the index and re-ingest to "
                f"change the embedding model."
            )
    finally:
        es.close()
