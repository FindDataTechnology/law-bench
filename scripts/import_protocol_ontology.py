#!/usr/bin/env python3
"""Import the observation-layer ontology from ``fd-open-data-protocol`` (read-only).

The protocol package is the authority for the outside-world vocabulary — 30
entity types, 14 relation types, and the concept families that anchor every
`semantic_observations` row. It is also a *PyPI package with golden digest
tests*, so this script only ever reads it: nothing here writes to that repo, and
the template it produces is marked ``authority: external`` so no editor can
quietly diverge the two.

Why a template at all, if the package already holds the vocabulary: a domain
workspace needs a *layer it can anchor to* — the same six-key shape every other
template has, versioned, with the layer stamped on it. The distinction the
`authority` field preserves is that this platform does not own those words.

Idempotent by ``(source, version)``: importing the same protocol release twice
produces no new template version. A new upstream version produces one new
version and leaves the old one byte-identical (domains pin versions).

Run:
    uv run python scripts/import_protocol_ontology.py --dry-run
    uv run python scripts/import_protocol_ontology.py
    uv run python scripts/import_protocol_ontology.py --protocol-dir /path/to/fd-open-data-protocol
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import templates  # noqa: E402
from src.bench.promotion import SENSITIVITY_LEVELS  # noqa: E402
from src.bench.tiers import TIERS  # noqa: E402

CREATED_BY = "system:protocol-import"

#: Template name carries no version — versions live in the template's own
#: ``version`` column, and the *upstream* version lives in ``authority``.
TEMPLATE_NAME = "external-world"


def _load_registry(source_dir: Path | None):
    """Load the protocol vocabulary.

    Two paths, in this order, and the order matters:

    1. **Installed package** (the normal case in production and CI) — the wheel
       lives in ``vendor/`` and is declared as a dependency, so the vocabulary
       ships with the image and no sibling checkout is needed.
    2. **Sibling checkout** (``--protocol-dir`` / ``FD_OPEN_DATA_PROTOCOL_DIR``)
       — for local work against an unreleased protocol change.

    A missing source is a hard failure. An empty vocabulary template would look
    like "the upstream has no types", which is a silent lie.
    """
    if source_dir is None:
        try:
            from fd_open_data_protocol.vocabulary import load_vocabulary
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "fd_open_data_protocol is not installed and no --protocol-dir "
                "was given. It ships as vendor/fd_open_data_protocol-*.whl "
                "(see pyproject [tool.uv.sources])."
            ) from exc
        return load_vocabulary()

    if not (source_dir / "fd_open_data_protocol" / "vocabulary.py").exists():
        raise SystemExit(
            f"protocol package not found at {source_dir} "
            "(set FD_OPEN_DATA_PROTOCOL_DIR or pass --protocol-dir)"
        )
    sys.path.insert(0, str(source_dir))
    try:
        from fd_open_data_protocol.vocabulary import load_vocabulary
    finally:
        sys.path.pop(0)
    return load_vocabulary()


def _aligned_with(registry) -> list:
    """Cross-layer alignment, read from the protocol's own declaration.

    Hardcoding the map here was a second copy of a fact the protocol already
    publishes (`vocabulary/alignment/foundation.yaml`), and the two drifted
    immediately: this file listed 7 entries while the declaration had 8 (it was
    missing `venue`). Reading the declaration means there is exactly one place
    to add an alignment.

    An empty/missing declaration is not an error — an older protocol release
    simply has no alignment file, and the template then declares none.
    """
    from fd_open_data_protocol.vocabulary import load_alignment

    try:
        declared = load_alignment()
    except Exception:  # noqa: BLE001 - alignment is optional; never block an import
        return []
    alignments = declared.get("alignments") or {}
    if not alignments:
        return []
    target = declared.get("target") or {}
    return [
        {
            "target_template": target.get("template", "foundation-v1"),
            "target_layer": target.get("layer", "foundation"),
            "type_map": {src: entry["to"] for src, entry in alignments.items()},
        }
    ]


def build_schema(registry) -> dict:
    """The six required keys, with vocabularies taken verbatim from the release."""
    entity_types = list(registry.entity_type_ids())
    if not entity_types:
        raise SystemExit(
            "protocol vocabulary yielded zero entity types — refusing to write "
            "an empty observation-layer template"
        )
    relation_ids = [e.id for e in registry.entries.get("relation-type", [])]
    concept_ids = [e.id for e in registry.entries.get("concept", [])]

    return {
        "layer": "observation",
        "authority": {
            "kind": "external",
            "source": "fd-open-data-protocol",
            "version": str(getattr(registry, "version", "unknown")),
        },
        # Readings of the same word in two layers are declared, never merged:
        # the observation layer's `company` is an object being observed (it has
        # tickers and identifiers), the foundation's `organization` is a party
        # to transactions. Same referent, different lifecycles.
        "aligned_with": _aligned_with(registry),
        "entity_types": entity_types,
        "concept_structures": {concept: ["code", "unit", "frequency"] for concept in concept_ids},
        "relationship_kinds": relation_ids,
        "tier_vocabulary": list(TIERS),
        "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
        "corpus_declaration": {"source_types": ["observation"], "granularity": "observation"},
    }


def eval_dsn() -> str:
    """The real PostgreSQL DSN (``database_url`` env), never the SQLite path constant."""
    from src.eval import db as edb

    return edb._dsn()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--protocol-dir", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)

    # An explicit source (flag or env) means "use this checkout"; otherwise the
    # installed package is authoritative — that is what ships in the image.
    explicit = args.protocol_dir or os.environ.get("FD_OPEN_DATA_PROTOCOL_DIR")
    source = Path(explicit) if explicit else None
    registry = _load_registry(source)
    schema = build_schema(registry)

    problems = templates.validate_template_schema(schema)
    if problems:
        print("INVALID template built from protocol: " + "; ".join(problems),
              file=sys.stderr)
        return 1

    upstream_version = schema["authority"]["version"]
    where = str(source) if source is not None else "installed package"
    print(
        f"protocol {upstream_version} at {where}: "
        f"{len(schema['entity_types'])} entity types, "
        f"{len(schema['relationship_kinds'])} relationship kinds, "
        f"{len(schema['concept_structures'])} concept structures, "
        f"{len(schema['aligned_with'][0]['type_map'])} alignments"
    )
    if args.dry_run:
        print("DRY-RUN — nothing written.")
        return 0

    import psycopg

    from src.eval import store as eval_store

    # DEFAULT_DB is the legacy SQLite path constant, NOT a DSN — passing it to
    # psycopg makes conninfo parsing blow up on a PosixPath. Read the real DSN.
    dsn = args.database_url or eval_dsn()
    conn = psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)
    try:
        eval_store.ensure_schema(db_path=conn)
        latest = templates.get_template(conn, name=TEMPLATE_NAME)
        if latest is not None:
            same = (
                latest["schema"].get("authority", {}).get("version") == upstream_version
                and sorted(latest["schema"].get("entity_types") or [])
                == sorted(schema["entity_types"])
            )
            if same:
                print(
                    f"{TEMPLATE_NAME} v{latest['version']} already reflects "
                    f"protocol {upstream_version} — nothing to do"
                )
                return 0
            created = templates.update_template(
                conn, name=TEMPLATE_NAME, schema=schema, created_by=CREATED_BY
            )
            print(
                f"imported {TEMPLATE_NAME} v{created['version']} "
                f"(protocol {upstream_version}); previous v{latest['version']} unchanged"
            )
            return 0
        created = templates.create_template(
            conn, name=TEMPLATE_NAME, schema=schema, created_by=CREATED_BY
        )
        print(f"created {TEMPLATE_NAME} v{created['version']} (protocol {upstream_version})")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
