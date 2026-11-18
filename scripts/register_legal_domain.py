#!/usr/bin/env python3
"""Register the legal domain as the FIRST retroactive ontology-template instance.

Pure DATA operation (openspec change ``add-ontology-template-and-workspaces``,
design D4): insert one ``ontology_templates`` row + one ``domains`` row binding
the existing legal domain key. It changes NO runtime behavior — nothing in
``src/bench`` or the legal pack is modified, and no existing table row is
touched (only new inserts into the two workspace tables).

The template vocabulary is retro-distilled from the legal domain pack AS IT
EXISTS ON DISK — this is a registration of current reality, not an invention:

- ``entity_types`` / ``concept_structures`` come from the pack's actual data
  model: ``packs/legal/pack.yaml`` (``kinds: [clause]``), the stored-clause DDL
  (``public.clauses``, declared in ``src/eval/store.py::CLAUSES_SCHEMA``) and
  the law-catalog replica DDL (``law_catalog.laws``, declared in
  ``packs/legal/law_catalog/store.py``).
- ``relationship_kinds`` are the relationships actually materialized in tables:
  clause→law citations (``clauses.law_refs`` + ``law_catalog.clause_law_refs``
  / ``clause_article_refs``), law→law succession (``law_catalog.successor_map``)
  and the clause→contract_type axis (``clauses.contract_type``).
- ``tier_vocabulary`` / ``sensitivity_vocabulary`` are imported verbatim from
  the kernel single sources of truth (``src.bench.tiers.TIERS`` and
  ``src.bench.promotion.SENSITIVITY_LEVELS``) — equality with them is enforced
  by ``src.bench.templates.validate_template_schema``.
- ``corpus_declaration`` describes the real corpus sources (declaration level
  only — no corpus content lives in the template).
- ``rubric_refs`` are the rubric identifiers actually defined for this domain
  by ``scripts/seed_contract_rubrics.py`` (``contract_<type>_v1`` for every
  type key in its ``RUBRICS`` list) plus the law-refined v2 names for the
  types covered by ``src.eval.law_refined_citations.LAW_REFINED_CITATIONS``.

Idempotent: a re-run checks before inserting — an existing domain key prints
the existing registration and exits 0; an existing template name is reused
(never re-versioned). ``--dry-run`` performs every check and prints what WOULD
happen, but writes nothing (it does not even run the idempotent DDL).

Run:
    uv run python scripts/register_legal_domain.py [--dry-run] [--database-url DSN]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# scripts/ is not a package: make the repo root importable so the src.* modules
# resolve whether this is run directly or invoked via subprocess.
sys.path.insert(0, str(REPO_ROOT))

TEMPLATE_NAME = "legal-domain"
DOMAIN_KEY = "legal"  # the existing legal domain key (packs/legal/pack.yaml name)
DOMAIN_NAME = "法律域"
CREATED_BY = "system:retro-register"

# Workspace tables this script depends on (created by ensure_schema via
# src.bench.workspace_store.WORKSPACE_SCHEMA).
WORKSPACE_TABLES = ("ontology_templates", "domains")


# --- vocabulary retro-distilled from the legal pack (with sources) -----------
#
# entity_types: the knowledge-unit kinds / entity-like categories actually
# present. "clause" = packs/legal/pack.yaml kinds:[clause] and the stored
# contract clauses (public.clauses; also the unit_kind used by store_result).
# "law" = the 法规目录只读副本 (law_catalog.laws in packs/legal/law_catalog/store.py).
ENTITY_TYPES = ["clause", "law"]

# Structural fields as observed in the pack's data model, verbatim from the
# table DDL (bookkeeping columns like created_at/body_hash/source_path omitted).
CONCEPT_STRUCTURES = {
    # public.clauses DDL (src/eval/store.py::CLAUSES_SCHEMA). The seed
    # manifests in data/clause_seeds/*.yaml additionally carry
    # family/stance/strength/why/verdict — generation-time attributes, not
    # columns of the stored clause.
    "clause": [
        "contract_type",
        "category",  # CHECK IN ('base','tagged','custom')
        "section",
        "body",
        "slot_instructions",  # JSONB: [{name, label, description, example, required}]
        "law_refs",  # JSONB: cited 法条 per clause
        "level",  # CHECK IN ('national','local')
        "tags",
    ],
    # law_catalog.laws DDL (packs/legal/law_catalog/store.py::_EXPORT_FIELDS).
    "law": [
        "id",
        "title",
        "category",
        "publish",  # 施行日期, stored verbatim
        "expiry",
        "status",
        "src_db",
        "content_status",
    ],
}

# Relationship kinds actually materialized in the pack's tables (not invented):
RELATIONSHIP_KINDS = [
    # clause → law: clauses.law_refs (derived column) and the resolution
    # results law_catalog.clause_law_refs / clause_article_refs
    # (clause_id × cited_name/citation × article_ordinal → law_id).
    "cites_law",
    # law → law: law_catalog.successor_map (dead_law_id → successor_law_id /
    # authority_law_id).
    "superseded_by",
    # clause → contract_type: the organizing axis clauses.contract_type
    # (41 types in data/clause_seeds), shared with tag_dims.contract_type.
    "belongs_to_contract_type",
]


def _count_seed_manifests() -> int:
    """Number of per-type seed manifests under data/clause_seeds/."""
    return len(list((REPO_ROOT / "data" / "clause_seeds").glob("*.yaml")))


def _derive_rubric_refs() -> list[str]:
    """Rubric identifiers actually defined for this domain in the repo.

    v1 names come from the ``_rubric("...")`` entries in
    ``scripts/seed_contract_rubrics.py`` (its ``RUBRICS`` list); v2 names exist
    for the types covered by the law-refined citation survey
    (``src.eval.law_refined_citations.LAW_REFINED_CITATIONS``). If the seed
    script is unavailable the list degrades honestly to [] — rubric refs are
    declared, never invented.
    """
    seed_script = REPO_ROOT / "scripts" / "seed_contract_rubrics.py"
    if not seed_script.exists():
        print(
            f"note: {seed_script.relative_to(REPO_ROOT)} not found — "
            "rubric_refs degrades to []",
            file=sys.stderr,
        )
        return []
    type_keys = sorted(set(re.findall(r'_rubric\("([a-z_]+)"', seed_script.read_text(encoding="utf-8"))))
    refs = [f"contract_{key}_v1" for key in type_keys]
    try:
        from src.eval.law_refined_citations import LAW_REFINED_CITATIONS

        refs.extend(f"contract_{key}_v2" for key in sorted(LAW_REFINED_CITATIONS))
    except Exception as exc:  # noqa: BLE001 - v2 names are additive, not required
        print(f"note: law-refined v2 rubric names unavailable ({exc})", file=sys.stderr)
    return sorted(set(refs))


def build_template_schema() -> dict:
    """Assemble the retro-distilled template schema (pure function of disk state).

    tier/sensitivity vocabularies are imported from the kernel single sources
    of truth (src.bench.tiers.TIERS, src.bench.promotion.SENSITIVITY_LEVELS);
    validate_template_schema enforces equality with them.
    """
    from src.bench.promotion import SENSITIVITY_LEVELS
    from src.bench.tiers import TIERS

    return {
        "entity_types": list(ENTITY_TYPES),
        "concept_structures": {k: list(v) for k, v in CONCEPT_STRUCTURES.items()},
        "relationship_kinds": list(RELATIONSHIP_KINDS),
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {
            "source_types": [
                # data/clause_seeds/*.yaml — one per-type manifest per
                # contract_type (186 seed clauses per data/clause_seeds/INDEX.md).
                "contract_clause_seed_manifests",
                # PostgreSQL law_catalog schema — full-replace import of the
                # external 法规库 catalog export (.json/.jsonl), plus aliases,
                # clause_law_refs, clause_article_refs, successor_map,
                # citation_revisions.
                "law_catalog_replica",
                # public.clauses — stored/generated contract clauses
                # (category: base | tagged | custom).
                "stored_clauses",
                # public.law_info — per contract_type × source survey of
                # governing statutes (src/eval/law_info.py, a pack component).
                "law_info_survey",
            ],
            "locations": {
                "contract_clause_seed_manifests": (
                    f"data/clause_seeds/*.yaml ({_count_seed_manifests()} per-type "
                    "manifests, audit trail in data/clause_seeds/INDEX.md)"
                ),
                "law_catalog_replica": (
                    "PostgreSQL schema law_catalog (laws, aliases, clause_law_refs, "
                    "clause_article_refs, successor_map, citation_revisions); "
                    "replica imported from the external 法规库 catalog export "
                    "(.json/.jsonl)"
                ),
                "stored_clauses": "PostgreSQL table public.clauses",
                "law_info_survey": "PostgreSQL table public.law_info",
            },
            "organization": (
                "clause knowledge units are keyed by contract_type; their "
                "法条 citations resolve against the law_catalog replica"
            ),
        },
        "rubric_refs": _derive_rubric_refs(),
    }


# --- registration flow -------------------------------------------------------


def _tables_exist(conn) -> dict[str, bool]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)",
        (list(WORKSPACE_TABLES),),
    ).fetchall()
    present = {(r["table_name"] if isinstance(r, dict) else r[0]) for r in rows}
    return {t: t in present for t in WORKSPACE_TABLES}


def _print_vocabulary(schema: dict) -> None:
    print("\ntemplate schema (retro-distilled from packs/legal/):")
    print(json.dumps(schema, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Register the legal domain as the first retroactive "
        "ontology-template instance (data only; no runtime code changes)."
    )
    ap.add_argument("--dry-run", action="store_true", help="check and print only; write nothing")
    ap.add_argument("--database-url", default=None, help="PostgreSQL DSN override (env database_url)")
    args = ap.parse_args(argv)

    # DSN override must land before the first connect(): src.eval.db._dsn reads
    # the env at call time and load_dotenv() does not override existing vars.
    if args.database_url:
        os.environ["database_url"] = args.database_url

    from src.bench.templates import validate_template_schema
    from src.eval.db import connect

    schema = build_template_schema()

    problems = validate_template_schema(schema)
    if problems:
        print("template schema INVALID — nothing written:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("template schema validation: OK")

    conn = connect()
    try:
        from src.bench import templates, workspaces

        if not args.dry_run:
            # Real run: ensure the workspace schema exists first (the repo's own
            # idempotent DDL mechanism; also creates the four workspace tables
            # via WORKSPACE_SCHEMA). Only ever INSERTs new rows into the two
            # workspace tables afterwards; no existing row anywhere is updated
            # or deleted.
            from src.eval.store import ensure_schema

            ensure_schema()

        table_state = _tables_exist(conn)
        missing = [t for t, ok in table_state.items() if not ok]
        if missing:
            print(f"\nworkspace tables missing: {', '.join(missing)}")
            if args.dry_run:
                print(
                    "dry-run: a real run would first create them via "
                    "src.eval.store.ensure_schema() (idempotent DDL), then insert "
                    f"template {TEMPLATE_NAME!r} v1 and domain {DOMAIN_KEY!r}. "
                    "Nothing written."
                )
            else:
                print(
                    "ensure_schema ran but the tables are still missing — refusing "
                    "to insert (check WORKSPACE_SCHEMA registration in src/eval/store.py)."
                )
                return 1
            _print_vocabulary(schema)
            return 0

        domain = workspaces.get_domain(conn, domain_key=DOMAIN_KEY)
        template = templates.get_template(conn, name=TEMPLATE_NAME)

        if args.dry_run:
            if domain is not None:
                print(
                    f"\nALREADY REGISTERED — domain key {DOMAIN_KEY!r} exists "
                    f"(id={domain['id']}, name={domain['name']!r}, template "
                    f"{domain['template_name']!r} v{domain['template_version']}). "
                    "A real run would print this and exit 0. Nothing written."
                )
            else:
                action = (
                    f"reuse existing template {TEMPLATE_NAME!r} "
                    f"v{template['version']} (id={template['id']})"
                    if template is not None
                    else f"create template {TEMPLATE_NAME!r} v1 "
                    "(created_by='system:retro-register')"
                )
                print(f"\nDRY-RUN plan: would {action}, then instantiate domain "
                      f"key={DOMAIN_KEY!r} name={DOMAIN_NAME!r} anchored to that "
                      "template version (created_by='system:retro-register'). "
                      "Nothing written.")
            _print_vocabulary(schema)
            return 0

        # Check-before-insert on both rows.
        domain = workspaces.get_domain(conn, domain_key=DOMAIN_KEY)
        if domain is not None:
            print(
                f"\nALREADY REGISTERED — domain key {DOMAIN_KEY!r} exists "
                f"(id={domain['id']}, name={domain['name']!r}, template "
                f"{domain['template_name']!r} v{domain['template_version']}); "
                "no new rows written."
            )
            return 0

        template = templates.get_template(conn, name=TEMPLATE_NAME)
        if template is not None:
            print(
                f"template {TEMPLATE_NAME!r} already exists "
                f"(id={template['id']}, v{template['version']}) — reusing it, "
                "no new version written."
            )
        else:
            template = templates.create_template(
                conn, name=TEMPLATE_NAME, schema=schema, created_by=CREATED_BY
            )
            print(f"created template {TEMPLATE_NAME!r} (id={template['id']}, v{template['version']})")

        domain = workspaces.instantiate_domain(
            conn,
            key=DOMAIN_KEY,
            name=DOMAIN_NAME,
            template_name=TEMPLATE_NAME,
            template_version=template["version"],
            created_by=CREATED_BY,
        )
        print(
            f"created domain key={domain['key']!r} (id={domain['id']}, "
            f"name={domain['name']!r}) anchored to template "
            f"{domain['template_name']!r} v{domain['template_version']} "
            f"(template_id={domain['template_id']})"
        )
        print(
            "\nregistration summary: template id/version = "
            f"{template['id']}/{template['version']}, domain id/key = "
            f"{domain['id']}/{domain['key']}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
