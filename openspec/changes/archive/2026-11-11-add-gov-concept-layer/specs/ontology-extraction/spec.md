## MODIFIED Requirements

### Requirement: 抽取支持非向量文本源

抽取 SHALL 能从「按表读取的文本源」取样（表名 + 列映射），SHALL NOT 要求该语料先被向量化。取样结果 SHALL 与原 qdrant 取样同形（`chunk_id`/`text`/`title`/来源），使下游校验与键方案无需分支。

当块表**没有**标题列、但源已声明 `ingest_rule.document {table, id, doc_ref, title}` 时，取样器 SHALL 按 `块.doc_ref = 文档.id` LEFT JOIN 该文档表取标题。标题最终取不到 SHALL 留空（`None`），不得因此拒绝整源；`text` 或 `id` 列缺失 SHALL 报错并指名缺哪一列。

#### Scenario: 裁判要点按表取样
- **WHEN** 语料源声明为 `text-table`，表 `guide_cases`，文本列 `gist`
- **THEN** 取样返回该表的行，`title` 取案例标题，`chunk_id` 取案例编号

#### Scenario: 列缺失时报错而不是空跑
- **WHEN** 声明的文本列在表里不存在
- **THEN** 取样报错并指明缺的列，不返回空列表冒充「没有语料」

#### Scenario: 块表与文档表分表时按声明 join 取标题
- **WHEN** 块表只有 `id/document_id/chunk_text`（无标题列），源声明 `document.table=corpus_documents`、`document.doc_ref=document_id`、`document.title=title`
- **THEN** 取样成功，每块带 `chunk_id`、`text`，且 `title` 来自对应文档行

#### Scenario: 两边都没有标题
- **WHEN** 块表无标题列，源也未声明可 join 的文档表
- **THEN** 取样成功，`title` 为 `None`；不抛错，因为缺标题是可接受状态，缺文本/主键不是
