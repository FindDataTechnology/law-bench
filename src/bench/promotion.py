"""Client-agnostic promotion machine for external-registry entities.

An *external registry* (an upstream semantic layer, e.g. a wire entity graph)
is the identity master: every entity/relation it declares already owns a
stable primary key. The bench platform keeps **no second identity store** —
it mirrors registry declarations into knowledge units whose upsert identity is
``(kind, namespace, external_key)`` with ``external_key`` being the registry's
own stable id, and runs them through a human review ladder:

    bronze (machine pre-annotation, the landing tier of a graph sync)
      -> silver (annotations/tags completed by an operator)
      -> gold   (human verification passed; requires a reviewer identity)

Rules enforced here (contract 柏讯实体升格契约, bench-platform spec):

- Sync is idempotent: re-fetching an unchanged registry mutates no rows (no
  ``updated_at`` bump, no tier/provenance churn). Content changes update the
  mirrored body/attrs only — they never demote a promoted unit.
- Tier moves one way, one adjacent step at a time: bronze→silver,
  silver→gold. Gold never demotes on its own; a demotion is only possible as
  an explicit admin action (``force=True`` + a reviewer stamp) and otherwise
  raises :class:`TierTransitionError` (routes map it to HTTP 409).
- Promotion to gold requires a reviewer identity written into the unit's
  provenance (``review.reviewer`` / ``review.at`` / ``review.note``). Missing
  reviewer => refused. The reviewer is always the session identity of the
  operator — this module only ever receives it as an argument; the web layer
  must never accept it from a form field.
- ``export_gold`` assembles the registry writeback payload: the identity key,
  the ``tier``/``sensitivity`` markers, and the mirrored registry-field
  snapshot so the connector can address the upstream record. NOTE (contract
  gap, discovered from the real upstream entity API): the upstream CRUD
  surface accepts only registry-native fields (name/dataset/pk_columns/
  description/display metadata); it has NO writable ``tier``/``sensitivity``
  column today. The payload shape below is therefore *documented*, and the
  connector writeback encodes the promotion mark into a writable field until
  the upstream side adds first-class tier/sensitivity (see the internal
  wire-connector README).
- ``run_writeback`` calls an injected ``writeback_fn`` per gold payload. A
  payload is marked ``written_back`` ONLY when the call returns without
  raising; failures are recorded per unit and never abort the other units, and
  the result lists (succeeded/failed/skipped) reflect what actually happened.
  The registry key is the writeback idempotency key: a unit already marked
  written back is skipped on rerun unless ``force=True`` re-sends it (the
  idempotency key rides in the payload so an upstream that supports it can
  dedupe).

Traceability: every gold unit carries, in provenance, the registry origin
(``synced_from`` / ``synced_at``), the review stamp, and the writeback receipt
— so a gold unit can always be traced back to its source declaration, its
reviewer, and its writeback outcome.

The module is domain-neutral (kernel) and depends only on the sibling
``store`` and ``tiers`` modules of this package plus the standard library.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import store
from .tiers import TIER_RANK

# --- vocabulary -------------------------------------------------------------

#: Knowledge-unit kinds this machine syncs and promotes.
KIND_ENTITY = "entity"
KIND_RELATION = "relation"
PROMOTABLE_KINDS = (KIND_ENTITY, KIND_RELATION)

#: The one-way promotion ladder. ``raw`` (bulk corpus ingest) is intentionally
#: outside this machine; graph-sync units land at bronze.
CHAIN = ("bronze", "silver", "gold")
SYNC_TIER = CHAIN[0]

#: Sensitivity marker attached to gold payloads for the registry's ACL layer.
#: Kept as an attribute of the *promotion decision* (provenance), never of the
#: mirrored registry attrs, so a re-sync cannot erase it.
DEFAULT_SENSITIVITY = "internal"
SENSITIVITY_LEVELS = ("public", "internal", "confidential")


class TierTransitionError(ValueError):
    """Illegal tier move (demotion, skipped step, same-tier re-promotion)."""


class UnitNotFoundError(KeyError):
    """The (kind, namespace, external_key) triple is not in the unit store."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Round-trip through JSON so anything we persist into JSONB is storable."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


# --- registry snapshot rendering --------------------------------------------


def entity_external_key(node: dict) -> str:
    """Stable identity key for a registry entity node (the registry's own id)."""
    if "id" not in node or node["id"] is None:
        raise ValueError("registry entity node has no stable 'id'")
    return str(node["id"])


def relation_external_key(edge: dict) -> str:
    """Stable identity key for a registry relation edge (the registry's own id)."""
    if "id" not in edge or edge["id"] is None:
        raise ValueError("registry relation edge has no stable 'id'")
    return str(edge["id"])


