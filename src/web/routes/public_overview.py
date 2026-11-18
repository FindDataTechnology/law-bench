"""Anonymous read-only platform overview for the public API pod.

Change ``add-bench-public-overview-tier``: one narrowly-exempted endpoint,
``GET /api/public/overview``, that lets unauthenticated callers (the intro
website via same-origin proxy, external evaluators) read the platform's
published-ontology state:

- ``as_of``: the newest ``published_at`` among the listed snapshots — the
  *data's* timestamp, never the server clock (an empty state yields ``null``).
  This is the honest-freshness contract the website's hydration layer relies
  on: a stale overview never masquerades as fresh.
- ``ontology_versions``: the LATEST published version per domain
  (``domain_key``/``version``/``digest``/``published_at``/``counts``), a
  read-only projection of the ``ontology_publications`` rows owned by
  ``src.bench.distribution`` (same digest values the distribution pull API
  serves — the overview is not a second publication surface).
- ``totals``: platform-level sums over those latest snapshots.

What deliberately does NOT leave the building: the manifest itself (it carries
every unit's ``body`` — corpus content), the changelog, ``published_by``, and
consumer/credential rows. Counts are *derived from* the manifest without
emitting it.

Degradation is honest: a database failure yields ``503`` with an error class
reason (never an exception string — DSN/host details must not leak), and there
is no stale-cache fallback. The route is strictly read-only: no table writes,
no ``last_used_at`` touches (it consumes no credential at all).

Sibling paths under ``/api/public/`` are registered as an authenticated
catch-all so an anonymous caller gets ``401`` (constructor-level auth runs
before the handler) instead of FastAPI's default route-less ``404`` — the
exemption covers exactly one path and nothing around it. A valid key on a
sibling still 404s (nothing is served there).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..deps import DbConn, get_db

router = APIRouter(prefix="/api/public")

# The exact path registered as the public pod's app-level auth exemption.
OVERVIEW_PATH = "/api/public/overview"

# Tiers always present in the distribution payload (a tier outside this set is
# still counted — added honestly to the dict rather than dropped).
_TIERS = ("gold", "silver", "bronze")

# Latest publication per domain. DISTINCT ON pins one row per domain at the
# highest version; the join resolves the publication's domain_id to its public
# domain key (workspaces owns the domains table).
_LATEST_SQL = (
    "SELECT DISTINCT ON (p.domain_id) "
    "d.key AS domain_key, p.version, p.digest, p.published_at, p.manifest "
    "FROM ontology_publications p "
    "JOIN domains d ON d.id = p.domain_id "
    "ORDER BY p.domain_id, p.version DESC"
)

_ROW_FIELDS = ("domain_key", "version", "digest", "published_at", "manifest")


def _row_values(row: Any) -> tuple:
    """Normalize a driver row (dict-row or tuple) to the projected field order."""
    if isinstance(row, dict):
        return tuple(row.get(k) for k in _ROW_FIELDS)
    return tuple(row)


def _decode_manifest(raw: Any) -> dict:
    """Decode the publication manifest (jsonb dict or JSON text) to a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            decoded = json.loads(bytes(raw).decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        except (ValueError, UnicodeDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _count_manifest(manifest: dict) -> dict:
    """Derive tier/shape counts from a manifest WITHOUT emitting its content.

    The manifest's ``entities``/``relationships`` entry lists carry every
    unit's ``body`` — counted here, never copied into the response.
    """
    entities = manifest.get("entities") or []
    relations = manifest.get("relationships") or []
    by_tier: dict[str, int] = {tier: 0 for tier in _TIERS}
    for entry in [*entities, *relations]:
        if not isinstance(entry, dict):
            continue
        tier = entry.get("tier")
        by_tier[tier] = by_tier.get(tier, 0) + 1
    return {"entities": len(entities), "relations": len(relations), "by_tier": by_tier}


def _ts_key(val: Any) -> Optional[datetime]:
    """Comparable datetime for freshness ordering; ``None`` when unusable."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def _iso(val: Any) -> Optional[str]:
    if val is None:
        return None
    return val.isoformat() if hasattr(val, "isoformat") else str(val)


def _build_overview(rows: list) -> dict:
    """Project publication rows into the public payload (pure, no I/O)."""
    versions: list[dict] = []
    totals = {"domains": 0, "entities": 0, "relations": 0, "by_tier": {t: 0 for t in _TIERS}}
    newest_raw: Any = None
    newest_key: Optional[datetime] = None
    for row in rows:
        domain_key, version, digest, published_at, manifest = _row_values(row)
        counts = _count_manifest(_decode_manifest(manifest))
        versions.append(
            {
                "domain_key": domain_key,
                "version": version,
                "digest": digest,
                "published_at": _iso(published_at),
                "counts": counts,
            }
        )
        totals["domains"] += 1
        totals["entities"] += counts["entities"]
        totals["relations"] += counts["relations"]
        for tier, n in counts["by_tier"].items():
            totals["by_tier"][tier] = totals["by_tier"].get(tier, 0) + n
        key = _ts_key(published_at)
        if key is not None and (newest_key is None or key > newest_key):
            newest_key = key
            newest_raw = published_at
    # as_of is the DATA's timestamp (newest publish), never the query clock —
    # an overview of untouched data must not look fresh.
    return {
        "as_of": _iso(newest_raw),
        "ontology_versions": versions,
        "totals": totals,
    }


@router.get("/overview")
def public_overview(db: DbConn = Depends(get_db)) -> JSONResponse:
    """Anonymous platform overview (see module docstring for the contract)."""
    try:
        rows = list(db.execute(_LATEST_SQL).fetchall())
    except Exception as exc:  # noqa: BLE001 - degrade honestly, never fake freshness
        # Reason is the exception CLASS only: a string could carry DSN/host
        # internals, which must not cross the anonymous boundary.
        return JSONResponse(
            status_code=503,
            content={"error": "overview unavailable", "reason": type(exc).__name__},
        )
    return JSONResponse(_build_overview(rows))


@router.api_route("/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def public_overview_no_siblings(rest: str) -> JSONResponse:
    """Authenticated catch-all under ``/api/public/``.

    The constructor-level auth dependency runs BEFORE this handler, so an
    anonymous caller on any sibling path gets ``401`` (the exemption covers
    exactly ``/api/public/overview`` — no prefixes, no wildcards). A validly
    keyed caller reaches the handler and gets ``404``: nothing is served on
    siblings, but the 404 here proves the route boundary, not an open door.
    """
    raise HTTPException(status_code=404, detail="not found")
