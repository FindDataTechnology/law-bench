## 1. 共享检测模块与治理驱动（b0 前）

- [x] 1.1 把 `scripts/content_check_offline.py` 的检测规则函数抽成可导入模块（`src/clauses/content_checks.py` 或同级），离线脚本改为薄壳调用；既有报告输出格式不变
- [x] 1.2 新增 `scripts/content_remediation.py`：支持 `--batch b0-data|b1|b2|b3|b4`、`--dry-run`、`--rollback <batch>`、`--limit`；按 design D3 落 `output/remediation/<batch>/{manifest,before,applied}` 快照布局；写路径只复用 `update_clause`/`bulk_review`（tag_review 清除/回滚走窄口径单列 UPDATE——`update_clause` 不支持 tag_review 字段，design 已修订）
- [x] 1.3 rollback 命令：从 before 快照恢复 body/tag_review，manifest 记录的去重 id 重批准；本地空库上用造数据验证回滚幂等（回滚两次结果一致）

## 2. 门控代码修复（b0-code）

- [x] 2.1 `src/clauses/tag_review.py`：`is_assembly_ready`/`bulk_review` 及审核状态消费点跳过 `_` 前缀键；新增常量 `REVIEW_STATUSES = {"pending","approved","rejected"}`（实现为既有 `_REVIEW_STATUSES` 之上补充 `METADATA_PREFIX` 常量；实施核查确认门控按 tags 维度遍历，真实缺陷是 bulk_review 整体替换——已改为合并写）
- [x] 2.2 单测：`{"stance":"approved","_note":"..."}` → ready；`{"stance":"pending","_imported_at":"..."}` → not ready；`bulk_review` 不触碰 `_` 键
- [x] 2.3 跑既有 clause/tag 相关测试（`tests/`）确认无回归，提交并走 Jenkins 构建部署（`sha-f8bb681`，Jenkins #12；`test_assemble_with_scenario_includes_tagged` 在未改动的 main 上同样失败，属既有问题非本变更引入）

## 3. 生产库访问与只读预检

- [x] 3.1 按设计 D2 建立 SSH 隧道 + kubectl port-forward，写一页 runbook 片段（命令、验证、断开）追加到 `deploy/cheap-box/README.md`（改为落在 `scripts/infra/open_prod_tunnel.py` 模块文档——README 有另一工作线的未提交改动，不宜混入提交）
- [x] 3.2 只读预检：隧道下用驱动对生产库跑 detector 全量，与本地 dump 报告 diff（b0=74/b1=36 受害/b2=16+1 豁免/b3=360，与 dump 报告口径差异已逐项核对）

## 4. 数据治理批次（依次执行，每批 dry-run → 应用 → 验收）

- [x] 4.1 b0-data：清除 74 条 tag_review `_` 前缀键；验收——`_` 键清零、bulk_review 不再抹除溯源键；#421/#423 因缺 legal_topic 维度进入待审清单（不自动批准），#422/#7093 保持组装就绪
- [x] 4.2 b1：去重 65 组 body_hash 重复（保留最小 id，其余 `bulk_review(rejected)`，manifest 记录全部 id）；验收——同 source 内重复组归零（37 条受害条款置 rejected），剩余 7 组为 tagged 与 base 跨 source 同文（组装优先级天然消解，属库噪声，已在验收报告留档）
- [x] 4.3 b2：17 条 scenario 地域条款改写（全国泛化 + `{{arbitration_commission}}` 占位；#2370 白名单豁免）；草拟→人工确认→`region_lint==0` 验证后落库；验收——住宅租赁实机组装 9 个城市/地方条例关键词命中 0，争议解决渲染为占位符
- [x] 4.4 b3 首批 50 条：签署壳/`___`/表格碎片确定性清理（设计 D5 规则 + 白名单）；人工抽检 diff（抽检发现两类规则缺陷：整块签署条款被剥成碎片、空格间隔标签漏匹配——已回滚修正后重做）
- [x] 4.5 b3 放量：剩余伪影条款清理（+40 修正版重做 +110 补扫 = 150 条改写）；验收——可确定性清理项归零；残余 = 约 230 条整块签署条款（section 白名单豁免，留模板层决策）+ 46 条混合残留（留 LLM 通道），已在验收报告量化
- [x] 4.6 b4：#7267 违约金改 `{{penalty}}`；3 条悬空法条尾缀整合；15 条超短残桩逐条分拣（triage 结论：全部保留——纯槽位 stub 无实质危害）；验收——detector 复扫 literal_money 4→3（余 1 条为里程数误报）、法条尾缀清零

## 5. 收尾

- [x] 5.1 全量复扫 detector + 生成验收报告（`output/remediation/final_report.md`：before/after 计数对比、各 batch manifest 索引）
- [x] 5.2 更新 `output/content_audit_report_2026-09-15.md` 头部加"已治理"标注指向本变更；孤儿池 158 条地域条款登记为后续项（依赖网关 glm-5.3-flash 修复）
- [x] 5.3 `openspec validate content-remediation --strict` 通过后走 archive 流程（用户确认后执行 `/opsx:archive`）