def render_entity_body(node: dict) -> str:
    """Deterministic one-line text mirror of an entity node."""
    ds = node.get("dataset") or {}
    pk = ",".join(node.get("pk_columns") or [])
    return (
        f"entity {node.get('name')} | dataset "
        f"{ds.get('key') or ds.get('id')} rows={ds.get('row_count')} pk=[{pk}]"
    )


def render_relation_body(edge: dict) -> str:
    """Deterministic one-line text mirror of a relation edge (the four-tuple)."""
    return (
        f"relation {edge.get('from_entity_id')}.{edge.get('from_column')} "
        f"-({edge.get('kind')})-> "
        f"{edge.get('to_entity_id')}.{edge.get('to_column')}"
    )


# --- sync ---------------------------------------------------------------------


def _get_unit(conn: Any, *, kind: str, external_key: str, namespace: str) -> dict:
    unit = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=namespace
    )
    if unit is None:
        raise UnitNotFoundError(
            f"no {kind} unit {namespace!r}/{external_key!r} in the store"
        )
    return unit


def _merge_provenance(old: dict, new: dict) -> dict:
    """Shallow-merge provenance; promotion/review/writeback records survive a
    re-sync (sync-owned keys refresh, operator-owned keys are untouched)."""
    merged = {**old}
    for key, value in new.items():
        if key in ("synced_from", "synced_at") or key not in merged:
            merged[key] = value
    return merged


def _sync_one(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    body: str,
    attrs: dict,
    result: dict,
) -> None:
    existing = store.get_knowledge_unit(
        conn, kind=kind, external_key=external_key, namespace=namespace
    )
    stamp = {"synced_from": namespace, "synced_at": _now()}
    if existing is None:
        store.upsert_knowledge_unit(
            conn,
            kind=kind,
            external_key=external_key,
            namespace=namespace,
            body=body,
            tags={"registry": namespace, "origin": "graph_sync"},
            attrs=attrs,
            tier=SYNC_TIER,
            provenance=stamp,
        )
        result["created"].append(external_key)
        return
    if existing["body"] == body and existing["attrs"] == attrs:
        # Unchanged mirror: no write at all (idempotent — no updated_at bump).
        result["unchanged"].append(external_key)
        return
    # Content drifted upstream: refresh the mirror only. tier stays (never
    # demoted by sync), operator tags stay, provenance merges sync keys only.
    store.upsert_knowledge_unit(
        conn,
        kind=kind,
        external_key=external_key,
        namespace=namespace,
        body=body,
        tags=existing["tags"],
        attrs=attrs,
        tier=existing["tier"],
        source_path=existing["source_path"],
        provenance=_merge_provenance(existing["provenance"], stamp),
    )
    result["updated"].append(external_key)


def sync_graph(
    conn: Any,
    *,
    fetch_fn: Callable[[], dict],
    namespace: str,
) -> dict:
    """Mirror an external-registry entity graph into bronze knowledge units.

    ``fetch_fn()`` must return ``{"nodes": [...], "edges": [...]}`` in the
    registry's graph shape (entity nodes with id/name/dataset summary/
    pk_columns; relation edges with the four-tuple + kind). Idempotent: an
    unchanged second sync touches no rows.
    """
    if not namespace:
        raise ValueError("namespace is required")
    graph = fetch_fn() or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    result: dict = {
        "namespace": namespace,
        "nodes": len(nodes),
        "edges": len(edges),
        "created": [],
        "updated": [],
        "unchanged": [],
    }
    for node in nodes:
        _sync_one(
            conn,
            kind=KIND_ENTITY,
            external_key=entity_external_key(node),
            namespace=namespace,
            body=render_entity_body(node),
            attrs=dict(node),
            result=result,
        )
    for edge in edges:
        _sync_one(
            conn,
            kind=KIND_RELATION,
            external_key=relation_external_key(edge),
            namespace=namespace,
            body=render_relation_body(edge),
            attrs=dict(edge),
            result=result,
        )
    return result


# --- promotion ladder ---------------------------------------------------------


def _restamp(conn: Any, unit: dict, **overrides: Any) -> dict:
    """Re-upsert an existing unit with selective field overrides."""
    fields = {
        "kind": unit["kind"],
        "external_key": unit["external_key"],
        "namespace": unit["namespace"],
        "body": unit["body"],
        "tags": unit["tags"],
        "attrs": unit["attrs"],
        "tier": unit["tier"],
        "source_path": unit["source_path"],
        "provenance": unit["provenance"],
    }
    fields.update(overrides)
    return store.upsert_knowledge_unit(conn, **fields)


