"""Compatibility surface over :mod:`fd_ontology_kernel.keys`.

The mechanisms — slugging, clause addressing, ordered rule folding, and the
per-domain rule registry — moved to the kernel so that every ontology surface
shares one implementation. This module stays because a couple of dozen call
sites import ``from . import keys`` and the legal pack imports ``FoldRule`` /
``register_rules`` from here.

The re-export is deliberate rather than a wrapper: there must be exactly **one**
registry process-wide, otherwise a pack registering here would be invisible to
code that imported the kernel module directly.
"""

from __future__ import annotations

from fd_ontology_kernel.keys import (  # noqa: F401  (re-export surface)
    CONCEPT_MAX_CHARS,
    FoldRule,
    chinese_to_int,
    clause_key,
    clause_no,
    concept_counters_for,
    concept_examples_for,
    concept_reject_for,
    concept_shape_ok,
    distinct_document_for,
    fold,
    register_rules,
    registered,
    relationship_rule_for,
    rules_for,
    slug,
    strip_trailing_qualifier,
)

__all__ = [
    "CONCEPT_MAX_CHARS",
    "FoldRule",
    "chinese_to_int",
    "clause_key",
    "clause_no",
    "concept_counters_for",
    "concept_examples_for",
    "concept_reject_for",
    "concept_shape_ok",
    "distinct_document_for",
    "fold",
    "register_rules",
    "registered",
    "relationship_rule_for",
    "rules_for",
    "slug",
    "strip_trailing_qualifier",
]
