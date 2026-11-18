"""Read-only projection of a domain's ontology ledger.

The ledger answers one question for a domain owner: *what does this domain's
ontology actually look like right now?* It is deliberately a projection, not a
store. Every layer reads pre-existing tables and reports what is there:

- **declaration** — the template row the domain is anchored to (name, version,
  vocabularies) from ``ontology_templates``;
- **curation** — what has actually been written into the domain's namespace in
  ``knowledge_units``, with the anchored vocabulary used only to label each
  kind's lane (entity / relationship / out-of-vocabulary);
- **publication** — the immutable snapshots already frozen in
  ``ontology_publications``;
- **consumption** — the registered consumers bound to the domain and their
  latest pull footprint from the append-only ``distribution_pull_events``.

Why four read-only layers instead of new tables or a second publication
surface: the ledger has no content of its own. Any copy it kept would be a
second truth that drifts from the kernel the moment an authoring write lands.
Projecting the four authoritative tables on demand means the page can never
disagree with the machine pull surface, and opening the ledger performs no
write at all (a ledger that rewrote its own cache would violate the spec's
"opening the ledger writes nothing" rule).

Why the digest is single-source: a publication's ``digest`` anchors the
content-only manifest frozen at publish time. Recomputing it here — even with
the same canonical-JSON helper — would make the ledger a second digest
producer, so a later change to the canonical form could make the page and the
pull surface disagree about a version that never changed. This module therefore
returns the stored ``digest`` verbatim and never imports the digest helper.

Consistency reconciliation (``reconcile``) is facts only: it reports unused
vocabulary kinds, out-of-vocabulary kinds present in the DB, and whether the
anchored template version is stale. It never fixes, migrates, or publishes
anything; the page decides what to say, and the module returns an i18n key
instead of prose.

Style: borrowed connection (never opened or closed here), ``%s`` placeholders,
no writes and no ``conn.commit()`` ever. Rows are decoded from either dict-row
or plain tuple cursors, and JSONB is decoded with ``json.loads`` when the
driver hands back text.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import authoring, templates

# Honest provenance labels: each layer names the exact source the page should
# show next to it, so a reader can trace every number back to one table set.
SOURCE_DECLARATION = "ontology_templates"
SOURCE_CURATION = "knowledge_units"
SOURCE_PUBLICATION = "ontology_publications"
SOURCE_CONSUMPTION = "distribution_consumers + distribution_pull_events"

# Lane labels for the per-kind distribution (the template vocabulary decides
# which lane a kind belongs to; anything else is flagged out of vocabulary).
LANE_ENTITY = "entity"
LANE_RELATIONSHIP = "relationship"
LANE_OUT_OF_VOCAB = "out_of_vocab"

# Zero-filled tier histogram shape (CHECK-constrained to these four tiers in
# ``src/bench/store.py::BENCH_SCHEMA``).
_TIER_ORDER = ("raw", "bronze", "silver", "gold")

# i18n keys the page renders for the reconciliation verdict. This module never
# carries page copy; it names the key only.
SUMMARY_CONSISTENT = "ledger.reconcile.consistent"
SUMMARY_GAPS = "ledger.reconcile.gaps"


# ------------------------------------------------------------------ helpers


def _decode_jsonb(val: Any) -> Any:
    """JSONB may arrive as dict/list (dict-row + psycopg jsonb) or as text."""
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _scalar(row: Any) -> Any:
    """First value of a single-column row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _values(row: Any, keys: tuple[str, ...]) -> list[Any]:
    """Row values in ``keys`` order; supports dict rows and tuple rows."""
    if isinstance(row, dict):
        return [row[k] for k in keys]
    return list(row)


def _string_list(val: Any) -> list[str]:
    """A schema vocabulary as a list of strings; anything unusable is empty."""
    if not isinstance(val, list):
        return []
    return [item for item in val if isinstance(item, str)]


def _anchored_template(conn: Any, *, domain: dict) -> Optional[dict]:
    """The exact template row the domain is anchored to, or ``None``."""
    template_id = domain.get("template_id")
    if template_id is None:
        return None
    return templates.get_template_by_id(conn, template_id=template_id)


def _latest_template_version(conn: Any, *, name: Optional[str]) -> Optional[int]:
    """``max(version)`` among rows sharing ``name``; ``None`` when unknown."""
    if not name:
        return None
    row = conn.execute(
        "SELECT MAX(version) AS latest_version FROM ontology_templates "
        "WHERE name = %s",
        (name,),
    ).fetchone()
    value = _scalar(row)
    return int(value) if value is not None else None


