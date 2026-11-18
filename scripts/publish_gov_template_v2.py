"""Publish the gov domain's concept layer as template v2 (additive).

Run from the repo root with the database reachable::

    python3 scripts/publish_gov_template_v2.py --dry-run
    python3 scripts/publish_gov_template_v2.py --reanchor-gov

Why a version bump and not an edit: template rows are immutable by design (a
domain pins a version, and a later edit must never retroactively change what an
existing domain declares). v2 is a **new row** that adds two vocabulary entries:

- ``entity_types`` += ``concept`` — a policy concept (政府采购, 预算绩效管理) is the
  unit a reader reasons with. Without the type it can only be squeezed into
  ``document``/``policy``, which it is not, so the domain's ``grounding`` has a
  permanent zero denominator and reads ``None``.
- ``relationship_kinds`` += ``defines`` — direction is fixed **concept → 公文**:
  this document is the evidence the concept is grounded in. Same direction as
  the legal line so ``quality.grounding`` reads both lines identically.

The live ``gov`` domain is **not** re-anchored by default: moving a production
anchor is a deliberate action (``--reanchor-gov``), and the rollback is the v1
row id — v1 is never modified.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bench import templates, workspaces  # noqa: E402

TEMPLATE_NAME = "gov-domain"
DOMAIN_KEY = "gov"

#: Added by this version. Kept explicit (not "whatever the pack says") so the
#: diff between v1 and v2 is readable in the script itself.
ADDED_ENTITY_TYPES = ("concept",)
ADDED_RELATIONSHIP_KINDS = ("defines",)


def build_v2_schema(base: dict) -> dict:
    """v1 schema with the concept layer appended; everything else untouched."""
    schema = json.loads(json.dumps(base))  # deep copy, JSON-safe by construction
    entities = list(schema.get("entity_types") or [])
    for kind in ADDED_ENTITY_TYPES:
        if kind not in entities:
            entities.append(kind)
    schema["entity_types"] = entities
    relations = list(schema.get("relationship_kinds") or [])
    for kind in ADDED_RELATIONSHIP_KINDS:
        if kind not in relations:
            relations.append(kind)
    schema["relationship_kinds"] = relations
    # What a reviewer needs to judge a proposed concept, no more.
    structures = dict(schema.get("concept_structures") or {})
    structures.setdefault("concept", ["definition", "source_document"])
    schema["concept_structures"] = structures
    return schema


_ADDED_RELATION_DIRECTIONS = {
    "defines": "concept -> document（该公文是这条概念的依据）",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", default=TEMPLATE_NAME)
    ap.add_argument("--domain", default=DOMAIN_KEY)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reanchor-gov", action="store_true",
                    help="ALSO move the gov domain to v2 (deliberate, reversible)")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        latest = templates.get_template(conn, name=args.template)
        if latest is None:
            print(f"template {args.template!r} not found", file=sys.stderr)
            return 1
        schema_v1 = latest["schema"] or {}
        if "concept" in (schema_v1.get("entity_types") or []):
            print(f"template already carries the concept layer (v{latest['version']})")
            return 0
        if schema_v1.get("relationship_kinds") and "defines" in schema_v1["relationship_kinds"]:
            print(f"template already declares 'defines' (v{latest['version']})")
            return 0

        schema_v2 = build_v2_schema(schema_v1)
        print(f"v{latest['version']} entity_types      : {schema_v1.get('entity_types')}")
        print(f"v2 entity_types      : {schema_v2['entity_types']}")
        print(f"v{latest['version']} relationship_kinds : {schema_v1.get('relationship_kinds')}")
        print(f"v2 relationship_kinds : {schema_v2['relationship_kinds']}")
        for kind, direction in _ADDED_RELATION_DIRECTIONS.items():
            print(f"  {kind}: {direction}")

        if args.dry_run:
            print("[dry-run] would create the next version; nothing written")
            return 0

        created = templates.update_template(
            conn, name=args.template, schema=schema_v2, created_by="publish_gov_v2"
        )
        print(f"published template {args.template!r} v{created['version']} (id={created['id']})")

        if not args.reanchor_gov:
            print("the gov domain is still anchored to the old version "
                  "(pass --reanchor-gov to move it on purpose)")
            return 0

        domain = workspaces.get_domain(conn, domain_key=args.domain)
        if domain is None:
            print(f"domain {args.domain!r} not found; nothing to re-anchor", file=sys.stderr)
            return 1
        before = domain["template_version"]
        conn.execute(
            "UPDATE domains SET template_id = %s, template_version = %s WHERE id = %s",
            (created["id"], created["version"], domain["id"]),
        )
        conn.commit()
        print(f"re-anchored domain {args.domain!r}: v{before} -> v{created['version']}")
        print(f"rollback: domains.template_id={latest['id']}, template_version={latest['version']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
