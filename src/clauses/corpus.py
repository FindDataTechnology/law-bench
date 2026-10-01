"""Read the 示范文本 corpus from MinIO and parse ``.docx``/``.pdf`` to text.

The corpus lives in the ``scraw-law-contracts`` bucket under the ``contracts/``
prefix - 823 provincial-department model contracts, UUID-named, paired as
``.docx``+``.pdf`` under ``contracts/{1,2,3,4,5,None}/``. This reader talks to
MinIO directly via the ``minio`` client (reusing ``src.settings`` MinIO config)
and parses with ``python-docx`` / ``pypdf`` - it does **not** depend on
Elasticsearch or ``llama-index-readers-file``.

Province is not in the object path (filenames are UUIDs); it is inferred from
content by :mod:`src.clauses.extract`. The ``1``..``5``/``None`` top-level dirs
are an unknown upstream bucketing and are preserved only as provenance.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# botocore/minio honor the macOS system proxy, which 502s against MinIO; bypass
# proxies entirely for the S3 client (same workaround as src/search/minio_source).
os.environ.setdefault("NO_PROXY", "*")

from minio import Minio

from src.settings import (
    ConfigError,
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
)

_CONTRACTS_PREFIX = "contracts/"
_EXTS = (".docx", ".pdf")

# Light boilerplate cleanup. The 示范文本 carry a "使用说明" preamble, blank
# "合同编号：" lines, and page artifacts; these add noise without aiding clause
# extraction, so they are stripped. Kept conservative to avoid losing content.
_BLANK_NUMBER_LINE = re.compile(r"^合同编号[:：]?\s*$")
_USE_NOTICE_RE = re.compile(r"^\s*使\s*用\s*说\s*明\s*$")
_WS_RUN_RE = re.compile(r"\n{3,}")


@dataclass
class CorpusDoc:
    """One parseable corpus document (a single MinIO object)."""

    object_name: str
    source_path: str
    ext: str
    stem: str


def _client() -> Minio:
    if not MINIO_ENDPOINT:
        raise ConfigError("minio_host is not set (MinIO corpus unreachable).")
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
        cert_check=False,
    )


def list_corpus_documents(prefix: str = _CONTRACTS_PREFIX) -> list[CorpusDoc]:
    """List every ``.docx``/``.pdf`` object under ``prefix``.

    Returns a list of :class:`CorpusDoc` (one per object). Raises
    :class:`ConfigError` if MinIO is unreachable - it never silently returns an
    empty list when the bucket is missing/inaccessible.
    """
    client = _client()
    docs: list[CorpusDoc] = []
    try:
        for obj in client.list_objects(MINIO_BUCKET, prefix=prefix, recursive=True):
            if not obj.object_name.lower().endswith(_EXTS):
                continue
            name = obj.object_name
            ext = Path(name).suffix.lower()
            stem = Path(name).stem
            docs.append(
                CorpusDoc(
                    object_name=name,
                    source_path=f"{MINIO_BUCKET}/{name}",
                    ext=ext,
                    stem=stem,
                )
            )
    except Exception as exc:  # noqa: BLE001 - surface as a clear config error
        raise ConfigError(f"could not list MinIO corpus at {MINIO_BUCKET}/{prefix}: {exc}") from exc
    return docs


def iter_unique_documents(
    prefix: str = _CONTRACTS_PREFIX, *, prefer: str = "docx"
) -> list[CorpusDoc]:
    """Deduplicate ``.docx``/``.pdf`` pairs by UUID stem.

    The corpus stores each contract as both ``<uuid>.docx`` and ``<uuid>.pdf``;
    only one is needed. When ``prefer="docx"`` (default) the ``.docx`` is kept
    (cleaner paragraph text) and the ``.pdf`` dropped; when a stem has only one
    extension, that one is kept. Returns a list ordered by source_path.
    """
    docs = list_corpus_documents(prefix)
    by_stem: dict[str, CorpusDoc] = {}
    for d in docs:
        cur = by_stem.get(d.stem)
        if cur is None:
            by_stem[d.stem] = d
            continue
        # keep the preferred extension when both exist
        if cur.ext != f".{prefer}" and d.ext == f".{prefer}":
            by_stem[d.stem] = d
    return sorted(by_stem.values(), key=lambda d: d.source_path)


def _parse_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    parts: list[str] = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _parse_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return "\n".join(pages)


def _clean(text: str) -> str:
    """Strip light boilerplate and collapse whitespace runs."""
    kept: list[str] = []
    for line in text.splitlines():
        if _BLANK_NUMBER_LINE.match(line):
            continue
        if _USE_NOTICE_RE.match(line):
            continue
        kept.append(line.rstrip())
    cleaned = "\n".join(kept).strip()
    return _WS_RUN_RE.sub("\n\n", cleaned)


def read_document(object_name: str) -> dict:
    """Download and parse one corpus object to text.

    Returns ``{source_path, ext, text}``. ``.docx`` is parsed with
    ``python-docx`` (paragraphs + table cells), ``.pdf`` with ``pypdf``.
    Raises :class:`ConfigError` if MinIO is unreachable.
    """
    client = _client()
    ext = Path(object_name).suffix.lower()
    suffix = ext or ".bin"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        client.fget_object(MINIO_BUCKET, object_name, tmp_path)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"could not download {MINIO_BUCKET}/{object_name}: {exc}") from exc
    try:
        if ext == ".docx":
            text = _parse_docx(tmp_path)
        elif ext == ".pdf":
            text = _parse_pdf(tmp_path)
        else:
            text = ""
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return {
        "source_path": f"{MINIO_BUCKET}/{object_name}",
        "ext": ext,
        "text": _clean(text),
    }