def _schema_vocabularies(
    tmpl: Optional[dict],
) -> tuple[list[str], list[str], list[str], list[str]]:
    """``(entity_types, relationship_kinds, tier_vocabulary, sensitivity_vocabulary)``.

    A missing template or a non-dict schema yields empty lists rather than an
    exception: the ledger must be able to render "no template anchor".
    """
    schema = (tmpl or {}).get("schema")
    if not isinstance(schema, dict):
        schema = {}
    return (
        _string_list(schema.get("entity_types")),
        _string_list(schema.get("relationship_kinds")),
        _string_list(schema.get("tier_vocabulary")),
        _string_list(schema.get("sensitivity_vocabulary")),
    )


def _lane(kind: str, *, entity_types: list[str], relationship_kinds: list[str]) -> str:
    """Which vocabulary lane a stored kind belongs to (entity wins a tie)."""
    if kind in entity_types:
        return LANE_ENTITY
    if kind in relationship_kinds:
        return LANE_RELATIONSHIP
    return LANE_OUT_OF_VOCAB


def _dedupe(values: list[str]) -> list[str]:
    """Stable dedupe preserving first-seen (declared vocabulary) order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


# --------------------------------------------------------------------- layers


def declaration_layer(conn: Any, *, domain: dict) -> dict:
    """The domain's template declaration: name, anchored version, vocabularies.

    Reads the exact template row named by ``domain["template_id"]`` (never the
    latest row for that name — a later template version must not retroactively
    change what this domain declares). ``latest_version`` is computed among
    rows sharing the template *name* so the page can flag a stale anchor.

    A missing anchored row never raises: ``has_template`` is ``False``, the
    ``template`` fields are ``None`` and every vocabulary is empty, which is
    exactly the "no template anchor" state the page needs to explain.
    """
    anchored_version = int(domain.get("template_version") or 0)
    tmpl = _anchored_template(conn, domain=domain)

    if tmpl is None:
        return {
            "template": {
                "id": domain.get("template_id"),
                "name": None,
                "version": None,
                "latest_version": None,
                "is_latest": False,
            },
            "has_template": False,
            "entity_types": [],
            "relationship_kinds": [],
            "tier_vocabulary": [],
            "sensitivity_vocabulary": [],
            "template_version": anchored_version,
            "source": SOURCE_DECLARATION,
        }

    latest_version = _latest_template_version(conn, name=tmpl["name"])
    if latest_version is None:
        latest_version = int(tmpl["version"])
    entity_types, relationship_kinds, tier_vocabulary, sensitivity_vocabulary = (
        _schema_vocabularies(tmpl)
    )
    return {
        "template": {
            "id": tmpl["id"],
            "name": tmpl["name"],
            "version": int(tmpl["version"]),
            "latest_version": latest_version,
            "is_latest": int(tmpl["version"]) == latest_version,
        },
        "has_template": True,
        "entity_types": entity_types,
        "relationship_kinds": relationship_kinds,
        "tier_vocabulary": tier_vocabulary,
        "sensitivity_vocabulary": sensitivity_vocabulary,
        "template_version": anchored_version,
        "source": SOURCE_DECLARATION,
    }


def curation_layer(conn: Any, *, domain: dict, recent_limit: int = 5) -> dict:
    """What is actually curated in the domain namespace.

    ``total``, ``by_kind`` and ``by_tier`` count every stored row in the
    namespace, soft-deleted ones included — the ledger's job is to report the
    database as it is, and ``deleted`` carries the soft-deleted subset
    separately so the page can say "N units, of which M deleted". Hard-deleted
    rows never exist (authoring only soft-deletes).

    ``by_kind`` lists only kinds that exist. A declared-but-unused kind is a
    coverage gap, not a zero row: it belongs to :func:`reconcile`.
    """
    namespace = domain.get("key")

    counts_row = conn.execute(
        "SELECT COUNT(*) AS total, "
        "COUNT(*) FILTER (WHERE tags->>'deleted' = 'true') AS deleted "
        "FROM knowledge_units WHERE namespace = %s",
        (namespace,),
    ).fetchone()
    total, deleted = _values(counts_row, ("total", "deleted"))

    kinds_cur = conn.execute(
        "SELECT kind, COUNT(*) AS n FROM knowledge_units "
        "WHERE namespace = %s GROUP BY kind ORDER BY n DESC, kind ASC",
        (namespace,),
    )
    kind_counts = [
        (kind, int(count))
        for kind, count in (
            _values(row, ("kind", "n")) for row in kinds_cur.fetchall()
        )
    ]

    tmpl = _anchored_template(conn, domain=domain)
    entity_types, relationship_kinds, _tiers, _sensitivities = _schema_vocabularies(
        tmpl
    )
    by_kind = [
        {
            "kind": kind,
            "count": count,
            "lane": _lane(
                kind,
                entity_types=entity_types,
                relationship_kinds=relationship_kinds,
            ),
        }
        for kind, count in kind_counts
    ]

    tier_counts = {tier: 0 for tier in _TIER_ORDER}
    tier_cur = conn.execute(
        "SELECT tier, COUNT(*) AS n FROM knowledge_units "
        "WHERE namespace = %s GROUP BY tier",
        (namespace,),
    )
    for row in tier_cur.fetchall():
        tier, count = _values(row, ("tier", "n"))
        if tier in tier_counts:
            tier_counts[tier] = int(count)

    try:
        recent_events = authoring.authoring_events_for(
            conn, domain_id=domain.get("id"), limit=recent_limit
        )
    except Exception:
        recent_events = []

    # ``rows`` is the authoring-shaped projection of the same facts: the union
    # of the DECLARED vocabulary (in declaration order, count 0 when unused)
    # and the kinds that exist but are out of vocabulary. by_kind answers
    # "what is in the database"; rows answers "what can I write next", which is
    # what the console's curation layer links to. A declared-but-unused kind is
    # rendered as a zero row here on purpose: on the authoring surface it is a
    # hole to fill, and only the reconcile panel treats it as a gap.
    seen: set[str] = set()
    rows: list[dict] = []
    for lane, kinds in (
        ("entity", entity_types),
        ("relationship", relationship_kinds),
    ):
        for kind in kinds:
            seen.add(kind)
            rows.append(
                {"kind": kind, "lane": lane, "count": int(dict(kind_counts).get(kind, 0))}
            )
    for kind, count in kind_counts:
        if kind not in seen:
            rows.append({"kind": kind, "lane": "out", "count": int(count)})

    return {
        "total": int(total or 0),
        "by_kind": by_kind,
        "rows": rows,
        "by_tier": tier_counts,
        "recent_events": recent_events,
        "deleted": int(deleted or 0),
        "source": SOURCE_CURATION,
    }


def _publication_row(row: Any) -> dict:
    """Project one publication row onto the ledger surface (digest verbatim)."""
    version, digest, published_at, published_by, changelog = _values(
        row,
        ("version", "digest", "published_at", "published_by", "changelog"),
    )
    return {
        "version": int(version),
        "digest": digest,
        "published_at": _iso(published_at),
        "published_by": published_by,
        "changelog": _decode_jsonb(changelog),
    }


def publication_layer(conn: Any, *, domain: dict, history_limit: int = 20) -> dict:
    """The domain's immutable publication snapshots, newest first.

    ``digest`` is copied out of ``ontology_publications`` verbatim: this module
    never recomputes it, so the ledger and the machine pull surface can only
    ever report the same anchor for the same version.
    """
    limit = max(0, int(history_limit))
    cur = conn.execute(
        "SELECT version, digest, published_at, published_by, changelog "
        "FROM ontology_publications WHERE domain_id = %s "
        "ORDER BY version DESC LIMIT %s",
        (domain.get("id"), limit),
    )
    history = [_publication_row(row) for row in cur.fetchall()]
    return {
        "has_publication": bool(history),
        "latest": history[0] if history else None,
        "history": history,
        "source": SOURCE_PUBLICATION,
    }


def _last_pull(
    conn: Any, *, consumer_id: Any, domain_key: Optional[str]
) -> Optional[dict]:
    """Newest recorded pull for one consumer scoped to this domain, or ``None``.

    ``distribution_pull_events`` only holds successful pulls that resolved a
    publication, so a row here is evidence, never an inference; no row is
    "never pulled".
    """
    if consumer_id is None or not domain_key:
        return None
    row = conn.execute(
        "SELECT version, happened_at FROM distribution_pull_events "
        "WHERE consumer_id = %s AND domain_key = %s "
        "ORDER BY happened_at DESC, id DESC LIMIT 1",
        (consumer_id, domain_key),
    ).fetchone()
    if row is None:
        return None
    version, happened_at = _values(row, ("version", "happened_at"))
    return {"version": int(version), "happened_at": _iso(happened_at)}


def consumption_layer(conn: Any, *, domain: dict) -> dict:
    """Consumers bound to this domain plus their latest pull footprint.

    ``token_hash`` is never selected — not the digest, not a prefix. The page
    has no business showing credential material (the spec forbids it), and the
    only credential fact the ledger exposes is the derived ``revoked`` flag.
    """
    domain_key = domain.get("key")
    cur = conn.execute(
        "SELECT id, name, domains, created_at, revoked_at "
        "FROM distribution_consumers WHERE %s = ANY(domains) ORDER BY id",
        (domain_key,),
    )
    consumers: list[dict] = []
    for row in cur.fetchall():
        consumer_id, name, domains, created_at, revoked_at = _values(
            row, ("id", "name", "domains", "created_at", "revoked_at")
        )
        consumers.append(
            {
                "name": name,
                "domains": list(domains) if domains is not None else [],
                "created_at": _iso(created_at),
                "revoked": revoked_at is not None,
                "last_pull": _last_pull(
                    conn, consumer_id=consumer_id, domain_key=domain_key
                ),
            }
        )
    return {"consumers": consumers, "source": SOURCE_CONSUMPTION}


def reconcile(conn: Any, *, domain: dict) -> dict:
    """Declaration-vs-curation diff: facts only, never a repair.

    Three facts are reported:

    - kinds the anchored vocabulary declares but has no **live** unit for
      (coverage gaps, in declared order);
    - kinds the DB has that neither vocabulary declares (always an anomaly:
      either the template needs a new version or those units need migration);
    - whether the domain is anchored to an older version of its template name.

    The classification itself is the kernel's: ``ledger.project`` decides what
    counts as a gap, an out-of-vocabulary kind and a smoke leftover, so this page
    and every other surface cannot disagree about the same content. What stays
    here is the surface's own facts (template anchoring) and its response shape.

    A missing template anchor yields no vocabulary, so every stored kind is
    reported out of vocabulary; the page surfaces the missing anchor itself from
    :func:`declaration_layer` (``has_template``). No write, fix, or migration
    happens here.
    """
    from fd_ontology_kernel import ledger as kernel_ledger

    from . import kernel_ports

    tmpl = _anchored_template(conn, domain=domain)
    entity_types, relationship_kinds, _tiers, _sensitivities = _schema_vocabularies(
        tmpl
    )
    declared = _dedupe(entity_types + relationship_kinds)
    scope = domain.get("key") or ""

    try:
        vocabulary = kernel_ports.TemplateVocabulary(conn, domain=domain).load(
            scope_id=scope
        )
    except ValueError:
        # No usable anchor: report every stored kind as out of vocabulary rather
        # than pretending the domain is consistent.
        vocabulary = None

    if vocabulary is not None:
        projection = kernel_ledger.project(
            vocabulary=vocabulary,
            units=kernel_ports.PgUnitStore(conn).list_live(scope_id=scope),
            relationship_kinds=tuple(relationship_kinds),
        )
        unused_kinds = _dedupe(
            list(projection.gaps.get("entity_types") or [])
            + list(projection.gaps.get("relationship_kinds") or [])
        )
        out_of_vocab_kinds = list(projection.reconcile.get("out_of_vocabulary") or [])
    else:
        kinds_cur = conn.execute(
            "SELECT DISTINCT kind FROM knowledge_units "
            "WHERE namespace = %s ORDER BY kind",
            (scope,),
        )
        present_set = {_scalar(row) for row in kinds_cur.fetchall()}
        declared_set = set(declared)
        unused_kinds = [kind for kind in declared if kind not in present_set]
        out_of_vocab_kinds = sorted(
            kind for kind in present_set if kind not in declared_set
        )

    latest_version = (
        _latest_template_version(conn, name=tmpl["name"]) if tmpl is not None else None
    )
    anchored_version = int(domain.get("template_version") or 0)
    template_outdated = (
        latest_version is not None and anchored_version < latest_version
    )

    consistent = not unused_kinds and not out_of_vocab_kinds and not template_outdated
    return {
        "unused_kinds": unused_kinds,
        "out_of_vocab_kinds": out_of_vocab_kinds,
        "template_outdated": template_outdated,
        "consistent": consistent,
        "summary_key": SUMMARY_CONSISTENT if consistent else SUMMARY_GAPS,
    }


def ledger(conn: Any, *, domain: dict) -> dict:
    """All five projections in one call — the shape the ledger page renders.

    ``domain`` is a dict from :func:`src.bench.workspaces.get_domain` (``id``,
    ``key``, ``template_id``, ``template_version`` at minimum). The function is
    pure read: no write path exists in this module, and opening the ledger
    twice leaves the database unchanged.
    """
    return {
        "declaration": declaration_layer(conn, domain=domain),
        "curation": curation_layer(conn, domain=domain),
        "publication": publication_layer(conn, domain=domain),
        "consumption": consumption_layer(conn, domain=domain),
        "reconcile": reconcile(conn, domain=domain),
    }
