#!/usr/bin/env python3
"""Backfill ``domain_assets`` from an explicit per-domain manifest.

Why this exists: making an evaluation asset belong to a domain is a **directory**
fact (change ``add-domain-first-workbench``, P1 §6.4). The tempting shortcut —
"assign every rubric / prompt / clause to ``legal``" — is exactly what the
kernel forbids: ``domain_assets.backfill`` has no "assign all" mode, because the
whole corpus of a shared platform does not become one domain's shelf merely
because that domain happened to exist first. So a backfill must *state* what it
is claiming, in a file a human reviews.

Manifest shape (JSON)::

    {
      "legal": {
        "rubric": ["contract_lease_v1", "contract_loan_v1"],
        "prompt": ["clause_extract_v1"],
        "clause": ["1042", "1043"]
      }
    }

Keys are ``domain_key → asset_kind → [asset_key, ...]``. ``asset_kind`` and
``asset_key`` are validated by the kernel against the registered providers
(``packs/legal/asset_catalog.py``): an unknown kind is refused outright, while a
*known* kind with a key that does not exist (yet) is reported as ``missing``
instead of raising — a manifest is data, and may legitimately name an asset that
arrives in a later deploy.

Idempotent: re-running inserts nothing (``ON CONFLICT DO NOTHING``), and
unassigning never deletes the asset itself — only the directory row. ``--dry-run``
writes nothing at all: it resolves the same facts read-only and prints the
counts a real run would produce.

Run:
    uv run python scripts/backfill_domain_assets.py --manifest <path.json> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is not a package: make the repo root importable so the src.* modules
# resolve whether this is run directly or invoked via subprocess.
sys.path.insert(0, str(REPO_ROOT))


def _load_manifest(path: Path) -> dict[str, dict[str, list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise SystemExit(f"manifest {path}: expected a non-empty object of domain_key → kind → [keys]")
    out: dict[str, dict[str, list[str]]] = {}
    for domain_key, kinds in data.items():
        if not isinstance(kinds, dict) or not kinds:
            raise SystemExit(f"manifest {path}: domain {domain_key!r} must map at least one asset kind")
        for kind, keys in kinds.items():
            if not isinstance(keys, list) or not keys:
                raise SystemExit(
                    f"manifest {path}: {domain_key}.{kind} must be a non-empty list of asset keys"
                )
            for key in keys:
                if not isinstance(key, str) or not key.strip():
                    raise SystemExit(
                        f"manifest {path}: {domain_key}.{kind} contains a blank or non-string key"
                    )
                if key.startswith("*") or key == "all":
                    raise SystemExit(
                        f"manifest {path}: {domain_key}.{kind} — {key!r} is a wildcard; "
                        "a backfill must name each asset (the kernel has no 'assign all' mode)"
                    )
        out[domain_key] = {kind: list(keys) for kind, keys in kinds.items()}
    return out


def _dry_run_counts(
    conn: Any, *, domain_key: str, asset_kind: str, asset_keys: list[str], providers: dict
) -> dict:
    """Read-only twin of ``domain_assets.backfill`` for ``--dry-run``.

    Same three buckets — would be assigned / already catalogued / missing from
    the asset relation — and **in the same order of decision as the kernel**:
    a key whose asset row is gone is ``missing`` even if a directory row for it
    still exists (that is an orphan, not a catalogued asset). Getting this order
    wrong is why an orphan showed up as "already present" in dry-run and
    "missing" in a real run.
    """
    from src.bench.domain_assets import list_for_domain

    relation = providers[asset_kind]["relation"]
    existing = {
        item["asset_key"]
        for group in list_for_domain(conn, domain_key=domain_key, providers=providers)["groups"]
        if group["kind"] == asset_kind
        for item in group["items"]
        if item["exists"]
    }
    assigned = already = 0
    missing: list[str] = []
    for key in dict.fromkeys(asset_keys):
        found = conn.execute(
            f"SELECT 1 FROM ({relation}) a WHERE a.asset_key = %s LIMIT 1", (key,)
        ).fetchone()
        if found is None:
            missing.append(key)
        elif key in existing:
            already += 1
        else:
            assigned += 1
    return {"assigned": assigned, "already": already, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True, help="JSON manifest: domain_key → asset_kind → [keys]")
    ap.add_argument("--added-by", default="script:backfill_domain_assets", help="provenance recorded on each row")
    ap.add_argument("--dry-run", action="store_true", help="resolve and print counts; write nothing")
    ap.add_argument("--database-url", default=None, help="PostgreSQL DSN override (env database_url)")
    args = ap.parse_args(argv)

    if args.database_url:
        os.environ["database_url"] = args.database_url

    manifest = _load_manifest(Path(args.manifest))

    from src.bench import domain_assets
    from src.eval.db import connect

    # Importing the pack is what registers its providers with the kernel; a
    # deployment that never imports the pack has no asset kinds at all.
    import packs.legal.asset_catalog  # noqa: F401

    providers = domain_assets.providers()
    if not providers:
        print("no asset providers registered — import the domain pack first", file=sys.stderr)
        return 1

    conn = connect()
    try:
        total_assigned = total_already = 0
        total_missing: list[tuple[str, str, str]] = []
        for domain_key, kinds in manifest.items():
            for asset_kind, keys in kinds.items():
                if asset_kind not in providers:
                    print(
                        f"unknown asset kind {asset_kind!r} for domain {domain_key!r}; "
                        f"registered kinds: {', '.join(sorted(providers))}",
                        file=sys.stderr,
                    )
                    return 1
                if args.dry_run:
                    counts = _dry_run_counts(
                        conn,
                        domain_key=domain_key,
                        asset_kind=asset_kind,
                        asset_keys=keys,
                        providers=providers,
                    )
                else:
                    counts = domain_assets.backfill(
                        conn,
                        domain_key=domain_key,
                        asset_kind=asset_kind,
                        asset_keys=keys,
                        added_by=args.added_by,
                        providers=providers,
                    )
                total_assigned += counts["assigned"]
                total_already += counts["already"]
                total_missing.extend((domain_key, asset_kind, k) for k in counts["missing"])
                verb = "would assign" if args.dry_run else "assigned"
                print(
                    f"{domain_key}.{asset_kind}: {verb} {counts['assigned']}, "
                    f"already catalogued {counts['already']}, missing {len(counts['missing'])}"
                )

        print(
            f"\n{'dry-run — nothing written' if args.dry_run else 'done'}: "
            f"{total_assigned} {'new rows' if not args.dry_run else 'rows would be added'}, "
            f"{total_already} already present, {len(total_missing)} keys missing from their asset table"
        )
        for domain_key, asset_kind, key in total_missing:
            print(f"  missing: {domain_key}.{asset_kind} {key}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
