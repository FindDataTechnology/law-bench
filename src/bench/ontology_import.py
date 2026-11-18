"""Bulk ontology import: one validator, two modes (§3).

The rule that shapes this module: **the dry run and the real run must be the
same code path**. A preview computed by a lighter checker would be decoration —
it would say "40 rows fine" and the write would fail on row 7 for a reason the
preview never looked at. So ``plan()`` produces the whole verdict, and
``apply()`` consumes that verdict row by row. The only thing that can differ
between preview and write is the database changing in between, and then the row
is reported as an error rather than silently skipped.

Partial success is deliberate: a 20-row import with 2 bad rows writes 18. The
caller gets per-row results, never a single boolean.

Nothing here writes SQL. Every row goes through ``src.bench.authoring`` — the
kernel that gates the vocabulary and appends the event trail.
"""

from __future__ import annotations

from typing import Any, Optional

from . import authoring, keys

#: Marker used to flag units that came from smoke tests rather than curation.
#: Only ever used to *label* rows; nothing is auto-deleted.
SMOKE_MARKERS = ("smoke", "冒烟")


class ImportPayloadError(ValueError):
    """The payload is not shaped like an import (as opposed to a bad row)."""


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def parse_payload(payload: Any) -> tuple[list[dict], list[dict]]:
    """Split ``{"units": [...], "relationships": [...]}``; tolerate omissions."""
    if not isinstance(payload, dict):
        raise ImportPayloadError("import payload must be a JSON object with 'units' and/or 'relationships'")
    units = payload.get("units") or []
    rels = payload.get("relationships") or []
    if not isinstance(units, list):
        raise ImportPayloadError("'units' must be an array")
    if not isinstance(rels, list):
        raise ImportPayloadError("'relationships' must be an array")
    return units, rels


def is_smoke(unit: dict) -> bool:
    key = (_text(unit.get("external_key")) or "").lower()
    body = _text(unit.get("body")).lower()
    return any(m in key or m in body for m in SMOKE_MARKERS)


def plan(conn: Any, *, domain_key: str, payload: Any) -> list[dict]:
    """Per-row verdict: ``create`` / ``update`` / ``error`` + reason.

    A row that is already stored with the same external key is ``update`` (the
    kernel upserts, and its event says "update"), so re-importing a file is
    idempotent by construction rather than by a special case.
    """
    units, rels = parse_payload(payload)
    live_units = authoring.authoring_live_entities(conn, domain_key=domain_key)
    live = {e["external_key"] for e in live_units}
    live_kinds = {e["external_key"]: e["kind"] for e in live_units}
    rows: list[dict] = []

    for raw in units:
        if not isinstance(raw, dict):
            rows.append({"section": "units", "action": "error",
                         "reason": "row must be an object"})
            continue
        kind = _text(raw.get("kind"))
        key = _text(raw.get("external_key") or raw.get("key"))
        body = _text(raw.get("body"))
        label = {"section": "units", "kind": kind, "external_key": key}
        if not kind or not key or not body:
            rows.append({**label, "action": "error",
                         "reason": "kind, external_key and body are required"})
            continue
        # Same key discipline as extraction: a clause is never addressable by its
        # article number alone. Hand-written imports must not smuggle in keys the
        # extractor is no longer allowed to produce.
        from . import keys as key_mod

        if kind.endswith("clause") and "#" not in key:
            rows.append({**label, "action": "error",
                         "reason": "a clause key must be '<parent>#第N条'; a bare article "
                                   "number matches nearly every document"})
            continue
        try:
            # Ask the kernel's own gate rather than re-implementing the rule.
            authoring._gate_kind(
                conn,
                domain=authoring._load_domain(conn, domain_key=domain_key),
                kind=kind,
                vocab_key="entity_types",
            )
        except ValueError as exc:
            rows.append({**label, "action": "error", "reason": str(exc)})
            continue
        existed = authoring.authoring_get_unit(
            conn, domain_key=domain_key, kind=kind, external_key=key
        )
        rows.append({**label, "action": "update" if existed else "create",
                     "reason": None, "payload": raw})
        live.add(key)

    pending: set[str] = set()
    for raw in rels:
        if not isinstance(raw, dict):
            rows.append({"section": "relationships", "action": "error",
                         "reason": "row must be an object"})
            continue
        kind = _text(raw.get("kind"))
        from_key = _text(raw.get("from_key") or raw.get("from"))
        to_key = _text(raw.get("to_key") or raw.get("to"))
        label = {"section": "relationships", "kind": kind,
                 "external_key": f"{from_key}->{to_key}"}
        if not kind or not from_key or not to_key:
            rows.append({**label, "action": "error",
                         "reason": "kind, from_key and to_key are required"})
            continue
        domain = authoring._load_domain(conn, domain_key=domain_key)
        try:
            authoring._gate_kind(conn, domain=domain, kind=kind,
                                 vocab_key="relationship_kinds")
        except ValueError as exc:
            rows.append({**label, "action": "error", "reason": str(exc)})
            continue
        # Endpoints may be created earlier in this same payload.
        missing = [k for k in (from_key, to_key) if k not in live and k not in pending]
        if missing:
            rows.append({**label, "action": "error",
                         "reason": f"endpoint not a live entity of this domain: {', '.join(missing)}"})
            continue
        # Direction is domain policy ("a definition starts at a concept"), so the
        # pack supplies the rule. Kinds come from what this payload will create,
        # falling back to what the domain already holds.
        rule = keys.relationship_rule_for(domain_key)
        if rule is not None:
            kinds = {**live_kinds}
            kinds.update({u["external_key"]: u["kind"] for u in units
                          if isinstance(u, dict) and u.get("external_key")})
            reason = rule(kind, kinds.get(from_key, ""), kinds.get(to_key, ""))
            if reason:
                rows.append({**label, "action": "error", "reason": reason})
                continue
        ext = authoring.relationship_external_key(from_key=from_key, kind=kind, to_key=to_key)
        existed = authoring.authoring_get_unit(
            conn, domain_key=domain_key, kind=kind, external_key=ext
        )
        rows.append({**label, "action": "update" if existed else "create",
                     "reason": None, "payload": raw})
        pending.update((from_key, to_key))

    return rows