def annotate_unit(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    tags: Optional[dict] = None,
    attrs: Optional[dict] = None,
    reviewer: Optional[str] = None,
) -> dict:
    """Attach operator annotations (tags + attrs) to a mirrored unit.

    Annotation placement is sync-safe by construction: operator ``tags`` merge
    into the unit's tags and operator ``attrs`` into
    ``provenance.annotations`` — the mirrored ``attrs`` column itself always
    holds the *registry snapshot verbatim*, so the next ``sync_graph`` can
    overwrite it without losing any human annotation. Annotations do not
    change the tier; the silver step of the ladder is where the queue expects
    them to have been completed. The stamp of who annotated (``annotated_by``)
    is provenance-owned, separate from the mirror.
    """
    if kind not in PROMOTABLE_KINDS:
        raise ValueError(f"kind {kind!r} is not promotable by this machine")
    unit = _get_unit(conn, kind=kind, external_key=external_key, namespace=namespace)
    prov = dict(unit["provenance"])
    if reviewer:
        prov["annotated_by"] = reviewer
        prov["annotated_at"] = _now()
    if attrs:
        prov["annotations"] = {**(prov.get("annotations") or {}), **_json_safe(attrs)}
    updated = _restamp(
        conn,
        unit,
        tags={**unit["tags"], **(tags or {})},
        provenance=prov,
    )
    return updated


def promote_unit(
    conn: Any,
    *,
    kind: str,
    external_key: str,
    namespace: str,
    to_tier: str,
    reviewer: Optional[str] = None,
    note: str = "",
    sensitivity: Optional[str] = None,
    force: bool = False,
) -> dict:
    """Move one unit along the bronze→silver→gold ladder.

    - Only adjacent forward steps without ``force``: bronze→silver,
      silver→gold. Skipping a step or demoting raises
      :class:`TierTransitionError` (HTTP 409 at the route layer).
    - ``to_tier='gold'`` requires ``reviewer`` (the session identity —
      never a form field); missing reviewer raises ``ValueError`` and the
      unit stays untouched.
    - Demotion (gold→silver etc.) is refused unless ``force=True`` AND a
      ``reviewer`` is given, marking it an explicit admin action recorded in
      provenance (``demoted_by``).
    - The review stamp (reviewer / at / note / sensitivity) is persisted into
      provenance so every gold unit traces back to its human verification.
    """
    if kind not in PROMOTABLE_KINDS:
        raise ValueError(f"kind {kind!r} is not promotable by this machine")
    if to_tier not in CHAIN:
        raise TierTransitionError(
            f"tier {to_tier!r} is outside the promotion ladder {CHAIN}"
        )
    unit = _get_unit(conn, kind=kind, external_key=external_key, namespace=namespace)
    current = unit["tier"]
    if current == to_tier:
        raise TierTransitionError(f"unit already at tier {to_tier!r}")
    step = CHAIN.index(to_tier) - CHAIN.index(current)
    moving_up = TIER_RANK[to_tier] < TIER_RANK[current]

    if moving_up:
        if step != 1:
            raise TierTransitionError(
                f"tier moves one adjacent step at a time: {current}→{to_tier} "
                "skips a step; verify at each tier before promoting"
            )
        if to_tier == "gold":
            if not reviewer:
                raise ValueError(
                    "gold promotion requires a reviewer identity (the session "
                    "operator stamp); refusing to promote unverified"
                )
            if sensitivity is not None and sensitivity not in SENSITIVITY_LEVELS:
                raise ValueError(
                    f"unknown sensitivity level {sensitivity!r}; "
                    f"expected one of {SENSITIVITY_LEVELS}"
                )
            prov = dict(unit["provenance"])
            prov["review"] = {
                "reviewer": reviewer,
                "at": _now(),
                "note": note,
            }
            prov["sensitivity"] = sensitivity or DEFAULT_SENSITIVITY
            return _restamp(conn, unit, tier="gold", provenance=prov)
        # bronze→silver: annotation step, operator stamp optional.
        prov = dict(unit["provenance"])
        if reviewer:
            prov.setdefault("silver_by", reviewer)
            prov["silver_at"] = _now()
        return _restamp(conn, unit, tier="silver", provenance=prov)

    # Moving down the ladder (demotion): explicit admin action only.
    if not force:
        raise TierTransitionError(
            f"{current}→{to_tier} would demote a {current} unit; tiers promote "
            "one way (bronze→silver→gold). Use force=True with a reviewer to "
            "record an explicit admin demotion."
        )
    if not reviewer:
        raise ValueError("an admin demotion requires a reviewer identity stamp")
    prov = dict(unit["provenance"])
    prov["demoted"] = {
        "by": reviewer,
        "at": _now(),
        "from": current,
        "to": to_tier,
        "note": note,
    }
    return _restamp(conn, unit, tier=to_tier, provenance=prov)


