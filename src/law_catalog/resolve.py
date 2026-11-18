"""Backward-compat shim: implementation lives at ``packs.legal.law_catalog.resolve``."""

from packs.legal.law_catalog.resolve import (
    LawCatalogIndex,
    normalize_name,
    resolve_all_clauses,
)

__all__ = [
    "normalize_name",
    "LawCatalogIndex",
    "resolve_all_clauses",
]
