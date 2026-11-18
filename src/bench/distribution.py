"""Versioned publication of a domain's content and consumer registration.

The publishing contract treats a domain's knowledge units as a projected
snapshot: building the manifest reads the full in-vocabulary, non-deleted unit
set (entities from the template's ``entity_types`` vocabulary, relationships
from ``relationship_kinds``), freezes it as one JSONB document plus its
changelog, and anchors it with a content-only digest. Snapshots are immutable
once written — ``ontology_publications`` is append-only (no UPDATE/DELETE code
paths exist), so a historical version stays byte-identical forever and later
edits in the workspace can never rewrite it.

Digest canonicalization follows the platform's canonical-JSON convention:
``json.dumps(manifest, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)`` UTF-8 encoded, hashed with sha256. Only the manifest
content is anchored — generation timestamps, the publisher, and the version
number are never part of the manifest, so identical content always yields the
identical digest and re-publishing is idempotent (the existing version row is
returned as-is, no new row). Entry lists are ordered by external key so the
digest depends on content, not on list order.

Consumer registration stores machine credentials by digest only (never a
plaintext token); revocation is a soft flag that the lookup layer treats as
fail-closed. Domain binding is a plain list of domain keys, replaced as a
whole group on update.

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Writes are committed once, at the end of the
operation. JSONB is encoded/decoded with ``json.dumps``/``json.loads``; rows
are decoded from either dict-row or plain tuple cursors.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from fd_ontology_kernel import manifest as kernel_manifest

from . import authoring, submitters, templates, workspaces

# The contract surface carried per knowledge-unit entry in a manifest.
# Relationship entries additionally carry the structured endpoints
# ("from_key"/"to_key") so consumers can rebuild identity from the
# deterministic relationship key convention alone.
MANIFEST_FIELDS = ("kind", "external_key", "body", "tier", "sensitivity", "attrs")

# Fields compared when generating a changelog: the contract surface minus the
# identity fields (kind/external_key are the diff keys), plus the structured
# relationship endpoints.
_DIFFABLE_FIELDS = tuple(f for f in MANIFEST_FIELDS if f not in ("kind", "external_key")) + (
    "from_key",
    "to_key",
)

# Upper bound for the per-kind unit fetch while building a snapshot. Publishing
# must see the full domain content (a silently truncated manifest would corrupt
# the snapshot), and P1 domain scale is tens to hundreds of units, so this is
# orders of magnitude above realistic size while keeping the query bounded.
_SNAPSHOT_FETCH_LIMIT = 100_000

_PUBLICATION_COLS = (
    "id, domain_id, version, digest, manifest, changelog, published_by, published_at"
)
_PUBLICATION_KEYS = (
    "id",
    "domain_id",
    "version",
    "digest",
    "manifest",
    "changelog",
    "published_by",
    "published_at",
)

_CONSUMER_COLS = (
    "id, name, domains, token_hash, created_by, created_at, revoked_at, kind, fleet_ref"
)
_CONSUMER_KEYS = (
    "id",
    "name",
    "domains",
    "token_hash",
    "created_by",
    "created_at",
    "revoked_at",
    "kind",
    "fleet_ref",
)

#: Registered consumer kinds. ``machine`` only pulls published artefacts;
#: ``fleet`` additionally submits proposals and writes back runs, so its stable
#: ``fleet_ref`` is the anchor that turns a ``source`` string into a fact.
CONSUMER_KINDS: tuple[str, ...] = ("machine", "fleet")


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _decode_jsonb(val: Any) -> Any:
    if isinstance(val, (dict, list)) or val is None:
        return val
    return json.loads(val)


def _scalar(row: Any) -> Any:
    """First value of a single-column row, dict-row or tuple."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()))
    return row[0]


def _publication_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _PUBLICATION_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "domain_id": values[1],
        "version": values[2],
        "digest": values[3],
        "manifest": _decode_jsonb(values[4]),
        "changelog": _decode_jsonb(values[5]),
        "published_by": values[6],
        "published_at": _iso(values[7]),
    }


