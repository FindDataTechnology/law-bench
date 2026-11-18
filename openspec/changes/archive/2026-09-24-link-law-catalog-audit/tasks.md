# Tasks: link-law-catalog-audit

## 1. Schema 与目录副本

- [x] 1.1 建 `law_catalog` schema：`laws` 副本表（id/title/category/publish/expiry/status/src_db/content_status）、`aliases` 别名表（alias → title/law_id、来源标记）、`clause_law_refs` 解析结果表（clause_id、law_id、status 快照、resolved_via、resolved_at）；law_bench 迁移脚本随现有迁移体系
- [x] 1.2 写导入脚本：从 RustFS 上的目录导出文件（法规库 PG 全量导出）幂等灌入 `law_catalog.laws`（全量替换语义），报告行数与 max_id；`laws.title` 建 pg_trgm 索引
- [x] 1.3 人工动作清单写入 runbook（首灌已执行：21,746 行/max_id=74,584 对账精确命中，sha256 已验）（法规库侧导出 SQL → 上传 RustFS 路径 → 导入命令），并实际执行一次首灌，校验 21,746 行级别对账

## 2. 名称解析层

- [x] 2.1 实现归一化函数（去 `中华人民共和国` 前缀、去书名号/空白），语义对齐 `legal_refs._dedup_key`
- [x] 2.2 实现解析阶梯：归一化精确 → 别名表 → pg_trgm 过阈值（阈值环境变量配置化，给默认值）→ unresolved；每条结果带 `resolved_via`
- [x] 2.3 别名表种子：从 `law_refined_citations.py`、law_info surveys、`docs/legal_references.md` 收集已知简称/不一致写法（九民纪要、各司法解释简称等）首批录入
- [x] 2.4 全量解析任务：读全部条款 `law_refs` → 写 `clause_law_refs`（幂等全量重算）；验证不改写 `clauses.law_refs` 且条款编辑后重跑结果跟随更新

## 3. 引法审计

- [x] 3.1 实现审计 CLI：join `clause_law_refs` × `law_catalog.laws`，按设计 D5 规则分类（已废止/失效、已修改、兜底清单），判定逻辑零引用 `expiry` 列
- [x] 3.2 产出 markdown 报告到 `docs/`（报告头含目录快照标识：行数/max_id/导出时间；按 resolved_via 分层；per-clause 明细）
- [x] 3.3 首跑审计并人工抽查（阈值校准 0.65 后：已废 297 全部 exact，trigram 仅留书名号变体命中）：trgm 命中抽样核对、已废止命中抽样核对（重点验证《合同法》类条款被正确标红）

## 4. Web 复核队列

- [x] 4.1 审计结果页 + 未解析项复核队列路由/页面（复用 tag_review 的路由与模板模式），展示引用名、候选匹配、状态分类
- [x] 4.2 复核动作：确认映射（沉淀为别名表记录）、标记故意不匹配、保持 pending；动作只写别名表/复核标记，不触碰条款
- [x] 4.3 复核闭环验证：确认别名后重跑解析，该名称 `resolved_via` 变为 alias

## 5. 测试与收尾

- [x] 5.1 单测：归一化/别名/trgm 阶梯各分支、状态分类规则（含 expiry 陷阱用例：expiry 过去 + status 有效 不标废）、导入幂等、重跑确定性
- [x] 5.2 更新 `docs/`：法规目录副本的刷新 runbook、审计报告使用说明
