# Tasks: remediate-repealed-citations

## 1. Schema 与映射种子

- [x] 1.1 `law_catalog.successor_map` 表（dead/successor/authority law_id、effective_date、rule_version、needs_human）+ `citation_revisions` 表（幂等键 clause_id+batch+cited_before，disposition/rule_version/git_sha/applied_at）入 store DDL
- [x] 1.2 承继映射种子：民法典承继六法（authority 引民法典施行+废止决定，effective 2021-01-01）、建工解释（二）→（一）、网络交易管理办法→监督管理办法；地方废规 7 处以 needs_human=true 占位
- [x] 1.3 conftest 集成（两张新表入截断清单与 session 建库）

## 2. 修复引擎

- [x] 2.1 dry-run：审计查询 → 映射 → 每条款 before/after diff + 证据链 + skipped（叙述白名单：实施以来/施行以来/废止/历史/原《）分列报告
- [x] 2.2 apply：逐条经 `update_clause()`（apply 前重验 body 含旧串，否则 skipped）；写表记录（applied）+ `output/remediation/<batch>/` 快照（manifest 含 git sha、before 整行、applied 记录）
- [x] 2.3 rollback：`--rollback <batch>`（--clause-id 可选）从 before 快照经 `update_clause` 恢复，表记录置 rolled-back；幂等重跑为 no-op
- [x] 2.4 闭环验证命令：apply 后重跑 resolve+audit，断言已废数=needs_human 占位数、applied 条款全部解析为"有效"法规

## 3. Batch 执行（每片 dry-run 人工过目后放量）

- [x] 3.1 r0：已修改 17 处 → reviewed-no-action 留档（零 body 修改）
- [x] 3.2 r1-首批（66 条款 diff 逐条过目，含全 body 抽样 3 条）：民法典承继 sale 片（~66 条款）dry-run → 人工抽检 50 条 diff → apply → verify
- [x] 3.3 r1-放量：其余合同类型片逐片 apply+verify；终态已废 298 → ≈7
- [x] 3.4 r2：建工解释（二）、网络交易管理办法两条（随 r1-rest 映射类型一并收编）
- [x] 3.5 r3：人工判定 2026-09-26 落库——天津旅游替换 1 处；广州 4 处承继法不在目录留档；山东/天津市场打包废止无承继留档（权威 law_id 入链）

## 4. 消费面

- [x] 4.1 论文统计导出：disposition × contract_type 聚合 + 修复前后审计对照（JSONL+markdown 入 docs/）
- [x] 4.2 web `/law-catalog/revisions` 只读列表页（batch 筛选、before/after diff、三 law_id 证据链展示）
- [x] 4.3 微调修正对导出（before→after + 原因上下文，对齐 data/finetune/ 既有约定）

## 5. 测试与收尾

- [x] 5.1 单测：映射占位永不自动应用；幂等（同 batch 重跑 no-op）；叙述白名单跳过；apply 前 body 漂移检测；回滚恢复与表置位一致；reviewed-no-action 零修改；闭环断言
- [x] 5.2 文档：runbook 补修复批次操作（dry-run/apply/verify/rollback）与消费导出说明
