"""Domain-scoped ontology resolution (change add-domain-tree-and-shared-libraries §3).

Two rules, both about inheritance, both easy to get subtly wrong:

- **Template vocabulary**: a child template ``extends`` a parent *version* and
  may only ADD vocabulary. Removing or renaming an inherited item is refused at
  save time, and instantiation validates the **effective** vocabulary (parent ∪
  child), not the child's delta — otherwise a child could "validate" while
  missing the vocabulary its parent guarantees.
- **Knowledge units**: ``namespace`` holds the domain path. A read for
  ``legal/contract-review`` resolves its own units first, then walks ancestors;
  the same ``(kind, external_key)`` in a nearer namespace wins. Siblings never
  participate because they are not on the chain.
"""

from __future__ import annotations

from typing import Any, Optional

from . import templates

#: Vocabulary keys that may be inherited and extended (never shrunk). The
#: tier/sensitivity vocabularies are platform-fixed, so inheritance only makes
#: sense for the domain-extensible ones.
EXTENSIBLE_KEYS = ("entity_types", "relationship_kinds")


class InheritanceError(ValueError):
    """A template tried to shrink or rename what its parent granted."""


def ancestors(path: str) -> list[str]:
    """``legal/a/b`` → ``['legal', 'legal/a', 'legal/a/b']`` (root first)."""
    parts = [p for p in (path or "").split("/") if p]
    return ["/".join(parts[: i + 1]) for i in range(len(parts))]


def resolve_template_schema(
    conn: Any, schema: dict
) -> dict:
    """Return the *effective* schema: the parent chain merged under ``schema``.

    ``schema['extends']`` is ``{"name": ..., "version": ...}``. A missing parent
    raises ``InheritanceError`` — silently treating it as "no inheritance" would
    let a typo drop a whole vocabulary.
    """
    if not isinstance(schema, dict):
        raise InheritanceError("schema must be a dict")
    ext = schema.get("extends")
    if not ext:
        return dict(schema)
    if not isinstance(ext, dict) or not ext.get("name") or not ext.get("version"):
        raise InheritanceError('extends must be {"name": ..., "version": ...}')
    parent = templates.get_template(
        conn, name=str(ext["name"]), version=int(ext["version"])
    )
    if parent is None:
        raise InheritanceError(
            f"parent template {ext['name']!r} v{ext['version']} not found"
        )
    parent_eff = resolve_template_schema(conn, dict(parent["schema"]))
    return merge_schema(parent_eff, schema)


def merge_schema(parent: dict, child: dict) -> dict:
    """Merge child over parent: extensible lists union, maps deep-merge.

    Raises :class:`InheritanceError` when the child drops an inherited item
    ("may add, may override a map entry, may not remove") or when the two sides
    answer to **different authorities**.

    The guard is on authority, not on the layer name. Layers rank how *specific*
    a vocabulary is (foundation → industry → domain); authority says who may
    change it. A foundation an industry template inherits from is a normal,
    intended relationship — refusing it would make the foundation layer
    pointless. What must never be merged is a platform-owned vocabulary with an
    externally-owned one: those two have separate release cycles, and a merge
    would force one side to accept the other's lifecycle. That relationship is a
    *mapping* (``aligned_with``), not inheritance.
    """
    parent_layer = templates.template_layer(parent)
    child_layer = templates.template_layer(child)
    parent_auth = templates.template_authority(parent)
    child_auth = templates.template_authority(child)
    if parent_auth != child_auth:
        raise InheritanceError(
            f"extends crosses vocabulary authorities: parent {parent_layer!r} is "
            f"{parent_auth!r}, child {child_layer!r} is {child_auth!r}. Only "
            "same-authority vocabularies may inherit; relate cross-authority "
            "types with 'aligned_with' instead (a mapping, not a merge)."
        )
    merged = dict(parent)
    for key in EXTENSIBLE_KEYS:
        pv = list(parent.get(key) or [])
        cv = list(child.get(key) or [])
        missing = [x for x in pv if x not in cv]
        if missing:
            raise InheritanceError(
                f"{key} may not drop inherited item(s): {', '.join(missing)}"
            )
        merged[key] = pv + [x for x in cv if x not in pv]
    for key in ("concept_structures", "corpus_declaration"):
        pm = parent.get(key) or {}
        cm = child.get(key) or {}
        if isinstance(pm, dict) and isinstance(cm, dict):
            merged[key] = {**pm, **cm}
        elif cm:
            merged[key] = cm
    for key, value in child.items():
        if key in ("extends",) or key in EXTENSIBLE_KEYS:
            continue
        if key in ("concept_structures", "corpus_declaration"):
            continue
        merged[key] = value
    # The effective schema never carries the extends link onward: it is resolved.
    merged.pop("extends", None)
    return merged


