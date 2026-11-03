"""法规目录副本与引法关联层 (link-law-catalog-audit).

只读镜像外部法规库的权威目录（law_db.laws），并把条款引用的
``《...》`` 法律名解析到目录条目（law_id）。设计要点：

- 解析结果存独立表 ``law_catalog.clause_law_refs``，绝不写回
  ``clauses.law_refs`` 派生列（每次条款编辑都会从 body 重算该列）。
- ``expiry`` 列的实义是施行日期，任何判定逻辑不得使用。
- 全部本地 SQL，无向量、无外部运行时依赖。
"""
