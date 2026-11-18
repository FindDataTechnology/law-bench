"""Publish the legal domain's concept layer as template v2 (additive).

Run inside the law-bench pod::

    python3 scripts/publish_legal_template_v2.py --dry-run
    python3 scripts/publish_legal_template_v2.py

Why a version bump and not an edit: template rows are immutable by design (a
domain pins a version, and a later edit must never retroactively change what an
existing domain declares). v2 is a **new row** that adds two vocabulary entries
and changes nothing else:

- ``entity_types`` += ``concept`` — legal concepts (违约责任, 连带清偿责任) are the
  unit people actually reason with; without the type they can only be squeezed
  into ``clause``/``law``, which they are not.
- ``relationship_kinds`` += ``defines`` — a concept is *grounded in* an article.

The live ``legal`` domain is **not** re-anchored here. Re-anchoring changes the
production anchor of the main domain; that is a separate, deliberate action
(``--reanchor-legal`` exists so it can be done on purpose, never by accident).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bench import templates, workspaces  # noqa: E402

TEMPLATE_NAME = "legal-domain"

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
    # A concept's structural fields: what a reviewer needs to judge it, no more.
    structures = dict(schema.get("concept_structures") or {})
    structures.setdefault("concept", ["definition", "statute_refs", "source_case"])
    schema["concept_structures"] = structures
    return schema


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--template", default=TEMPLATE_NAME)
    ap.add_argument("--reanchor-legal", action="store_true",
                    help="ALSO move the legal domain to v2 (deliberate, reversible)")
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
            print(f"template already carries the concept layer "
                  f"(v{latest['version']}); nothing to publish")
            return 0
        schema_v2 = build_v2_schema(schema_v1)
        print(f"v{latest['version']} entity_types     : {schema_v1.get('entity_types')}")
        print(f"v2 entity_types     : {schema_v2['entity_types']}")
        print(f"v{latest['version']} relationship_kinds: {schema_v1.get('relationship_kinds')}")
        print(f"v2 relationship_kinds: {schema_v2['relationship_kinds']}")

        if args.dry_run:
            print("[dry-run] would create the next version; nothing written")
            return 0

        created = templates.update_template(
            conn, name=args.template, schema=schema_v2, created_by="publish_legal_v2"
        )
        print(f"published template {args.template!r} v{created['version']}")

        if not args.reanchor_legal:
            print("the legal domain is still anchored to the old version "
                  "(pass --reanchor-legal to move it on purpose)")
            return 0

        domain = workspaces.get_domain(conn, domain_key="legal")
        if domain is None:
            print("domain 'legal' not found; nothing to re-anchor", file=sys.stderr)
            return 1
        before = domain["template_version"]
        conn.execute(
            "UPDATE domains SET template_id = %s, template_version = %s WHERE id = %s",
            (created["id"], created["version"], domain["id"]),
        )
        conn.commit()
        print(f"re-anchored domain 'legal': v{before} -> v{created['version']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
