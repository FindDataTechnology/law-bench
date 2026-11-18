"""Ontology candidate extraction: corpus → candidates → human review queue (§§1-4).

The shape of this module is a direct consequence of one fact: **a model can
invent evidence**. Everything here exists to keep that from reaching the
ontology:

- every candidate must carry a ``quote``, and the quote is looked up **verbatim**
  (whitespace-normalised) inside the chunk it claims to come from. No similarity
  threshold: a paraphrase is exactly what a hallucination looks like.
- nothing is written to ``knowledge_units``. Candidates go to the proposal layer
  as pending rows, so a human decides. The kernel remains the only write path.
- kinds must be in the domain's declared vocabularies, and a relationship's
  endpoints must exist or be nominated in the same batch (else a same-batch
  ``A→B`` could never be proposed, because ``B`` is not confirmed yet).
- caps on chunks, candidates-per-chunk and total candidates; hitting one stops
  the run and says so, rather than quietly costing more.

What it deliberately does *not* do: judge whether a well-quoted conclusion is
correct. That is why ``impact`` carries the quoted text — the reviewer reads the
source, not a summary.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional

import httpx

from src.bench import authoring, keys, libraries, ontology_import, proposals, submitters
from src.search import library_index

#: Bumped whenever the prompt changes — recorded on every proposal so a batch can
#: be traced back to the instruction that produced it.
PROMPT_VERSION = "2026-11-10.1"

#: Hard ceilings. The parameters can lower them, never raise them.
MAX_CHUNKS = 200
MAX_PER_CHUNK = 8
MAX_TOTAL = 500

_WS = re.compile(r"\s+")


class ExtractionError(ValueError):
    """The request cannot be run (bad scope, no chunks, no model configured)."""


# ── sampling ────────────────────────────────────────────────────────────────


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "")).strip()


def sample_chunks(
    conn: Any,
    *,
    domain_path: str,
    sources: Optional[list[str]] = None,
    limit: int = 20,
    cursor: Any = None,
) -> dict:
    """Page through a domain's subscribed corpus, oldest point id first.

    Sampling (not similarity search) because extraction wants coverage: a top-k
    query would keep returning the same nearest chunks and the ontology would
    grow only around whatever the query happened to say.

    Only ``qdrant`` libraries are supported here: they are the ones with a
    paging API. A domain whose scope has no qdrant library raises rather than
    silently returning nothing.
    """
    limit = max(1, min(int(limit), MAX_CHUNKS))
    scope = libraries.effective_sources(conn, domain_path=domain_path)
    if not scope:
        raise ExtractionError(f"domain {domain_path!r} subscribes to no corpus")
    if sources:
        unknown = sorted(set(sources) - {s for v in scope.values() for s in v})
        if unknown:
            raise ExtractionError(
                f"source(s) not in this domain's scope: {', '.join(unknown)}; "
                f"available: {sorted({s for v in scope.values() for s in v})}"
            )
    collected: list[dict] = []
    next_cursor = cursor
    for library_key, granted in sorted(scope.items()):
        lib = libraries.get_library(conn, library_key=library_key)
        if lib is None:
            continue
        backend = lib.get("backend") or ""
        wanted = (set(sources) if sources else set(granted)) & set(granted)
        if not wanted:
            continue
        if backend == "pgvector-external":
            # A text table needs no vectors: extraction only reads text. Sampling
            # it here is why the guide cases can be used without re-embedding
            # them into the statute collection (which would pollute that space).
            collected.extend(
                _sample_text_tables(
                    conn, lib=lib, allowed=wanted, limit=limit - len(collected),
                    skip=int(cursor or 0),
                )
            )
            if len(collected) >= limit:
                next_cursor = int(cursor or 0) + len(collected)
                break
            next_cursor = int(cursor or 0) + limit
            continue
        if backend != "qdrant":
            continue
        loc = libraries.resolve_location(lib)
        filt = _filter_for(conn, lib=lib, allowed=wanted)
        # Fetch a wider window than the page size: spreading across documents
        # needs candidates beyond the first few, and scroll is document-ordered.
        want = max(1, limit - len(collected))
        body: dict[str, Any] = {"limit": min(MAX_CHUNKS, want * 4), "with_payload": True}
        if filt is not None:
            body["filter"] = filt
        if next_cursor is not None:
            body["offset"] = next_cursor
        data = _post(loc["url_env"], f"/collections/{loc['collection']}/points/scroll", body)
        result = data.get("result") or {}
        window: list[dict] = []
        for point in result.get("points") or []:
            payload = point.get("payload") or {}
            text = payload.get("chunk_text") or ""
            if not text or ontology_import.is_smoke({"external_key": str(point.get("id")), "body": text}):
                continue
            window.append(
                {
                    "chunk_id": str(point.get("id")),
                    "library": library_key,
                    "source_key": _source_of(conn, lib=lib, payload=payload),
                    "law_id": payload.get("law_id"),
                    "title": payload.get("title"),
                    "chunk_no": payload.get("chunk_no"),
                    "text": text,
                }
            )
        next_cursor = result.get("next_page_offset")
        collected.extend(_spread(window, limit - len(collected)))
        if len(collected) >= limit:
            break
    return {"chunks": collected[:limit], "cursor": next_cursor}


def _spread(chunks: list[dict], limit: int, *, per_doc: int = 2) -> list[dict]:
    """Pick chunks spread across documents instead of in ingest order.

    Qdrant scroll is ordered by point id, and points are written document by
    document — so a naive page of 20 chunks can be 2 laws (measured: 20 chunks
    from 2 `law_id`s). Extraction wants coverage, so take at most ``per_doc``
    chunks from each document, round robin, until the page is full.

    Chunks left over in the window are dropped rather than re-queued: this is
    sampling, not an exhaustive walk, and the cursor already moved past them.
    """
    if limit <= 0:
        return []
    by_doc: dict[Any, list[dict]] = {}
    order: list[Any] = []
    for chunk in chunks:
        doc = chunk.get("law_id") or chunk.get("chunk_id")
        if doc not in by_doc:
            by_doc[doc] = []
            order.append(doc)
        if len(by_doc[doc]) < per_doc:
            by_doc[doc].append(chunk)
    picked: list[dict] = []
    for round_no in range(per_doc):
        for doc in order:
            if round_no < len(by_doc[doc]):
                picked.append(by_doc[doc][round_no])
                if len(picked) >= limit:
                    return picked
    if len(picked) < limit:
        # The window was dominated by a few documents: top up in window order so
        # the caller still gets the page size it asked for. A short page here
        # would silently reduce coverage without saying so.
        taken = {id(c) for c in picked}
        for chunk in chunks:
            if id(chunk) in taken:
                continue
            picked.append(chunk)
            if len(picked) >= limit:
                break
    return picked


#: Default column mapping for a ``text-table`` source. Overridable per source via
#: ``ingest_rule.columns`` so one code path serves any table.
DEFAULT_TABLE_COLUMNS = {
    "text": "chunk_text",
    "title": "title",
    "id": "chunk_id",
}


def _sample_text_tables(
    conn: Any, *, lib: dict, allowed: set[str], limit: int, skip: int = 0
) -> list[dict]:
    """Read rows from foreign text tables — no vectors involved.

    The declared columns are honoured (``ingest_rule.columns``), and a missing
    column raises with its name instead of returning an empty page: "the table
    has nothing" and "you pointed at the wrong column" must not look alike.

    Chunks and their documents often live in different tables, and the chunk
    table then carries no title of its own (measured 2026-11-11: a real chunk
    table is ``id/document_id/chunk_no/chunk_text/section_path``). When the
    source declares ``ingest_rule.document {table, id, doc_ref, title}`` the
    title is taken from the document row by ``chunk.doc_ref = document.id``.
    A missing title is acceptable (``None``); a missing text or id column is
    not — those two are what a chunk *is*.
    """
    import psycopg

    loc = libraries.resolve_location(lib)
    out: list[dict] = []
    with psycopg.connect(loc["dsn_env"], connect_timeout=10) as ext:
        for src in libraries.list_sources(conn, library_id=lib["id"]):
            if src["source_key"] not in allowed:
                continue
            table = src["uri"]
            if not library_index._IDENT.match(table or ""):
                raise ValueError(f"unsafe table name: {table!r}")
            rule = src.get("ingest_rule") or {}
            if isinstance(rule, str):
                import json as _json

                rule = _json.loads(rule or "{}")
            cols = {**DEFAULT_TABLE_COLUMNS, **(rule.get("columns") or {})}
            present = {
                r[0]
                for r in ext.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                    (table,),
                ).fetchall()
            }
            required = [c for c in (cols["text"], cols["id"]) if c not in present]
            if required:
                raise ValueError(
                    f"source {src['source_key']!r}: table {table!r} has no column(s) {required}"
                )

            # Title: own column first, then the declared document table. Every
            # identifier is checked before it reaches the SQL text.
            title_expr = "NULL"
            join_clause = ""
            if cols["title"] in present:
                title_expr = cols["title"]
            else:
                doc = rule.get("document") or {}
                doc_table, doc_id = doc.get("table"), doc.get("id")
                doc_ref, doc_title = doc.get("doc_ref"), doc.get("title")
                if (
                    doc_table
                    and doc_id
                    and doc_ref
                    and doc_title
                    and doc_ref in present
                    and all(
                        library_index._IDENT.match(str(x) or "")
                        for x in (doc_table, doc_id, doc_title)
                    )
                ):
                    join_clause = (
                        f"LEFT JOIN {doc_table} AS d ON {table}.{doc_ref} = d.{doc_id} "
                    )
                    title_expr = f"d.{doc_title}"

            order = rule.get("order_by") or cols["id"]
            if not library_index._IDENT.match(str(order) or ""):
                raise ValueError(f"unsafe order column: {order!r}")
            rows = ext.execute(
                f"SELECT {table}.{cols['id']} AS chunk_id, {table}.{cols['text']} AS text, "
                f"{title_expr} AS title FROM {table} {join_clause}"
                f"WHERE coalesce({table}.{cols['text']}, '') <> '' "
                f"ORDER BY {table}.{order} OFFSET %s LIMIT %s",
                (max(0, skip), max(1, limit)),
            ).fetchall()
            for chunk_id, text, title in rows:
                if ontology_import.is_smoke({"external_key": str(chunk_id), "body": text}):
                    continue
                out.append(
                    {
                        "chunk_id": str(chunk_id),
                        "library": lib["library_key"],
                        "source_key": src["source_key"],
                        "law_id": None,
                        "title": title,
                        "chunk_no": None,
                        "text": text,
                    }
                )
    return out


def _filter_for(conn: Any, *, lib: dict, allowed: set[str]) -> Optional[dict]:
    from src.search import library_index

    return library_index.qdrant_filter(
        libraries.list_sources(conn, library_id=lib["id"]), allowed
    )


def _source_of(conn: Any, *, lib: dict, payload: dict) -> str:
    from src.search import library_index

    return library_index._source_for_payload(
        libraries.list_sources(conn, library_id=lib["id"]), payload
    )


# ── evidence gate ───────────────────────────────────────────────────────────


def verify_quote(quote: str, chunk_text: str) -> bool:
    """True when ``quote`` really is a verbatim slice of ``chunk_text``.

    Whitespace is normalised on both sides (models reflow lines); nothing else
    is forgiven. A single changed character or a truncated phrase must fail —
    that is the whole point.
    """
    q, t = _norm(quote), _norm(chunk_text)
    if not q or not t:
        return False
    return q in t


# ── prompt & parsing ────────────────────────────────────────────────────────


def _concept_counters(domain_key: str) -> list[str]:
    """Negative examples the pack offers (what looks like a concept but is not)."""
    try:
        return list(keys.concept_counters_for(domain_key))
    except Exception:
        return []


def _concept_examples(domain_key: str) -> list[str]:
    """Names the pack offers as concept examples (empty when it offers none)."""
    try:
        return list(keys.concept_examples_for(domain_key))
    except Exception:
        return []


def build_prompt(*, schema: dict, chunks: list[dict], concept_mode: bool = False,
                 domain_key: str = "") -> str:
    """Instruction + the chunk texts, constrained to the domain's vocabularies.

    ``concept_mode`` switches the ask from "find articles" to "find the legal
    concepts this reasoning establishes, and the article each rests on". The
    corpus decides which makes sense: statute text is structured as
    「第N条」, so it can only yield clauses; a judgment's 裁判要点 is written in
    conceptual language and is where concepts live.
    """
    entity_types = sorted((schema or {}).get("entity_types") or [])
    relation_kinds = sorted((schema or {}).get("relationship_kinds") or [])
    blocks = []
    for c in chunks:
        blocks.append(
            f"[chunk_id={c['chunk_id']}] title={c.get('title')} "
            f"source={c['source_key']}\n{c['text'][:1200]}"
        )
    concept_instruction = ""
    if concept_mode:
        # Examples come from the pack: the kernel must not carry domain
        # vocabulary (there is a gate). It only knows *how* to ask.
        examples = _concept_examples(domain_key)
        counters = _concept_counters(domain_key)
        sample = f"正例：{('、'.join(examples))}。" if examples else ""
        counter = f"反例：{('、'.join(counters))}。" if counters else ""
        concept_instruction = (
            "这份语料是裁判说理/裁判要点。请抽取**法律概念**——判据是："
            "①名词短语（不是一句话），②可跨案复用，③不含具体数额、当事人名称或"
            "「本案/本决定」这类指向。"
            f"{sample}{counter}"
            "并为每个概念用 quote 逐字引用原文里确立它的那句表述。"
            "案件类别（归档标签）与个案事实描述都不要。"
        )
    return f"""你是本体候选抽取器（prompt_version={PROMPT_VERSION}）。

