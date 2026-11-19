"""Estate matrix: one row per visible domain, with its four-pillar gaps.

Change ``add-domain-tree-and-shared-libraries`` §4.2. The console used to land on
"the domains I belong to" — a list with no health signal. With many sub-domains
that page cannot answer the only question an operator has: *what is missing
where?*

This module is a **read-only projection**. Every number is derived from the same
stores the domain pages read, so the matrix cannot drift from the detail pages:

- 本体 — declared vocabulary size (from the anchor template) + curated unit count
- 语料 — whether any subscription resolves to sources, and how many
- 评测 — rubric count effective in this domain + date of the last attributed run
- 提案 — pending proposal count + the newest proposal time

Nothing here writes, and nothing fabricates a "0" for a domain whose data could
not be read: an unreadable pillar reports ``None`` so the page can show "—".
"""

from __future__ import annotations

from typing import Any, Optional

from . import domain_rubrics, libraries, quality, template_readiness

#: Gap keys, in the order the matrix renders them.
PILLARS = ("ontology", "knowledge", "eval", "inbox")


def _pillar_ontology(conn: Any, domain: dict) -> dict:
    """Declared vocabulary size and how much of it is actually curated.

    Smoke-test rows are **excluded** from ``curated_units`` and reported
    separately. On 2026-11-09 this pillar read "1 unit" for the legal domain —
    and that unit was ``smoke-clause-001``, so the matrix reported a curated
    ontology where there was only left-over test data. Excluding it is not
    deletion (the row stays, and the page names the count); it keeps the number
    answering "did a human curate anything here".

    Soft-deleted units are excluded for the same reason — a retired unit is no
    longer curated. Measured 2026-11-10, the gov line read 85 curated units while
    31 were live: the rest were rows a curation pass had retired, still counted
    because the query carried no deleted filter.
    """
    from . import ontology_import

    declared = conn.execute(
        "SELECT COUNT(*) AS n FROM ("
        "  SELECT jsonb_array_elements_text(schema::jsonb -> 'entity_types') "
        "  FROM ontology_templates WHERE id = %s"
        ") t",
        (domain["template_id"],),
    ).fetchone()
    rows = conn.execute(
        "SELECT kind, external_key, body FROM knowledge_units "
        "WHERE namespace = %s AND (tags->>'deleted') IS NULL",
        (domain.get("path") or domain["key"],),
    ).fetchall()
    smoke = [r for r in rows if ontology_import.is_smoke({"external_key": r["external_key"],
                                                          "body": r["body"]})]
    return {
        "declared_types": declared["n"] if declared else None,
        "curated_units": len(rows) - len(smoke),
        "smoke_units": len(smoke),
    }


def _pillar_knowledge(conn: Any, domain: dict, *, cache: Optional[dict] = None) -> dict:
    """Subscribed scope **and** how much of it is actually retrievable.

    The gap is about retrievable content, not about paperwork: a domain that
    subscribed two sources but ingested nothing is still a gap, and reporting it
    green would be exactly the kind of "the report looks better than reality"
    failure this page exists to prevent.

    External libraries (Qdrant, the text engine's pgvector) are counted **in
    their own store** — see ``library_index.count_scope``. Counting only
    ``corpus_chunks`` here would mark 364,916 law chunks as a missing corpus.
    """
    from src.search import library_index

    try:
        scope = libraries.effective_sources(
            conn, domain_path=domain.get("path") or domain["key"]
        )
    except ValueError as exc:
        # A stored subscription that would widen its parent's scope: report the
        # breakage instead of pretending the domain has no corpus.
        return {"libraries": 0, "sources": 0, "chunks": 0, "error": str(exc)}

    counted = library_index.count_scope(
        conn, domain_path=domain.get("path") or domain["key"], cache=cache
    )
    out = {
        "libraries": len(scope),
        "sources": sum(len(v) for v in scope.values()),
        "chunks": counted["chunks"],
    }
    if counted["errors"]:
        # An unreachable store is not an empty one: surface it next to the count.
        out["error"] = "; ".join(counted["errors"])
    return out


def _pillar_eval(conn: Any, domain: dict) -> dict:
    standards = domain_rubrics.effective_rubrics(
        conn, domain_path=domain.get("path") or domain["key"]
    )
    last = conn.execute(
        "SELECT MAX(e.scored_at) AS last FROM eval_runs e "
        "JOIN domains d ON d.id = e.rubric_domain_id "
        "WHERE d.path = %s",
        (domain.get("path") or domain["key"],),
    ).fetchone()
    return {
        "standards": len(standards),
        "own": len([s for s in standards if s["origin"] == "own"]),
        "last_run": (last or {}).get("last"),
    }


def _pillar_inbox(conn: Any, domain: dict) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE state = 'pending') AS pending, "
        "       MAX(submitted_at) AS newest "
        "FROM domain_proposals WHERE domain_id = %s",
        (domain["id"],),
    ).fetchone()
    return {
        "pending": (row or {}).get("pending", 0),
        "newest": (row or {}).get("newest"),
    }


