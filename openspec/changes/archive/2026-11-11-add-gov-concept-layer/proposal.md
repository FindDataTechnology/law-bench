## Why

政务域的本体只能装「公文、机关、政策」三种实体（`gov-domain` v1 的 `entity_types`），关系只有 `issued_by`/`implements`/`supersedes`。因此政务两线的质量比率里，`grounding` 的分母恒为 0 —— 它读出来是 `None`，**不是「很好」，是「没有可量的东西」**。

补这一层之前先查了两件事，两件都指向同一处：

1. **政务语料其实取不到**。`corpus_chunks_gov` 的真表列是 `id / domain / document_id / chunk_no / chunk_text / char_start / char_end / section_path / tsv / embedding`（2160 行，2026-11-11 实查）。而取样器 `_sample_text_tables` 的默认列映射要求 `chunk_id` / `title`，两者都不存在，于是 `sample_chunks(domain_path='gov')` 直接抛
   `table 'corpus_chunks_gov' has no column(s) ['title', 'chunk_id']`。概念抽取是从语料块里抽的，语料取不到，概念层就无从谈起。
   注意这不是「表没数据」：同一份声明里**文档**侧的映射是对的（`document.table=corpus_documents`、`doc_ref=document_id`、`title=title`），所以 14 份公文能被采纳进本体；只有**块**侧的映射与真表不符。
2. **模板词表里没有 `concept`**，也没有一条能把概念与公文连起来的 relation。就算抽出概念，词表闸也会按 `bad_kind` 全拒。

所以缺口是两层：取样器只会从**块表自己**拿标题（政务的块表没有标题，标题在文档表上）；模板不给概念类型。

## What Changes

- **取样器按声明 join 文档表取标题**：`_sample_text_tables` 遇到「块表无 title 列、但源已声明 `document.table` + `doc_ref`」时，LEFT JOIN 该文档表取标题；标题仍缺则如实留空（`None`），不再因为缺 title 而拒绝整源。缺 `text`/`id` 列仍然报错并指名。
- **政务源的块侧映射显式声明**：`columns = {id: id, text: chunk_text}`（写进 `scripts/register_libraries.py`，并同步库内那一行，避免只在库里生效、重跑登记就丢）。
- **政务模板升 v2**：`entity_types` 增 `concept`（政策概念），`relationship_kinds` 增 `defines`（方向固定 **概念 → 公文**：该公文是这条概念的依据）。其余词表（tier/sensitivity/structures）不变。
- **政务域切到 v2**：`domains.template_id/template_version` 变更；v1 行保留不动，切回即回滚。
- **政务包声明 concept 岗位**：`sources: [gov]`、`batch_chunks`、`min_usable_rate`、`max_total`，与法律线同形但语料面不同。
- **跑一轮概念抽取并如实过审**：候选只在引文**逐字**出现在块里时才进箱；入箱的概念要挂 `defines` 才叫接地。审查通过才写本体，验收口径是 `quality.grounding(namespace='gov')` 从 `None` 变成一个有分子分母的比率。

## Capabilities

### New Capabilities

- `gov-concept-layer`: 政务概念作为一类本体实体的契约——概念从哪类语料来（政务公开全文）、概念键怎么取、概念与公文如何用 `defines` 关联（方向与依据）、以及「接地率」在这条线上如何被算出来。

### Modified Capabilities

- `ontology-extraction`: 非向量文本源的取样补齐两种真实形态——块表与文档表分表时按声明 join 取标题；标题缺失是可接受状态（留空），但 `text`/`id` 缺失必须报错指名。

## Impact

- 代码：`src/bench/extraction.py::_sample_text_tables`（join + title 可选）；`packs/gov/pack.yaml`（concept 岗位）；`scripts/register_libraries.py`（块侧列映射）。
- 数据：`ontology_templates` 新增 `gov-domain` v2 一行（v1 不动）；`domains` 的 gov 行指向 v2；`library_sources` 的 gov 行补 `columns`；抽取产生的候选走提案层，**不直接写本体**。
- 风险：
  - 概念边界没有客观标准（「政府采购」与「政府采购信息发布」谁是更小的概念）。本 change 只要求「每条概念都能在公文里逐字找到依据」，不追求概念体系完备。
  - 切换模板是这条线的锚点变更，回滚点＝把 `domains` 的 gov 行改回 `template_id=3, template_version=1`（v1 行始终在）。
  - 外部 text 库需要 `FDTEXT_DATABASE_URL`（集群 secret `law-bench-fdtext`）；本机跑抽取时必须注入，取不到时取样器报变量名而不是返回空。