def _consumer_to_dict(row: Any) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in _CONSUMER_KEYS]
    else:
        values = list(row)
    return {
        "id": values[0],
        "name": values[1],
        "domains": list(values[2]) if values[2] is not None else [],
        "token_hash": values[3],
        "created_by": values[4],
        "created_at": _iso(values[5]),
        "revoked_at": _iso(values[6]),
        "kind": values[7] or "machine",
        "fleet_ref": values[8],
    }


def _normalize_domain_keys(domains: Any) -> list[str]:
    """Validate the bound-domain list shape (a list of domain key strings)."""
    if domains is None:
        return []
    if not isinstance(domains, (list, tuple)) or not all(
        isinstance(key, str) for key in domains
    ):
        raise ValueError("domains must be a list of domain key strings")
    return list(domains)


# -------------------------------------------------------------------- digest


def canonical_digest(manifest: dict) -> str:
    """Sha256 of the manifest's canonical JSON (content-only anchor).

    Delegates the recipe to the shared kernel: one canonical-JSON definition for
    every surface, so a snapshot taken here and one taken by another surface
    cannot disagree about what "the same content" means. The digest still covers
    this payload only — timestamps, publisher and version number never enter it.
    """
    return kernel_manifest.digest_of(manifest)


# ------------------------------------------------------------- manifest build


def _entry_from_unit(unit: dict, *, domain_key: str, require_endpoints: bool) -> dict:
    """Project one stored KU onto the distribution contract surface.

    ``sensitivity`` is read from the unit's tags (authoring has no dedicated
    column) and is ``None`` when unset. Relationship units must carry their
    structured endpoints in ``attrs`` — a missing endpoint means the stored
    data is corrupt, and corrupt data must fail loudly instead of publishing a
    snapshot consumers cannot decode.
    """
    tags = unit.get("tags") or {}
    attrs = unit.get("attrs") or {}
    entry = {
        "kind": unit["kind"],
        "external_key": unit["external_key"],
        "body": unit["body"],
        "tier": unit["tier"],
        "sensitivity": tags.get("sensitivity") or None,
        "attrs": attrs,
    }
    if require_endpoints:
        from_key = attrs.get("from_key")
        to_key = attrs.get("to_key")
        if not from_key or not to_key:
            raise ValueError(
                f"relationship unit {unit['kind']!r}/{unit['external_key']!r} in "
                f"domain {domain_key!r} is missing its structured endpoints "
                f"(attrs['from_key']/attrs['to_key']); stored data is corrupt"
            )
        entry["from_key"] = from_key
        entry["to_key"] = to_key
    return entry


def build_manifest(conn: Any, *, domain: dict) -> tuple[dict, int, int]:
    """Project the domain's full in-vocabulary content into a publish manifest.

    ``domain`` is a dict from :func:`src.bench.workspaces.get_domain`. Entities
    are all non-deleted units of every kind in the anchored template's
    ``entity_types`` vocabulary; relationships likewise for
    ``relationship_kinds`` (with structured ``from_key``/``to_key`` projected
    from ``attrs``). Soft-deleted units are excluded. Entry lists are ordered
    by external key so the manifest is a pure function of content.

    Returns ``(manifest, entity_count, relationship_count)``. Refuses a domain
    with no content at all (an empty snapshot must never be published) and
    refuses an unusable template anchor or corrupt relationship data loudly.
    """
    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    if tmpl is None:
        raise ValueError(
            f"domain {domain['key']!r} anchors template id "
            f"{domain['template_id']!r}, which does not exist"
        )
    schema = tmpl["schema"]
    if not isinstance(schema, dict):
        raise ValueError(
            f"domain {domain['key']!r} template schema is not a dict; "
            "cannot read the vocabularies to publish"
        )
    entity_types = schema.get("entity_types")
    relationship_kinds = schema.get("relationship_kinds")
    if not isinstance(entity_types, list) or not entity_types:
        raise ValueError(
            f"domain {domain['key']!r} template schema has no usable "
            "entity_types vocabulary"
        )
    if not isinstance(relationship_kinds, list) or not relationship_kinds:
        raise ValueError(
            f"domain {domain['key']!r} template schema has no usable "
            "relationship_kinds vocabulary"
        )

    entities: list[dict] = []
    for kind in entity_types:
        units = authoring.authoring_list_units(
            conn,
            domain_key=domain["key"],
            kind=kind,
            include_deleted=False,
            limit=_SNAPSHOT_FETCH_LIMIT,
        )
        entities.extend(
            _entry_from_unit(u, domain_key=domain["key"], require_endpoints=False)
            for u in units
        )
    relationships: list[dict] = []
    for kind in relationship_kinds:
        units = authoring.authoring_list_units(
            conn,
            domain_key=domain["key"],
            kind=kind,
            include_deleted=False,
            limit=_SNAPSHOT_FETCH_LIMIT,
        )
        relationships.extend(
            _entry_from_unit(u, domain_key=domain["key"], require_endpoints=True)
            for u in units
        )

    if not entities and not relationships:
        raise ValueError(f"domain {domain['key']!r} has no content to publish")

    # The shape itself is owned by the kernel (key-addressed, version 2): it
    # fixes the entry key set, the sort order and the null normalization. Building
    # it here instead would let this surface drift from every other publisher
    # while both claim the same shape version.
    manifest = kernel_manifest.build_payload(
        shape=kernel_manifest.SHAPE_KEY_ADDRESSED,
        entities=entities,
        relationships=relationships,
        header={
            "domain": domain["key"],
            "template_name": tmpl["name"],
            "template_version": domain["template_version"],
            "entity_types": list(entity_types),
            "relationship_kinds": list(relationship_kinds),
        },
    )
    return manifest, len(entities), len(relationships)


