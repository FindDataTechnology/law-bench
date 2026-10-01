"""Clause knowledge base: extract reusable contract clauses from the 823 示范文本
corpus in MinIO, store them in Postgres (base / tagged / custom), and assemble
contracts from base + provincial-tagged + custom clauses around the existing
``{{slot}}`` model.
"""

from __future__ import annotations

from .assemble import generate_contract_assembled
from .corpus import iter_unique_documents, list_corpus_documents, read_document
from .extract import SECTION_ORDER, extract_document, section_rank
from .store import (
    count_clauses,
    counts_by_type,
    create_clause,
    delete_auto_clauses,
    delete_clause,
    delete_clauses,
    get_custom_clause,
    list_clauses,
    list_extracted_source_paths,
    search_clauses,
    update_clause,
    upsert_clause,
    upsert_clauses,
)
from .tags import (
    FREE_FORM_TAGS,
    TAG_CATEGORIES,
    TAG_VOCAB,
    load_vocab_from_db,
    register_tag_dim,
    tag_vocab_for_type,
    validate_tags,
)
from .tag_review import bulk_review, is_assembly_ready, list_pending, review_tag

__all__ = [
    "SECTION_ORDER",
    "TAG_VOCAB",
    "count_clauses",
    "counts_by_type",
    "create_clause",
    "delete_auto_clauses",
    "delete_clause",
    "delete_clauses",
    "extract_document",
    "generate_contract_assembled",
    "get_custom_clause",
    "iter_unique_documents",
    "list_clauses",
    "list_corpus_documents",
    "list_extracted_source_paths",
    "load_vocab_from_db",
    "read_document",
    "register_tag_dim",
    "search_clauses",
    "section_rank",
    "update_clause",
    "upsert_clause",
    "upsert_clauses",
    "validate_tags",
]