def _template_readiness(conn: Any, domain: dict) -> Optional[dict]:
    """The anchored template's ruler resolution, or ``None`` when unreadable.

    Read as a *report*, never a gate: a domain whose template declares no rulers
    is a draft, not a broken domain, and the quality view is where that becomes
    visible. Instantiation is the place a ruler-less template is refused.
    """
    row = conn.execute(
        "SELECT schema FROM ontology_templates WHERE id = %s", (domain["template_id"],)
    ).fetchone()
    if row is None:
        return None
    schema = row["schema"]
    if isinstance(schema, str):
        import json as _json
        schema = _json.loads(schema)
    return template_readiness.readiness(
        conn, domain_path=domain.get("path") or domain["key"], schema=schema or {}
    )


def matrix(conn: Any, *, domains: list[dict], probed: Optional[dict] = None,
           with_quality: bool = True) -> list[dict]:
    """One row per domain: identity + tree depth + the four pillar summaries."""
    rows = []
    # One memo for the whole matrix: sub-domains inheriting the same grant must
    # not each re-count the same external store (ten rows, one round trip).
    scope_cache: dict = {}
    for domain in domains:
        # A domain row written before the tree existed may still have no path
        # (the backfill only touches rows present when it runs). A root's path
        # is its key, so this cannot invent a false hierarchy.
        path = domain.get("path") or domain["key"]
        # Computed once: the knowledge pillar may call out to an external store,
        # and asking twice per row would double that round trip.
        ontology = _pillar_ontology(conn, domain)
        knowledge = _pillar_knowledge(conn, domain, cache=scope_cache)
        evaluation = _pillar_eval(conn, domain)
        row_quality = (
            quality.all_metrics(conn, domain_key=domain["key"], namespace=path,
                                probed=probed,
                                template_readiness=_template_readiness(conn, domain))
            if with_quality else {}
        )
        rows.append(
            {
                "domain": {**domain, "path": path},
                "depth": max(0, path.count("/")),
                "ontology": ontology,
                "knowledge": knowledge,
                "eval": evaluation,
                "inbox": _pillar_inbox(conn, domain),
                "quality": row_quality,
                "gaps": gaps_for(
                    {"ontology": ontology, "knowledge": knowledge, "eval": evaluation},
                    row_quality,
                ),
            }
        )
    return rows


def gaps_for(pillars: dict, quality_metrics: Optional[dict] = None) -> list[str]:
    """Which pillars are empty, plus which quality ratios are below their floor.

    两类缺口刻意分开命名：``ontology`` 是"没有内容"，``quality:evidence`` 是
    "有内容但立不住"。合成一个词，就会有人用灌量把第二个也抹平。
    """
    gaps = []
    if (pillars["ontology"].get("curated_units") or 0) == 0:
        gaps.append("ontology")
    # Zero *chunks* is the gap — a subscription with nothing ingested is not
    # knowledge, it is a promise. But an *unreadable* store is not an empty one:
    # when the count could not be taken, reporting a gap would send someone to
    # rebuild a corpus that already exists. Unknown is not a gap; the page shows
    # the error itself (the row still renders it as a warning badge).
    knowledge = pillars["knowledge"]
    if not knowledge.get("error") and (knowledge.get("chunks") or 0) == 0:
        gaps.append("knowledge")
    if (pillars["eval"].get("standards") or 0) == 0:
        gaps.append("eval")
    # 质量缺口：只有"有物可算且不达标"才算；无物可算（value is None）不是缺口，
    # 那由对应柱的空态去表达，否则同一件事会被数两遍。
    for name, metric in (quality_metrics or {}).items():
        if name == "review_lag":
            if metric.get("over_threshold"):
                gaps.append("quality:review_lag")
            continue
        if name == "crosswalk":
            # 覆盖率不达标是缺口；两类"映射有问题"由 estate 单独追加（见
            # crosswalk_gaps），因为它们的处置动作不同：stale 要重验对接，
            # unconfirmed 要找人看。合成一个数，值班的人无从下手。
            if quality.below_threshold(name, metric):
                gaps.append("quality:crosswalk")
            continue
        if name == "template":
            # 模板一条尺子都没声明是**独立缺口**，不能靠 value=None 悄悄略过：
            # 一个本体与语料都非空、却完全无法被评的域，正是这条判据要抓的。
            if metric.get("undeclared"):
                gaps.append("quality:template")
            elif quality.below_threshold(name, metric):
                gaps.append("quality:template")
            continue
        if quality.below_threshold(name, metric):
            gaps.append(f"quality:{name}")
    return gaps


def filter_rows(rows: list[dict], gap: Optional[str]) -> list[dict]:
    """Rows still missing ``gap``; ``None``/empty keeps everything."""
    if not gap:
        return rows
    return [r for r in rows if gap in r["gaps"]]
