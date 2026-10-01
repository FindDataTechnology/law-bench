"""Read contract documents (markdown / pdf / docx) from MinIO via LlamaIndex ``MinioReader``."""

from __future__ import annotations

import os
import sys

# botocore (used by MinioReader) honors the macOS system proxy, which 502s
# against MinIO; bypass proxies entirely for the S3 client.
os.environ.setdefault("NO_PROXY", "*")

from llama_index.core import Document
from llama_index.readers.minio import MinioReader

from src.settings import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_DRAFTS_PREFIX,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    MINIO_TEMPLATES_PREFIX,
)

# Optional PDF/DOCX extractors (require llama-index-readers-file). When absent,
# only .md documents parse; pdf/docx are skipped with a warning.
_FILE_EXTRACTORS = {}
try:
    from llama_index.readers.file import DocxReader, PyPDFReader

    _FILE_EXTRACTORS = {".pdf": PyPDFReader(), ".docx": DocxReader()}
except Exception:
    pass


def _reader(prefix: str) -> MinioReader:
    return MinioReader(
        minio_endpoint=MINIO_ENDPOINT,
        minio_access_key=MINIO_ACCESS_KEY,
        minio_secret_key=MINIO_SECRET_KEY,
        bucket=MINIO_BUCKET,
        prefix=prefix,
        required_exts=[".md", ".pdf", ".docx"],
        file_extractor=_FILE_EXTRACTORS or None,
        minio_secure=MINIO_SECURE,
        minio_cert_check=False,
    )


def load_documents(prefix: str | None = None) -> list[Document]:
    """Load markdown documents from MinIO.

    If ``prefix`` is None, load from both the templates and drafts prefixes; a
    missing/empty prefix is skipped (not fatal) so a bucket with only templates
    still ingests. Each document carries ``source_prefix`` and ``source_path``
    metadata for retrieval attribution.
    """
    if prefix is not None:
        return _annotate(_reader(prefix).load_data(), prefix)

    docs: list[Document] = []
    for p in (MINIO_TEMPLATES_PREFIX, MINIO_DRAFTS_PREFIX):
        try:
            loaded = _reader(p).load_data()
        except Exception as e:  # one prefix missing must not abort the batch
            print(f"WARNING: could not load MinIO prefix {p!r}: {e}", file=sys.stderr)
            continue
        docs.extend(_annotate(loaded, p))
    return docs


def _annotate(docs: list[Document], prefix: str) -> list[Document]:
    for d in docs:
        d.metadata.setdefault("source_prefix", prefix)
        d.metadata.setdefault(
            "source_path",
            f"{MINIO_BUCKET}/{prefix}{d.metadata.get('file_name') or d.metadata.get('file_path') or ''}",
        )
    return docs
