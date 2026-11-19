#!/usr/bin/env python3
"""Register the layered foundation / industry templates.

Four templates, one script, because they share one vocabulary decision table and
splitting them would let the four drift apart the moment somebody edits one.

    foundation-v1         layer=foundation   authority=platform
    enterprise-base       layer=industry     authority=platform   extends foundation-v1
    finance-market        layer=industry     authority=platform   extends foundation-v1
    (external-world-*  is NOT here — it is imported read-only from the protocol
     package by ``scripts/import_protocol_ontology.py``, because its authority
     lives outside this repository.)

Why `customer` is a relationship and not an entity type: the same company is a
customer in one system, a vendor in another and a supplier in a third, and each
of those is a *role that an organisation plays*. Making the roles into types
would put the cross-system alignment between types, where there is no stable
landing spot — you would need a mapping table between "customer" and "Acme
GmbH". As a relationship it stays one `organization` entity with three roles.

Idempotent: an existing template name is reused, never re-versioned. ``--dry-run``
performs every check and prints the plan without writing.

Run:
    uv run python scripts/register_layered_templates.py --dry-run
    uv run python scripts/register_layered_templates.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import templates  # noqa: E402
from src.bench.promotion import SENSITIVITY_LEVELS  # noqa: E402
from src.bench.tiers import TIERS  # noqa: E402

CREATED_BY = "system:layered-templates"

#: The shared base. Eight generic types, four generic relations — deliberately
#: small. A foundation that tries to cover everything becomes the "big pile
#: nobody agrees with", and every industry template then inherits the pile.
FOUNDATION = {
    "layer": "foundation",
    "authority": {"kind": "platform"},
    "entity_types": [
        "organization",   # a legal or operational body: company, agency, store
        "person",         # a natural person acting in some capacity
        "place",          # a geographic or physical location
        "item",           # a thing that can be counted, moved, or sold
        "document",       # a record that carries content: contract, invoice, filing
        "event",          # something that happened at a time: a shipment, a payment
        "agreement",      # a two-or-more-party arrangement with obligations
        "measurement",    # a value with a unit, a time and a subject
    ],
    "relationship_kinds": [
        "part_of",    # item -> item / place -> place
        "member_of",  # person -> organization
        "about",      # document -> any subject it concerns
        "located_at", # organization / event -> place
    ],
    "concept_structures": {
        "organization": ["name", "kind", "jurisdiction"],
        "person": ["name", "role"],
        "place": ["name", "admin_level"],
        "item": ["name", "unit"],
        "document": ["title", "issued_at", "issuer"],
        "event": ["occurred_at", "kind"],
        "agreement": ["parties", "effective_from"],
        "measurement": ["value", "unit", "observed_at"],
    },
    "corpus_declaration": {"source_types": [], "granularity": "document"},
}

#: What an ERP domain needs on top of the foundation. The five accounting
#: primitives (`account`, `journal_entry`, `invoice`, `purchase_order`,
#: `payment`) are here because every ERP — Kingdee, Salesforce-adjacent CRMs,
#: Yonyou — has them; the vendor-specific spellings go into crosswalks, not here.
ENTERPRISE_BASE_ADDITIONS = {
    "entity_types": ["item", "warehouse", "account", "journal_entry",
                     "invoice", "purchase_order", "payment"],
    "relationship_kinds": [
        "sells_to",    # organization(customer role) -> organization
        "supplies",    # organization(vendor role) -> organization
        "employed_by", # person -> organization
        "posts_to",    # journal_entry -> account
        "settles",     # payment -> invoice
    ],
    "concept_structures": {
        "warehouse": ["name", "location"],
        "account": ["code", "name", "kind"],
        "journal_entry": ["posted_at", "amount", "currency"],
        "invoice": ["number", "issued_at", "amount"],
        "purchase_order": ["number", "ordered_at", "amount"],
        "payment": ["paid_at", "amount", "method"],
    },
}

#: Market-side concepts. `instrument` is the traded thing (stock/bond/fund), not
#: a synonym for `company`: the observatory keys quotes on the instrument, and a
#: company may have several instruments listed.
FINANCE_MARKET_ADDITIONS = {
    "entity_types": ["instrument", "quote", "position", "indicator"],
    "relationship_kinds": [
        "issued_by",   # instrument -> organization
        "quoted_as",   # quote -> instrument
        "held_in",     # position -> instrument
        "measures",    # indicator -> measurement
    ],
    "concept_structures": {
        "instrument": ["symbol", "kind", "currency"],
        "quote": ["observed_at", "value", "currency"],
        "position": ["quantity", "as_of"],
        "indicator": ["code", "unit", "frequency"],
    },
}


def _base_schema() -> dict:
    """The six required keys every template carries (with empty vocabularies)."""
    return {
        "entity_types": [],
        "concept_structures": {},
        "relationship_kinds": [],
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": [], "granularity": "document"},
    }


def foundation_schema() -> dict:
    schema = _base_schema()
    schema.update(
        {k: v for k, v in FOUNDATION.items() if k not in ("entity_types",
                                                          "relationship_kinds",
                                                          "concept_structures",
                                                          "corpus_declaration")}
    )
    schema["entity_types"] = list(FOUNDATION["entity_types"])
    schema["relationship_kinds"] = list(FOUNDATION["relationship_kinds"])
    schema["concept_structures"] = dict(FOUNDATION["concept_structures"])
    schema["corpus_declaration"] = dict(FOUNDATION["corpus_declaration"])
    return schema


def _child_schema(additions: dict, *, name: str) -> dict:
    """An industry template: the additions **on top of** the foundation's items.

    The inherited items are listed explicitly rather than omitted. That is not
    redundancy — ``merge_schema`` refuses a child that does not name every item
    its parent granted, precisely so a typo cannot silently drop a vocabulary
    item. Writing the union here means the child's own schema reads as the
    complete vocabulary it declares, and the parent link only supplies the
    provenance.
    """
    schema = _base_schema()
    schema["layer"] = "industry"
    schema["authority"] = {"kind": "platform"}
    schema["extends"] = {"name": "foundation-v1", "version": 1}
    schema["entity_types"] = list(FOUNDATION["entity_types"]) + [
        t for t in additions["entity_types"] if t not in FOUNDATION["entity_types"]
    ]
    schema["relationship_kinds"] = list(FOUNDATION["relationship_kinds"]) + [
        r for r in additions["relationship_kinds"]
        if r not in FOUNDATION["relationship_kinds"]
    ]
    schema["concept_structures"] = {
        **FOUNDATION["concept_structures"], **additions["concept_structures"]
    }
    return schema


def plans() -> list[tuple[str, dict]]:
    return [
        ("foundation-v1", foundation_schema()),
        ("enterprise-base", _child_schema(ENTERPRISE_BASE_ADDITIONS, name="enterprise-base")),
        ("finance-market", _child_schema(FINANCE_MARKET_ADDITIONS, name="finance-market")),
    ]


def _describe(name: str, schema: dict) -> str:
    return (
        f"{name}: layer={schema.get('layer')} "
        f"authority={(schema.get('authority') or {}).get('kind')} "
        f"extends={schema.get('extends')} "
        f"entity_types={len(schema.get('entity_types') or [])} "
        f"relationship_kinds={len(schema.get('relationship_kinds') or [])}"
    )


def eval_dsn() -> str:
    """The real PostgreSQL DSN (``database_url`` env), never the SQLite path constant."""
    from src.eval import db as edb

    return edb._dsn()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and validate, write nothing")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)

    # Validation is pure, so dry-run catches a broken vocabulary without a DB.
    for name, schema in plans():
        problems = templates.validate_template_schema(schema)
        if problems:
            print(f"INVALID {name}: " + "; ".join(problems), file=sys.stderr)
            return 1

    if args.dry_run:
        print("DRY-RUN — nothing written. Plan:")
        for name, schema in plans():
            print("  " + _describe(name, schema))
        return 0

    import psycopg

    from src.eval import store as eval_store

    # DEFAULT_DB is the legacy SQLite path constant, NOT a DSN — passing it to
    # psycopg makes conninfo parsing blow up on a PosixPath. Read the real DSN.
    dsn = args.database_url or eval_dsn()
    conn = psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)
        for name, schema in plans():
            existing = templates.get_template(conn, name=name)
            if existing is not None:
                print(f"reuse {name} v{existing['version']} (id={existing['id']}) — "
                      "no new version written")
                continue
            created = templates.create_template(
                conn, name=name, schema=schema, created_by=CREATED_BY
            )
            print(f"created {name} v{created['version']} (id={created['id']}): "
                  f"{_describe(name, schema)}")
        print("\nsummary:")
        for row in templates.list_templates(conn):
            schema = row["schema"]
            if schema.get("layer") in ("foundation", "industry"):
                print(f"  {row['name']} v{row['version']} "
                      f"layer={schema.get('layer')}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
