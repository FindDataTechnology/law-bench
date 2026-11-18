"""Domain catalog of evaluation assets: a many-to-many *directory*, not ownership.

An evaluation asset (a rubric, a prompt set, a corpus, a comparison run …)
predates domains and is organized by its own pack's vocabulary. It is not owned
by anyone. This module records one extra fact per domain: "this asset belongs on
this domain's shelf". The registry lives in ``domain_assets`` (see
``src/bench/workspace_store.py``) and is deliberately modelled as a directory:

- *Why not ownership.* Ownership implies a lifecycle: an owner could reasonably
  be expected to delete or transfer the asset, and a cascade would make
  unassigning a destructive act. Assets are shared truths here — the same rubric
  can be the yardstick of two domains, and the same corpus backs every domain
  that cites it. Unassigning therefore removes exactly one directory row and
  never touches the asset, its table, or its evaluation behaviour.
- *Why a text key and no foreign key.* Asset tables are heterogeneous and
  predate domains: some are identified by a name, some by an integer id, some by
  a content hash; some identity columns are not even unique. A real FK would
  require one shape per kind and a schema change on every asset table, which the
  capability explicitly forbids. ``asset_key`` is each asset's own stable
  textual identifier, interpreted only by the per-kind relation below, so the
  directory stays a weak reference: a deleted asset leaves an orphan row that is
  reported (``exists: False``) and can be purged, never a dangling FK that
  blocks the asset's own maintenance.
- *Why evaluation never imports this.* The directory is a console/navigation
  concern. Nothing in the evaluation path reads it, so assigning an asset can
  never change a prompt, a criterion, or a score, and it grants no permission
  over the asset's content.

**Domain freedom.** The kernel knows nothing about which asset kinds exist. A
domain pack registers one *provider* per kind — a one-row-per-key SELECT that
projects ``(asset_key, name)`` plus the label key its UI uses — through
:func:`register_providers`. Everything in this module is the generic directory
mechanics; the vocabulary lives in the pack (e.g. ``packs/legal/asset_catalog``),
so adding a vertical needs no kernel change and the kernel-purity gate holds.

Provider contract (per kind)::

    {
      "relation": "<SELECT: one row per asset_key, columns asset_key, name>",
      "label_key": "<i18n key naming the kind in the console>",
    }

``relation`` must be a self-contained SELECT (DISTINCT where the underlying
identity column is not unique) that returns exactly two columns: ``asset_key``
(the directory identity) and ``name`` (display only; may be ``NULL``).

All public functions borrow a DB-API connection supplied by the caller; this
module never opens or closes one. Writes are committed once, at the end of the
operation. Rows are decoded from either dict-row or plain tuple cursors.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from . import workspaces

#: Every registered kind, in registration order. Replaced (not mutated) by
#: :func:`register_providers`, so ``list(ASSET_KINDS)`` always reflects the
#: providers currently available to this process.
ASSET_KINDS: tuple[str, ...] = ()

_PROVIDERS: dict[str, dict] = {}

_PROVIDER_FIELDS = ("relation", "label_key")

_DIRECTORY_COLS = "domain_id, asset_kind, asset_key, added_by, added_at"
_DIRECTORY_KEYS = ("domain_id", "asset_kind", "asset_key", "added_by", "added_at")


# ------------------------------------------------------------------ registry


def _validate_provider(kind: str, provider: Any) -> dict:
    """Shape-check one provider; raise naming the offending kind."""
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError(f"asset kind must be a non-empty string; got {kind!r}")
    if not isinstance(provider, Mapping):
        raise ValueError(f"provider for {kind!r} must be a mapping")
    out: dict = {}
    for field in _PROVIDER_FIELDS:
        value = provider.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"provider for {kind!r} needs a non-empty {field!r} string"
            )
        out[field] = value
    return out


def register_providers(providers: Mapping[str, Mapping[str, str]]) -> None:
    """Register (or replace) the asset kinds this process can catalogue.

    Called by a domain pack at import time. Registration is idempotent per kind:
    importing a pack twice does not duplicate anything. The pack owns the SQL and
    the label keys; this module never inspects their content.
    """
    if not isinstance(providers, Mapping) or not providers:
        raise ValueError("providers must be a non-empty mapping of kind -> provider")
    validated = {
        kind: _validate_provider(kind, provider)
        for kind, provider in providers.items()
    }
    global ASSET_KINDS
    _PROVIDERS.update(validated)
    ASSET_KINDS = tuple(_PROVIDERS)


def providers() -> dict[str, dict]:
    """A copy of the registered providers (kind → {relation, label_key})."""
    return {kind: dict(provider) for kind, provider in _PROVIDERS.items()}


def _resolve(
    providers_arg: Optional[Mapping[str, Mapping[str, str]]],
) -> dict[str, dict]:
    """Use the explicit mapping when given, else the registered providers."""
    if providers_arg is None:
        if not _PROVIDERS:
            raise ValueError(
                "no asset catalog providers registered: import the domain pack "
                "that declares this deployment's asset kinds"
            )
        return {kind: dict(p) for kind, p in _PROVIDERS.items()}
    return {
        kind: _validate_provider(kind, provider)
        for kind, provider in providers_arg.items()
    }


# ------------------------------------------------------------------ decoding


def _iso(val: Any) -> Any:
    """Return a consistent ISO-8601 string for driver timestamps; pass text through."""
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return val


def _row_to_dict(row: Any, keys: tuple[str, ...]) -> dict:
    if isinstance(row, dict):
        values = [row[k] for k in keys]
    else:
        values = list(row)
    return {k: _iso(v) for k, v in zip(keys, values)}


def _items(rows: list[Any], *, with_present: bool) -> list[dict]:
    """Decode listing rows into ``{asset_key, name, exists}`` items.

    ``name`` falls back to ``asset_key`` when the asset row is gone, so an
    orphan still renders as a recognizable identifier rather than ``None``.
    """
    items: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            key, name = row["asset_key"], row["name"]
            present = row["present"] if with_present else True
        else:
            key, name = row[0], row[1]
            present = row[2] if with_present else True
        items.append(
            {
                "asset_key": key,
                "name": name if name is not None else key,
                "exists": bool(present),
            }
        )
    return items


# ------------------------------------------------------------------- helpers


def _load_domain(conn: Any, *, domain_key: str) -> dict:
    """Resolve the domain or refuse the operation (unknown key is a ValueError)."""
    domain = workspaces.get_domain(conn, domain_key=domain_key)
    if domain is None:
        raise ValueError(f"domain {domain_key!r} not found")
    return domain


def _require_kind(asset_kind: str, catalog: Mapping[str, dict]) -> str:
    if asset_kind not in catalog:
        raise ValueError(
            f"asset_kind must be one of {list(catalog)}; got {asset_kind!r}"
        )
    return asset_kind


def _require_key(asset_key: str) -> str:
    if not isinstance(asset_key, str) or not asset_key.strip():
        raise ValueError("asset_key must be a non-empty string")
    return asset_key


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


# ------------------------------------------------------------------- writes


def assign(
    conn: Any,
    *,
    domain_key: str,
    asset_kind: str,
    asset_key: str,
    added_by: str,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict:
    """Register ``asset_key`` on the domain's shelf; idempotent, asset untouched.

    ``ON CONFLICT DO NOTHING`` makes a repeated assign a no-op and keeps the
    original ``added_by``/``added_at`` as the record of who first catalogued the
    asset. Returns the current directory row either way.

    The key is deliberately NOT validated against the asset relation: the
    directory is a weak reference, so a manifest written before the asset lands
    is legal and shows up as an orphan (``exists: False``) instead of being lost.
    """
    catalog = _resolve(providers)
    _require_kind(asset_kind, catalog)
    _require_key(asset_key)
    _require_text(added_by, "added_by")
    domain = _load_domain(conn, domain_key=domain_key)
    conn.execute(
        "INSERT INTO domain_assets (domain_id, asset_kind, asset_key, added_by) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (domain_id, asset_kind, asset_key) DO NOTHING",
        (domain["id"], asset_kind, asset_key, added_by),
    )
    row = conn.execute(
        f"SELECT {_DIRECTORY_COLS} FROM domain_assets "
        "WHERE domain_id = %s AND asset_kind = %s AND asset_key = %s",
        (domain["id"], asset_kind, asset_key),
    ).fetchone()
    conn.commit()
    return _row_to_dict(row, _DIRECTORY_KEYS)


def unassign(
    conn: Any,
    *,
    domain_key: str,
    asset_kind: str,
    asset_key: str,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> bool:
    """Remove the directory row only; returns whether one was removed.

    The asset table is never touched: this is the directory semantic the
    capability promises ("解除归属不影响资产").
    """
    catalog = _resolve(providers)
    _require_kind(asset_kind, catalog)
    _require_key(asset_key)
    domain = _load_domain(conn, domain_key=domain_key)
    cur = conn.execute(
        "DELETE FROM domain_assets "
        "WHERE domain_id = %s AND asset_kind = %s AND asset_key = %s",
        (domain["id"], asset_kind, asset_key),
    )
    conn.commit()
    return cur.rowcount > 0


def purge_orphans(
    conn: Any,
    *,
    domain_key: Optional[str] = None,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> int:
    """Delete directory rows whose asset no longer exists; returns the count.

    Scoped to one domain when ``domain_key`` is given, otherwise across all
    domains. Only kinds with a registered provider are inspected: a row of an
    unknown kind cannot be checked against any asset relation, so it is left
    alone rather than guessed at.
    """
    catalog = _resolve(providers)
    domain_id: Optional[int] = None
    if domain_key is not None:
        domain_id = _load_domain(conn, domain_key=domain_key)["id"]

    removed = 0
    for kind, provider in catalog.items():
        relation = provider["relation"]
        sql = (
            "DELETE FROM domain_assets da WHERE da.asset_kind = %s "
            "AND NOT EXISTS ("
            f"SELECT 1 FROM ({relation}) a WHERE a.asset_key = da.asset_key"
            ")"
        )
        params: list[Any] = [kind]
        if domain_id is not None:
            sql += " AND da.domain_id = %s"
            params.append(domain_id)
        removed += conn.execute(sql, tuple(params)).rowcount
    conn.commit()
    return removed


def backfill(
    conn: Any,
    *,
    domain_key: str,
    asset_kind: str,
    asset_keys: list[str],
    added_by: str,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict:
    """Assign an explicit list of keys; idempotent, missing keys are reported.

    Only the given keys are considered — there is deliberately no "assign every
    asset" mode, so a backfill script must state what it is claiming instead of
    silently attributing the whole corpus to one domain. Keys absent from the
    asset relation are returned in ``missing`` (not raised): a backfill manifest
    is data and may legitimately outlive or precede the asset it names.
    """
    catalog = _resolve(providers)
    _require_kind(asset_kind, catalog)
    _require_text(added_by, "added_by")
    domain = _load_domain(conn, domain_key=domain_key)
    relation = catalog[asset_kind]["relation"]
    keys = list(dict.fromkeys(asset_keys))  # de-dupe, preserve manifest order

    assigned = 0
    already = 0
    missing: list[str] = []
    for key in keys:
        _require_key(key)
        found = conn.execute(
            f"SELECT 1 FROM ({relation}) a WHERE a.asset_key = %s LIMIT 1",
            (key,),
        ).fetchone()
        if found is None:
            missing.append(key)
            continue
        cur = conn.execute(
            "INSERT INTO domain_assets (domain_id, asset_kind, asset_key, added_by) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (domain_id, asset_kind, asset_key) DO NOTHING",
            (domain["id"], asset_kind, key, added_by),
        )
        if cur.rowcount:
            assigned += 1
        else:
            already += 1
    conn.commit()
    return {"assigned": assigned, "already": already, "missing": missing}


# ------------------------------------------------------------------- reads


def list_for_domain(
    conn: Any,
    *,
    domain_key: str,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict:
    """Group the domain's catalogued assets by kind (registration order).

    Only kinds with at least one item appear. ``exists`` is a LEFT JOIN against
    the asset's own relation: ``False`` means the directory row is an orphan
    (the asset was deleted independently) and the console offers a purge. The
    query never reads asset content, only the identity/display columns.
    """
    catalog = _resolve(providers)
    domain = _load_domain(conn, domain_key=domain_key)
    groups: list[dict] = []
    total = 0
    for kind, provider in catalog.items():
        relation = provider["relation"]
        rows = conn.execute(
            "SELECT da.asset_key, a.name, (a.asset_key IS NOT NULL) AS present "
            "FROM domain_assets da "
            f"LEFT JOIN ({relation}) a ON a.asset_key = da.asset_key "
            "WHERE da.domain_id = %s AND da.asset_kind = %s "
            "ORDER BY a.name NULLS LAST, da.asset_key",
            (domain["id"], kind),
        ).fetchall()
        items = _items(rows, with_present=True)
        if items:
            groups.append(
                {
                    "kind": kind,
                    "label_key": provider["label_key"],
                    "items": items,
                }
            )
            total += len(items)
    return {"groups": groups, "total": total}


def list_unassigned(
    conn: Any,
    *,
    domain_key: str,
    asset_kind: Optional[str] = None,
    providers: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> dict:
    """The pool of assets catalogued by *no* domain, optionally one kind.

    ``domain_key`` is validated (the console is always opened inside a domain)
    but does not narrow the pool: an asset assigned to another domain is not
    "unassigned", so it must not be offered here. Items always report
    ``exists: True`` — the pool is built from asset rows, not from the directory.
    """
    catalog = _resolve(providers)
    _load_domain(conn, domain_key=domain_key)
    kinds = (
        list(catalog) if asset_kind is None else [_require_kind(asset_kind, catalog)]
    )

    groups: list[dict] = []
    total = 0
    for kind in kinds:
        provider = catalog[kind]
        relation = provider["relation"]
        rows = conn.execute(
            "SELECT a.asset_key, a.name FROM "
            f"({relation}) a "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM domain_assets da "
            "WHERE da.asset_kind = %s AND da.asset_key = a.asset_key"
            ") "
            "ORDER BY a.name, a.asset_key",
            (kind,),
        ).fetchall()
        items = _items(rows, with_present=False)
        if items:
            groups.append(
                {
                    "kind": kind,
                    "label_key": provider["label_key"],
                    "items": items,
                }
            )
            total += len(items)
    return {"groups": groups, "total": total}
