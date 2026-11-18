# Design: link-law-catalog-audit

## Context

外部法规库已建成：权威目录在法规库侧 PostgreSQL `law_db.laws`（21,746 行；lawv2 13,930 / flk 3,239 / law 4,577），其 `id` 与 Qdrant payload 中的 `law_id` 一致。law-bench 侧的法律引用是纯字符串：`clauses.law_refs` 由 `《...》` 正则从 body 派生，`store.py` 在每次条款 upsert/update 时重算该列。法规库的向量层（Qdrant law_chunks_v2 / Qwen3-Embedding 1024 维）与查询侧（embedding-svc、law-api）属于另一条链路，本变更完全不触碰。本设计只回答：目录副本怎么进 law-bench、字符串怎么变成 law_id、审计怎么跑。

## Goals / Non-Goals

**Goals:**

- law-bench 主 PG 内拥有一份可独立使用的法规目录只读副本，外部服务全挂也能查。
- 条款引用名 → law_id 的解析层独立于 `law_refs` 派生管线，可重跑、可审计（记录 resolved_via）。
- 全库引法审计产出可交付的报告 + 可操作的复核队列，直接暴露"条款引用已废止法律"这类问题。

**Non-Goals:**

- 不做语义检索（Qdrant / law-api / drafter 工具——第二批 change `integrate-law-semantic-search`）。
- 不做条文级（第X条）解析（第二批）。
- 不修改条款 body、`law_refs` 派生逻辑、任何现有表结构。
- 不把审计挂成 `validation_check` 硬校验（先以报告验证解析质量，后续另行变更）。

## Decisions

### D1: 副本进主 PG 独立 schema，经 RustFS 传递，从法规库 PG 导出

- **位置**：law-bench 主 PG 新增 `law_catalog` schema（`law_catalog.laws`、`law_catalog.aliases`、`law_catalog.clause_law_refs`）。不另起数据库——备份、连接池、权限随现有体系走。
- **来源**：法规库侧一次性导出 `SELECT id,title,category,publish,expiry,status,src_db,content_status FROM laws`（两万多行、几 MB），上传 RustFS（laws-export 桶或 law-bench 自有桶），law-bench 侧导入脚本读取并灌入。flk 增量后人工重复该流程，导入幂等（先清后灌或 upsert 全量替换）。
- **备选否决**：从 `law_fixed.db`（SQLite 源）搬——SQLite 行号 ≠ PG law_id 且缺 flk 增量；从 Qdrant payload 按 law_id 去重拼目录——JSONL/payload 是嵌入工作队列的冗余字段，目录权威在 PG。

### D2: 类型按 PG 原生类型入库；"law_id 是字符串"的坑留给第二批

副本表 `id` 沿用法规库 PG 的原生整数类型。law_id/chunk_no 在 JSONL/Qdrant 里是字符串这一陷阱只影响未来直连 Qdrant 的功能（第二批），届时在消费侧显式处理，不在本变更引入字符串主键。

### D3: 解析层独立建表，绝不写回 `law_refs`

`clauses.law_refs` 是派生列（每次 `clause_update` 从 body 重算，`store.py:105/220`），law_id 塞进去会在下一次条款编辑时被冲掉。解析结果放 `law_catalog.clause_law_refs`（clause_id × law_id × status 快照 × resolved_via × resolved_at），由独立任务全量重算。审计与后续功能（UI 链接、评测核对）都读这张表。

### D4: 解析阶梯——归一化 → 别名表 → trgm 阈值 → 复核队列

1. 归一化精确匹配：去 `中华人民共和国` 前缀（沿用 `legal_refs._dedup_key` 约定）、去首尾空白与书名号。
2. 人工别名表：简称/旧称 → 全称（如 `九民纪要` → `全国法院民商事审判工作会议纪要`；各司法解释简称）。初始种子从 `law_refined_citations.py`、law_info surveys、`docs/legal_references.md` 里已知的不一致写法收集。
3. pg_trgm 相似度过阈值匹配（阈值配置化，实现期用复核队列反馈调）。
4. 未命中 → 复核队列；运营者确认映射即沉淀为别名（下次解析生效），或标记为故意不匹配。

每条结果记录 `resolved_via`（exact/alias/trigram/unresolved），审计报告按来源分层展示，模糊命中的可信度一眼可辨。

### D5: 状态判定只用 status 列，规则即分类

- `status IN ('已废止','失效')` → **引用已废法律**（实测约 2,007 部）。
- `status = '已修改'` → 单列**已修改**（多数仍有效，仅被修正，不与废止混同）。
- 解析 `unresolved`、或命中的行 status 为 NULL / 脏值（如 `sxx:3`，实测 310 条）→ **兜底清单**，走人工处置。
- `expiry` 列在判定逻辑中零出现——其实义是施行日期（实测 13,562 条 expiry ≤ 今天但 status=有效）。

"修改、废止的决定"正文挖废止清单的增强（比 status 多捕一批被取代旧版本）不在本期。

### D6: 审计是纯本地 SQL join，产出 markdown 报告 + web 复核队列

- 执行形态：CLI（`src/law_catalog/` 内，仿 `clauses/audit.py` / `scripts/extract_legal_references.py` 的既有风格），输出 markdown 报告提交到 `docs/`（先例：`docs/legal_references.md`）。
- web 侧：审计结果 + 未解析项复核队列页（复用 tag_review 的路由/模板模式），运营者动作只写别名表/复核标记，不碰条款。
- 报告头记录目录快照标识（行数 + max_id + 导出时间），保证可追溯。

## Risks / Trade-offs

- [trgm 模糊匹配假阳性（司法解释"（一）（二）"版本、名称相近的法规）] → 阈值配置化 + resolved_via 分层展示 + 模糊命中默认不沉淀为别名，须经复核确认。
- [条款库持续变动，审计结果与库内状态漂移] → 审计为快照型报告、可随时重跑；`clause_law_refs` 重算是幂等全量。
- [目录副本与法规库漂移（flk 增量未重灌）] → 导入幂等 + 报告头记录快照标识；重灌是明确的人工动作，不追求自动同步。
- [脏值/NULL status（2,243 部）拖低覆盖率] → 全部进兜底清单而非猜测分类；准确率优先于覆盖率。
- [别名表冷启动为空，首批解析 unresolved 偏多] → 首跑即产出复核队列，别名表按复核结果自然增长。

## Migration Plan

纯增量：新 schema + 新模块 + 新路由。部署顺序：建 schema → 灌目录 → 跑解析 → 跑审计。回滚 = drop schema `law_catalog` + 移除新路由，对现有功能零影响（无现有表改动、无运行时新依赖）。

## Open Questions

- trgm 阈值初值（实现期以复核队列反馈定，不阻塞设计）。
- MCP 是否暴露审计工具（`law_citation_audit`）——实现后看需要，另行小变更。