def validate_effective(conn: Any, schema: dict) -> list[str]:
    """Validate the resolved schema; returns problems (empty = valid)."""
    try:
        effective = resolve_template_schema(conn, schema)
    except InheritanceError as exc:
        return [str(exc)]
    return templates.validate_template_schema(effective)


def aligned_types(conn: Any, *, name: str, version: Optional[int] = None) -> dict[str, dict]:
    """Cross-layer equivalence declared by one template version.

    Returns ``{type: {"aligned_type", "target_template", "target_layer"}}``.
    A type with no declaration is simply absent — this never guesses. The
    declarations are *read*, never merged: the template's own vocabulary is
    unchanged, which is the whole point of not using ``extends`` across layers.
    """
    row = templates.get_template(conn, name=name, version=version)
    if row is None:
        return {}
    out: dict[str, dict] = {}
    for entry in (row["schema"] or {}).get("aligned_with") or []:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target_template")
        for local_type, target_type in (entry.get("type_map") or {}).items():
            out[local_type] = {
                "aligned_type": target_type,
                "target_template": target,
                "target_layer": entry.get("target_layer"),
            }
    return out


# ── knowledge units along the ancestor chain ─────────────────────────────────


def get_unit_inherited(
    conn: Any, *, kind: str, external_key: str, domain_path: str
) -> Optional[dict]:
    """Nearest-namespace-wins lookup along the ancestor chain."""
    for ns in reversed(ancestors(domain_path)):
        row = conn.execute(
            "SELECT id, kind, namespace, external_key, body, tags, attrs, tier, "
            "       source_path, provenance, derived_from, created_at, updated_at "
            "FROM knowledge_units WHERE kind = %s AND namespace = %s AND external_key = %s",
            (kind, ns, external_key),
        ).fetchone()
        if row is not None:
            return dict(row)
    return None


def list_units_inherited(
    conn: Any, *, domain_path: str, kind: Optional[str] = None, limit: int = 200
) -> list[dict]:
    """Every unit visible to ``domain_path``, with shadowing applied.

    A unit is shadowed when a nearer namespace defines the same
    ``(kind, external_key)``. The winner keeps its own namespace in the row, so
    the caller can always tell where a definition actually lives.
    """
    chain = ancestors(domain_path)
    params: list[Any] = [chain]
    sql = (
        "SELECT id, kind, namespace, external_key, body, tags, attrs, tier, "
        "       source_path, provenance, derived_from, created_at, updated_at "
        "FROM knowledge_units WHERE namespace = ANY(%s)"
    )
    if kind is not None:
        sql += " AND kind = %s"
        params.append(kind)
    rows = [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    depth = {ns: i for i, ns in enumerate(chain)}
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["kind"], row["external_key"])
        cur = best.get(key)
        if cur is None or depth.get(row["namespace"], -1) > depth.get(cur["namespace"], -1):
            best[key] = row
    ordered = sorted(
        best.values(), key=lambda r: (r["updated_at"], r["id"]), reverse=True
    )
    return ordered[:limit]
