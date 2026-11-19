"""Versioned ontology-template records: structural validation + CRUD.

A template is a versioned, append-only JSONB record: creating one writes
version 1, and every edit inserts a new row with ``max(version) + 1`` instead
of rewriting a historical row. The schema's controlled vocabularies are
checked against the kernel's single sources of truth so a structurally
incomplete template can neither be stored nor used to open a domain.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Rows are decoded from either dict-row or
plain tuple cursors, and JSONB is encoded/decoded with ``json.dumps``/
``json.loads``.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .promotion import SENSITIVITY_LEVELS
from .tiers import TIERS

REQUIRED_SCHEMA_KEYS = (
    "entity_types",
    "concept_structures",
    "relationship_kinds",
    "tier_vocabulary",
    "sensitivity_vocabulary",
    "corpus_declaration",
)

#: Ontology layers (change add-layered-ontology-templates). A template declares
#: which semantic layer its vocabulary belongs to; ``extends`` may only join two
#: templates of the same layer, so cross-layer semantics go through
#: ``aligned_with`` instead of inheritance.
LAYERS = ("foundation", "observation", "industry", "domain")

#: A template that declares no layer is its own legacy single-layer world.
#: Keeping it a pseudo-layer (rather than rejecting the save) preserves every
#: pre-layering template and still makes cross-layer inheritance impossible:
#: ``unlayered`` and any declared layer never compare equal.
UNLAYERED = "unlayered"

#: ``authority.kind``: ``platform`` owns the vocabulary here and may edit it;
#: ``external`` means a package/protocol owns it and this platform only imports.
AUTHORITY_KINDS = ("platform", "external")


_TEMPLATE_COLS = "id, name, version, schema, created_by, created_at"
_TEMPLATE_KEYS = ("id", "name", "version", "schema", "created_by", "created_at")
_LIST_KEYS = (
    "entity_types",
    "relationship_kinds",
    "tier_vocabulary",
    "sensitivity_vocabulary",
)


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _scalar(row: Any) -> Any:
    """First value of an aggregate row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _row_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _TEMPLATE_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "name": values[1],
        "version": values[2],
        "schema": _decode_jsonb(values[3]),
        "created_by": values[4],
        "created_at": _iso(values[5]),
    }


def template_layer(schema: dict) -> str:
    """The declared layer, or :data:`UNLAYERED` when the template predates layers.

    ``extends`` compares via this function, so a legacy template can still
    inherit another legacy template but can never join a declared layer.
    """
    value = (schema or {}).get("layer")
    return value if isinstance(value, str) and value else UNLAYERED


def external_edit_problem(*, existing: dict, new_schema: dict) -> Optional[str]:
    """Why an edit to an ``authority: external`` template must be refused.

    An external vocabulary's owner lives in another repository (today: the
    ``fd-open-data-protocol`` package, whose golden digest tests pin the release).
    Letting this platform edit it in place would fork the two silently, and
    nobody downstream could tell which side changed. The legal move is a new
    import, which produces a new version and leaves the old one byte-identical.

    Silent when ``existing`` is not external — including every pre-layering
    template, which declares no authority at all.
    """
    existing_schema = (existing or {}).get("schema") or existing or {}
    authority = existing_schema.get("authority") or {}
    if authority.get("kind") != "external":
        return None
    for key in ("entity_types", "relationship_kinds", "concept_structures"):
        if new_schema.get(key) != existing_schema.get(key):
            return (
                f"该模板的词表权威为 external（{authority.get('source')} "
                f"{authority.get('version')}）：'{key}' 不可就地修改。"
                "须以重新导入产生新版本（ownership 在别处，就地改会与上游分叉）。"
            )
    return None


def layer_change_problem(*, existing: dict, new_schema: dict) -> Optional[str]:
    """Why moving a template to a different layer must be refused.

    A layer change is a different template, not a different version: domains
    pin a version, and a version that silently switches layers would change what
    its children may inherit without any record of the decision.

    ``unlayered`` is the one exception, because it is not a layer — it is the
    absence of one, meaning "this template predates the concept". Adopting a
    layer for the first time is the migration, not a layer switch; refusing it
    would make the concept impossible to roll out to anything that already
    exists.
    """
    existing_schema = (existing or {}).get("schema") or existing or {}
    old = template_layer(existing_schema)
    new = template_layer(new_schema)
    if old == new:
        return None
    if old == UNLAYERED:
        return None  # first adoption: the migration, never a switch
    if new == UNLAYERED:
        return (
            f"模板已声明层 {old!r}，不可退回未声明层："
            "那一栏表达的是「分层概念出现之前」，不是一种可以后退的状态。"
        )
    return (
        f"模板的层不可在版本间变更（原 {old!r} → 新 {new!r}）："
        "换层须以新模板名创建，否则已锚定该版本的域会看到不同的继承规则。"
    )