# --- gold export (registry writeback payloads) ----------------------------------


def export_gold(conn: Any, namespace: str, *, limit: int = 1000) -> list[dict]:
    """Assemble writeback payloads for every gold unit in ``namespace``.

    Payload shape (see module docstring for the contract-gap note — the
    upstream entity API mirrors registry-native fields only, no tier column):

        {
          "idempotency_key":   "<namespace>/<kind>/<external_key>",  # registry
          "registry_namespace": namespace,                           #   key is
          "kind":              "entity" | "relation",                # the
          "external_key":      "<registry stable id>",               # idempotency
          "tier":              "gold",                               # marker
          "sensitivity":       "public|internal|confidential",       # marker
          "registry_fields":   { ...node/edge snapshot... },         # addressable
          "review":            {"reviewer", "at", "note"} | None,    # trace
          "written_back":      bool,                                 # current state
        }
    """
    payloads: list[dict] = []
    for kind in PROMOTABLE_KINDS:
        for unit in store.list_knowledge_units(
            conn, kind=kind, namespace=namespace, tier="gold", limit=limit
        ):
            prov = unit["provenance"] or {}
            payloads.append(
                {
                    "idempotency_key": f"{namespace}/{kind}/{unit['external_key']}",
                    "registry_namespace": namespace,
                    "kind": kind,
                    "external_key": unit["external_key"],
                    "tier": "gold",
                    "sensitivity": prov.get("sensitivity", DEFAULT_SENSITIVITY),
                    "registry_fields": unit["attrs"],
                    "review": prov.get("review"),
                    "written_back": bool(prov.get("written_back")),
                }
            )
    return payloads


# --- writeback -------------------------------------------------------------------


def _record_writeback(conn: Any, unit: dict, *, ok: bool, receipt: Any, error: Any,
                      payload: dict) -> dict:
    """Persist one writeback outcome into the unit's provenance.

    Failure records the attempt but never marks the unit written back (contract:
    回写失败不误标已回写). Success marks ``written_back=True`` plus the receipt
    reference, keyed by the registry idempotency key.
    """
    prov = dict(unit["provenance"])
    attempt = {
        "at": _now(),
        "ok": ok,
        "idempotency_key": payload["idempotency_key"],
    }
    if ok:
        prov["written_back"] = True
        prov["written_back_at"] = attempt["at"]
        prov["writeback_idempotency_key"] = payload["idempotency_key"]
        prov["writeback_receipt"] = _json_safe(receipt)
    else:
        prov["written_back"] = False  # honest, explicit: NOT written back
        prov["last_writeback_error"] = str(error)
    prov["last_writeback"] = attempt
    return _restamp(conn, unit, provenance=prov)


def run_writeback(
    conn: Any,
    namespace: str,
    writeback_fn: Callable[[dict], Any],
    *,
    force: bool = False,
    limit: int = 1000,
) -> dict:
    """Push every gold payload in ``namespace`` back through ``writeback_fn``.

    - Per payload: call ``writeback_fn(payload)``. Return value (if any) is
      stored as the receipt reference; raising anything counts as failure.
    - Success marks the unit written back; failure keeps it un-marked with a
      recorded error — the rest of the batch still runs (no abort).
    - Idempotent by registry key: a unit already marked written back is
      *skipped* on rerun (no second push, so no duplicate rows upstream).
      ``force=True`` re-sends, with the idempotency key riding in the payload.
    - The returned dict states exactly what happened:
      ``{"succeeded": [...], "failed": [{..., "error"}], "skipped": [...],
         "counts": {...}}``.
    """
    payloads = export_gold(conn, namespace, limit=limit)
    succeeded: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []
    for payload in payloads:
        unit = _get_unit(
            conn,
            kind=payload["kind"],
            external_key=payload["external_key"],
            namespace=namespace,
        )
        if payload["written_back"] and not force:
            skipped.append(
                {
                    "kind": payload["kind"],
                    "external_key": payload["external_key"],
                    "reason": "already written back (registry key is the "
                              "idempotency key; force=True to re-send)",
                }
            )
            continue
        try:
            receipt = writeback_fn(payload)
        except Exception as exc:  # noqa: BLE001 — any error means "not written"
            _record_writeback(
                conn, unit, ok=False, receipt=None, error=exc, payload=payload
            )
            failed.append(
                {
                    "kind": payload["kind"],
                    "external_key": payload["external_key"],
                    "error": str(exc),
                }
            )
            continue
        _record_writeback(
            conn, unit, ok=True, receipt=receipt, error=None, payload=payload
        )
        succeeded.append(
            {
                "kind": payload["kind"],
                "external_key": payload["external_key"],
                "receipt": _json_safe(receipt),
            }
        )
    return {
        "namespace": namespace,
        "attempted": len(payloads),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "counts": {
            "succeeded": len(succeeded),
            "failed": len(failed),
            "skipped": len(skipped),
        },
    }