# ----------------------------------------------------------------- changelog


def _manifest_key_index(manifest: dict) -> dict:
    """Index a manifest's entries by external key (entities + relationships).

    Key namespaces do not collide by construction; encountering a duplicate
    means corrupt content, which must fail loudly rather than silently drop an
    entry from the diff.
    """
    index: dict[str, dict] = {}
    entries = list(manifest.get("entities") or []) + list(
        manifest.get("relationships") or []
    )
    for entry in entries:
        key = entry["external_key"]
        if key in index:
            raise ValueError(
                f"duplicate external key {key!r} in manifest; cannot diff "
                "corrupt content"
            )
        index[key] = entry
    return index


def diff_manifests(old: Optional[dict], new: dict) -> dict:
    """Keyed diff of the previous snapshot's manifest against the new one.

    ``old is None`` means first publication: the changelog is the initial
    inventory (``{"initial": True, "counts": {...}}``). Otherwise entries are
    keyed by external key across entities and relationships: ``added`` /
    ``removed`` list keys, ``changed`` records field-level ``before``/``after``
    for every differing contract field (body/tier/sensitivity/attrs and the
    relationship endpoints). ``counts`` always describes the new snapshot.
    """
    new_counts = {
        "entities": len(new.get("entities") or []),
        "relationships": len(new.get("relationships") or []),
    }
    if old is None:
        return {"initial": True, "counts": new_counts}

    old_index = _manifest_key_index(old)
    new_index = _manifest_key_index(new)
    added = sorted(key for key in new_index if key not in old_index)
    removed = sorted(key for key in old_index if key not in new_index)
    changed: list[dict] = []
    for key in sorted(new_index):
        previous = old_index.get(key)
        if previous is None:
            continue
        current = new_index[key]
        fields: dict[str, dict] = {}
        for field in _DIFFABLE_FIELDS:
            before = previous.get(field)
            after = current.get(field)
            if before != after:
                fields[field] = {"before": before, "after": after}
        if fields:
            changed.append({"key": key, "kind": current["kind"], "fields": fields})
    return {"added": added, "removed": removed, "changed": changed, "counts": new_counts}


# ---------------------------------------------------------------- publishing


