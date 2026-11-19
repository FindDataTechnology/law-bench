#!/usr/bin/env python3
"""Import the ERP line's three-state connector evidence as crosswalks.

The ERP package keeps this evidence in ``connector-status.json`` (derived from
the connector catalog). The platform is the read authority from now on, so this
script moves what already exists into ``kind='crosswalk'`` units — once, idempotently.

**Two units per integration, on purpose:**

1. the provider entity (``external_system:<provider>``) — a crosswalk must point
   at a real endpoint, and the inbox refuses to manufacture one;
2. the crosswalk asserting our system's relationship to it, carrying
   ``connectivity`` verbatim.

Why not invent a mapping per ERP *field*? We do not have field-level mappings in
this file — it holds connectivity, not column correspondence. Writing「this whole
system maps to that type」is exactly what the evidence supports, and nothing more.
Fabricating field maps to make the numbers look richer is the failure mode the
whole feature exists to prevent.

Idempotent by ``(kind, external_key)``: a re-run updates the same units and
reports「幂等命中」instead of creating duplicates.

Run:
    uv run python scripts/import_connector_crosswalks.py --dry-run
    uv run python scripts/import_connector_crosswalks.py
    uv run python scripts/import_connector_crosswalks.py \\
        --status /path/to/connector-status.json --domain erp
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

#: Where the ERP package keeps the derived evidence. Overridable because the two
#: repos sit side by side in the workspace but are separate checkouts.
DEFAULT_STATUS = (
    REPO_ROOT.parent / "fd-erp-vertical-templates" / "connector-status.json"
)

#: The provider entity's kind. Deliberately a *type* the template declares for
#: this import (see --ensure-type), not a crosswalk: an external system is a
#: thing, and the assertion about it goes in the crosswalk.
PROVIDER_KIND = "external_system"

#: The internal endpoint a provider is mapped onto. Every connector in this file
#: is an outside system the business ontology relates to; `organization` is the
#: foundation's landing spot for "a body we exchange with".
DEFAULT_TARGET = "organization"


def load_status(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"connector-status.json not found at {path}")
    body = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict) or not isinstance(body.get("integrations"), list):
        raise SystemExit(f"{path}: missing 'integrations'")
    return body


def plans(status: dict, *, target: str) -> list[dict]:
    """One crosswalk per (template, provider), plus the provider entity.

    ``connectivity`` is copied verbatim so the platform records exactly what the
    ERP file says — normalising it here would make the two sides disagree the
    first time either changes.
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in status["integrations"]:
        provider = (row.get("provider") or "").strip()
        template = (row.get("template") or "").strip()
        if not provider or not template:
            continue
        # The same provider appears once per vertical (wechatpay: restaurant +
        # supply-chain). Keying by provider alone would collapse two distinct
        # bindings into one.
        if (template, provider) in seen:
            continue
        seen.add((template, provider))

        states = row.get("states") or {}
        connectivity = {
            state: {
                "ok": bool((states.get(state) or {}).get("ok")),
                "evidence": (states.get(state) or {}).get("evidence"),
            }
            for state in ("catalog", "executor_tests", "live")
        }
        missing = [
            s for s in ("catalog", "executor_tests", "live")
            if not connectivity[s]["ok"]
        ]
        out.append({
            "template": template,
            "provider": provider,
            "provider_key": f"{PROVIDER_KIND}:{provider}",
            "crosswalk_key": f"{target}:{provider}",
            "connectivity": connectivity,
            "missing": missing,
            "external_system": row.get("external_system") or provider,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", default=str(DEFAULT_STATUS))
    ap.add_argument("--domain", default="erp",
                    help="target domain key (one per vertical; see --list-domains)")
    ap.add_argument("--target", default=DEFAULT_TARGET,
                    help="internal entity type a provider is mapped onto")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="confirm even when the domain is not judgeable yet")
    args = ap.parse_args(argv)

    status = load_status(Path(args.status))
    rows = plans(status, target=args.target)
    if not rows:
        print("no integrations to import")
        return 0

    by_template: dict[str, list[dict]] = {}
    for row in rows:
        by_template.setdefault(row["template"], []).append(row)

    print(f"{len(rows)} integration(s) across {len(by_template)} template(s):")
    for template, items in sorted(by_template.items()):
        complete = sum(1 for i in items if not i["missing"])
        print(f"  {template}: {len(items)} provider(s), {complete} fully connected")

    if args.dry_run:
        for row in rows:
            flag = "✓" if not row["missing"] else "缺 " + "/".join(row["missing"])
            print(f"  would import {row['crosswalk_key']:38s} [{flag}]")
        print("\nDRY-RUN — nothing written.")
        return 0

    import psycopg

    from src.bench import authoring, crosswalk as cw
    from src.bench import store
    from src.eval import store as eval_store

    from src.eval import db as edb

    conn = psycopg.connect(edb._dsn(), row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)

        created_entities = updated_entities = 0
        created_crosswalks = updated_crosswalks = 0

        for row in rows:
            # 1. the provider entity — a crosswalk needs a real endpoint, and the
            #    proposal inbox deliberately refuses to manufacture one.
            if store.get_knowledge_unit(
                conn, kind=PROVIDER_KIND, external_key=row["provider_key"],
                namespace=args.domain,
            ) is None:
                authoring.authoring_create_unit(
                    conn, domain_key=args.domain, kind=PROVIDER_KIND,
                    external_key=row["provider_key"],
                    body=f"{row['external_system']}（外部系统）", operator="system:import",
                )
                created_entities += 1
            else:
                updated_entities += 1

            # 2. the assertion itself. `confidence` is omitted on purpose: the
            #    ERP file says nothing about how sure anyone is, and inventing a
            #    number would count as reviewed something nobody reviewed.
            attrs = {
                "relation": "same_as",
                "peer": {
                    "kind": "external_id",
                    "system": row["provider"],
                    "id": row["provider"],
                },
                "connectivity": row["connectivity"],
            }
            problems = cw.validate_crosswalk(attrs)
            if problems:
                print(f"  SKIP {row['crosswalk_key']}: {'; '.join(problems)}",
                      file=sys.stderr)
                continue
            existed = store.get_knowledge_unit(
                conn, kind="crosswalk", external_key=row["crosswalk_key"],
                namespace=args.domain,
            ) is not None
            authoring.authoring_create_crosswalk(
                conn, domain_key=args.domain, external_key=row["crosswalk_key"],
                body=f"{row['external_system']} ← {args.target}（三态证据）",
                operator="system:import", attrs=attrs,
            )
            if existed:
                updated_crosswalks += 1
            else:
                created_crosswalks += 1

        print(
            f"entities: +{created_entities} new / {updated_entities} existing; "
            f"crosswalks: +{created_crosswalks} new / {updated_crosswalks} existing"
        )
        print(
            "note: 未复核的映射不会计入覆盖率——这份文件没说置信度，"
            "所以它们落库后仍是「待复核」，等真人看过才算数。"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
