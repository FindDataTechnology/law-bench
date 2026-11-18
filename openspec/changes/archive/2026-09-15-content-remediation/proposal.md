# Proposal: content-remediation

## Why

2026-09-15 对线上条款库（lawbench origin Postgres，7044 条条款）做了全量内容检测
（`output/content_audit_report_2026-09-15.md`），发现一批真实缺陷：18 条带 scenario 的条款把特定城市法规/仲裁委写死（住宅租赁场景生成的合同会随机绑定深圳/济南/南京等地方法规）；约 600 条正文残留签署壳/下划线填空/表格碎片；65 组 body_hash 完全重复；74 条条款的 tag_review 被历史导入脚本写入 `_imported_at`/`_note` 等元数据键，导致 4 条已批准的 custom 条款被 `is_assembly_ready` 静默排除出组装。缺陷清单已全部枚举到条款 id，修复成本低；但所有修改都落在生产库上，必须可审计、可回退。

## What Changes

- **生产库条款内容一次性治理**（全部基于已枚举的 id 清单，逐条留痕）：
  - 改写 18 条带 scenario 的地域泄露条款：地方性法规泛化为国家法律通用表述，写死的仲裁机构改为 `{{jurisdiction}}`/`{{arbitration_org}}` 占位符；
  - 清理签署壳/下划线填空/表格碎片伪影（`extraction_artifact` 类，约 600 条，含 5 条 markdown 表格碎片、95 条 `___` 填空、~500 条签署栏残留）；
  - 走既有 P3 确定性去重通道拒绝 65 组 body_hash 重复（保留最小 id，可通过重新批准恢复）；
  - 零散修复：#7267 写死违约金改 `{{penalty}}`、3 条 merger_acquisition 悬空法条尾缀整合、15 条超短残桩人工分拣（合并或保留）。
- **tag_review 门控代码修复 + 数据迁移**：
  - 实施核查修正：74 条条款的元数据键（`_imported_at`/`_note`/`_source_hash`）只存在于 tag_review，当前 `is_assembly_ready` 按 tags 维度遍历、事实上已忽略它们；真实缺陷是 `bulk_review` 以整体替换方式重写 tag_review——任何一次批量审核都会连带抹掉这些溯源键（且若 tags 未来出现 `_` 维度，门控会被破坏）。修复：门控与批量审核显式忽略/保护 `_` 前缀键；
  - 生产库一次性清除 74 条条款 tag_review 中的 `_` 前缀键；另发现 2 条 custom（#421/#423）缺 `legal_topic` 审核维度，转入待审清单（不做自动批准）。
- **可回退性为一等要求**：每次批量修改前对目标条款做修改前快照落盘；逐条 result 文件留档（沿用 `output/audit/<type>_<id>.json` 约定）；去重走可恢复的 rejected 状态而非删除。

## Capabilities

### New Capabilities

- `clause-content-remediation`: 条款库内容治理——确定性缺陷检测、可回退的批量修复（地域泛化、伪影剥离、重复拒绝、审核元数据清理）、修改前快照与回滚。

### Modified Capabilities

- `contract-assembly`: 组装就绪（assembly-ready）判定改为只认审核状态维度、忽略 `_` 前缀元数据键；使 4 条被元数据键误伤的 custom 条款恢复参与组装。

## Impact

- **代码**：`src/clauses/tag_review.py`（`is_assembly_ready`、`bulk_review`）；`scripts/content_check_offline.py`（扩展为治理驱动脚本或新增驱动）；`src/clauses/audit.py` 不改判定逻辑。无 API 面变化。
- **数据**：生产 `clauses` 表（cheap 集群 origin Postgres）——body 改写、tag_review 键清理、重复条款置 rejected。公共只读 API 走中国侧读副本，逻辑复制会自动传播，无需单独处理。
- **运维**：需要生产库访问路径（cheap4 `kubectl exec` 或端口转发）；LLM 语义判定优先用免费 `glm-5.3-flash`（网关修复后），网关修复本身**不在本变更内**（另行 ops 处理）。
- **回退**：修改前快照 + 逐条 result 文件 + rejected 重批准，三层兜底；不做任何删除性操作。
