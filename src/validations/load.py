"""One-shot loader: populate ``type_validations`` from generator YAMLs.

Reuses ``src.clauses.generator_import.build_registry()`` (which itself wraps
the generator's ``RulesRegistry``) so inheritance is resolved by the
generator's own loader — we never parse YAML ad hoc.

Idempotent via ``UNIQUE (contract_type, constraint_id)`` — re-running
upserts in place.  Run once:  ``python -m src.validations.load``
"""

from __future__ import annotations

import json
from typing import Any

# generator type id → law-bench contract_type key
TYPE_MAP: dict[str, str] = {
    # Cat A (overlap, renamed)
    "sale": "sale", "lease": "lease", "loan": "loan", "transport": "transport",
    "technology": "technology", "project": "construction", "work": "work",
    "labor": "employment", "gift": "gift", "mandate": "entrustment",
    "brokerage": "brokerage", "consignment": "intermediation",
    "partnership": "partnership", "guarantee": "guarantee",
    "factoring": "factoring", "property": "property_service",
    "service": "service", "utility": "utilities_supply",
    "deposit": "bailment", "storage": "warehousing",
    "equity-transfer": "equity_transfer", "franchise": "franchise",
    "nominee-holding": "equity_holding_in_trust",
    "labor-dispatch": "labor_dispatch", "tourism": "tourism_service",
    "rural-land": "land_transfer",
    # Cat B (identity — generator id == law-bench key)
    "mortgage": "mortgage", "pledge": "pledge", "will": "will",
    "prenup": "prenup", "marital-property": "marital_property",
    "divorce": "divorce", "adoption": "adoption",
    "legacy-support": "legacy_support",
    "elderly-support": "elderly_support",
    "estate-division": "estate_division",
    "debt-transfer": "debt_transfer",
    "debt-restructuring": "debt_restructuring",
    "settlement": "settlement",
    "accident-settlement": "accident_settlement",
    "nda": "nda", "non-compete": "non_compete",
    "internship": "internship", "training": "training",
    "labor-service": "labor_service", "housekeeping": "housekeeping",
    "shareholders": "shareholders", "investment": "investment",
    "shop-transfer": "shop_transfer",
}

_DDL = """
CREATE TABLE IF NOT EXISTS type_validations (
  id SERIAL PRIMARY KEY,
  contract_type TEXT NOT NULL,
  constraint_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  field TEXT,
  params JSONB NOT NULL DEFAULT '{}',
  message TEXT,
  severity TEXT NOT NULL DEFAULT 'error',
  law_ref TEXT,
  inherited_from TEXT,
  UNIQUE (contract_type, constraint_id)
);
"""

_UPSERT = """
INSERT INTO type_validations
  (contract_type, constraint_id, kind, field, params, message, severity, law_ref, inherited_from)
VALUES
  (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (contract_type, constraint_id) DO UPDATE SET
  kind = EXCLUDED.kind,
  field = EXCLUDED.field,
  params = EXCLUDED.params,
  message = EXCLUDED.message,
  severity = EXCLUDED.severity,
  law_ref = EXCLUDED.law_ref,
  inherited_from = EXCLUDED.inherited_from
"""


def load_all(db: Any = None) -> dict:
    """Create table (if missing) + upsert all mapped validation constraints.

    Returns ``{table_created: bool, types_processed: int, rows_upserted: int,
    types_skipped_empty: list}``.
    """
    from src.eval.db import connect, table_exists
    from src.clauses.generator_import import build_registry

    conn = connect(db)
    created = not table_exists(conn, "type_validations")
    if created:
        conn.execute(_DDL)

    registry, _ = build_registry()

    processed = 0
    upserted = 0
    skipped_empty: list[str] = []

    for gen_id, lb_key in TYPE_MAP.items():
        constraints = registry.validations_for(gen_id)
        if not constraints:
            skipped_empty.append(gen_id)
            continue
        processed += 1
        for c in constraints:
            rule = c.get("rule") or {}
            kind = rule.get("op")
            if not kind:
                continue
            field = rule.get("field")
            params = {k: v for k, v in rule.items()
                      if k not in ("op", "field")}
            message = c.get("message")
            severity = c.get("severity") or "error"
            law_ref = c.get("law_ref")
            inherited = c.get("inherited_from")

            conn.execute(_UPSERT, (
                lb_key,
                c.get("id"),
                kind,
                field,
                json.dumps(params),
                message,
                severity,
                law_ref,
                inherited,
            ))
            upserted += 1

    return {
        "table_created": created,
        "types_processed": processed,
        "rows_upserted": upserted,
        "types_skipped_empty": skipped_empty,
    }


if __name__ == "__main__":
    result = load_all()
    print(f"table_created={result['table_created']}")
    print(f"types_processed={result['types_processed']}")
    print(f"rows_upserted={result['rows_upserted']}")
    print(f"types_skipped_empty={result['types_skipped_empty']}")
