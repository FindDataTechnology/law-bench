"""Controlled-vocabulary tag dimensions for clauses, per contract type.

Universal dims (source/stance/strength/risk/mandatory) are shared across
all contract types (``contract_type=NULL`` in ``tag_dims``). Type-specific dims
belong to one contract type (``contract_type=<key>``), decoupled per type.
:func:`validate_tags` accepts universal + the given type's dims; free-form dims
accept any non-empty string. Tags are curatorial, NOT derived from the clause
body.

``scenario`` (业务场景) is a per-type controlled dim that captures the
transaction sub-type (e.g. ``sale`` -> 农产品买卖/消费品零售/工业品建材/...).
It replaces the former province ``region`` dimension: corpus analysis showed
clauses vary by sub-type, not geography, so province (provenance) was the wrong
axis. ``scenario`` is auto-tagged at extraction (body-judgeable, unlike
province) and drives tagged-clause assembly selection. Its vocab is seeded from
:mod:`src.clauses.scenario_vocab`.

The vocabulary is loaded from the ``tag_dims`` table at app startup via
:func:`load_vocab_from_db`, building ``TAG_VOCAB[contract_type][dim] = values``.
``register_tag_dim`` is the in-memory reuse-or-create governance gate (merge
values if the dim exists, else create) -- the seeder, extraction, and manual
entry all route through it so dims don't proliferate.
"""

from __future__ import annotations

TAG_CATEGORIES = ("来源", "利益倾向", "风险合规", "地域", "类型专属", "业务场景")

# TAG_VOCAB[contract_type][dim] = [allowed values].
# contract_type=None => universal (shared by all types).
# contract_type=<key> => type-specific (decoupled per type).
TAG_VOCAB: dict[str | None, dict[str, list[str]]] = {
    None: {
        "source": ["base", "tagged", "custom"],
        "stance": ["pro_a", "pro_b", "balanced"],
    }
}

# Lazy-load guard: once a DB-backed vocab has been loaded, the starter set is
# considered overridden and validate/normalize won't re-merge the module default.
_VOCAB_LOADED = False

# Dims that accept any non-empty string (not a controlled vocabulary).
# Populated from tag_dims.free_form at load. None by default since ``region``
# (province) was removed in favor of the controlled ``scenario`` dim.
FREE_FORM_TAGS: set[str] = set()


def register_tag_dim(
    contract_type: str | None,
    name: str,
    category: str = "类型专属",
    values: list[str] | None = None,
    free_form: bool = False,
    zh_label: str | None = None,
) -> None:
    """Register a tag dim in-memory (reuse-or-create governance).

    If ``(contract_type, name)`` already exists in ``TAG_VOCAB``, merge values
    (don't duplicate). Otherwise create. ``free_form`` dims are added to
    ``FREE_FORM_TAGS``.
    """
    vals = [str(v) for v in (values or [])]
    bucket = TAG_VOCAB.setdefault(contract_type, {})
    if name in bucket:
        merged = list(bucket[name])
        for v in vals:
            if v not in merged:
                merged.append(v)
        bucket[name] = merged
    else:
        bucket[name] = vals
    if free_form:
        FREE_FORM_TAGS.add(name)


def load_vocab_from_db(db=None) -> dict:
    """Load tag_dims into ``TAG_VOCAB`` (per-type) + ``FREE_FORM_TAGS``.

    Best-effort: if the DB/table is unreachable, the starter set remains.
    Sets ``_VOCAB_LOADED`` so validate/normalize can lazily refresh once.
    """
    global _VOCAB_LOADED
    from src.eval.db import connect

    try:
        conn = connect(db)
        try:
            rows = conn.execute(
                "SELECT name, contract_type, values, free_form FROM tag_dims"
            ).fetchall()
        finally:
            if db is None:
                conn.close()
    except Exception:  # noqa: BLE001
        return TAG_VOCAB
    for r in rows:
        ct = r["contract_type"]  # None for universal
        name = r["name"]
        vals = [str(v) for v in (r["values"] or [])]
        TAG_VOCAB.setdefault(ct, {})[name] = vals
        if r["free_form"]:
            FREE_FORM_TAGS.add(name)
    _VOCAB_LOADED = True
    return TAG_VOCAB


def _ensure_db_vocab(contract_type: str | None) -> None:
    """Lazily merge DB-backed type-specific dims into the in-memory vocab.

    Called from validate/normalize so a fresh process (script, MCP tool) sees
    persisted dims like ``legal_topic`` without an explicit load. One-shot per
    process via ``_VOCAB_LOADED``.
    """
    global _VOCAB_LOADED
    if _VOCAB_LOADED:
        return
    try:
        load_vocab_from_db()
    except Exception:  # noqa: BLE001 - never let validation crash on DB flake
        _VOCAB_LOADED = True