def publish_domain(conn: Any, *, domain_key: str, published_by: str) -> dict:
    """Freeze the domain's current content as the next immutable version.

    Refuses an unknown domain and a domain with no content. The digest anchors
    content only: an existing publication row with the same (domain, digest)
    is returned as-is — no INSERT, no new version, idempotent. Otherwise the
    version is ``max(version) + 1``, the changelog is the diff against the
    latest snapshot's manifest, and the row is inserted with one commit.

    Two publishes cannot race in-process (a single borrowed connection), so no
    extra locking is needed.
    """
    if not published_by:
        raise ValueError("published_by is required")
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")

    manifest, _entity_count, _relationship_count = build_manifest(conn, domain=domain)
    digest = canonical_digest(manifest)

    existing = conn.execute(
        f"SELECT {_PUBLICATION_COLS} FROM ontology_publications "
        "WHERE domain_id = %s AND digest = %s",
        (domain["id"], digest),
    ).fetchone()
    if existing is not None:
        return _publication_to_dict(existing)

    max_version = _scalar(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version "
            "FROM ontology_publications WHERE domain_id = %s",
            (domain["id"],),
        ).fetchone()
    )
    version = int(max_version or 0) + 1
    latest = conn.execute(
        f"SELECT {_PUBLICATION_COLS} FROM ontology_publications "
        "WHERE domain_id = %s ORDER BY version DESC LIMIT 1",
        (domain["id"],),
    ).fetchone()
    previous_manifest = _decode_jsonb(latest["manifest"]) if latest else None
    changelog = diff_manifests(previous_manifest, manifest)

    cur = conn.execute(
        f"INSERT INTO ontology_publications "
        f"(domain_id, version, digest, manifest, changelog, published_by) "
        f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_PUBLICATION_COLS}",
        (
            domain["id"],
            version,
            digest,
            json.dumps(manifest),
            json.dumps(changelog),
            published_by,
        ),
    )
    publication = _publication_to_dict(cur.fetchone())
    conn.commit()
    return publication


def get_publication(
    conn: Any, *, domain_key: str, version: Optional[int] = None
) -> Optional[dict]:
    """Fetch one publication; ``version is None`` means the latest.

    ``None`` when the domain or the requested version has no publication.
    """
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        return None
    if version is not None:
        cur = conn.execute(
            f"SELECT {_PUBLICATION_COLS} FROM ontology_publications "
            "WHERE domain_id = %s AND version = %s",
            (domain["id"], version),
        )
    else:
        cur = conn.execute(
            f"SELECT {_PUBLICATION_COLS} FROM ontology_publications "
            "WHERE domain_id = %s ORDER BY version DESC LIMIT 1",
            (domain["id"],),
        )
    row = cur.fetchone()
    return _publication_to_dict(row) if row else None


def list_publications(conn: Any, *, domain_key: str) -> list[dict]:
    """All of the domain's publications, version ascending."""
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        return []
    cur = conn.execute(
        f"SELECT {_PUBLICATION_COLS} FROM ontology_publications "
        "WHERE domain_id = %s ORDER BY version ASC",
        (domain["id"],),
    )
    return [_publication_to_dict(r) for r in cur.fetchall()]


# ----------------------------------------------------------------- consumers


def register_consumer(
    conn: Any,
    *,
    name: str,
    domains: list[str],
    token_hash: str,
    created_by: str,
    kind: str = "machine",
    fleet_ref: Optional[str] = None,
) -> dict:
    """Register one consumer: name, bound domain keys, credential digest.

    Only the credential digest is stored — the plaintext token never reaches
    this layer. A duplicate consumer name is refused.

    ``kind='fleet'`` additionally requires a stable ``fleet_ref`` (the bare id,
    e.g. ``fleet_1794335712751_wfa3ww`` — the same token that appears after
    ``fleet:`` in a submission's ``source``). At most one *live* registration
    may claim a given ``fleet_ref``: a revoked row keeps its history but stops
    claiming the identity, so a fleet can be re-registered after revocation.
    """
    if not name:
        raise ValueError("name is required")
    if not token_hash:
        raise ValueError("token_hash is required")
    if not created_by:
        raise ValueError("created_by is required")
    if kind not in CONSUMER_KINDS:
        raise ValueError(f"kind must be one of {list(CONSUMER_KINDS)}; got {kind!r}")
    if kind == "fleet":
        if not (fleet_ref or "").strip():
            raise ValueError("kind='fleet' requires a non-empty fleet_ref")
    elif fleet_ref:
        raise ValueError("kind='machine' must not carry a fleet_ref")

    bound = _normalize_domain_keys(domains)
    existing = conn.execute(
        "SELECT 1 FROM distribution_consumers WHERE name = %s LIMIT 1", (name,)
    ).fetchone()
    if existing:
        raise ValueError(f"consumer {name!r} already exists")
    if kind == "fleet":
        live = _consumer_by_fleet_ref(conn, fleet_ref.strip(), live_only=True)
        if live is not None:
            raise ValueError(
                f"fleet {fleet_ref!r} is already registered as {live['name']!r}; "
                "revoke that registration before registering it again"
            )
    cur = conn.execute(
        f"INSERT INTO distribution_consumers "
        f"(name, domains, token_hash, created_by, kind, fleet_ref) "
        f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_CONSUMER_COLS}",
        (name, bound, token_hash, created_by, kind, fleet_ref.strip() if kind == "fleet" else None),
    )
    consumer = _consumer_to_dict(cur.fetchone())
    conn.commit()
    return consumer


