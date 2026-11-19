# 设计：判官结构性误读修复与修后校准

对应 `add-knowledge-bench-platform` 任务 4.1。现状：judge = `src/eval/judge.py::get_judge()`（crewai GPTModel 包装 `EVAL_MODEL`），评分链 task prompt 分散在评审链构造处；自认缺陷三类（`docs/evaluation-system.md` §11 首条）。

## D1 缺陷与现状对照（apply 期实查修订）

| 误读 | 修法 | 现状 |
|---|---|---|
| 混淆「合同正文」与「评分项」 | prompt 分区声明 | **已在产**：`_JUDGE_STRUCTURE_RULES` 规则 1（角色分离），`EVAL_PROMPT_VERSION="v2-structure"` |
| 在合同里索要 PASS/FAIL 标记 | 输出契约显式声明 + fail-loud 检测 | 声明已产（规则 1）；**fail-loud 检测缺**——本 change 新增 |
| 误读字段 | 字段纪律规则 | **已在产**（规则 3）；解析层无 invalid 兜底——本 change 新增 |

时间线考古：`_JUDGE_STRUCTURE_RULES` 11-03 随任务 4.2/4.3 引入（444bd2d），晚于 §11 缺陷清单；4.1 注记未跟进。prompt 修复内容不变，本 change 做归属补账 + 解析硬化 + 校准实跑。

## D2 prompt 域化补账

`v2-structure` 规则文本从 `scoring.py` 模块常量迁入 `generation_prompts` 域：type=judge_scoring 版本行 + provenance（`{"motivation": "add-judge-misread-remediation", "scope": "judge_scoring", "inherits": "v2-structure"}`）；`build_judge_criteria` 改按域查询注入（缺省最新，域不可用时回落模块常量——**评审链永不因 prompt 域故障而断**）；回滚=指定旧 version。EVAL_PROMPT_VERSION 语义保留（指向域内版本标签）。

## D3 解析硬化（fail-loud 单点）

`src/eval/scoring.py` 评分结果收口处加三类检测（纯函数 `_classify_structural_soundness(reasoning, verdict) -> InvalidReason | None`）：
1. marker_in_contract：reasoning 语义归因「合同应包含/添加 PASS|FAIL 标记」（关键词+归因短语匹配，宁可漏判不误杀——只拦高置信模式）；
2. ambiguous_reference：CONFIDENCE 尾标缺失或格式违约（parse_confidence 已返 None）→ contract_violation；引用归属歧义检测谨慎——只在 reasoning 显式声明无法区分时判 invalid，不猜；
3. contract_violation：GEval error 非空（判官调用失败）已在既有 error 通道，本 change 补「success=True 但 reasoning 为空」→ invalid。
invalid 记入 criteria_results（verdict="invalid"，reason 留痕），不计 n_passed/n_total 分母——**分数语义：invalid 从分母剔除而非计 0**（与 §11 第二条 all-pass 放大噪声独立，另行处理）。invalid 率=invalid/total，纳入校准报告。

## D4 校准闭环实跑

gold pair 导出（prod review pilot 双标注+QC 过的 pair 集，`scripts/finetune/web_review_export.py` 既有导出族）→ `scripts/calibrate_judge_live.py` 复跑（driver 已支持 v2-structure + run_calibration 落库）→ 报告含 invalid 率 → 验收判据：误读用例清零 + all_pass 合理区间 + invalid 率不超阈值。OpenRouter 配额为硬约束：跑前预估 pair 数×criteria 数，配额不足如实记录跑不动的轮次。

## D5 风险

- 风险①：invalid 检测误杀正常评分——关键词+归因短语只拦高置信模式，校准报告的 invalid 率本身就是误杀监控；
- 风险②：prompt 域不可用回落路径保证评审链不断（域查询 try/except 回落模块常量）；
- 风险③：gold pair 导出依赖 prod review pilot 数据在库——apply 期实查数据量，不足则如实记录并缩小校准规模。
