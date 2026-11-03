"""Backward-compat shim: implementation lives at ``packs.legal.law_catalog.store``."""

from packs.legal.law_catalog.store import (
    catalog_snapshot,
    distinct_unresolved,
    ensure_schema,
    get_law,
    has_trgm,
    import_catalog,
    list_aliases,
    list_resolutions,
    load_export_file,
    seed_aliases,
    suggest_candidates,
    upsert_alias,
)

__all__ = [
    "ensure_schema",
    "has_trgm",
    "load_export_file",
    "import_catalog",
    "catalog_snapshot",
    "get_law",
    "upsert_alias",
    "list_aliases",
    "seed_aliases",
    "list_resolutions",
    "distinct_unresolved",
    "suggest_candidates",
]