只允许使用下面这些类型：
- 实体类型 entity_types: {entity_types}
- 关系类型 relationship_kinds: {relation_kinds}

从给定语料块中抽取候选实体与候选关系。类型只从上面两组词表里选，不认识的不要造。硬性要求：
1. 每条候选必须给出 quote 字段，且 quote 必须是所引块里**逐字出现**的一段原文（不要改写、不要概括、不要拼接跨段内容）。
2. 实体候选：kind 必须属于 entity_types，name 用原文里的称呼。
3. 关系候选：kind 必须属于 relationship_kinds，from_name/to_name 用实体候选或已有实体的名称。
   要指向**别的文档**里的条款时，把 to_name 写成「<文档名>#<第N条>」，
   不要只写条文号——只写条文号会被归到当前语料块所属文档下。
4. 不确定就不要输出。宁少不滥。

{concept_instruction}

只输出 JSON，形如：
{{"entities": [{{"kind": "...", "name": "...", "chunk_id": "...", "quote": "..."}}],
  "relationships": [{{"kind": "...", "from_name": "...", "to_name": "...", "chunk_id": "...", "quote": "..."}}]}}

语料块：
{chr(10).join(blocks)}
"""


def parse_candidates(raw: str) -> dict:
    """Parse the model's answer; tolerate fences and surrounding prose.

    A malformed *row* is dropped (and counted by the caller); a malformed
    *answer* yields empty lists. Neither raises — one bad answer must not abort
    a 200-chunk run.
    """
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {"entities": [], "relationships": [], "bad_rows": 0}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"entities": [], "relationships": [], "bad_rows": 0}
    if not isinstance(data, dict):
        return {"entities": [], "relationships": [], "bad_rows": 0}
    entities, bad = [], 0
    for row in data.get("entities") or []:
        if isinstance(row, dict) and row.get("kind") and row.get("name") and row.get("quote"):
            entities.append(row)
        else:
            bad += 1
    relationships = []
    for row in data.get("relationships") or []:
        if all(isinstance(row, dict) and row.get(k) for k in ("kind", "from_name", "to_name", "quote")):
            relationships.append(row)
        else:
            bad += 1
    return {"entities": entities, "relationships": relationships, "bad_rows": bad}


_ILLEGAL = re.compile(r"[\s\u3000/\\:：·、，,（）()\[\]【】《》]+")


def normalize_entity_key(name: str) -> str:
    """Stable external key for an entity name.

    Two spellings of the same name must land on one key or the same entity gets
    proposed twice and the reviewer sees a duplicate. Full-width spaces,
    punctuation and separators are folded away; length is capped.
    """
    key = _ILLEGAL.sub("-", (name or "").strip())
    key = re.sub(r"-{2,}", "-", key).strip("-")
    return key[:80] or "unnamed"


# ── key & normalisation gates (§§1-2 of fix-ontology-extraction-quality) ─────


def canonical_name(name: str, *, domain_key: str = "") -> str:
    """Normalise an entity name to the spelling its key is built from.

    Rules come from the kernel registry (a pack registers them on import); with
    nothing registered nothing is folded, which is the safe direction —
    under-merging is recoverable, over-merging destroys a distinction.
    """
    stripped = keys.strip_trailing_qualifier(name or "")
    folded, _applied = keys.fold(stripped, keys.rules_for(domain_key))
    return folded.strip() or (name or "").strip()


def law_name_matches(name: str, title: str, *, domain_key: str = "") -> bool:
    """Does ``name`` really designate the document whose ``title`` this is?

    Exact match after both sides are canonicalised — **not** a substring test.
    "中华人民共和国" is a true prefix of "中华人民共和国宪法修正案", and a substring
    check would wave through exactly the kind of mis-typing this gate exists to
    stop.
    """
    left = canonical_name(name, domain_key=domain_key)
    right = canonical_name(title, domain_key=domain_key)
    if not left or not right:
        return False
    if left == right:
        return True
    # A document may carry a suffix that makes it a *different* instrument; that
    # is a legitimate distinct name, not a match for the bare stem.
    is_distinct = keys.distinct_document_for(domain_key)
    if is_distinct and is_distinct(right) and not is_distinct(left):
        return False
    return False


def clause_parent(chunk: dict, *, domain_key: str = "") -> tuple[str, str]:
    """The parent document key for a clause in ``chunk``.

    Prefers the human-readable title; falls back to the corpus id when a block
    has no title, and says which was used so the provenance is explicit.
    """
    title = (chunk.get("title") or "").strip()
    if title:
        return keys.slug(canonical_name(title, domain_key=domain_key)), "title"
    law_id = chunk.get("law_id")
    if law_id is not None:
        return f"lawid-{law_id}", "law_id"
    return "", "none"


def resolve_entity_key(name: str, *, kind: str, chunk: dict,
                       domain_key: str = "") -> tuple[Optional[str], Optional[str], dict]:
    """The key an entity name must have, plus why it has none.

    Used for entities *and* for relationship endpoints — if the two paths
    disagreed, a clause could be submitted as `contract_law#第1条` while the
    relation pointing at it looked for `第一条`, and every clause-to-clause
    relation would be rejected as "endpoint missing".

    Returns ``(key, rejection, meta)``; ``rejection`` is one of
    ``not_clause`` / ``missing_parent`` when the name cannot be keyed.
    """
    meta: dict = {}
    raw = (name or "").strip()
    # An explicitly addressed article: "<document>#第N条". Needed because the
    # parent otherwise comes from the *chunk's* title — which is right for a
    # statute block and nonsense for a judgment block. Without this form a
    # concept extracted from a case could only ever point at an article "of that
    # case", so every grounding proposal read as a missing endpoint (measured
    # 2026-11-10, after the article base existed and it still could not land).
    if "#" in raw:
        parent_raw, _, clause_part = raw.partition("#")
        number = keys.clause_no(clause_part)
        if number is not None and parent_raw.strip():
            parent_key = keys.slug(canonical_name(parent_raw, domain_key=domain_key))
            meta.update(law_key=parent_key, clause_no=number, parent_source="explicit")
            return keys.clause_key(parent_key, number), None, meta
    number = keys.clause_no(raw)
    if kind.endswith("clause") or number is not None:
        if number is None:
            return None, "not_clause", meta
        parent_key, parent_source = clause_parent(chunk, domain_key=domain_key)
        if not parent_key:
            return None, "missing_parent", meta
        meta.update(law_key=parent_key, clause_no=number, parent_source=parent_source)
        return keys.clause_key(parent_key, number), None, meta
    canon = canonical_name(raw, domain_key=domain_key)
    if canon != raw:
        meta.update(canonical_name=canon, raw_name=raw)
    if kind == "concept":
        # A concept is addressable by its name alone — it is *cross-instrument*
        # ("违约责任" means the same thing in every statute that mentions it),
        # which is the opposite of a clause, whose address must carry its parent.
        #
        # Two independent gates: a generic shape check (a concept is a noun
        # phrase, not a sentence) and the pack's own verdict (case categories,
        # party roles, concrete amounts). Measured 2026-11-09: with neither, the
        # model proposed 「没收较大数额涉案财产的行政处罚决定」 as a concept.
        if not keys.concept_shape_ok(canon):
            return None, "not_concept", meta
        reject = keys.concept_reject_for(domain_key)
        if reject and reject(canon):
            return None, "not_concept", meta
        return normalize_entity_key(canon), None, meta
    return normalize_entity_key(canon), None, meta


# ── model call (injectable) ─────────────────────────────────────────────────


def complete(prompt: str) -> str:
    """Call the project's OpenAI-compatible endpoint. Tests replace this."""
    base = os.environ.get("OPENAI_API_BASE") or os.environ.get("OPENROUTER_API_BASE")
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("EVAL_MODEL") or os.environ.get("EXTRACT_MODEL")
    if not (base and key and model):
        raise ExtractionError(
            "extraction needs OPENAI_API_BASE + OPENAI_API_KEY + EVAL_MODEL "
            "(or the OPENROUTER_* / EXTRACT_MODEL equivalents)"
        )
    name = model.split("/", 1)[1] if model.startswith("openai/") else model
    # ``max_tokens`` is not optional here. The lane's models are reasoning
    # models: with no explicit budget they spend the allowance on the chain of
    # thought and return ``finish_reason=length`` with ``content=None``
    # (observed on 词元, 2026-11-09). The caller then sees what looks like a
    # timeout and goes hunting for a slow model instead of a short payload.
    #
    # Measured 2026-11-11 on a 2-chunk concept prompt (1,406 chars): the model
    # spent 3,531 reasoning tokens before answering, so the old 1,500 default
    # returned an empty string on **every** call. 4,000 completed; 8,000 was the
    # same answer. The default is now 4,000 — a budget that a real concept call
    # fits in, not the smallest number that looked plausible.
    budget = int(os.environ.get("EXTRACT_MAX_TOKENS", "4000"))
    call_timeout = float(os.environ.get("EXTRACT_TIMEOUT", "240"))
    resp = httpx.post(
        f"{base.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": name, "temperature": 0.0, "max_tokens": budget,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=call_timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    choices = payload.get("choices") or []
    if not choices:
        raise ExtractionError("model returned no choices")
    choice = choices[0]
    content = (choice.get("message") or {}).get("content") or ""
    if not content and choice.get("finish_reason") == "length":
        # An empty answer because the budget ran out is NOT "the corpus had
        # nothing" — reporting it as an empty run sends the reader to the wrong
        # place (measured: a whole gov round reported
        # 「语料可能不含可抽内容」 while the real cause was a 1,500-token cap).
        usage = payload.get("usage") or {}
        spent = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        raise ExtractionError(
            f"模型回答被 token 预算截断：max_tokens={budget}"
            f"（推理已用 {spent} tokens），content 为空。"
            "这不是语料为空；调大 EXTRACT_MAX_TOKENS 后重跑。"
        )
    return content


# ── the run ─────────────────────────────────────────────────────────────────


def run(
    conn: Any,
    *,
    domain_key: str,
    sources: Optional[list[str]] = None,
    max_chunks: int = 20,
    max_per_chunk: int = MAX_PER_CHUNK,
    max_total: int = 100,
    batch: Optional[str] = None,
    complete_fn: Optional[Callable[[str], str]] = None,
    submitted_by: str = "extraction",
) -> dict:
    """Extract candidates for one domain and file them as pending proposals.

    Returns a report, never a bare count: a run that produced nothing needs to
    say *why* (bad quotes? out-of-vocabulary kinds? duplicate hits?), otherwise
    the operator cannot tell "the corpus has nothing" from "the prompt is bad".
    """
    from src.bench import templates as bench_templates

    domain = authoring._load_domain(conn, domain_key=domain_key)
    tmpl = bench_templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    entity_types = set(schema.get("entity_types") or [])
    relation_kinds = set(schema.get("relationship_kinds") or [])
    model = os.environ.get("EVAL_MODEL") or os.environ.get("EXTRACT_MODEL") or "unknown"
    batch = batch or f"{domain_key}-{PROMPT_VERSION}"
    call = complete_fn or complete

    sampled = sample_chunks(
        conn, domain_path=domain["path"], sources=sources,
        limit=min(max_chunks, MAX_CHUNKS),
    )
    chunks = sampled["chunks"]
    by_id = {c["chunk_id"]: c for c in chunks}

    report = {
        "batch": batch,
        "sampled": len(chunks),
        "produced": 0,
        "submitted": 0,
        "duplicate": 0,
        "skipped": {
            "bad_quote": 0,      # the model quoted something not in the chunk
            "bad_kind": 0,       # kind outside the declared vocabularies
            "bad_endpoint": 0,   # relation endpoint neither live nor nominated
            "bad_row": 0,        # malformed row / refused by the proposal layer
            # 提交前预检的三种「都不用判」：键已在库、关系端点未闭合、kind 落在域锚定
            # 模板的词表外。它们不是坏行——内容可能是对的，只是本体里已经有了（或被软删
            # 了）、或者这个域的模板不接受这个 kind。混进 bad_row 会让读报告的人去改
            # 提示词，而该做的是换靶子。
            # `kind_not_in_vocabulary` 在**本路径上结构不可达**且通常恒为 0：上面的
            # `bad_kind` 已用同一张模板词表（本函数开头取的 `tmpl["schema"]`）在提交前
            # 预筛，只有直连提交方（MCP/控制台）能送进词表外的 kind。这里保留这个桶是
            # 为了 `report["skipped"][exc.reason]` 在预检新增理由词时不会 KeyError 打断
            # 整批——读到 0 不要当成「这类问题不存在」。
            "key_already_live": 0,
            "endpoints_missing": 0,
            "kind_not_in_vocabulary": 0,
            "missing_parent": 0,  # clause with no identifiable parent document
            "not_clause": 0,     # a structural name (preface/chapter) posing as a clause
            "type_mismatch": 0,  # a "law" whose name is not the block's title
            "normalised": 0,     # folded into an earlier candidate of this batch
            "not_concept": 0,    # a case-category label posing as a concept
        },
        "by_kind": {},
        "stopped": None,
        "cursor": sampled["cursor"],
    }

    # Unbounded on purpose: this is the set a relationship's endpoints are
    # resolved against, and a 1000-row cap would make every clause past the cap
    # look nonexistent (so a correct grounding proposal reads as bad_endpoint).
    live_kinds = authoring.authoring_live_key_kinds(conn, domain_key=domain_key)
    live = set(live_kinds)
    nominated: set[str] = set()
    nominated_kinds: dict[str, str] = {}
    total = 0

    for chunk in chunks:
        if total >= min(max_total, MAX_TOTAL):
            report["stopped"] = "cap"
            break
        # A guide-case block has a title but no article structure local to it;
        # statute blocks are dense in 「第N条」. Ask for what the text can give.
        clause_dense = bool(re.search(r"第[〇零一二三四五六七八九十百千0-9]+\s*条", chunk["text"][:400]))
        raw = call(build_prompt(schema=schema, chunks=[chunk],
                                concept_mode=not clause_dense, domain_key=domain_key))
        parsed = parse_candidates(raw)
        report["skipped"]["bad_row"] += parsed["bad_rows"]
        produced = parsed["entities"][:max_per_chunk] + parsed["relationships"][:max_per_chunk]
        for row in produced:
            if total >= min(max_total, MAX_TOTAL):
                report["stopped"] = "cap"
                break
            total += 1
            report["produced"] += 1
            kind = str(row.get("kind") or "")
            source_chunk = by_id.get(str(row.get("chunk_id") or chunk["chunk_id"]), chunk)
            if not verify_quote(str(row.get("quote") or ""), source_chunk["text"]):
                report["skipped"]["bad_quote"] += 1
                continue
            is_relation = "from_name" in row or "to_name" in row
            vocab = relation_kinds if is_relation else entity_types
            if kind not in vocab:
                report["skipped"]["bad_kind"] += 1
                continue
            evidence = {
                "chunk_id": source_chunk["chunk_id"],
                "quote": _norm(str(row.get("quote"))),
                "library": source_chunk["library"],
                "source_key": source_chunk["source_key"],
                "batch": batch,
                "model": model,
                "prompt_version": PROMPT_VERSION,
            }
            if is_relation:
                from_key, from_rej, _m1 = resolve_entity_key(
                    str(row.get("from_name")), kind=str(row.get("from_kind") or "entity"),
                    chunk=source_chunk, domain_key=domain_key,
                )
                to_key, to_rej, _m2 = resolve_entity_key(
                    str(row.get("to_name")), kind=str(row.get("to_kind") or "entity"),
                    chunk=source_chunk, domain_key=domain_key,
                )
                if from_rej or to_rej or not from_key or not to_key:
                    report["skipped"]["bad_endpoint"] += 1
                    continue
                missing = [k for k in (from_key, to_key) if k not in live and k not in nominated]
                if missing:
                    report["skipped"]["bad_endpoint"] += 1
                    continue
                # Direction is the pack's call; the kinds come from what this run
                # nominated (or from what the domain already holds).
                rule = keys.relationship_rule_for(domain_key)
                if rule is not None:
                    kinds = {**live_kinds, **nominated_kinds}
                    reason = rule(kind, kinds.get(from_key, ""), kinds.get(to_key, ""))
                    if reason:
                        report["skipped"]["bad_endpoint"] += 1
                        continue
                external_key = authoring.relationship_external_key(
                    from_key=from_key, kind=kind, to_key=to_key
                )
                body = f"{row.get('from_name')} {kind} {row.get('to_name')}"
                evidence["from_key"], evidence["to_key"] = from_key, to_key
            else:
                name = str(row.get("name"))
                # A candidate typed as a document must actually be the document
                # whose text it quotes; "中华人民共和国" is a prefix of the title
                # but not the title.
                if kind in ("law", "statute", "regulation") and not law_name_matches(
                    name, source_chunk.get("title") or "", domain_key=domain_key
                ):
                    report["skipped"]["type_mismatch"] += 1
                    continue
                external_key, rejection, meta = resolve_entity_key(
                    name, kind=kind, chunk=source_chunk, domain_key=domain_key
                )
                if rejection:
                    report["skipped"][rejection] += 1
                    continue
                evidence.update(meta)
                if external_key in nominated:
                    # Same entity, another spelling, same batch: one proposal,
                    # never two keys for one thing.
                    report["skipped"]["normalised"] += 1
                    continue
                body = name
                nominated.add(external_key)
                nominated_kinds[external_key] = kind
            evidence["usable_rate"] = round(
                report["submitted"] / max(1, report["produced"]), 3
            )
            try:
                _proposal, created = proposals.submit(
                    conn,
                    domain_key=domain_key,
                    source=f"extract:{model}:{PROMPT_VERSION}",
                    kind=kind,
                    external_key=external_key,
                    body=body,
                    evidence=evidence,
                    impact=f"原文：{evidence['quote']}",
                    submitted_by=submitted_by,
                    with_created=True,
                    # This is the in-process pipeline: the whole trust basis of
                    # an ``extract:`` source is that it cannot be reached over
                    # the network. Passing the channel explicitly is what keeps
                    # the external endpoint from accepting a forged one.
                    via=submitters.VIA_IN_PROCESS,
                )
            except proposals.ProposalTargetExists as exc:
                # 预检拒绝：`key_already_live` / `endpoints_missing` /
                # `kind_not_in_vocabulary` 各记各的桶，批照常往下跑（一批几百行，
                # 一条重复或一个越界 kind 不该中断整批）。
                report["skipped"][exc.reason] += 1
                continue
            except ValueError:
                report["skipped"]["bad_row"] += 1
                continue
            if created:
                report["submitted"] += 1
                report["by_kind"][kind] = report["by_kind"].get(kind, 0) + 1
            else:
                report["duplicate"] += 1
    # A ratio, not a verdict: below the threshold the right move is "don't scale
    # this up yet", and the refusal reasons say whether to fix the prompt or the
    # key rules.
    threshold = float(os.environ.get("EXTRACT_MIN_USABLE_RATE", "0.5"))
    report["usable_rate"] = round(report["submitted"] / report["produced"], 3) if report["produced"] else 0.0
    report["low_yield"] = report["usable_rate"] < threshold
    report["usable_threshold"] = threshold
    return report


def _post(url: str, path: str, body: dict, timeout: float = 30.0) -> dict:
    from src.search import library_index

    return library_index._qdrant_post(url, path, body, timeout=timeout)
