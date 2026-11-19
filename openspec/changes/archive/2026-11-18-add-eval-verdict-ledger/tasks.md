## 1. 记录形状（内核增列）

- [x] 1.1 在 `src/eval/store.py` 的 `_ADDITIVE_COLUMNS` 追加十条可空列（`subject_kind`/`subject_key`/`subject_version`/`ruler_kind`/`ruler_key`/`ruler_digest`/`gate`/`outcome`/`baseline_run_id`/`provisional`），`baseline_run_id` 带自引用外键约束；验证：`ensure_schema` 在一个已有 `eval_runs` 的库上重跑两次不报错、二次为幂等 no-op
- [x] 1.2 扩展 `store_result()`：新增可选形参（subject/ruler/gate/outcome/baseline_run_id/provisional），未传时行为与今日逐字节等价；验证：既有 `tests/test_store.py` 全绿且无人传新参时写入行与迁移前一致
- [x] 1.3 回填脚本：历史行 `outcome` 按 `all_pass` 推导（1→`pass`、0→`fail`），幂等；验证：重复执行两次行数不变、无 `inconclusive` 出现在历史行

## 2. 门词汇表与三态判定（纯函数）

- [x] 2.1 新建 `src/bench/verdicts.py`：`GATES = {no-worse, regression, all-pass, calibrated}` 闭集、`OUTCOMES = {pass, fail, inconclusive}` 闭集、写入校验（未知值拒绝并列出闭集）；验证：新增 `tests/test_verdicts.py`，未知门/未知结局各一条拒绝用例、四个合法值各一条接受用例
- [x] 2.2 同模块实现基线可比性：`comparable(baseline, current)` 按 `ruler_digest` 相等判定，不等返回「口径已迁移」；验证：同 digest 可比 / 异 digest 标迁移 / 无基线标立基线，三条用例
- [x] 2.3 同模块实现 `provisional` 推导：给定判官身份，查询其最近一条 `calibrated` 门结论的 `outcome`，非 `pass` 或无记录即 provisional；验证：能用注入的假查询函数覆盖三种状态（过门/未过门/无记录）

## 3. 两条线接入（其余六线留作后续）

- [x] 3.1 合同评测接上：`src/eval/scoring.py` 的落库调用携带 subject（`contract:<type>/<scenario>` + 内容指纹版本）、ruler（rubric 名 + `canonical_digest()` 算出的 digest）、gate=`all-pass`、outcome 由 `all_pass` 推导；验证：跑一次真实评测，`eval_runs` 新行四个新字段非空，且 ruler digest 与直接调 `canonical_digest()` 结果一致
- [x] 3.2 数据通道接上：`src/bench/data_checks.py` 的落库调用携带 subject（kind + key + 单元版本）、ruler（checker 集名 + digest）、gate=`regression`；验证：跑一次数据评测，记录带 subject 与 ruler，`channel='data'` 不变
- [x] 3.3 校准结论升级为结论行：`src/bench/calibration.py` 落库时补 subject（判官模型 + 提示词版本）、ruler（gold 集 digest）、gate=`calibrated`、outcome 三态；验证：跑一次校准（或用既有记录回放），产出的行可按 `calibrated` 门查询到，且 `inconclusive` 与 `fail` 分列
- [x] 3.4 判官可信度改为由结论推导：替换任何「是否已校准」的独立判定为 `verdicts.provisional()`；验证：无校准记录时 `provisional=true`，有通过记录时为 `false`，换 gold 集 digest 后自动回到 `true`

## 4. 运行台账互链

- [x] 4.1 `src/bench/agent_runs.py` 增可空 `verdict_run_ids`（JSONB 数组）并写入路径支持；验证：产出结论的运行行带 id 列表，未产出的为空数组而非 `null`
- [x] 4.2 反查读面：给定结论行可找到其运行行，给定运行行可列出其结论行；验证：一条运行 + 两条结论的往返查询用例

## 5. 晋升后复测项

- [x] 5.1 实现待复测项登记：晋升/发版动作调用一次登记（subject 地址 + 晋升前基线结论 id），选既有工单机制承载而不是新建表；验证：一次真实晋升后能查到该待复测项，且未触发任何评测执行
- [x] 5.2 复测结论引用晋升前基线；验证：对已晋升对象执行复测时，`baseline_run_id` 指向晋升前那条

## 5b. 机器读面（关闭 paas 侧依赖的缺口）

- [x] 5b.1 `src/eval/store.py::list_verdicts` 增 `domain_paths` 筛选（按 `rubric_domain_id` + 祖先链，与运行列表同口径）；显式空作用域返回空而不是全量
- [x] 5b.2 `src/web/routes/distribution.py` 增三条只读端点：`/verdicts`（列表 + 闭集校验筛选）、`/verdicts/{run_id}`（单条 + 逐条判据）、`/rulers`（尺子 + digest）；沿用 `X-Consumer-Token` 三态 + fleet 种类
- [x] 5b.3 测试 `tests/test_verdict_read_web.py`：11 例覆盖三态鉴权、域作用域、`inconclusive` 透传、未知门 400、他域 id 404、rulers 的 digest 与写入时一致
- [x] 5b.4 spec 增「结论台账的机器读面」需求；验证：`openspec validate --strict` 绿

## 6. 文档与验收

- [x] 6.1 `docs/evaluation-system.md` 增一节「结论台账」：四个门的语义、三态结局、baseline 与口径迁移、provisional 规则、六条线接入清单；验证：文档评审通过，且六个门→四道门的映射表与代码常量一致
- [x] 6.2 跨线可比性演示：合同线与数据线各一条结论，按 subject 聚合能在同一张趋势图上呈现；验证：手工查询或读面截图，两条线出现在同一结果集
- [x] 6.3 全量回归绿：`uv run pytest tests`；验证：测试数量不低于本次改动前，既有断言口径零变化
