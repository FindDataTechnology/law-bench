"""Ingestion pipeline: MinIO -> chunk -> embed (OpenRouter) -> Elasticsearch.

Chunks by markdown header section (``MarkdownNodeParser``) so legal clauses stay
structurally coherent. Re-runnable: each chunk gets a stable id
(``<source_path>:<md5>``) and is deleted-then-inserted, so re-ingesting a
document updates its chunks rather than duplicating them.

Domain-aware (add-domain-rag-corpus-service): ``run_ingest`` ingests a named
domain's registered corpus (``rag_corpora.sources``, via
``src.search.resolver``) into that domain's registered index. The default
domain ``legal`` keeps the pre-registry behavior byte-for-byte: ``MINIO_BUCKET``
templates+drafts prefixes into the global ``SEARCH_INDEX_NAME`` (zero
migration — no re-ingest, no index rebuild).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from typing import Any, Optional

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from .embeddings import get_embed_model, verify_dimensions
from .minio_source import load_documents
from .resolver import (
    LEGAL_DOMAIN_KEY,
    CorpusNotRegistered,
    get_corpus,
    resolve_index,
)
from .vector_store import get_vector_store


def chunk_documents(documents) -> list:
    """Split documents into chunks with stable ids + source metadata.

    Uses a token-based ``SentenceSplitter`` so any text (markdown, pdf-extracted,
    docx-extracted) chunks uniformly; markdown header structure is not assumed.
    """
    parser = SentenceSplitter(chunk_size=512, chunk_overlap=64)
    nodes = parser.get_nodes_from_documents(documents)
    for n in nodes:
        source_path = n.metadata.get("source_path") or n.metadata.get("file_name") or "unknown"
        n.metadata.setdefault("source_path", source_path)
        digest = hashlib.md5((n.get_content() or "").encode("utf-8")).hexdigest()[:10]
        n.node_id = f"{source_path}:{digest}"
    return nodes


def run_ingest(
    domain_key: str,
    prefix: Optional[str] = None,
    conn: Any = None,
) -> dict:
    """Ingest one domain's corpus into that domain's Elasticsearch index.

    Resolution: the domain's registered corpus (``rag_corpora`` via
    :mod:`src.search.resolver`) supplies the index name and the list of
    ``{bucket, prefix}`` MinIO sources. A registered ``prefix`` argument
    overrides every declared source prefix (buckets still come from the
    registration); ``prefix=None`` uses the registered prefixes.

    The ``legal`` domain is the zero-migration path: when it has no registered
    sources (or no registry row yet) it ingests exactly as before the registry
    existed — the ``MINIO_BUCKET`` templates+drafts prefixes (or the single
    ``prefix`` when given) into the default index.

    Any other domain without a registered corpus raises
    :class:`CorpusNotRegistered` (a domain that does not exist at all raises
    the same, naming the key) — fail closed, never fall back to another
    domain's index. The CLI translates that into an error message + exit 2.

    ``conn=None`` borrows the process-wide shared database connection
    (``src.eval.db.connect``).

    Returns ``{"documents": int, "chunks": int, "errors": int}``. Per-chunk
    failures are recorded and do not abort the batch; the run is non-zero only
    if nothing was ingested (handled by the CLI).
    """
    if conn is None:
        from src.eval.db import connect as _db_connect

        conn = _db_connect()
    from src.bench import workspaces

    corpus = get_corpus(conn, domain_key=domain_key)
    registered_sources: list[dict] = list(corpus["sources"]) if corpus else []

    if registered_sources:
        index_name = corpus["index_name"]
        if prefix is not None:
            registered_sources = [{**s, "prefix": prefix} for s in registered_sources]
        docs: list = []
        for src in registered_sources:
            try:
                loaded = load_documents(bucket=src["bucket"], prefix=src["prefix"])
            except Exception as e:  # one source failing must not abort the batch
                print(
                    f"WARNING: could not load corpus source "
                    f"{src['bucket']}/{src['prefix']}: {e}",
                    file=sys.stderr,
                )
                continue
            docs.extend(loaded)
    elif domain_key == LEGAL_DOMAIN_KEY:
        # Zero-migration legal path: the pre-registry behavior, into whichever
        # index resolves for legal (registered value if present, else default).
        index_name = resolve_index(conn, domain_key)
        docs = load_documents(prefix)
    elif corpus is not None:
        # Registered but no sources declared: searchable (already-ingested
        # content) but intentionally not ingestible — report honestly, no error.
        print(
            f"Domain {domain_key!r} has a registered corpus but no sources "
            f"configured; nothing to ingest.",
            file=sys.stderr,
        )
        return {"documents": 0, "chunks": 0, "errors": 0}
    else:
        domain = workspaces.get_domain(conn, domain_key=domain_key)
        if domain is None:
            raise CorpusNotRegistered(
                f"Domain {domain_key!r} does not exist; create it before "
                f"ingesting."
            )
        raise CorpusNotRegistered(
            f"Domain {domain_key!r} has no registered RAG corpus; register one "
            f"with src.search.resolver.register_corpus before ingesting."
        )

    if not docs:
        return {"documents": 0, "chunks": 0, "errors": 0}

    verify_dimensions()
    nodes = chunk_documents(docs)
    vs = get_vector_store(index_name)
    embed = get_embed_model()
    storage_context = StorageContext.from_defaults(vector_store=vs)
    index = VectorStoreIndex.from_vector_store(
        vs, storage_context=storage_context, embed_model=embed
    )

    errors = 0
    for n in nodes:
        try:
            vs.delete(nodes=[n.node_id]) if _supports_delete(vs) else None  # idempotent upsert
        except Exception:
            pass  # delete of a missing node is fine
        try:
            index.insert_nodes([n])
        except Exception as e:  # :free rate-limit / availability -> isolate per chunk
            print(f"WARNING: failed to ingest chunk {n.node_id}: {e}", file=sys.stderr)
            errors += 1
    return {"documents": len(docs), "chunks": len(nodes), "errors": errors}


def _supports_delete(vs) -> bool:
    return hasattr(vs, "delete")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Ingest a domain's corpus: MinIO -> chunk -> embed (OpenRouter) -> "
            "that domain's Elasticsearch index. Domains other than the default "
            "'legal' must have a registered RAG corpus "
            "(src.search.resolver.register_corpus)."
        )
    )
    ap.add_argument(
        "--domain",
        default=LEGAL_DOMAIN_KEY,
        help=(
            "Domain key whose corpus to ingest (default: 'legal', the "
            "pre-registry contracts index). A registered domain ingests its "
            "declared sources into its registered index; 'legal' without "
            "registered sources keeps the legacy behavior below."
        ),
    )
    ap.add_argument(
        "--prefix",
        default=None,
        help=(
            "MinIO prefix. For 'legal' without registered sources: the prefix "
            "to ingest (default: templates + drafts prefixes of MINIO_BUCKET). "
            "For a registered corpus: overrides every declared source prefix "
            "(buckets still come from the registration)."
        ),
    )
    args = ap.parse_args()
    try:
        summary = run_ingest(args.domain, prefix=args.prefix)
    except CorpusNotRegistered as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(
        f"Ingested {summary['documents']} documents / {summary['chunks']} chunks "
        f"({summary['errors']} per-chunk errors)."
    )
    return 0 if summary["chunks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
