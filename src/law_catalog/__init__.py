"""法规目录副本与引法关联层 (link-law-catalog-audit).

只读镜像外部法规库的权威目录（law_db.laws），并把条款引用的
``《...》`` 法律名解析到目录条目（law_id）。设计要点：

- 解析结果存独立表 ``law_catalog.clause_law_refs``，绝不写回
  ``clauses.law_refs`` 派生列（每次条款编辑都会从 body 重算该列）。
- ``expiry`` 列的实义是施行日期，任何判定逻辑不得使用。
- 全部本地 SQL，无向量、无外部运行时依赖。

向后兼容 shim：实现已迁至 ``packs.legal.law_catalog``（域包化，
add-knowledge-bench-platform）。此处显式再导出全部公开名，既有
``from src.law_catalog ...`` 使用点无需改动。新代码请直接从
``packs.legal.law_catalog`` 导入。
"""

from __future__ import annotations

from packs.legal.law_catalog import (
    alias_seed,
    article,
    audit,
    remediate,
    resolve,
    store,
    successor_seed,
)
from packs.legal.law_catalog.article import (
    ArticleCite,
    CachedIndex,
    cn_to_int,
    find_article,
    int_to_cn,
    parse_citations,
    resolve_all_article_citations,
    resolve_article,
)
from packs.legal.law_catalog.audit import (
    AMENDED_STATUS,
    CATEGORY_ORDER,
    CATEGORY_ZH,
    OK_STATUSES,
    REPEALED_STATUSES,
    classify,
    collect_audit,
    generated_at,
    render_report,
    write_report,
)
from packs.legal.law_catalog.remediate import (
    REPO_ROOT,
    SNAPSHOT_ROOT,
    apply_batch,
    plan_batch,
    record_no_action,
    rollback_batch,
    verify_batch,
)
from packs.legal.law_catalog.resolve import (
    LawCatalogIndex,
    normalize_name,
    resolve_all_clauses,
)
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
from packs.legal.law_catalog.successor_seed import EXPLICIT_MAP, seed_successor_map
from packs.legal.law_catalog.alias_seed import ALIAS_SEEDS, seed

__all__ = [
    # submodules
    "alias_seed",
    "article",
    "audit",
    "remediate",
    "resolve",
    "store",
    "successor_seed",
    # store
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
    # resolve
    "normalize_name",
    "LawCatalogIndex",
    "resolve_all_clauses",
    # article
    "cn_to_int",
    "int_to_cn",
    "ArticleCite",
    "parse_citations",
    "find_article",
    "CachedIndex",
    "resolve_article",
    "resolve_all_article_citations",
    # audit
    "REPEALED_STATUSES",
    "AMENDED_STATUS",
    "OK_STATUSES",
    "CATEGORY_ORDER",
    "CATEGORY_ZH",
    "classify",
    "collect_audit",
    "render_report",
    "write_report",
    "generated_at",
    # remediate
    "REPO_ROOT",
    "SNAPSHOT_ROOT",
    "plan_batch",
    "apply_batch",
    "record_no_action",
    "rollback_batch",
    "verify_batch",
    # alias_seed
    "ALIAS_SEEDS",
    "seed",
    # successor_seed
    "EXPLICIT_MAP",
    "seed_successor_map",
]
