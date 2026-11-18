"""Corpus documents: browse what a library holds, then take a slice into an ontology.

The gap this closes (2026-11-09): ``law-library`` held 364,916 chunks across
34,010 documents, the ontology held 4 documents and 1 clause, and there was no
path between them that did not run text through a model. The corpus already
states which document each chunk belongs to and which article it starts with —
reading that is deterministic, so it should never be guessed.

Three rules shape this module:

- **The catalog is derived, never stored.** A second document table would
  drift, and a drifted list is worse than no list: people make adoption
  decisions from it. Every call reads the store.
- **The source declares its own document shape** (``ingest_rule.document``):
  which payload/column holds the document id, title, text and order. The kernel
  must not know that a given vertical calls it ``law_id`` — there is a gate.
- **Adoption is a human action, and only the kernel writes.** Nothing is
  imported in bulk; a person picks a document, and the write goes through
  ``authoring`` so the vocabulary gate and the event log apply.

Unreachable and empty are different answers: a store that cannot be reached
raises :class:`StoreError`, a source that never declared its document shape
raises :class:`DocumentMappingError`, and only a working store with no rows
reports zero.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from psycopg.rows import dict_row

from src.bench import authoring, keys, libraries
from src.search import library_index

#: How many document ids to consider when browsing one source. A source with
#: more documents than this (the local-regulation slice has ~25k) is browsed in
#: its largest documents only, and the response says so — a silently cut list is
#: the same lie as a silent zero.
DEFAULT_WINDOW = 2000

#: Hard ceilings. Callers may lower them, never raise them.
MAX_PAGE = 200
MAX_DOC_CHUNKS = 4000
MAX_ADOPT_CLAUSES = 200

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

#: A clause header at the start of a line. Anchoring on the line is the whole
#: difference between reading the corpus and inventing structure: "依据第585条"
#: inside a sentence is a *reference*, not the start of an article.
_HEAD = re.compile(r"(?m)^[ \t\u3000]*(第\s*(?:[0-9]+|[〇零一二三四五六七八九十百千两]+)\s*条)")


class DocumentMappingError(ValueError):
    """The source does not say how to read documents out of it."""


class StoreError(RuntimeError):
    """The corpus store could not answer. Distinct from "it holds nothing"."""


# ── source declarations ──────────────────────────────────────────────────────


def _rule(src: dict) -> dict:
    rule = src.get("ingest_rule") or {}
    if isinstance(rule, str):
        rule = json.loads(rule or "{}")
    return rule if isinstance(rule, dict) else {}


def document_mapping(src: dict) -> dict:
    """The source's declared document shape, with every required field present.

    ``unit_kind``/``clause_kind`` are part of the declaration for the same reason
    as the field names: which entity type a corpus document becomes is a
    property of the data line, not of this kernel.

    ``table`` is for corpora whose **chunks and documents live in different
    tables** — a common shape: one row per document, many rows per chunk, joined
    by the document id. It names where the *document* row lives; the source's own
    uri stays what retrieval reads, so declaring it changes nothing about search.
    """
    doc = _rule(src).get("document")
    if not isinstance(doc, dict):
        raise DocumentMappingError(
            f"source {src.get('source_key')!r} declares no document mapping — "
            "add ingest_rule.document {id, title, text} so it can be browsed"
        )
    missing = [k for k in ("id", "title", "text") if not doc.get(k)]
    if missing:
        raise DocumentMappingError(
            f"source {src.get('source_key')!r} document mapping is missing "
            f"{', '.join(missing)}"
        )
    for name, value in doc.items():
        if name in ("doc_filter", "document"):
            continue
        if isinstance(value, str) and not _IDENT.match(value):
            raise DocumentMappingError(
                f"source {src.get('source_key')!r} document mapping has an unsafe "
                f"field name {value!r}"
            )
    table = doc.get("table")
    if table is not None and not _IDENT.match(str(table)):
        raise DocumentMappingError(
            f"source {src.get('source_key')!r} document mapping has an unsafe "
            f"table name {table!r}"
        )
    return {
        "id": doc["id"],
        "title": doc["title"],
        "text": doc["text"],
        "order": doc.get("order") or "id",
        "table": table,
        "doc_ref": doc.get("doc_ref"),
        "kind": doc.get("kind"),
        "status": doc.get("status"),
        "publish": doc.get("publish"),
        "unit_kind": doc.get("unit_kind"),
        "clause_kind": doc.get("clause_kind"),
        "filter": doc.get("doc_filter") or None,
    }


def _sources(conn: Any, *, library_key: str, source_key: Optional[str]) -> tuple[dict, list[dict], dict]:
    lib = libraries.get_library(conn, library_key=library_key)
    if lib is None:
        raise ValueError(f"library {library_key!r} not found")
    sources = libraries.list_sources(conn, library_id=lib["id"])
    picked = [s for s in sources if s["source_key"] == source_key] if source_key else sources
    if source_key and not picked:
        raise ValueError(f"library {library_key!r} has no source {source_key!r}")
    return lib, sources, picked[0] if len(picked) == 1 else {}


def _merge_filter(base: Optional[dict], extra: Optional[dict]) -> Optional[dict]:
    if not extra:
        return base
    if not base:
        return extra
    return {"must": [base, extra]}


def _doc_filter(filter_spec: Optional[dict]) -> Optional[dict]:
    """The per-source narrowing (``doc_filter``), as an extra Qdrant filter."""
    if not filter_spec:
        return None
    must = []
    for key, value in sorted((filter_spec.get("match") or {}).items()):
        vals = list(value) if isinstance(value, (list, tuple, set)) else [value]
        must.append({"key": str(key), "match": {"any": vals}})
    return {"must": must} if must else None


# ── browse ───────────────────────────────────────────────────────────────────


def documents(
    conn: Any,
    *,
    library_key: str,
    source_key: Optional[str] = None,
    offset: int = 0,
    limit: int = 25,
    q: str = "",
    window: int = DEFAULT_WINDOW,
    domain_key: Optional[str] = None,
) -> dict:
    """One page of documents held by a library source.

    ``total`` is what the store reports, not what this page shows; ``partial`` is
    true when the browsable window is smaller than ``total``. ``adopted`` marks
    the documents whose canonical key already exists in ``domain_key``.
    """
    lib, sources, src = _sources(conn, library_key=library_key, source_key=source_key)
    limit = max(1, min(int(limit or 25), MAX_PAGE))
    offset = max(0, int(offset or 0))
    window = max(limit, min(int(window or DEFAULT_WINDOW), 50000))
    query = (q or "").strip()

    backend = lib.get("backend") or "array-cosine"
    if backend == "qdrant":
        out = _qdrant_documents(conn, lib=lib, sources=sources, source_key=source_key,
                                offset=offset, limit=limit, q=query, window=window)
    elif backend == "pgvector-external":
        out = _pg_documents(conn, lib=lib, sources=sources, source_key=source_key,
                            offset=offset, limit=limit, q=query)
    else:
        raise ValueError(
            f"library {library_key!r} is backend {backend!r}; its content is stored here, "
            "not in a foreign store, so there are no external documents to browse"
        )

    adopted: set[str] = set()
    if domain_key:
        # Unbounded on purpose: the page answers "is this document already in the
        # ontology", and a capped list would start answering "no" past the cap.
        adopted = authoring.authoring_live_keys(conn, domain_key=domain_key)
    for row in out["rows"]:
        key = _canonical(row["title"], domain_key)
        row["adopted_as"] = key if key in adopted else None
    out.update({"library": library_key, "source": source_key, "query": query})
    return out


def _canonical(title: str, domain_key: Optional[str]) -> str:
    canonical, _applied = keys.fold(title or "", keys.rules_for(domain_key or ""))
    return canonical.strip()


def _qdrant_documents(
    conn: Any, *, lib: dict, sources: list[dict], source_key: Optional[str],
    offset: int, limit: int, q: str, window: int,
) -> dict:
    mapping_src = next((s for s in sources if s["source_key"] == source_key), None)
    if mapping_src is None:
        # Library-wide browse: every source must declare the same document shape,
        # otherwise one column layout would be read with another's field names.
        maps = {}
        for src in sources:
            maps[src["source_key"]] = document_mapping(src)
        shapes = {json.dumps({k: v for k, v in m.items() if k != "filter"}, sort_keys=True)
                  for m in maps.values()}
        if len(shapes) > 1:
            raise DocumentMappingError(
                "library-wide browse needs one document shape; pick a source instead "
                f"(found {len(shapes)} different shapes)"
            )
        mapping = next(iter(maps.values()))
        allowed: set[str] = set()
    else:
        mapping = document_mapping(mapping_src)
        allowed = {mapping_src["source_key"]}

    loc = libraries.resolve_location(lib)
    url, collection = loc["url_env"], loc["collection"]
    base_filter = library_index.qdrant_filter(sources, allowed)
    base_filter = _merge_filter(base_filter, _doc_filter(mapping["filter"]))

    facet_body: dict[str, Any] = {"key": mapping["id"], "limit": window, "exact": True}
    if base_filter:
        facet_body["filter"] = base_filter
    try:
        facet = library_index._qdrant_post(url, f"/collections/{collection}/facet", facet_body)
    except Exception as exc:  # unreachable store must not read as "empty"
        raise StoreError(f"{library_key_name(lib)}: {exc}") from exc

    hits = (facet.get("result") or {}).get("hits") or []
    total = len(hits)
    partial = total >= window
    ids = [str(h["value"]) for h in hits]
    counts = {str(h["value"]): int(h.get("count") or 0) for h in hits}

    if q:
        # Title search needs the titles, and titles live on the payload — so the
        # search runs over the browsable window, not over the whole store. The
        # response says `partial` when the window was the limit.
        rows = _qdrant_rows(url, collection, mapping, ids, counts)
        needle = q.lower()
        rows = [r for r in rows if needle in (r["title"] or "").lower()]
        total = len(rows)
        return {"rows": rows[offset:offset + limit], "total": total, "window": window,
                "partial": partial, "backend": "qdrant"}
    rows = _qdrant_rows(url, collection, mapping, ids[offset:offset + limit], counts)
    return {"rows": rows, "total": total, "window": window, "partial": partial,
            "backend": "qdrant"}


def library_key_name(lib: dict) -> str:
    return str(lib.get("library_key") or "library")


def _qdrant_rows(url: str, collection: str, mapping: dict, ids: list[str],
                 counts: dict[str, int]) -> list[dict]:
    if not ids:
        return []
    payload_fields = [mapping[k] for k in ("id", "title", "kind", "status", "publish") if mapping.get(k)]
    payload_fields = sorted(set(payload_fields))
    body = {
        "limit": len(ids),
        "with_payload": payload_fields,
        "with_vector": False,
        "filter": {"must": [
            {"key": mapping["id"], "match": {"any": list(ids)}},
            {"key": mapping["order"], "match": {"value": 0}},
        ]},
    }
    data = library_index._qdrant_post(url, f"/collections/{collection}/points/scroll", body)
    first: dict[str, dict] = {}
    for point in (data.get("result") or {}).get("points") or []:
        payload = point.get("payload") or {}
        doc_id = str(payload.get(mapping["id"]))
        if doc_id and doc_id not in first:
            first[doc_id] = payload
    rows = []
    for doc_id in ids:
        payload = first.get(doc_id) or {}
        rows.append({
            "id": doc_id,
            "title": str(payload.get(mapping["title"]) or doc_id),
            "kind": payload.get(mapping["kind"]) if mapping.get("kind") else None,
            "status": payload.get(mapping["status"]) if mapping.get("status") else None,
            "published": payload.get(mapping["publish"]) if mapping.get("publish") else None,
            "chunks": counts.get(doc_id, 0),
        })
    return rows


def _pg_documents(
    conn: Any, *, lib: dict, sources: list[dict], source_key: Optional[str],
    offset: int, limit: int, q: str,
) -> dict:
    import psycopg

    mapping_src = next((s for s in sources if s["source_key"] == source_key), None)
    if mapping_src is None:
        mapping_src = sources[0] if len(sources) == 1 else None
        if mapping_src is None:
            raise DocumentMappingError("pick a source: this library holds several")
    mapping = document_mapping(mapping_src)
    doc_table = mapping.get("table") or mapping_src["uri"]
    chunk_table = mapping_src["uri"]
    for name in (doc_table, chunk_table):
        if not _IDENT.match(name or ""):
            raise ValueError(f"source {mapping_src['source_key']!r} has an unsafe table name")
    cols = [mapping["id"], mapping["title"], mapping["text"]]
    cols += [mapping[k] for k in ("kind", "status", "publish") if mapping.get(k)]
    if not mapping.get("table"):
        cols.append(mapping["order"])
    for col in cols:
        if not _IDENT.match(col or ""):
            raise DocumentMappingError(f"unsafe column name {col!r}")

    loc = libraries.resolve_location(lib)
    where, params = _pg_where(mapping_src, mapping, q=q)
    visible = [c for c in (mapping.get("kind"), mapping.get("status"), mapping.get("publish")) if c]
    select_extra = "".join(f", {c} AS {name}" for c, name in zip(
        visible, [n for n in ("kind", "status", "published") if mapping.get(n)]))
    if mapping.get("table"):
        # Documents live in their own table; the chunk count is the only thing
        # the chunk table has to contribute here.
        ref = mapping.get("doc_ref") or mapping["id"]
        if not _IDENT.match(str(ref)):
            raise DocumentMappingError(f"unsafe join column {ref!r}")
        chunks_expr = (
            f"(SELECT COUNT(*) FROM {chunk_table} c "
            f"WHERE c.{ref} = d.{mapping['id']})"
        )
        sql = (
            f"SELECT d.{mapping['id']} AS doc_id, d.{mapping['title']} AS title, "
            f"{chunks_expr} AS chunks{select_extra} FROM {doc_table} d{where} "
            f"ORDER BY chunks DESC, doc_id LIMIT %s OFFSET %s"
        )
        count_sql = f"SELECT COUNT(*) AS count FROM {doc_table} d{where}"
    else:
        sql = (
            f"SELECT {mapping['id']} AS doc_id, MIN({mapping['title']}) AS title, "
            f"COUNT(*) AS chunks{select_extra} FROM {doc_table}{where} "
            f"GROUP BY {mapping['id']} ORDER BY COUNT(*) DESC, doc_id LIMIT %s OFFSET %s"
        )
        count_sql = (f"SELECT COUNT(DISTINCT {mapping['id']}) AS count "
                     f"FROM {doc_table}{where}")
    try:
        with psycopg.connect(loc["dsn_env"], connect_timeout=10,
                             row_factory=dict_row) as ext:
            total = int(ext.execute(count_sql, tuple(params)).fetchone()["count"])
            rows = ext.execute(sql, tuple(params) + (limit, offset)).fetchall()
    except Exception as exc:
        raise StoreError(f"{library_key_name(lib)}: {exc}") from exc
    out = []
    for row in rows:
        item = dict(row)
        out.append({
            "id": str(item["doc_id"]),
            "title": str(item.get("title") or item["doc_id"]),
            "kind": item.get("kind"),
            "status": item.get("status"),
            "published": item.get("published"),
            "chunks": int(item.get("chunks") or 0),
        })
    return {"rows": out, "total": total, "window": total, "partial": False,
            "backend": "pgvector-external"}


def _pg_where(src: dict, mapping: dict, *, q: str) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    where = _rule(src).get("where") or {}
    for key, value in sorted(where.items()):
        if not _IDENT.match(str(key)):
            raise DocumentMappingError(f"unsafe filter column {key!r}")
        vals = list(value) if isinstance(value, (list, tuple, set)) else [value]
        clauses.append(f"{key} = ANY(%s)")
        params.append(vals)
    if q:
        clauses.append(f"{mapping['title']} ILIKE %s")
        params.append(f"%{q}%")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


# ── document bodies ──────────────────────────────────────────────────────────


def document_chunks(
    conn: Any, *, library_key: str, source_key: str, doc_id: str,
    limit: int = MAX_DOC_CHUNKS,
) -> dict:
    """Every chunk of one document, in order — the text a clause split reads."""
    lib, sources, src = _sources(conn, library_key=library_key, source_key=source_key)
    mapping = document_mapping(src)
    limit = max(1, min(int(limit or MAX_DOC_CHUNKS), MAX_DOC_CHUNKS))
    backend = lib.get("backend") or ""
    if backend == "qdrant":
        chunks = _qdrant_chunks(lib, mapping, doc_id=doc_id, limit=limit)
    elif backend == "pgvector-external":
        chunks = _pg_chunks(lib, src, mapping, doc_id=doc_id, limit=limit)
    else:
        raise ValueError(f"library {library_key!r} is not an external store")
    chunks.sort(key=lambda c: c["order"])
    return {"chunks": chunks, "truncated": len(chunks) >= limit,
            "title": chunks[0]["title"] if chunks else None}


def _qdrant_chunks(lib: dict, mapping: dict, *, doc_id: str, limit: int) -> list[dict]:
    loc = libraries.resolve_location(lib)
    fields = {mapping["text"], mapping["order"], mapping["title"]}
    fields |= {mapping[k] for k in ("kind", "status", "publish") if mapping.get(k)}
    body = {
        "limit": limit,
        "with_payload": sorted(fields),
        "with_vector": False,
        "filter": {"must": [{"key": mapping["id"], "match": {"value": doc_id}}]},
    }
    try:
        data = library_index._qdrant_post(
            loc["url_env"], f"/collections/{loc['collection']}/points/scroll", body)
    except Exception as exc:
        raise StoreError(f"{library_key_name(lib)}: {exc}") from exc
    out = []
    for point in (data.get("result") or {}).get("points") or []:
        payload = point.get("payload") or {}
        out.append({
            "chunk_id": str(point.get("id")),
            "order": _order_value(payload.get(mapping["order"])),
            "text": str(payload.get(mapping["text"]) or ""),
            "title": str(payload.get(mapping["title"]) or ""),
            **_meta_from(payload, mapping),
        })
    return out


def _meta_from(payload: dict, mapping: dict) -> dict:
    """The document-level fields a chunk carries, so a head chunk is self-sufficient."""
    return {
        "kind": payload.get(mapping["kind"]) if mapping.get("kind") else None,
        "status": payload.get(mapping["status"]) if mapping.get("status") else None,
        "published": payload.get(mapping["publish"]) if mapping.get("publish") else None,
    }


def _order_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _pg_chunks(lib: dict, src: dict, mapping: dict, *, doc_id: str, limit: int) -> list[dict]:
    import psycopg

    # When documents live in their own table, that row is the whole document
    # text — reading the chunk table instead would return fragments with no
    # title and force the cutter to reassemble what was never split.
    table = mapping.get("table") or src["uri"]
    if not _IDENT.match(table or ""):
        raise ValueError(f"unsafe table name {table!r}")
    id_col = mapping.get("id") or "id"
    extras = "".join(
        f", {mapping[k]} AS {name}"
        for k, name in (("kind", "kind"), ("status", "status"), ("publish", "published"))
        if mapping.get(k)
    )
    order_col = mapping["order"] if not mapping.get("table") else "0"
    ordering = f" ORDER BY {mapping['order']}" if not mapping.get("table") else ""
    sql = (
        f"SELECT {mapping['text']} AS text, {order_col} AS ord, "
        f"{mapping['title']} AS title{extras} FROM {table} "
        f"WHERE {id_col} = %s{ordering} LIMIT %s"
    )
    loc = libraries.resolve_location(lib)
    try:
        with psycopg.connect(loc["dsn_env"], connect_timeout=10,
                             row_factory=dict_row) as ext:
            rows = ext.execute(sql, (doc_id, limit)).fetchall()
    except Exception as exc:
        raise StoreError(f"{library_key_name(lib)}: {exc}") from exc
    return [
        {"chunk_id": f"{doc_id}#{r['ord']}", "order": _order_value(r["ord"]),
         "text": str(r["text"] or ""), "title": str(r["title"] or ""),
         "kind": r.get("kind"), "status": r.get("status"),
         "published": r.get("published")}
        for r in rows
    ]


# ── clause splitting ─────────────────────────────────────────────────────────


def split_clauses(chunks: list[dict], *, document_complete: bool = True) -> dict:
    """Cut an ordered document into articles, verbatim.

    The text is joined first and cut afterwards, because an article regularly
    straddles a chunk boundary — cutting per chunk would silently truncate it.
    A trailing article whose end was never seen (because the document was read
    up to a cap) is marked ``truncated``; the rest of the document is not
    guessed at.
    """
    if not chunks:
        return {"clauses": [], "reason": "no_chunks", "duplicates": 0}
    texts = [c["text"] for c in chunks]
    joined = "\n".join(texts)
    # Where each chunk starts in the joined text, so a clause can name its chunk.
    starts, pos = [], 0
    for text in texts:
        starts.append(pos)
        pos += len(text) + 1

    heads = [(m.start(), m.group(1)) for m in _HEAD.finditer(joined)]
    if not heads:
        return {"clauses": [], "reason": "no_clause_headers", "duplicates": 0}

    out: list[dict] = []
    seen: set[int] = set()
    duplicates = 0
    for index, (start, label) in enumerate(heads):
        end = heads[index + 1][0] if index + 1 < len(heads) else len(joined)
        number = keys.clause_no(label)
        if number is None:
            continue
        if number in seen:
            duplicates += 1
            continue
        seen.add(number)
        body = joined[start:end].strip()
        chunk_index = max(i for i, at in enumerate(starts) if at <= start)
        out.append({
            "no": number,
            "text": body,
            "chunk_id": chunks[chunk_index]["chunk_id"],
            "chunk_order": chunks[chunk_index]["order"],
            "truncated": (not document_complete) and index + 1 == len(heads),
        })
    return {"clauses": out, "reason": None if out else "no_clause_headers",
            "duplicates": duplicates}


# ── adoption ─────────────────────────────────────────────────────────────────


def document_key(
    conn: Any, *, domain_key: str, library_key: str, source_key: str,
    doc_id: str,
) -> str:
    """The key this document would get — read-only, for previews and cleanups.

    Same fold as adoption, so a page or a cleanup pass cannot disagree with what
    ``adopt_document`` actually writes.
    """
    fetched = document_chunks(conn, library_key=library_key, source_key=source_key,
                              doc_id=doc_id, limit=1)
    if not fetched["chunks"]:
        return ""
    return _canonical(fetched["chunks"][0]["title"] or str(doc_id), domain_key)


def adopt_document(
    conn: Any, *, domain_key: str, library_key: str, source_key: str,
    doc_id: str, operator: str,
) -> dict:
    """Take one corpus document into the ontology as a single unit."""
    lib, _sources_list, src = _sources(conn, library_key=library_key, source_key=source_key)
    mapping = document_mapping(src)
    if not mapping.get("unit_kind"):
        raise DocumentMappingError(
            f"source {source_key!r} does not declare document.unit_kind — the domain's "
            "vocabulary decides what a document becomes, and the source must say which"
        )
    # The head chunk carries the document's own metadata, so adoption costs one
    # read of the document rather than a second pass over the whole catalog.
    body_info = document_chunks(conn, library_key=library_key, source_key=source_key,
                                doc_id=doc_id)
    if not body_info["chunks"]:
        raise StoreError(f"document {doc_id!r} has no readable chunks in {library_key!r}")
    head = body_info["chunks"][0]
    title = head["title"] or doc_id
    key = _canonical(title, domain_key)
    info = {"id": doc_id, "title": title, "kind": head.get("kind"),
            "status": head.get("status"), "published": head.get("published"),
            "chunks": len(body_info["chunks"]),
            "truncated": body_info.get("truncated")}
    existing = authoring.authoring_get_unit(conn, domain_key=domain_key,
                                            kind=mapping["unit_kind"], external_key=key)
    unit = authoring.authoring_create_unit(
        conn,
        domain_key=domain_key,
        kind=mapping["unit_kind"],
        external_key=key,
        body=_document_body(info),
        operator=operator,
        attrs={
            "corpus": {"library": library_key, "source_key": source_key, "doc_id": doc_id},
            **({"kind": info["kind"]} if info.get("kind") else {}),
            **({"status": info["status"]} if info.get("status") else {}),
            **({"published": info["published"]} if info.get("published") else {}),
            **({"chunks": info["chunks"]} if info.get("chunks") else {}),
            **({"truncated": True} if info.get("truncated") else {}),
            "evidence": {"chunk_id": head["chunk_id"],
                         "quote": head["text"].strip()[:280]},
        },
    )
    return {"unit": unit, "key": key, "created": existing is None}


def _document_body(info: dict) -> str:
    lines = [f"# {info['title']}"]
    for label, field in (("类型", "kind"), ("状态", "status"), ("发布", "published")):
        if info.get(field):
            lines.append(f"- {label}：{info[field]}")
    lines.append(f"- 语料块：{info['chunks']}" + ("（读取被上限截断）" if info.get("truncated") else ""))
    return "\n".join(lines)


def adopt_clauses(
    conn: Any, *, domain_key: str, library_key: str, source_key: str, doc_id: str,
    operator: str, law_key: Optional[str] = None, limit: int = MAX_ADOPT_CLAUSES,
) -> dict:
    """Take one document's articles in as clause units — all of them or none."""
    _lib, _list, src = _sources(conn, library_key=library_key, source_key=source_key)
    mapping = document_mapping(src)
    if not mapping.get("clause_kind"):
        raise DocumentMappingError(
            f"source {source_key!r} does not declare document.clause_kind"
        )
    limit = max(1, min(int(limit or MAX_ADOPT_CLAUSES), MAX_ADOPT_CLAUSES))
    fetched = document_chunks(conn, library_key=library_key, source_key=source_key,
                              doc_id=doc_id)
    split = split_clauses(fetched["chunks"], document_complete=not fetched["truncated"])
    clauses = split["clauses"]
    if not clauses:
        return {"adopted": 0, "key": law_key, "reason": split["reason"],
                "capped": False, "remaining": 0, "duplicates": split["duplicates"]}
    parent = (law_key or "").strip() or _canonical(
        (fetched["title"] or doc_id), domain_key)
    # One click must make progress. Cutting the first `limit` articles every time
    # would rewrite the same ones and report the same "remaining" forever — the
    # reader would click, see 200 written, and still be 1000 short. So the batch
    # is the articles that are not in the ontology yet, and a second click
    # continues where the first stopped.
    existing = authoring.authoring_live_keys(
        conn, domain_key=domain_key, kind=mapping["clause_kind"],
        prefix=f"{parent}#",
    )
    todo = [c for c in clauses if keys.clause_key(parent, c["no"]) not in existing]
    if not todo:
        return {"adopted": 0, "key": parent, "reason": "nothing_new", "capped": False,
                "remaining": 0, "duplicates": split["duplicates"]}
    batch = todo[:limit]
    units = []
    for clause in batch:
        units.append({
            "kind": mapping["clause_kind"],
            "external_key": keys.clause_key(parent, clause["no"]),
            "body": clause["text"],
            "attrs": {
                "law_key": parent,
                "clause_no": clause["no"],
                "chunk_id": clause["chunk_id"],
                "corpus": {"library": library_key, "source_key": source_key,
                           "doc_id": doc_id},
                **({"truncated": True} if clause["truncated"] else {}),
            },
        })
    written = authoring.authoring_create_units(
        conn, domain_key=domain_key, units=units, operator=operator
    )
    remaining = len(todo) - len(batch)
    return {
        "adopted": len(written),
        "key": parent,
        "reason": None,
        "capped": remaining > 0,
        "remaining": remaining,
        "duplicates": split["duplicates"],
        "truncated_document": bool(fetched["truncated"]),
    }
