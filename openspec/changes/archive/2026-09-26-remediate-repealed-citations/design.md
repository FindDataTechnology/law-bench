# Design: remediate-repealed-citations

## Context

引法审计终局基线：2,188 条引用，已废 298 处 / 248 条款（合同法 247、物权法 29、民法总则 10、担保法/侵权责任法/民法通则各 1、建工解释（二）1、网络交易管理办法 1、地方废规 7 处/7 条款），已修改 17 处。条文级 0 条落在废法上（全部名称级引用，无条号重映射）。2026-09-15 的 content-remediation（已归档）建立了本仓库的批量修改惯例：batch 目录 + before/applied 快照 + `--rollback` + 绝不 DELETE + 写入走同一套 store API。本设计是该惯例在引法域的特化，叠加法规链接层带来的新能力——机器可验证的原因记录。

## Goals / Non-Goals

**Goals:**

- 298 → ≈7（只剩无承继映射的地方废规），每处改动有证据链、有快照、可回滚、可重放验证。
- 修订记录同时服务三个已确认的消费者：论文统计、人工复核、微调数据。

**Non-Goals:**

- 不做 LLM 改写（确定性替换足够，语义漂移风险为零）。
- 不动"已修改"17 处的条款正文（仅留档 reviewed-no-action）。
- 不解决地方废规的承继确认（占位等人工，属目录/人工侧输入）。
- 不给条款新增条文级引用（"民法典第X条"的增补是后续独立增强，修订记录会标注可追踪的候选）。

## Decisions

### D1: 记录双面——DB 表为查询面，文件快照为恢复面

- `law_catalog.successor_map`（承继映射）：dead_law_id、successor_law_id、authority_law_id（废止决定/施行法，可空）、effective_date、rule_version、needs_human（地方废规占位=true，永不自动应用）。
- `law_catalog.citation_revisions`（修订记录）：clause_id、batch、cited_before、cited_after、dead_law_id、successor_law_id、authority_law_id、disposition（applied / skipped-review / reviewed-no-action / rolled-back）、rule_version、git_sha、applied_at；幂等键 (clause_id, batch, cited_before)。
- 文件快照沿用 D3 布局 `output/remediation/<batch>/{manifest,before/,applied/}`——回滚的权威来源是文件（before 整行），表是 SQL 可 JOIN 的查询面（论文统计/复核/微调导出都打表）。回滚时经 `update_clause` 恢复 body 并把表记录置 rolled-back。

**备选否决**：纯文件（content-remediation 先例）——三个消费者都要 SQL 聚合/JOIN 链接层，逐文件解析不划算；纯表——回滚要能对抗"表被误写"，文件快照是独立恢复面。

### D2: 证据链 = 三个 law_id + 规则版本，不是自由文本

原因字段的构成全部可重放验证：dead_law_id（join 副本 status 应为已废止/失效/已失效）、successor_law_id（应为有效）、authority_law_id（废止决定类文件，目录有则引用）。规则版本（如 `civilcode-2021`、`merge-2020`）对应映射表的 rule_version，映射本身也可被审计。论文引用这批数字时，任何人可重放断言。

### D3: 应用只走 `update_clause()`，`manual=true` 是特性

唯一写路径 = 既有 store 函数（web 编辑/MCP/脚本同源），law_refs/body_hash 自动重派生。`manual=true` 使后续重新抽取不覆盖修复——正式接受并写入文档。条款与抽取源（示范文本）从此分叉：源文件仍带死法（上游问题），law-bench 语料是修正后的视图；这个分叉本身由修订记录可解释。

### D4: 替换规则——精确引用串替换 + 叙述白名单

对 body 做两种匹配：①《书名号完整名》整串替换（合同法→民法典等）；②无书名号裸名（如"根据合同法和民法典"）按分词边界替换。叙述保护：替换上下文含"实施以来/施行以来/废止/历史/原《"等标记的跳过，进 skipped-review 清单人工裁决。dry-run 报告把 applied-candidates 与 skipped 分列，人工过目后才放量（首批 50 条抽检再全量的惯例）。

### D5: Batch 结构（爆炸半径递增）

| Batch | 内容 | 条款数 |
|---|---|---:|
| r0 | 已修改 17 处留档 reviewed-no-action（零修改，验收记录完整） | 17 |
| r1 | 民法典承继六法（合同法/物权法/民法总则/担保法/侵权责任法/民法通则） | ~240 |
| r2 | 建工解释（二）→（一）、网络交易管理办法→监督管理办法 | 2 |
| r3 | 地方废规 7 处——仅当人工确认承继后建映射占位转正再跑 | ≤7 |

r1 内部再按合同类型分片（sale 66 / real_estate_lease 23 / construction 22…），每片独立 dry-run→apply→verify。

### D6: 消费导出的最小实现

- **论文统计**：一个 SQL 视图/导出脚本（按 disposition × contract_type × 引用聚合计数 + 修复前后审计四类对照），输出 JSONL/markdown 进 `docs/`。
- **复核流**：`/law-catalog/revisions` 只读列表页（batch 筛选、before/after diff、证据链三 law_id 链接到 `/law-catalog/audit` 的法规行），复用现有路由/模板模式，写权限不涉及。
- **微调数据**：导出 before→after 修正对（原引用串→新引用串 + 证据链原因作上下文），落 `data/finetune/` 现有目录约定的独立子目录，不改既有 finetune 流程。

## Risks / Trade-offs

- [叙述误替换] → D4 白名单 + dry-run 人工闸门 + before 快照逐条回滚。
- [同一条款多引用跨 batch 交错] → 幂等键含 cited_before；apply 前重验当前 body 仍含旧串（否则跳过记 skipped）。
- [源示范文本仍是死法，未来新抽取复燃] → manual=true 防覆盖；审计例行跑（refresh 脚本）持续监控，新复燃条款进下一批。
- [回滚与表状态不同步] → 回滚是唯一同时写文件恢复+表置位的操作；表无其他写入口。
- [承继映射本身有错（如担保法部分内容去了担保制度解释而非民法典）] → 映射表带 authority 引用可审计；名称级替换不涉及条文归属，风险限于"引民法典而非具体解释"的粒度损失，可接受。

## Migration Plan

纯增量（两张新表 + 新脚本 + 新路由），条款修改是数据操作而非 schema 变更。批次可停可回滚；最终态以审计已废数 ≈7 验收。回滚整体 = 逐 batch `--rollback` + 表清空，对系统其他功能零影响。

## Open Questions

- 地方废规 7 处的承继确认（r3 的输入，用户/人工侧提供，不阻塞 r0–r2）。
- 微调对的格式细节（是否要构造对话式 prompt）——实现时对齐 `data/finetune/` 既有样例再定。