def promote_consumer_to_fleet(
    conn: Any,
    *,
    name: Optional[str] = None,
    token_hash: Optional[str] = None,
    fleet_ref: str,
) -> dict:
    """把一条既有登记**原地**升为舰队档：``machine`` → ``fleet``。

    为什么需要这条路：升级前登记的消费者全是 ``machine``，而其中就有真正在跑的
    舰队（产库 `ontology-fleet-win`）。部署后它的 ``kind`` 取列默认值 ``machine``、
    ``fleet_ref`` 为空，于是它的 ``fleet:*`` 提交会判成「来源未登记」——**而我们没有
    任何办法修**：``register_consumer`` 只会新建，撞 ``name`` 与 ``token_hash`` 两条
    唯一约束；吊销再重登记又会换掉 token，等于把在跑的舰队切断。

    所以升级只动两列（``kind`` / ``fleet_ref``），身份（id / name / token_hash /
    domains）一个字不改——凭据不变，客户端无感。定位可以按 ``name`` 或 ``token_hash``；
    后者更强：**持有那枚 token 本身就是授权**。

    重复调用幂等：已经是同一 ``fleet_ref`` 的舰队档时原样返回，不写库。
    """
    ref = (fleet_ref or "").strip()
    if not ref:
        raise ValueError("fleet_ref 不能为空")
    key = (name or "").strip()
    digest = (token_hash or "").strip()
    if not key and not digest:
        raise ValueError("需要 name 或 token_hash 之一来定位既有登记")

    if key:
        row = conn.execute(
            f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE name = %s", (key,)
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE token_hash = %s",
            (digest,),
        ).fetchone()
    if row is None:
        raise ValueError(
            f"找不到要升级的登记（name={key or None!r} token_hash={'(given)' if digest else None}）"
        )
    consumer = _consumer_to_dict(row)

    # 按 token_hash 定位时必须和给到的 name 一致，否则调用方以为在改 A、实际改的是 B。
    if key and digest and consumer["token_hash"] != digest:
        raise ValueError(
            f"登记 {consumer['name']!r} 的凭据与提供的 token 不一致——不升级（拿不出它的凭据就不算授权）"
        )
    if consumer["revoked_at"] is not None:
        raise ValueError(
            f"登记 {consumer['name']!r} 已吊销；吊销的登记不升级，重新登记一条新的"
        )

    if consumer["kind"] == "fleet":
        if consumer["fleet_ref"] == ref:
            return consumer  # 幂等：已经是这个舰队的登记
        raise ValueError(
            f"登记 {consumer['name']!r} 已绑定另一个舰队标识 {consumer['fleet_ref']!r}；"
            "要改绑定请先把旧的那条处理掉（吊销或改回 machine）"
        )

    other = _consumer_by_fleet_ref(conn, ref, live_only=True)
    if other is not None and other["id"] != consumer["id"]:
        raise ValueError(
            f"舰队标识 {ref!r} 已被登记 {other['name']!r} 占用；先处理那一条再升级"
        )

    cur = conn.execute(
        f"UPDATE distribution_consumers SET kind = 'fleet', fleet_ref = %s "
        f"WHERE id = %s RETURNING {_CONSUMER_COLS}",
        (ref, consumer["id"]),
    )
    promoted = _consumer_to_dict(cur.fetchone())
    conn.commit()
    return promoted