# --- queue view (for the web layer) ----------------------------------------------


def promotion_queue(
    conn: Any,
    *,
    namespace: Optional[str] = None,
    kind: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Paged promotion queue plus per (namespace, kind, tier) counts.

    Each unit row is decorated with the fields the queue page needs: current
    tier, reviewer (if verified), sensitivity, and writeback state — all read
    from provenance so nothing is duplicated outside the unit row.
    """
    # Counts aggregate over namespace+tier (kind is a dimension of the
    # aggregate, so it must not filter it); the paged list adds the kind filter.
    count_where, count_params = [], []
    unit_where, unit_params = [], []
    if namespace is not None:
        count_where.append("namespace = %s")
        count_params.append(namespace)
        unit_where.append("namespace = %s")
        unit_params.append(namespace)
    if tier is not None:
        count_where.append("tier = %s")
        count_params.append(tier)
        unit_where.append("tier = %s")
        unit_params.append(tier)
    if kind is not None:
        unit_where.append("kind = %s")
        unit_params.append(kind)
    # The aggregate already filters ``kind IN (...)``; operator filters are
    # ANDed on top of it (" AND ...", never a second WHERE).
    counts_clause = (" AND " + " AND ".join(count_where)) if count_where else ""
    unit_clause = (" WHERE " + " AND ".join(unit_where)) if unit_where else ""

    cur = conn.execute(
        "SELECT namespace, kind, tier, count(*) AS n FROM knowledge_units"
        " WHERE kind IN (%s, %s)" + counts_clause
        + " GROUP BY namespace, kind, tier ORDER BY namespace, kind, tier",
        (KIND_ENTITY, KIND_RELATION, *count_params),
    )
    counts = [
        dict(r) if isinstance(r, dict)
        else {"namespace": r[0], "kind": r[1], "tier": r[2], "n": r[3]}
        for r in cur.fetchall()
    ]
    if kind is not None:
        total = sum(c["n"] for c in counts if c["kind"] == kind)
    else:
        total = sum(c["n"] for c in counts)

    cur = conn.execute(
        "SELECT id, kind, namespace, external_key, body, tags, attrs, tier, "
        "provenance, updated_at FROM knowledge_units"
        + unit_clause
        + " ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
        (*unit_params, limit, offset),
    )
    rows = cur.fetchall()
    units = []
    for row in rows:
        if isinstance(row, dict):
            r = dict(row)
            prov = r.get("provenance") or {}
            if isinstance(prov, str):
                prov = json.loads(prov)
            units.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "namespace": r["namespace"],
                    "external_key": r["external_key"],
                    "body": r["body"],
                    "tier": r["tier"],
                    "tags": json.loads(r["tags"]) if isinstance(r.get("tags"), str) else (r.get("tags") or {}),
                    "reviewer": (prov.get("review") or {}).get("reviewer"),
                    "review_at": (prov.get("review") or {}).get("at"),
                    "sensitivity": prov.get("sensitivity"),
                    "written_back": bool(prov.get("written_back")),
                    "last_writeback_error": prov.get("last_writeback_error"),
                    "synced_from": prov.get("synced_from"),
                    "updated_at": r["updated_at"],
                }
            )
        else:
            prov = json.loads(row[8] or "{}")
            units.append(
                {
                    "id": row[0],
                    "kind": row[1],
                    "namespace": row[2],
                    "external_key": row[3],
                    "body": row[4],
                    "tier": row[7],
                    "tags": json.loads(row[5] or "{}"),
                    "reviewer": (prov.get("review") or {}).get("reviewer"),
                    "review_at": (prov.get("review") or {}).get("at"),
                    "sensitivity": prov.get("sensitivity"),
                    "written_back": bool(prov.get("written_back")),
                    "last_writeback_error": prov.get("last_writeback_error"),
                    "synced_from": prov.get("synced_from"),
                    "updated_at": row[9],
                }
            )
    return {"counts": counts, "total": total, "limit": limit, "offset": offset, "units": units}
