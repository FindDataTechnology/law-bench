# Proposal: expand-drafter-a-silver

## Why

Drafter-A（起草模型）SFT 轨道只有 131 条银牌配对、立场严重失衡（balanced 114 / pro_a 10 / pro_b 7），喂不饱即将在独立服务器上用 Qwen 27B QLoRA 进行的微调；而仓库快照里 401 份人工策划的母版合同模板（66 个合同类型、全 stance 覆盖、与现有池零重叠）因带 `{{中文槽位}}` 占位符被整表闲置——它们是现有最大的未开发高质量原料。

## What Changes

- **新增「合成槽位实例化」银牌配对构建器**：消费 `contract_artifacts.body_text`（跳过 `superseded_at` 非空行），用确定性槽位值库填充 `{{槽位名}}`，槽位值如实写入 user prompt 的【槽位值】段，产出 `(task_desc/slots, 正文)` 银牌配对。预计 +395 条，Drafter-A 池 131 → ~520。
- **槽位一致性检查器支持 CJK 槽位名**：现 `_SLOT_RE` 只匹配 ASCII 标识符，检测不到 `{{甲方名称}}`；统一为 CJK+ASCII 兼容正则，pipeline 源与 artifact 源共用。
- **pipeline_runs 源去重保留最高分配次**：同正文多条 run 时改为保留 `score/max_score` 最高的那条，并在 provenance 记录 `score_ratio` / `all_pass` 质量元数据供训练端降权（现 150 个 distinct 正文仅 2 个 best-ratio ≥0.8，质量元数据必须可见）。
- **跨源正文去重**：pipeline 源与 artifact 源合并后按正文哈希统一去重，审计记录各源去重前/后计数。
- **SFT 导出升级**：val 切分按 stance 分层（避免少数立场全落 train 或全落 val）；manifest 新增 source_breakdown（pipeline_runs vs contract_artifacts）、合成标记、质量字段分布。
- **任务描述合成**：artifact 源配对的 task_desc 由 contract_type（经 zh 名映射）+ scenario + stance 确定性模板合成；provenance 标 `synthetic_slots: true`。

不改变的原则：机器产出永不自动晋金；银牌仅限 SFT 暖启、永不进 reward 正样本；抽取任务只读幂等。

## Capabilities

- **New Capabilities**: （无）
- **Modified Capabilities**:
  - `finetune-data-sources` — 「银牌配对去重」需求扩展为跨源去重；新增「合成槽位实例化配对构建」需求（artifact 源消费规则、槽位值如实进 prompt、CJK 占位符校验）。
  - `finetune-data-flywheel` — 「Drafter-A 配对数据集」需求的银牌来源定义从单一 `pipeline_runs.filled_text` 扩为「LLM 草稿 + 确定性合成实例化母版」双源，并新增质量元数据与 stance 分层切分场景。

## Impact

- `scripts/finetune/export_dataset.py`：drafter-a 子命令新增 artifact 源构建器、跨源去重、CJK 正则、pipeline 源质量择优。
- `scripts/finetune/export_sft_dataset.py`：stance 分层切分、manifest source_breakdown。
- 新增 `scripts/finetune/slot_value_bank.py`（槽位值库，纯标准库）与 zh 类型名映射。
- 新增 `tests/test_finetune_expand_drafter.py`（构建器确定性、占位符清零、superseded 跳过、跨源去重、切分分层）。
- 重新导出的 `data/finetune/drafter-a/drafter_a_silver.jsonl`、`data/finetune/sft/*` 与 `manifest.json`（manifest 入库跟踪，jsonl 按惯例 gitignore）。
- 不影响 Judge-C 轨道、飞轮闸门、训练器 `train_sft.py` 的数据接口（ChatML 三元组形状不变，仅 `_meta` 增字段）。