def _consumer_by_fleet_ref(
    conn: Any, fleet_ref: str, *, live_only: bool = False
) -> Optional[dict]:
    """The registration claiming ``fleet_ref`` (optionally only the live one)."""
    sql = f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE fleet_ref = %s"
    params: list[Any] = [fleet_ref]
    if live_only:
        sql += " AND revoked_at IS NULL"
    sql += " ORDER BY id DESC LIMIT 1"
    row = conn.execute(sql, tuple(params)).fetchone()
    return _consumer_to_dict(row) if row else None


def resolve_fleet(conn: Any, *, fleet_ref: str, domain_key: str) -> tuple[Optional[dict], str]:
    """Resolve a bare ``fleet_ref`` against the registry for one domain.

    Returns ``(consumer_or_None, verdict)`` where the verdict comes from the
    same vocabulary the source judgement uses (``submitters.verdict_for_fleet``).
    Used by work-order assignment, which holds a ``fleet_ref`` and no ``source``.
    """
    consumer = _consumer_by_fleet_ref(conn, (fleet_ref or "").strip())
    projection = (
        None
        if consumer is None
        else {"domains": consumer["domains"], "revoked": consumer["revoked_at"] is not None}
    )
    return consumer, submitters.verdict_for_fleet(domain_key=domain_key, fleet=projection)


def resolve_submitter(
    conn: Any,
    *,
    source: str,
    domain_key: str,
    via: str,
    authenticated_as: Optional[str] = None,
) -> tuple[Optional[dict], str]:
    """Resolve a submission's ``source`` into ``(registration_or_None, verdict)``.

    This function only *fetches the facts*; the judgement itself lives in
    ``submitters.verdict`` so both call sites (HTTP and in-process) and the
    pure tests share one implementation.

    ``via`` must be the caller's own channel constant — ``extract:`` is accepted
    only for ``in_process``, and passing the wrong value does not make the check
    lenient, it makes it disappear.
    """
    prefix, parts, _malformed = submitters.classify_source(source)
    consumer: Optional[dict] = None
    fleet: Optional[dict] = None
    agent_is_member: Optional[bool] = None

    if prefix == submitters.PREFIX_FLEET and parts:
        consumer = _consumer_by_fleet_ref(conn, parts["fleet_id"])
        if consumer is not None:
            fleet = {
                "domains": consumer["domains"],
                "revoked": consumer["revoked_at"] is not None,
            }

    if prefix == submitters.PREFIX_AGENT and parts:
        domain = workspaces.get_domain(conn, domain_key=parts["domain"])
        agent_is_member = bool(domain) and (
            workspaces.get_active_role(
                conn, domain_id=domain["id"], user_id=(source or "").strip()
            )
            is not None
        )

    return consumer, submitters.verdict(
        source,
        domain_key=domain_key,
        via=via,
        fleet=fleet,
        agent_is_member=agent_is_member,
        authenticated_as=authenticated_as,
    )


def list_consumers(conn: Any) -> list[dict]:
    """All registered consumers, id ascending (revoked ones included)."""
    cur = conn.execute(f"SELECT {_CONSUMER_COLS} FROM distribution_consumers ORDER BY id")
    return [_consumer_to_dict(r) for r in cur.fetchall()]


def get_consumer_by_token_hash(conn: Any, *, token_hash: str) -> Optional[dict]:
    """Look up a consumer by credential digest; ``None`` when unregistered.

    The lookup layer owns the three-state decision: a row with a non-null
    ``revoked_at`` fails closed there.
    """
    cur = conn.execute(
        f"SELECT {_CONSUMER_COLS} FROM distribution_consumers "
        "WHERE token_hash = %s",
        (token_hash,),
    )
    row = cur.fetchone()
    return _consumer_to_dict(row) if row else None