def template_authority(schema: dict) -> str:
    """Who owns this vocabulary: ``platform``, ``external``, or ``legacy``.

    This — not the layer name — is what ``extends`` must compare. Layers rank
    specificity (a foundation feeding an industry template is normal); authority
    says who may release a change. Merging a platform vocabulary with an
    externally-owned one would force one side to accept the other's lifecycle,
    which is exactly what ``aligned_with`` exists to avoid.

    ``legacy`` is the pseudo-authority for a template that declares none: every
    pre-layering template is platform-owned by definition, so it inherits freely
    among its peers and never into an ``external`` one.
    """
    authority = (schema or {}).get("authority") or {}
    kind = authority.get("kind") if isinstance(authority, dict) else None
    return kind if isinstance(kind, str) and kind else "legacy"


def validate_layer_declarations(schema: dict) -> list[str]:
    """Layer, authority and ``aligned_with`` structure (pure, no connection).

    Deliberately silent when ``layer`` is absent: a pre-layering template keeps
    saving. Everything that *is* declared must be well-formed, because a
    half-declared layer would be read as "this template has no layer" by one
    code path and as its declared layer by another.
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return ["schema must be a dict"]

    layer = schema.get("layer")
    if layer is not None and layer not in LAYERS:
        problems.append(f"layer {layer!r} is not one of {list(LAYERS)}")

    authority = schema.get("authority")
    if authority is not None:
        if not isinstance(authority, dict):
            problems.append("authority must be a dict")
        else:
            kind = authority.get("kind")
            if kind not in AUTHORITY_KINDS:
                problems.append(
                    f"authority.kind {kind!r} is not one of {list(AUTHORITY_KINDS)}"
                )
            if kind == "external":
                for field in ("source", "version"):
                    if not authority.get(field):
                        problems.append(f"authority: external requires {field!r}")

    aligned = schema.get("aligned_with")
    if aligned is not None:
        if not isinstance(aligned, list) or not aligned:
            problems.append(
                "aligned_with must be a non-empty list of "
                '{"target_template": ..., "type_map": {...}}'
            )
        else:
            for entry in aligned:
                if not isinstance(entry, dict):
                    problems.append("aligned_with entries must be dicts")
                    continue
                if not entry.get("target_template"):
                    problems.append("aligned_with entry is missing 'target_template'")
                type_map = entry.get("type_map")
                if not isinstance(type_map, dict) or not type_map:
                    problems.append(
                        "aligned_with entry is missing a non-empty 'type_map'"
                    )
                elif not all(
                    isinstance(k, str) and isinstance(v, str)
                    for k, v in type_map.items()
                ):
                    problems.append("aligned_with type_map must map strings to strings")

    # A role is a relationship, never a second entity type: declaring both
    # `customer` as a type and `customer` as a relationship makes the same word
    # mean two things, and cross-system alignment then has no stable landing.
    entities = schema.get("entity_types")
    relations = schema.get("relationship_kinds")
    if isinstance(entities, list) and isinstance(relations, list):
        both = sorted(set(entities) & set(relations))
        if both:
            problems.append(
                "entity type(s) also declared as relationship kinds "
                f"(a role is a relationship, not a type): {', '.join(both)}"
            )
    return problems


def validate_template_schema(schema: dict) -> list[str]:
    """Return the list of structural problems; an empty list means valid.

    Checks the required keys, the shape of the four controlled vocabularies and
    the two declaration objects, and equality of the tier/sensitivity
    vocabularies with the kernel's canonical tuples. This is a pure function:
    it needs no connection.
    """
    problems: list[str] = []
    if not isinstance(schema, dict):
        return ["schema must be a dict"]

    for key in REQUIRED_SCHEMA_KEYS:
        if key not in schema:
            problems.append(f"missing required key: {key}")

    for key in _LIST_KEYS:
        if key not in schema:
            continue
        value = schema[key]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) for item in value)
        ):
            problems.append(f"{key} must be a non-empty list of strings")

    for key in ("concept_structures", "corpus_declaration"):
        if key in schema and not isinstance(schema[key], dict):
            problems.append(f"{key} must be a dict")

    tier_vocab = schema.get("tier_vocabulary")
    if isinstance(tier_vocab, list) and all(isinstance(v, str) for v in tier_vocab):
        if set(tier_vocab) != set(TIERS):
            problems.append(
                "tier_vocabulary must equal the platform vocabulary "
                f"{list(TIERS)}"
            )
    sensitivity_vocab = schema.get("sensitivity_vocabulary")
    if isinstance(sensitivity_vocab, list) and all(
        isinstance(v, str) for v in sensitivity_vocab
    ):
        if set(sensitivity_vocab) != set(SENSITIVITY_LEVELS):
            problems.append(
                "sensitivity_vocabulary must equal the platform vocabulary "
                f"{list(SENSITIVITY_LEVELS)}"
            )
    problems.extend(validate_layer_declarations(schema))
    return problems


def create_template(conn: Any, *, name: str, schema: dict, created_by: str) -> dict:
    """Insert version 1 of a new template; duplicate names are refused."""
    if not name:
        raise ValueError("name is required")
    problems = validate_template_schema(schema)
    if problems:
        raise ValueError("; ".join(problems))
    existing = conn.execute(
        "SELECT 1 FROM ontology_templates WHERE name = %s LIMIT 1", (name,)
    ).fetchone()
    if existing:
        raise ValueError(f"template {name!r} already exists")
    cur = conn.execute(
        f"""
        INSERT INTO ontology_templates (name, version, schema, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING {_TEMPLATE_COLS}
        """,
        (name, 1, json.dumps(schema), created_by),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def update_template(conn: Any, *, name: str, schema: dict, created_by: str) -> dict:
    """Append a new version (``max(version) + 1``); never rewrite a row.

    An as-yet unseen name gets version 1 (the literal ``max + 1`` with ``max``
    treated as 0); callers that require an existing template should guard with
    :func:`get_template` first.
    """
    if not name:
        raise ValueError("name is required")
    problems = validate_template_schema(schema)
    if problems:
        raise ValueError("; ".join(problems))
    previous = get_template(conn, name=name)
    if previous is not None:
        # Two edits that shape validation cannot see, because both need the
        # stored version to compare against: an external vocabulary may not be
        # edited in place, and a layer may not change between versions.
        for guard in (external_edit_problem, layer_change_problem):
            problem = guard(existing=previous, new_schema=schema)
            if problem:
                raise ValueError(problem)
    current_max = _scalar(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version "
            "FROM ontology_templates WHERE name = %s",
            (name,),
        ).fetchone()
    )
    new_version = int(current_max or 0) + 1
    cur = conn.execute(
        f"""
        INSERT INTO ontology_templates (name, version, schema, created_by)
        VALUES (%s, %s, %s, %s)
        RETURNING {_TEMPLATE_COLS}
        """,
        (name, new_version, json.dumps(schema), created_by),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def get_template(
    conn: Any, *, name: str, version: Optional[int] = None
) -> Optional[dict]:
    """Fetch one version of a template; ``version is None`` means the latest."""
    if version is not None:
        cur = conn.execute(
            f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
            "WHERE name = %s AND version = %s",
            (name, version),
        )
    else:
        cur = conn.execute(
            f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
            "WHERE name = %s ORDER BY version DESC LIMIT 1",
            (name,),
        )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_template_by_id(conn: Any, *, template_id: int) -> Optional[dict]:
    """Fetch the exact template row a domain was anchored to."""
    cur = conn.execute(
        f"SELECT {_TEMPLATE_COLS} FROM ontology_templates WHERE id = %s",
        (template_id,),
    )
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_templates(conn: Any) -> list[dict]:
    """One row per name: the latest version, ordered by name."""
    cur = conn.execute(
        f"""
        SELECT DISTINCT ON (name) {_TEMPLATE_COLS}
        FROM ontology_templates
        ORDER BY name, version DESC
        """
    )
    return [_row_to_dict(r) for r in cur.fetchall()]


def list_template_versions(conn: Any, *, name: str) -> list[dict]:
    """All versions of one name, ascending."""
    cur = conn.execute(
        f"SELECT {_TEMPLATE_COLS} FROM ontology_templates "
        "WHERE name = %s ORDER BY version ASC",
        (name,),
    )
    return [_row_to_dict(r) for r in cur.fetchall()]
