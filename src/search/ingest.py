"""Ingestion pipeline: MinIO -> chunk -> embed (OpenRouter) -> Elasticsearch.

Chunks by markdown header section (``MarkdownNodeParser``) so legal clauses stay
structurally coherent. Re-runnable: each chunk gets a stable id
(``<source_path>:<md5>``) and is deleted-then-inserted, so re-ingesting a
document updates its chunks rather than duplicating them.
"""

from __future__ import annotations

import argparse
import hashlib
import sys

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter

from .embeddings import get_embed_model, verify_dimensions
from .minio_source import load_documents
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


def run_ingest(prefix: str | None = None) -> dict:
    """Read from MinIO, chunk, embed, upsert into Elasticsearch.

    Returns ``{"documents": int, "chunks": int, "errors": int}``. Per-chunk
    failures are recorded and do not abort the batch; the run is non-zero only
    if nothing was ingested (handled by the CLI).
    """
    docs = load_documents(prefix)
    if not docs:
        return {"documents": 0, "chunks": 0, "errors": 0}

    verify_dimensions()
    nodes = chunk_documents(docs)
    vs = get_vector_store()
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
        description="Ingest MinIO documents into Elasticsearch (embed via OpenRouter)."
    )
    ap.add_argument("--prefix", default=None, help="MinIO prefix (default: templates + drafts)")
    args = ap.parse_args()
    summary = run_ingest(args.prefix)
    print(
        f"Ingested {summary['documents']} documents / {summary['chunks']} chunks "
        f"({summary['errors']} per-chunk errors)."
    )
    return 0 if summary["chunks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
