# Design: expand-drafter-a-silver

## Context

Drafter-A 银牌池现在只由 `scripts/finetune/export_dataset.py` 的 `_build_silver_pairs()` 产出：读仓库快照 `pipeline_runs`（548 行，356 条非空 `filled_text`），按正文 sha256 去重得 150 条 distinct、校验后 131 条配对——该源已榨干（150 distinct 是上限，131 ≈ 池容量的 87%）。仓库里另一张表 `contract_artifacts`（401 行）存的是人工策划母版经条款装配后的**带槽位骨架**：`body_text` 全部含 `{{中文槽位名}}`（如 `{{甲方名称}}`），`slots` 是槽位名列表（无值），6 行已 superseded。SFT 导出层 `export_sft_dataset.py` 把配对转成 Qwen ChatML 三元组，随机 90/10 切分，manifest 已暴露 stance 倾斜为已知弱点。

关键约束：微调脚本只依赖 Python 标准库（项目 venv 在部分开发机因 litellm 编译失败不可用）；spec 规定抽取只读幂等、机器产出永不晋金、银牌仅限 SFT 暖启。

事实基础（2026-08-24 快照实测）：401 条母版正文与 pipeline 池**零重叠**、66 个合同类型（现池 41）、stance 覆盖 balanced 151 / pro_a 22 / pro_b 22 / 未标 206；pipeline 源 150 条 distinct 正文中仅 2 条 best score_ratio ≥ 0.8（LLM 草稿质量普遍偏低，母版条款装配质量反而更高）。

## Goals / Non-Goals

**Goals:**

- Drafter-A 银牌池 131 → ~520 条（+~395 条母版实例化配对），覆盖 66 类型、补齐 pro_a/pro_b 立场样本。
- 全流程离线确定性：相同快照重跑逐字节一致，无 LLM 调用、无新依赖。
- 槽位值「诚实呈现」：prompt 里给什么值，正文里就是什么值，训练信号无泄漏。
- 质量元数据可见：pipeline 源配对带 score_ratio / all_pass，合成源带 synthetic_slots 标记，训练端可分层降权。
- SFT 导出可复现且立场分层，manifest 反映双源构成。

**Non-Goals:**

- 不做 LLM 批量填充（走线上 pipeline 产新 `pipeline_runs` 是飞轮正路，但依赖服务与算力，属后续运营动作）。
- 不做 DPO/偏好对构造（需要 M3 训练器，本次仅 SFT 数据）。
- 不修改 Judge-C 轨道、飞轮闸门、`train_sft.py` 数据接口（ChatML 形状不变，`_meta` 仅增字段）。
- 不改仓库抽取层（`extract_warehouse.py` 保持只读幂等；母版行在抽取层仍标 `raw`，实例化配对在配对层标 `silver`——两层标签语义不同，spec 增量已澄清）。

## Decisions

### D1 合成槽位实例化而非「直接训练带槽位模板」

三个候选：(a) 把 `{{槽位}}` 模板直接当 assistant 目标训练；(b) 用确定性值库实例化；(c) LLM 批量填充。
选 (b)。(a) 改变任务语义（模型学会输出占位符而非成文合同），且违反现有「正文不得残留占位符」spec；(c) 质量最高但需服务在线 + 每条 1 次 LLM 调用，非离线确定性，留作后续飞轮运营。母版正文本身是 base+tagged+custom 条款装配的人工策划结构，法律文本质量高于 LLM 草稿（2/150 ≥0.8 分），合成实例化只注入槽位值这一「变量」，结构信号保真。

### D2 槽位值库：按槽位名的类别化值库 + 记录级确定性抽取

新模块 `scripts/finetune/slot_value_bank.py`（纯标准库）：

- **值库结构**：`{"<槽位名>": ["值1", "值2", ...], ...}`，每个显式槽位名 ≥8 个互异值；另设类别兜底表（当事人名称/日期/金额/比例/期限/地点/义务/方式…，按槽位名后缀或关键词归类）。
- **确定性**：`rng = random.Random(int(sha256(body_text)[:16], 16))`，对排序后的槽位名依次 `rng.choice`；同一槽位名在同一正文多处出现 → 同值替换。Mersenne Twister + 整数种子跨平台跨版本稳定，满足幂等重跑要求。
- **防退化**：同槽位名多值变体（不同公司名、不同日期、不同金额量级）避免模型记住单一填充值；值用真实感中文（「晟华科技有限公司」「2026年3月15日」「人民币壹拾贰万元整（¥120,000）」）。
- **普查结论与三层解析**（实现期修正）：快照实测 2,588 个 distinct 槽位名（395 行），长尾约 180 名仅出现 1-3 次（碎屏险/充电桩/车架号类模板特有槽位），逐名策展不可行。解析层次为：显式表 → 有序类别规则（纯 ASCII 名兜入当事人类）→ **通用法律兜底值**（「双方另行协商确定」等，取自 text 池）。实测 311/395 行（79%）全规则归类，84 行对 129 个一次性槽位名使用兜底（占比 21%，全部 ≤2 次出现），兜底用量计入导出审计；结构错配（占位符不在 `slots` 清单）实测为 0，仍保留整行丢弃规则作守卫。

