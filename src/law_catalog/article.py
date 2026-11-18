"""Backward-compat shim: implementation lives at ``packs.legal.law_catalog.article``."""

from packs.legal.law_catalog.article import (
    ArticleCite,
    CachedIndex,
    cn_to_int,
    find_article,
    int_to_cn,
    logger,
    parse_citations,
    resolve_all_article_citations,
    resolve_article,
)

__all__ = [
    "cn_to_int",
    "int_to_cn",
    "ArticleCite",
    "parse_citations",
    "find_article",
    "CachedIndex",
    "resolve_article",
    "resolve_all_article_citations",
    "logger",
]