def set_consumer_domains(conn: Any, *, name: str, domains: list[str]) -> dict:
    """Replace the consumer's bound domain keys as a whole group."""
    bound = _normalize_domain_keys(domains)
    current = conn.execute(
        f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE name = %s",
        (name,),
    ).fetchone()
    if current is None:
        raise ValueError(f"consumer {name!r} not found")
    cur = conn.execute(
        f"UPDATE distribution_consumers SET domains = %s WHERE name = %s "
        f"RETURNING {_CONSUMER_COLS}",
        (bound, name),
    )
    consumer = _consumer_to_dict(cur.fetchone())
    conn.commit()
    return consumer


def rotate_consumer_token(conn: Any, *, name: str, token_hash: str) -> dict:
    """Replace one registration's credential digest **in place**.

    Why this exists: ``promote_consumer_to_fleet`` deliberately leaves
    ``token_hash`` alone ("凭据不变，客户端无感"), and both ``register_consumer``
    uniqueness rules make re-registration impossible under the same name. So
    when a registration's plaintext is genuinely lost (the operator who created
    it is gone, and the credential was never stored anywhere else), the only
    remaining options were "revoke + register under a new name" — which changes
    the identity the audit trail is keyed on — or nothing. This is the third
    option: same ``id``, same ``name``, same ``domains``, same ``kicker``
    (``kind``/``fleet_ref``); only the digest moves.

    What it does NOT do: prove the caller holds the old credential. That is the
    caller's problem (``scripts/register_fleet.py --rotate-token`` prints the
    new plaintext exactly once at issuance, which is the same "shown once"
    contract the console's own key creation uses). Rotating is a *deliberate
    cut-off* of the previous holder — legitimate when the old value is lost,
    never as a convenience.

    Idempotent on the hash: passing the digest already stored returns the row
    unchanged instead of rewriting (and so does not perturb ``created_at``
    ordering in an audit diff).
    """
    key = (name or "").strip()
    digest = (token_hash or "").strip()
    if not key:
        raise ValueError("name is required")
    if not digest:
        raise ValueError("token_hash is required")
    current = conn.execute(
        f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE name = %s",
        (key,),
    ).fetchone()
    if current is None:
        raise ValueError(f"consumer {key!r} not found")
    consumer = _consumer_to_dict(current)
    if consumer["revoked_at"] is not None:
        raise ValueError(
            f"登记 {key!r} 已吊销；吊销的登记不轮换凭据（重新登记一条新的，而不是复活旧的）"
        )
    if consumer["token_hash"] == digest:
        return consumer
    # 另一条活登记拿着同一枚摘要会撞 token_hash 唯一约束；先判再写，让报错说人话。
    other = conn.execute(
        f"SELECT name FROM distribution_consumers WHERE token_hash = %s AND id <> %s",
        (digest, consumer["id"]),
    ).fetchone()
    if other is not None:
        raise ValueError(f"这枚凭据已经属于登记 {other['name']!r}，不能同时给 {key!r}")
    cur = conn.execute(
        f"UPDATE distribution_consumers SET token_hash = %s WHERE id = %s "
        f"RETURNING {_CONSUMER_COLS}",
        (digest, consumer["id"]),
    )
    rotated = _consumer_to_dict(cur.fetchone())
    conn.commit()
    return rotated


def revoke_consumer(conn: Any, *, name: str) -> dict:
    """Revoke the consumer's credential (``revoked_at`` is set).

    Idempotent: an already-revoked consumer is returned unchanged (the
    revocation timestamp is not moved). The lookup layer treats a non-null
    ``revoked_at`` as fail-closed.
    """
    current = conn.execute(
        f"SELECT {_CONSUMER_COLS} FROM distribution_consumers WHERE name = %s",
        (name,),
    ).fetchone()
    if current is None:
        raise ValueError(f"consumer {name!r} not found")
    cur = conn.execute(
        f"UPDATE distribution_consumers SET revoked_at = now() "
        f"WHERE name = %s AND revoked_at IS NULL RETURNING {_CONSUMER_COLS}",
        (name,),
    )
    updated = cur.fetchone()
    consumer = _consumer_to_dict(updated if updated is not None else current)
    conn.commit()
    return consumer