*备选被拒*：按 hash 直接伪造槽位值（`公司A_1f3a`）——退化值会让模型学到垃圾填充模式。

### D3 占位符正则统一为 CJK+ASCII

现 `_SLOT_RE = \{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}` 只匹配 ASCII，`{{甲方名称}}` 完全漏检。统一为 `\{\{\s*(\w+)\s*\}\}`（Python `re` 默认 Unicode 下 `\w` 含 CJK 与数字下划线），下沉到 `common.py` 单点定义，`export_dataset.py` 校验与实例化共用。`validate_pair` 同步受益：今后任何源的 CJK 残留占位符都会被拒。

### D4 pipeline 源择优去重 + 质量元数据

现行为「首条有效出现胜出」——重复正文的早期低分迭代可能压过后期高分迭代。改为：按正文哈希分组，组内取 `score/max_score` 最高者（平分取 `all_pass=True` 者，再平取更晚 `created_at`），被保留配对的 `provenance` 增 `score_ratio`（两位小数）与 `all_pass` 字段。不按阈值过滤（≥0.8 仅 2 条，过滤即清空），只做元数据透传，降权决策留给训练端。

### D5 跨源去重，草稿源优先

合并顺序：pipeline 源先入池（占据哈希位），artifact 源后入、撞哈希即弃并计数。现实快照零重叠，但规则必须确定以应对未来快照。审计输出按源分计「去重前/去重后」。

### D6 task_desc 确定性合成

模板：`请起草一份{类型中文名}合同{（业务场景：{scenario}）}{（立场：{stance_zh}）}，条款结构完整、符合中国法律。`（可选段按字段存在与否拼接）。类型中文名映射从 `src/contracts` 的模板注册表一次性提取为 `slot_value_bank.py` 内的静态字典（脚本层不可 import src，避免依赖项目 venv）；stance_zh：pro_a→「侧重甲方利益」、pro_b→「侧重乙方利益」、balanced→省略。未标 stance/scenario 的行合法保留（206 行母版无 stance，SFT `_meta` 按现状记 `(untagged)`）。

### D7 stance 分层验证切分

`export_sft_dataset.py` 的 `_split_indices` 扩展为按 stance 分组切分：组内 seeded shuffle 后取 `ceil(n*val_frac)` 入 val（至少 1 条当 n ≥ 2），跨组 RNG 派生自 `(SPLIT_SEED, stance)`，保证复现且少数立场不全落一侧。judge-c 切分逻辑不动。

### D8 manifest 增源构成

`drafter_a` 段新增：`source_breakdown`（pipeline_runs / contract_artifacts 计数）、`synthetic_count`、`score_ratio_bands`（<0.5 / 0.5-0.8 / ≥0.8，仅草稿源）。`_meta` 增 `source` 与 `synthetic_slots` 字段（trainer tokenization 前丢弃 `_meta`，无兼容性影响）。

## Risks / Trade-offs

- [模型学到合成填充值的风格偏差] → 值库每槽位 ≥8 变体 + 真实感取值；`synthetic_slots` 标记允许训练端把合成子集当独立域降权或做消融对比。
- [值库覆盖不全导致大量丢弃] → 实现首步做槽位名普查；类别兜底兜住长尾；丢弃计数进审计，若 >5% 回补值库而非放宽整行弃置规则。
- [同一模板不同记录同值组合碰撞] → 种子含 body_text 哈希，不同正文几乎必然不同组合；不影响正确性（无唯一性要求），仅多样性。
- [双源混合后 balanced 仍占多数] → 分层切分保证验证集有各立场；训练侧再加权属训练器超参，不在本变更强行上采样（避免重复样本的过拟合副作用）。
- [zh 类型名映射与 src 注册表漂移] → 映射生成时记录来源快照；类型集变化率低，普查步骤会在新类型出现时暴露缺口。

## Migration Plan

1. 新增 `slot_value_bank.py`（值库 + zh 名映射，独立可测）。
2. `common.py` 下沉 CJK 正则；`export_dataset.py` 接入双源构建、择优去重、跨源合并（`drafter-a` 子命令一次产出全部）。
3. `export_sft_dataset.py` 分层切分 + manifest 增量。
4. 重导出：`export_dataset.py drafter-a` → `export_sft_dataset.py all` → `inspect_sft_lengths.py` 更新长度统计。
5. 回滚：`git revert` 代码即可；数据文件均可再生，`manifest.json` 随代码回滚后重导出即恢复原状。

## Open Questions

（无——值库具体条目在实现期由槽位名普查确定，不影响本设计与任务结构。）