def validate_tags(tags: dict | None, contract_type: str | None = None) -> dict:
    """Return a clean tag dict: unknown keys dropped; bad values raise.

    Checks universal dims (``TAG_VOCAB[None]``) + type-specific dims
    (``TAG_VOCAB[contract_type]``). Free-form dims accept any non-empty string.
    ``scenario`` is lenient (any non-empty value kept) because it is
    LLM-suggested and governance-extended; its seeded vocab is advisory (UI
    dropdown) rather than a hard whitelist.

    >>> validate_tags({"stance": "pro_a", "mood": "happy"})
    {'stance': 'pro_a'}
    >>> validate_tags({"region": "吉林"})
    {}
    >>> validate_tags({"scenario": "农产品买卖"}, contract_type="sale")
    {'scenario': '农产品买卖'}
    >>> validate_tags({"stance": "pro_A"})
    Traceback (most recent call last):
        ...
    ValueError: invalid tag value: stance='pro_A'; allowed: ['pro_a', 'pro_b', 'balanced']
    """
    if not tags:
        return {}
    # Lazily merge DB-backed type-specific dims (legal_topic, etc.) so fresh
    # processes validate persisted tags correctly.
    _ensure_db_vocab(contract_type)
    universal = TAG_VOCAB.get(None, {})
    type_specific = TAG_VOCAB.get(contract_type, {}) if contract_type else {}
    out: dict[str, str] = {}
    for k, v in tags.items():
        vs = str(v)
        if not vs:
            continue
        # Resolve stance aliases for backward compatibility
        if k == "stance" and vs in ("pro_seller", "pro_buyer"):
            vs = "pro_a" if vs == "pro_seller" else "pro_b"
        if k == "scenario":
            out[k] = vs  # lenient: LLM-suggested/governed, keep any non-empty
        elif k in FREE_FORM_TAGS:
            out[k] = vs
        elif k in universal:
            if vs not in universal[k]:
                raise ValueError(
                    f"invalid tag value: {k}={v!r}; allowed: {universal[k]}"
                )
            out[k] = vs
        elif k in type_specific:
            if vs not in type_specific[k]:
                raise ValueError(
                    f"invalid tag value: {k}={v!r}; allowed: {type_specific[k]}"
                )
            out[k] = vs
        # else: drop unknown (not in universal or this type's vocab)
    return out


def tag_vocab_for_type(contract_type: str | None = None) -> dict[str, list[str]]:
    """Merged flat vocab for a contract type: universal + type-specific.

    Returns ``{dim: [allowed values]}`` for all dims valid for this type.
    Free-form dims (none by default) have an empty list.
    """
    merged: dict[str, list[str]] = {}
    merged.update(TAG_VOCAB.get(None, {}))
    if contract_type:
        merged.update(TAG_VOCAB.get(contract_type, {}))
    return merged


def register_legal_topic_dims(contract_type: str, criteria_names: list[str], db=None) -> None:
    """Register legal_topic dimension for a contract type based on rubric criteria.

    Each rubric criterion becomes a legal_topic value, establishing a 1-to-1
    mapping between rubric criteria and clause topics. This enables the
    self-iteration pipeline to target specific legal concepts when generating
    or selecting clauses.

    Args:
        contract_type: The contract type key (e.g., "sale", "lease")
        criteria_names: List of rubric criterion names (e.g., ["ownership_transfer", "risk_transfer"])
        db: Database connection (optional, uses default if None)
    """
    if not criteria_names:
        return

    # Register as type-specific dimension
    register_tag_dim(
        contract_type=contract_type,
        name="legal_topic",
        category="法律主题",
        values=criteria_names,
        free_form=False,
        zh_label="法律主题",
    )

    # Persist to database
    try:
        from src.eval.db import connect
        from psycopg.types.json import Jsonb

        conn = connect(db)
        try:
            conn.execute(
                "INSERT INTO tag_dims (name, contract_type, category, values, free_form, zh_label) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (name, contract_type) DO UPDATE SET values = EXCLUDED.values",
                ("legal_topic", contract_type, "法律主题", Jsonb(criteria_names), False, "法律主题"),
            )
            conn.commit()
        finally:
            if db is None:
                conn.close()
    except Exception:
        # If database persistence fails, in-memory registration still works
        pass