def apply(conn: Any, *, domain_key: str, rows: list[dict], operator: str) -> dict:
    """Write the planned rows that are writable; report every row.

    ``plan`` decided *what* each row is; this only performs it. A row that fails
    here (the data moved between preview and write) is reported as ``failed``
    with the kernel's own message — never dropped.
    """
    done: list[dict] = []
    for row in rows:
        if row["action"] == "error":
            done.append({**row, "result": "failed"})
            continue
        raw = row.get("payload") or {}
        try:
            if row["section"] == "units":
                existed = authoring.authoring_get_unit(
                    conn, domain_key=domain_key, kind=row["kind"],
                    external_key=row["external_key"],
                )
                if existed:
                    authoring.authoring_update_unit(
                        conn, domain_key=domain_key, kind=row["kind"],
                        external_key=row["external_key"], body=_text(raw.get("body")),
                        operator=operator,
                    )
                else:
                    authoring.authoring_create_unit(
                        conn, domain_key=domain_key, kind=row["kind"],
                        external_key=row["external_key"], body=_text(raw.get("body")),
                        operator=operator,
                    )
            else:
                from_key = _text(raw.get("from_key") or raw.get("from"))
                to_key = _text(raw.get("to_key") or raw.get("to"))
                authoring.authoring_create_relationship(
                    conn, domain_key=domain_key, kind=row["kind"],
                    from_key=from_key, to_key=to_key,
                    body=_text(raw.get("body")) or f"{from_key} {row['kind']} {to_key}",
                    operator=operator,
                )
        except ValueError as exc:
            done.append({**row, "result": "failed", "reason": str(exc)})
            continue
        done.append({**row, "result": row["action"]})
    return summarise(done)


def summarise(rows: list[dict]) -> dict:
    """Counts + the rows that need attention. Empty failure list means all good."""
    created = [r for r in rows if r.get("result") == "create"]
    updated = [r for r in rows if r.get("result") == "update"]
    failed = [r for r in rows if r.get("result") == "failed"]
    return {
        "rows": rows,
        "created": len(created),
        "updated": len(updated),
        "failed": len(failed),
        "failures": failed,
        "ok": not failed,
    }
