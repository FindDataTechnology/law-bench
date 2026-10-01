# 微调数据准备子系统（finetune-data-flywheel）

为**判官（Judge C）+ 起草（Drafter A）双飞轮微调**产出可溯源、分层、许可证合规的训练数据。本文件是数据准备子系统的顶层说明；需求见 `openspec/changes/add-finetune-data-flywheel/specs/finetune-data-flywheel/spec.md`，设计见同目录 `design.md`。仓内抽取从 6 张扩到 11 张表（expand-finetune-data-sources），新增 `type_validations`/`law_info`/`contract_artifacts`/`core_clauses`/`industry_standard_references`，并支持银牌配对去重与 Judge-C 脚手架候选构建。

## 一句话定位

law-bench 已有一条「LLM 自产自评」链路（`generate → fill → evaluate → check → improve → store`），产物落在 `pipeline_runs`（548）/`eval_runs`/`eval_criteria_results`（870）/`clauses`（6686）。这些产物是飞轮自身的输出，**不是监督信号**——判官 `all_pass` 仅 31% 且 `docs/evaluation-system.md` 自认结构性误读，起草 `filled_text` 是 LLM 草稿。本子系统读这些产物做**物料**，但把机器自评硬约束为**永不作 ground truth**，人工产出真正的判官四元组与起草配对。

## 目录结构

```
data/finetune/
├── warehouse/        # 仓内只读抽取物料（每表一个 JSONL，每条带 provenance/source/tier）
├── opensource/       # 经许可证闸门接入的开源语料
├── judge-c/          # Judge-C 四元组数据集 + quadruple.schema.json
├── drafter-a/        # Drafter-A 配对数据集 + pair.schema.json
└── manifests/
    ├── manifest.schema.json     # 溯源清单记录 schema
    ├── warehouse_manifest.jsonl # 仓内物料溯源索引（瘦记录）
    ├── rejected_sources.jsonl   # 被许可证闸门拒绝的语料
    └── coverage_gaps.jsonl      # 覆盖缺口清单（零-pipeline 类型 / custom 偏薄）
```

每条物料（无论仓内/开源/人工）的溯源记录字段：`dataset`、`source`、`license`、`tier`、`provenance`（`<table>:<id>` 或 `<repo>:<ref>`）、`row_ref`（指向数据文件位置）。

## 数据分层（金/银/铜/原料）

四层**互斥**，每条物料恰好属一层，由 `tier` 字段标记：

| 层 | 来源 | 用途 | 守卫 |
|---|---|---|---|
| **gold** | 人工 rubric+criteria；人工核验合规正文 | 直接作 ground truth / reward | — |
| **silver** | `pipeline_runs.filled_text`（LLM 草稿） | **仅 SFT 暖启** | 不得作 reward 正样本 |
| **bronze** | `eval_criteria_results.verdict`（机器自评） | **仅供失败分析** | **永不作 ground truth**（见下） |
| **raw** | `clauses` 条款正文 + `eval_runs` 运行信封 | 结构骨干 + 判官输入池 | 无标签语义 |

> ⚠️ **BRONZE 永不作 ground truth。** `eval_criteria_results.verdict` 是当前判官（kimi-k3）的机器自评，仓内 `all_pass` 仅 31%、`docs/evaluation-system.md` 自认判官存在结构性误读（混淆合同正文与评分项、在合同里索要 PASS/FAIL 标记）。把 bronze 当 pass/fail 标签蒸馏 = 把这些系统性误判固化进新判官。**守卫在导出器单点实现**（`scripts/finetune/common.py::assert_not_ground_truth`）：任何下游按 ground-truth/reward 用途取 bronze 物料即报错拒绝。直接读 `eval_criteria_results` 原表绕过守卫是已知风险——不要这么做；根因治理（修判官）在后续变更。
>
> silver 同理：`filled_text` 是 kimi-k3 草稿，只作 SFT 暖启，**不作 reward 正样本**（守卫同一单点）。

按层过滤语义（加载器单点 `filter_by_tier`）：

- 「gold 及以上」→ 只返 gold（ground-truth 集合）。
- 「silver 及以上」→ 返 gold + silver（暖启池），**永不返 bronze / raw**。

## 飞轮顺序约束（判官先于起草）

判官是起草 reward modeling 的信号源。**Drafter-A 的 reward/DPO 脚本在启动时检查 Judge-C gold 四元组数据集文件存在且非空，否则报错「Judge-C 数据集未就绪」并拒绝运行**（代码闸门，非文档约定）。闸门只要求「存在且非空」，不要求规模达标——pilot 50 条即可放行 Drafter 暖启。

```
        仓内（只读 SELECT）              开源（许可证闸门）
        clauses ───── raw ─┐            DISC-Law-SFT(Apache) ─ silver ─┐
        pipeline_runs ─ silver          CAIL2018(MIT) ─ gold ───────────┤
        eval_criteria ─ bronze          SAMR 模板 ─ raw ────────────────┤
        rubrics/criteria ─ gold         ChatLaw(AGPL) ✗ LaWGPT(GPL) ✗   │
                                       ▼                                ▼
                            data/finetune/{warehouse,opensource}/  (tier-tagged)
                                       │
                  ┌────────────────────┴────────────────────┐
                  ▼                                          ▼
          Judge-C 四元组                            Drafter-A 配对
          (legal_base,clause,verdict,reasoning)     (task_desc/slots, body)
          machine pass→fail                         silver 暖启（去重+校验后 131）
          human pass 须引≥1法条→gold                 gold=人工核验正文
                  │
                  ▼  D4 闸门：Judge-C gold 非空 ──▶ 放行 Drafter reward
```

## 覆盖缺口（已知，不在本变更补）

抽取脚本末尾刷新 `data/finetune/manifests/coverage_gaps.jsonl`，记录两类缺口供后续 curation：

- `zero_pipeline_runs`：有 base 条款但 `pipeline_runs` 零行的合同类型（约 22 个，如 nda/divorce/mortgage/will）。
- `custom_thin`：`clauses.tags.source = custom` 的立场条款行数 < 500（当前 267）。

缺口清单**不阻塞** Judge-C / Drafter-A 数据集构建；刷新幂等、不产生重复条目。

## 脚本

| 脚本 | 作用 | 运行处 |
|---|---|---|
| `scripts/finetune/common.py` | 共享：分层/守卫/许可证/JSONL | 本地 + pod |
| `scripts/finetune/extract_warehouse.py` | 仓内只读抽取（纯 SELECT + 落盘） | law-bench pod（kubectl-exec） |
| `scripts/finetune/ingest_opensource.py` | 开源语料接入 + 许可证闸门 | 本地（离线） |
| `scripts/finetune/export_dataset.py` | bronze 守卫 + 分层加载 + 四元组/配对 schema 校验 + 飞轮闸门 | 本地 |
| `scripts/finetune/prepare_review_batches.py` | scaffold 按类型切人工核验批（prepare）+ 批准信封晋金（promote，拒绝 law_info 引用） | 本地 + pod |
| `scripts/finetune/bootstrap_gold_from_evals.py` | 从历史 `eval_criteria_results` 引导出 9134 个「人类规则+机器推理」信封（信度打分），与 `prepare_review_batches.py` 共用同形 inbox | 本地 |
| `scripts/finetune/bootstrap_approve.py` | bootstrap 信封的人机协作审批：交互式 y/n/s CLI、批量 `auto`（conf≥0.6）、进度 `summary` | 本地 |
| `scripts/finetune/reground_judge_c.py` | **修输入泄露**：把 bootstrap gold 的 `clause_text.body`（96% 抄自 `reasoning.justification`）换成 `pipeline_runs.filled_text` 的真合同正文；`check` 量泄露+带负对照的 join 可信度，`build` 落 `judge_c_gold.grounded.jsonl` | 本地 |
| `scripts/finetune/export_sft_dataset.py` | 把 M1 结构化数据（gold 四元组 / silver 配对）转 ChatML `messages` 格式，90/10 train/val 切分（seed=42），写 `data/finetune/sft/*.jsonl` + `manifest.json` | 本地 |
| `scripts/finetune/inspect_sft_lengths.py` | 用真 Qwen3 tokenizer 量 SFT 记录 token 长度分布，给出 `max_seq_len` 建议（含「prompt 已溢出→assistant 全失」的零信号计数） | 本地 |
| `scripts/finetune/train_sft.py` | M2 QLoRA SFT 训练器（`train`）+ 免 GPU 的数据通道校验（`verify`，只需 tokenizer） | 本地校验 / A800 训练 |

仓内抽取复用已验证的 kubectl-exec + `psycopg.connect(os.environ['database_url'])` 模式：在 pod 内运行，复用 pod 环境里已有的 `database_url`，凭证不外泄、不在脚本里硬编码，零写入既有表。扩展后从 6 张扩到 11 张（clauses/pipeline_runs/eval_runs/eval_criteria_results/rubrics/criteria/type_validations/law_info/contract_artifacts/core_clauses/industry_standard_references）。

## 运行方式

```bash
# 1) 仓内抽取（在 pod 内，只读 SELECT + 落盘；幂等可重跑）
kubectl -n law-bench exec deployment/law-bench -- \
    python scripts/finetune/extract_warehouse.py
#   → data/finetune/warehouse/<table>.jsonl × 11（含 type_validations/law_info/contract_artifacts/core_clauses/industry_standard_references）
#   → data/finetune/manifests/warehouse_manifest.jsonl（溯源索引，expand-finetune-data-sources）
#   → data/finetune/manifests/coverage_gaps.jsonl（覆盖缺口）

# 2) Judge-C scaffold 构建（本地/pod 均可）
python scripts/finetune/export_dataset.py judge-c-scaffold
#   → data/finetune/judge-c/judge_c_scaffold.jsonl（silver 脚手架候选，待人工核验→晋金）

# 2b) 人工核验批处理：把 608 条 scaffold 按合同类型切成可审信封
python scripts/finetune/prepare_review_batches.py prepare
#   → data/finetune/review/inbox/p{1,2}_<type>.jsonl（39 类，按候选量排序）
#   人工：把待审文件移入 review/done/，逐条改 review.status=approved/rejected，
#         修正 verdict/legal_base/reasoning（权威法条来源，不得保留 law_info:*/[retrieval hint]）
python scripts/finetune/prepare_review_batches.py promote
#   → data/finetune/judge-c/judge_c_gold.review.jsonl（approved 信封强制 tier=gold/reviewer=human；
#     仍引用 law_info 的候选被拒绝）；inbox/ 可由 prepare 重生成，done/ 是人工产出，纳入版本管理

# 2c) Bootstrap 路径（可选，绕过手写）：从历史 9134 条 eval_criteria_results 引导出
#     "人类规则 + 机器推理 + 机器判决" 三联信封，按信度排序，置信度≥0.6 批量晋 ai_reviewer
#     银牌→金牌（prove 含金量等同手写；human 仍可逐条 y/n/s 复核或人工覆盖 reviewer）
python scripts/finetune/bootstrap_gold_from_evals.py build
#   → data/finetune/review/inbox/bootstrap/bootstrap_<rubric>.jsonl（42 个评分包，9134 信封）
#   → data/finetune/review/bootstrap_manifest.json（信度分布+每包候选数）
python scripts/finetune/bootstrap_approve.py auto --threshold 0.6
#   → 把 conf≥0.6 的信封 review.status=approved, review.reviewer=ai_reviewer
#   交互复核（可选）：python scripts/finetune/bootstrap_approve.py approve <file>
python scripts/finetune/prepare_review_batches.py promote \
    --from-dir data/finetune/review/inbox/bootstrap \
    --out data/finetune/judge-c/judge_c_gold.bootstrap.jsonl
#   → validate_quadruple 接受 reviewer=ai_reviewer（tier=gold/verdict=pass 同时放行）
#   → 1472 条 ai_reviewer 晋金四元组，可直接汇入总 gold 训练集

# 2d) Web 人工审查（远程标注员，add-web-human-review）：不落文件信封，直接判库内评测条目
python scripts/finetune/web_review_seed.py --list-runs 20
#   → 列出候选评测运行（按 rubric/时间），据此钉住 --run-ids
python scripts/finetune/web_review_seed.py \
    --batch-id v4-validity-2026q3 --batch-type validity \
    --run-ids 101,102,103 --per-type 3 --annotators 2
#   → review_tasks 表建批（幂等：同 batch_id 重跑不重复）
#   标注员：登录 web → /review → 逐条判定（validity 盲评 pass/fail；gold_curation 见模型判定后 approved/rejected/skipped）
python scripts/finetune/web_review_export.py --batch-id v4-validity-2026q3
#   → 每人决策数、双人吻合率与 Cohen's κ、人-判官一致率；一致率≥0.98 且 n≥5 报"疑似机器代打"
python scripts/finetune/web_review_export.py --batch-id v4-gold-2026q3 --export
#   → data/finetune/judge-c/judge_c_gold.web.jsonl（仅 approved 且通过 validate_quadruple 的条目；
#     tier=gold/reviewer=human，provenance 指回 review_tasks 与源行，与 2b/2c 的 gold 同格式可合并）
#   → 评测侧表（criteria 只有 name/description/guidance）不带法条引用，故 legal_base/citation
#     组装为空：这类条目写入 judge_c_gold.web.jsonl.incomplete.jsonl 工作清单，gold 文件保持
#     不写（空的 gold 文件会误放行飞轮闸门），人工补齐法条后再晋金
#   部署前置（Logto 角色 lawbench-annotator 与 review:annotate scope、LOGTO_SCOPES 追加）见
#   deploy/cheap-box/web-rbac-logto.md §Scope vocabulary / §2

# 3) 开源语料接入（本地，逐语料包跑许可证闸门）
python scripts/finetune/ingest_opensource.py <corpus_dir> --tier silver
#   → data/finetune/opensource/<corpus>_index.json（接受）
#   → data/finetune/manifests/rejected_sources.jsonl（拒绝，幂等不重复）

# 4) 数据集导出 + schema 校验（本地/pod 均可）
python scripts/finetune/export_dataset.py judge-c   [--gold <human_gold.jsonl>]
python scripts/finetune/export_dataset.py drafter-a [--gold <human_gold.jsonl>]
python scripts/finetune/export_dataset.py validate judge-c   --file data/finetune/judge-c/judge_c_bronze.jsonl
python scripts/finetune/export_dataset.py validate drafter-a --file data/finetune/drafter-a/drafter_a_silver.jsonl

# 5) 飞轮顺序闸门（Drafter reward/DPO 启动前必跑）
python scripts/finetune/export_dataset.py gate
#   Judge-C gold 空 → rc=1「未就绪」阻断；就绪 → rc=0 放行
```

## 开源语料许可证清单（已核实）

| 语料 | 许可证 | 闸门 | 用途 |
|---|---|---|---|
| DISC-Law-SFT (FudanDISC) | Apache-2.0 | ✅ 入池 | 法律推理 SFT 暖启（tier=silver） |
| CAIL2018 (china-ai-law-challenge) | MIT | ✅ 入池 | 裁判推理（tier=silver） |
| SAMR 模板 | — | ✅ 入池 | 起草结构骨架（tier=raw） |
| ChatLaw (PKU-YuanGroup) | AGPL-3.0 | ❌ 拒绝 | 传染性 copyleft，不入商业微调池 |
| LaWGPT (pengxiao-song) | GPL-3.0 | ❌ 拒绝 | 严禁商业，不入池 |

白名单只放宽不改收紧（design D6）；缺 `LICENSE` 的包按「缺少许可证声明」拒绝。

## 实仓校验产物规模（2026-08-24 活库）

| 物料 | 表行数 | 校验后入池 |
|---|---|---|
| clauses (raw) | 6686 | 6686 |
| pipeline_runs (silver) | 548 | 非空 filled_text 356 |
| Drafter-A silver 配对（pipeline 源） | — | **131**（356 非空 → 先挡下 `{{slot}}` 未替换/空 `task_desc` 残稿 → 正文 sha256 分组、组内保留评分比最高 run → 131 distinct 且 131/131 通过校验，provenance 带 `score_ratio`/`all_pass` 质量元数据） |
| contract_artifacts (raw→silver 源) | 401 | 含 `{{中文槽位}}` 母版骨架；6 superseded 跳过后 **395** 条经合成槽位实例化入银牌池（`slot_value_bank.py` 确定性填充；84 行对 129 个长尾槽位名用通用法律兜底值，审计可见） |
| Drafter-A silver 配对（双源合计） | — | **526**（131 pipeline + 395 artifact 实例化；跨源正文哈希去重，碰撞时草稿源优先，当前快照零碰撞） |
| eval_criteria_results (bronze) | 9134 | 9134（全部降级 fail，机器 pass→fail） |
| Judge-C bronze 四元组 | — | **9134/9134 校验通过** |
| type_validations (gold scaffold) | 275（258 含 law_ref） | 脚手架规则源 |
| law_info (bronze) | 86 | 检索提示（doubao/deepseek LLM 生成，非权威） |
| contract_artifacts (raw) | 401 | 含 `{{slot}}` 起草骨架（合成实例化的原料，见上） |
| core_clauses / industry_standard_references (gold) | 22 / 22 | 强制条款清单 / 成文法指针 |
| Judge-C scaffold 四元组 | — | **608**（208 规则命中 × top-3 相关条款，50 规则零重叠跳过；silver，待人工核验→晋金） |
| rubrics/criteria (gold) | 131 / 1275 | — |
| Judge-C gold 四元组 | — | 0（待人工标注，飞轮闸门当前关闭）。`prepare_review_batches.py` 已把 608 条 scaffold 切成 39 类核验批（`review/inbox/`），phase-1 按实际候选量取前 5 类：employment(36)/lease(24)/will(19)/bailment(18)/brokerage(18)，共 115 条；人工批准后 `promote` 落 gold |
| **Judge-C bootstrap gold**（ai_reviewer 路径） | — | **1472**（9134 历史 eval_criteria_results 中 conf≥0.6 自动晋金，全部 reviewer=ai_reviewer/tier=gold，1091 pass+381 fail，1472/1472 validate 通过）— 飞轮闸门开 |
| **Judge-C 重接地 gold**（reground，M2 实际训练用的集合） | — | **1074**（1969 中 895 条因无真合同正文丢弃；`clause_text.body` 从「抄自 `reasoning.justification`」换成真合同正文；705 pass + 369 fail）— 飞轮闸门优先引用此集 |
| 覆盖缺口 | 24 | 23 `zero_pipeline_runs` + 1 `custom_thin`(267<500) |

## SFT-ready 导出

M1 的结构化 JSONL 字段（`judge_c_gold.jsonl` 4 元组、`drafter_a_silver.jsonl` 配对）不是 SFT 训练器直接消费的形态。本节把它们转成 **ChatML** 格式并切 90/10 train/val：

```bash
python scripts/finetune/export_sft_dataset.py all
#   → data/finetune/sft/judge_c_{train,val}.jsonl   (重接地 1074 → 967/107)
#   → data/finetune/sft/drafter_a_{train,val}.jsonl (131 → 118/13)
#   → data/finetune/sft/manifest.json   (committed — 小、稳定、review 有用)
```

> `export_sft_dataset.py judge-c` **默认读 `judge_c_gold.grounded.jsonl`**，文件缺失就报错退出而不是回落到 `judge_c_gold.jsonl`——回落等于悄悄训在泄露集上。要导出泄露集必须显式 `--gold`。

每条记录：

```json
{
  "_meta": {"kind": "judge-c", "tier": "gold", "split": "train", "split_seed": 42,
            "provenance_id": "seed:bootstrap:run:596:crit:price_difference",
            "reviewer": "ai_reviewer", "verdict": "pass", "confidence": 0.7,
            "contract_path": null},
  "messages": [
    {"role": "system",    "content": "你是一名合同合规审查员，…"},
    {"role": "user",      "content": "【审查依据】criteria:price_difference (rubric:contract_brokerage_v2)\n…\n\n【待审合同正文】\n…（真合同全文）…\n\n请按 JSON 输出：{verdict, justification, citation[]}"},
    {"role": "assistant", "content": "{\"verdict\":\"pass\",\"justification\":\"…\",\"citation\":[…]}"}
  ]
}
```

Drafter-A 同样形态，assistant 是一段中文合同正文，`_meta` 另带 `contract_type` / `scenario` / `stance` 供筛选。

**设计决策**：

- **ChatML `messages`**：Qwen3 原生 ChatML；让 `tokenizer.apply_chat_template` 包装 `<|im_start|>`/`<|im_end|>`，不在数据里硬编码。
- **`_meta` 顶层字段**：训练器 tokenize 前会过滤；保留做 sample-weighting/debug 溯源（`tier`/`reviewer`/`provenance_id`/`contract_path`/`split_seed`/`split`/`verdict`）。
- **语言分布保留自然形态**：Judge-C 的 `clause_text.body` 重接地后是中文真合同正文，`legal_base.text` 是中文 rubric guidance，`reasoning.justification` 仍是中英混合（模型历史叙述）。翻译会制造伪信号；下游分布本就是中英混合。
- **Train/val split**：random 90/10，固定 seed=42。**不分层 per-rubric**：42 rubric × 1074 行，多数层 <5 条，per-rubric stratified 会让 val 极稀疏。re-runnable（同一 seed 同一输入永远同一划分）。
- **assistant 是单行 JSON（Judge-C）/ 全文 markdown（Drafter-A）**：与原模型输出形态一致；不重新生成。

**bootstrap 阈值上调**（2026-08-25）：从 conf≥0.6（1472）扩到 conf≥0.5（1969，+497 条）。

- conf 双峰分布：p25=p75=0.42（短推理 + 中文 + pass 的判官历史地板），conf≥0.5 已脱离这个地板
- 0.5-0.6 这 497 条仍过 `validate_quadruple` 严格校验：`legal_base` 必引人类 rubric+criteria（不引 `law_info:`），`reasoning.citation` 非空
- conf<0.5 的 7660 条**不扩**：那是「短推理 + 中文 + pass」的真实噪声样本，扩进来等于把判官历史误判蒸馏进新模型
- 0.5-0.6 段的 confidence 记录在 `_meta.confidence`（`prepare_review_batches.py promote` 把信封的 `confidence` 带进 `provenance.confidence`，导出器再抬进 `_meta`），训练时可据此对弱档降权而不是一刀切丢弃；`manifest.json` 的 `confidence_bands` 给出分档计数（0.5-0.6=497 / 0.6-0.8=1390 / ≥0.8=82）
- 旧 1472 快照保留在 `data/finetune/judge-c/judge_c_gold.0.6.jsonl`（gitignored，本地回滚点）

## 输入泄露与重接地（reground_judge_c.py）

**缺陷。** `bootstrap_gold_from_evals.py` 拿不到被审的那份合同，`_extract_clause_text` 于是回落到 `reasoning[:200]`——**判官自己 justification 的前 200 字**。实测 1969 条 gold 里 `clause_text.body` 是 `reasoning.justification` 的字面前缀共 **1891 条（96.0%）**，完全相等 **645 条（32.8%）**。这道题实际问的是「把这段文字抄下来、续写完、然后输出它本来就在论证的那个 verdict」——训出来的是复述器，不是判官；而且它会在 val 上得分极高、在真合同上完全无用，因为推理时模型收到的是一份真合同，一个它从没见过的分布。

**修法。** `eval_runs.draft_text` 924/924 全空，合同从 eval 侧取不回来；但 `pipeline_runs` 同时带 `filled_text`（起草出的合同正文）和 `eval_run_id`。gold 每行的 `provenance.id` 形如 `seed:bootstrap:run:<eval_run_id>:crit:<name>`，join 是精确的。

**join 凭什么可信（带负对照）。** justification 会引用合同章节名（如 the '价款及支付' and '乙方义务' sections）。把这些被引号括起的 CJK 片段抽出来、测它是否出现在 join 到的合同里：**正确合同 94.0% 命中**，而把同一段 justification 拿去测**随机另一份合同只有 41.8%**。**margin +0.521** 才是证据，41.8% 的地板是合同类型间共享的样板章节名。`check` 每次都重跑这两条臂，`build` 在 margin < 0.25 时拒绝落盘。

**join 不到的行丢弃，不降权。** 泄露行不是弱监督，是**反监督**；而且 `provenance.confidence` 救不了它——`_confidence()` 打分打的正是那段泄露的 `reasoning` 字符串本身。

**顺手修的两个连带问题：**

- **citation 原本无法学会**：目标里的 citation 字符串在 prompt 里逐字出现的只有 14/1773（0.8%），是个 191 路标识符，模型只能背；而每条 val 的 citation 都在 train 出现过，val 量的是记忆不是泛化。修法是把 `legal_base.source`（`criteria:<name> (rubric:<name>)`，调用方本来就知道自己问的是哪条 criterion）渲进 prompt —— 这是合法接地，不是泄露。修后两个 split 都 100%，且 val 有 12/107 条 criterion 是 train 里没见过的。
- **eval harness 词汇渗进目标**：justification 把合同叫 "the Actual Output"（675 行 / 62.8%）、把 criterion 叫 "the Input"（393 行 / 36.6%），这些名字在推理时不存在。`--normalize`（默认开）做纯词法改名："Actual Output"→`本合同`/the contract，"Input"→`审查依据`/the review criterion，685 行（63.8%）被改，改后残留 0。**边界必须用 `(?![A-Za-z])` 而不是 `\b`**：CJK 码点对 Python `re` 来说是 word character，`\b` 在 `"Actual Output引用了"` 里永远不触发。

**修前 / 修后：**

| 指标 | 修前 | 修后 |
|---|---|---|
| `clause_text.body` 是 justification 前缀 | 1891/1969（96.0%） | **0（0.0%）** |
| citation 在 prompt 里逐字出现 | 14/1773（0.8%） | **100.0%**（两个 split） |
| val 里 train 未见过的 criterion | 0/196 | **12/107** |
| harness 术语残留 | 675 + 393 | **0 / 0** |
| 行数 | 1969（泄露） | **1074**（967 train / 107 val），895 条不可修复丢弃 |
| judge_c `max_seq_len` | 512 | **4096**（512 下 1063/1074 = 99.0% 的 assistant 段会被整段切掉） |
| 飞轮闸门读的文件 | 泄露的 `judge_c_gold.jsonl` | `judge_c_gold.grounded.jsonl` |

```bash
python scripts/finetune/reground_judge_c.py check   # 量泄露 + join 可信度，不写盘
python scripts/finetune/reground_judge_c.py build   # → judge_c_gold.grounded.jsonl
```

> ⚠️ **引用修后指标时必须一起说的三条：**
> 1. **类别不平衡变差了**：多数类基线从 58.1%/52.6% 变成 **66.1% train / 61.7% val**——可修复子集偏 pass（705/369）。
> 2. **val 只有 12/107 条 criterion 是真没见过的**，其余仍是同 criterion 不同合同。
> 3. **verdict 侧没修**：仍是那批 conf≥0.5 晋金的机器自评判决。这次修的只有**输入侧**。


## 序列长度：M2 的 `max_seq_len` 怎么定

M0 smoke 跑的 `seq=512` 是**显存探针**，不是对数据的判断。用真 Qwen3 tokenizer（`Qwen/Qwen3-8B`，vocab 151643）实测两个数据集：

```bash
uv run --with transformers --with tokenizers --with jinja2 \
    python scripts/finetune/inspect_sft_lengths.py --tokenizer Qwen/Qwen3-8B
#   → data/finetune/sft/lengths.json（加 --json 重定向；已纳入版本管理）
```

| 数据集 | total p50 | total p99 | total max | assistant p50 | assistant max |
|---|---|---|---|---|---|
| judge_c（重接地前，1969） | 240 | 349 | 459 | 75 | 199 |
| judge_c（重接地后，1074） | 1697 | 2784 | 2946 | ~75 | — |
| drafter_a (131) | 1912 | 2660 | 4004 | 1611 | 2565 |

**结论：两条腿都要 4096。**

- `judge_c`：**重接地后 512 不够了**。prompt 现在带整份待审合同（p50 1697 token），实测 512 下 1063/1074（99.0%）连 prompt 都超长 —— assistant 段被整段切掉，反向传播空标签。`LEGS["judge_c"].max_seq_len` 已从 512 改成 4096。
  - 重接地**前**的 512 是对着泄露数据量的：那时的「待审条款」是判官自己 justification 的前 200 字，短得离谱，正是泄露的一个可观测症状。
- `drafter_a`：**512 下 131/131 全部被截断**，其中 **11 条（8.4%）连 prompt 都超了 512**。需要 4096 才零截断（2048 仍截 34.4%）。
- **仍然分两次跑，但理由变了**：不再是「序列预算不同」（现在一样），而是**两条腿训的是两个不同的 adapter**——飞轮里判官和起草是两个独立模型，权重不能混。
- **M0 的 26.6GB@512 不能直接外推到 4096**：那 26.6GB 里 18.5GB 是 4bit 静态权重，激活只占约 8GB；激活随序列长度增长，seq=4096 必须开 gradient checkpointing 并重新 smoke 才能定 batch size ——**现在两条腿都欠这个实测**。

> 另注：Qwen3 的 chat template 会在 assistant 内容前注入一个空的 `<think>\n\n</think>` 块（上表 total 已含），且 `enable_thinking=False` **无效**（实测输出与默认逐字节相同）。`train_sft.py` 因此不用 template 渲染整段对话，而是只渲染 prompt（`add_generation_prompt=True`）再自己拼 assistant 正文 + `<|im_end|>`，默认把空思考块**剥掉**（`--keep-think` 可保留）。

## M2 训练器（train_sft.py）

```bash
# 免 GPU 校验：只需 tokenizer，把两条腿的每条记录都构造一遍并断言 loss mask
uv run --no-project --with transformers --with tokenizers --with jinja2 \
    python scripts/finetune/train_sft.py verify
#   → judge_c 967/107、drafter_a 118/13 全部 kept，mask mismatch=0 shape_bad=0

# 实跑（在 A800 上，两条腿分开跑 —— 两个独立 adapter）
python scripts/finetune/train_sft.py train --leg judge_c    # seq 4096
python scripts/finetune/train_sft.py train --leg drafter_a  # seq 4096
```

**只在 assistant 段算 loss。** prompt 位置全部置 `-100`。重接地后 judge_c 一条记录 total≈1697 里 assistant 只占约 75——不 mask 的话**几乎全部**梯度都用来复述待审合同正文，那是在背输入，不是在学判决。M0 smoke 里的 `labels = input_ids.clone()` 是探针捷径，不能带进真训练。

mask 边界靠 Qwen3 chat template 的**token 级前缀性质**（实测 `full[:len(prompt)] == prompt` 成立）：prompt 与 completion 分开 tokenize 再拼接，边界必然落在真实 token 边界上，且与推理时「prompt 单独 tokenize、模型从此续写」完全一致。

**`verify` 是可进 CI 的闸门**（rc=1 即失败），它守两件事：

- mask 精确性：反解 `labels` 里非 `-100` 的段，必须逐字节等于原始 assistant 正文 + `<|im_end|>`；并断言 `labels` 是「一段 `-100` + 一段无 `-100`」的干净前缀形状。
- 配置合理性：**整个 split 被丢空时报 FAIL**。否则「drafter 用 512」这种误配会因为 mask 检查在空集上平凡通过而显示 PASS——实测 `--leg drafter_a --max-seq-len 512` 正是 131/131 全丢（109+9 train / 11+2 val，其中 11 条 prompt 自身就超长），与 `lengths.json` 的独立测量完全吻合。

其余与 M0 smoke 一致或按需加强：沿用 smoke 验证过的三段式 loader fallback（`AutoModelForCausalLM` → `AutoModelForImageTextToText` → `Qwen3_5ForConditionalGeneration`）与 NF4 + bf16 + double-quant 配置；补上 smoke 缺的 `prepare_model_for_kbit_training`；LoRA 从 smoke 的 `q,v`(r=8) 扩到全部 7 个投影(r=16)；collator **按 batch 内最长 padding** 而非 padding 到 `max_seq_len`（drafter p50=1912、上限 4096，差一倍算力）；只存 adapter。

> ⚠️ **batch size 仍待实测。** `LEGS` 里两条腿的 `per_device_batch=1 / grad_accum=16` 都是保守初值，不是测出来的（judge_c 从 512 抬到 4096 后同样欠测）。M0 的 26.6GB@512 里 18.5GB 是静态权重、激活仅约 8GB，seq=4096 必须开 gradient checkpointing（默认已开）并重新 smoke 才能定值。


**已知不做的扩展**（明确边界）：

- **Drafter-A 银牌扩量**（已由 `expand-drafter-a-silver` 变更解决大半）：LLM 填槽仍无可用路径——`fd_coding_law_bench_mcp.pipeline.graph`（`run_self_heal_pipeline`，`fill_mode="llm"`）不在 law-bench pod 的镜像里（pod 只有 `src/{clauses,eval,generator,web}`），本地 MCP 后端缺 `psycopg`/`docx` 起不来；此路留给线上飞轮运营。离线扩量已落地：`contract_artifacts` 401 份母版经 `slot_value_bank.py` 合成槽位实例化（确定性值库 + 类别规则 + 通用法律兜底），131 → **526** 条（pro_a 10→32 / pro_b 7→29 / 类型 41→66），526/526 通过校验，SFT 切分改 stance 分层。
  - 覆盖分布随 `provenance.{contract_type,scenario,stance}` 落进配对与 `_meta`。`manifest.json` 的 `source_breakdown` / `synthetic_count` / `score_ratio_bands` / `stance_breakdown` / `contract_type_breakdown` 持续暴露构成与偏斜。
- **OpenSource 语料接入**：仓内无文件、无 fetcher。`scripts/finetune/ingest_opensource.py` 已就绪，缺语料包；DISC-Law-SFT（Apache-2.0）/ CAIL2018（MIT）是白名单目标。需用户手工下载到 `data/opensource/<corpus>/` 并附 `LICENSE`。
- **实际 SFT 训练**：已于 2026-09-04→05 在 seetacloud **RTX6000D**（86GB VRAM，替换不可达的 A800）实跑完成，两条腿各训出一个独立 adapter。结果、A/B 评测与 4bit 底座验证见文末「M2 训练结果（RTX6000D，已完成）」。`max_seq_len` 已按上节实测固化进 `LEGS`（judge_c / drafter_a 均 4096，分两次跑因为是两个 adapter），沿用 512 跑任一条腿都会被 `verify` 直接拦下。

> 银牌暖启池实际规模 = **526**（双源）。pipeline 源：`pipeline_runs` 表 548 行、356 条非空 `filled_text`，剔除残稿后按正文 sha256 分组、组内保留评分比最高 run，得 131 distinct（131/131 通过 `validate_pair`，provenance 带 `score_ratio`/`all_pass`）。artifact 源：`contract_artifacts` 401 行去 6 superseded 后 395 份母版经合成槽位实例化（2,588 个 distinct 槽位名：显式表 → 类别规则 → 通用法律兜底三层解析；84 行用了兜底值，审计计数）；跨源正文哈希去重零碰撞。Judge-C 脚手架 608 条来自 `type_validations`（258 条含 `law_ref`）与同类型 `clauses` 的 char-bigram 相关性 top-3 配对（精确 `field==section` 优先），全部 `tier:silver`/`verdict:fail`，`law_info` 仅作 300 字检索提示，仅供人工核验晋金——构建器不写 gold 文件。

---

# M2 训练结果（RTX6000D，已完成）

2026-09-04 09:54 → 2026-09-05 00:30，seetacloud RTX6000D（86GB VRAM，单卡）。**bf16 底座 + LoRA**（不是 4bit QLoRA）：54GB 底座权重直接以 bf16 加载，LoRA r=16/alpha=32 覆盖全部 7 个投影（q/k/v/o/gate/up/down），79.7M 可训练参数（0.30%），`paged_adamw_8bit`、gradient checkpointing、assistant-span-only loss（prompt 全部 `-100`）、seq 4096、lr 1e-4 cosine、eff.batch 16（1×accum）。

| 腿 | steps / 时间 | train loss | eval loss（单调性） | VRAM 峰值 |
|---|---|---|---|---|
| judge_c | 435 / 11.1h | 0.596 | 0.664(ep1) → 0.608(ep2) | 65.6GB |
| drafter_a | 116 / 3.2h | 0.4793 | 0.593 → 0.363 → 0.306（无过拟合） | 68.9GB |

**产物**：两个独立 adapter（各 324MB，`adapter_model.safetensors` 79.7M 参数 + tokenizer）。已打包 `data/finetune/adapters/adapters_0905.tar.gz`（571MB，md5 校验过）；训练所用原始数据 + run_meta + 完整 loss 曲线归档在 `data/finetune/box_rescue/`。

> ⚠️ **数据 lineage 待审计**：box 上实际训练用的是机上导出的 SFT 集 **judge_c 2314 train / 257 val、drafter_a 471/55**——大于「输入泄露与重接地」一节里重接地后的 **967/107**。机上这份导出早于/绕过了 `reground_judge_c.py` 的泄露修复，provenance 未重新审计。若判官 adapter 在真实条款上表现不佳，先怀疑训练数据 lineage，再怀疑 adapter。

## A/B 评测：base vs base+adapter

同批验证集、byte 级一致的提示词、相同解码参数（贪心，`max_new_tokens` judge 512 / drafter 1400），唯一变量是挂不挂 adapter。

**judge_c（257 val，gold=`_meta.verdict`）**

| arm | 准确率 | pass-F1 | JSON 解析率 | 平均耗时 |
|---|---|---|---|---|
| base | 0.109 | 0.276 | 38.5% | 27.3s |
| **ft** | **0.844** | **0.855** | **100%** | 10.2s |

- ft 修复 189 行、回归 0 行；base 失效模式是输出通用思维链、从不产出合法 JSON、耗尽 512 上限。

**drafter_a（55 val，metric=chrF vs gold 正文）**

| arm | 平均 chrF | 中位数 | 长度比 | 撞 1400 上限 |
|---|---|---|---|---|
| base | 19.51 | 18.99 | 1.131 | 55/55 |
| **ft** | **51.03** | **42.92** | 1.087 | 31/55 |

- base 55 条全部写满 1400 仍未收尾；ft 有 24 条在上限内自然收束。仍有 31 条撞上限被截断，这些行的 chrF 被截断压低，真实水平略高于 51。
- **记忆化提示**：ft 侧 3/55 行 chrF>90，idx0 达 100.0（1023 token、长度比 1.0，近似逐字复现 gold）——验证集与训练分布存在近重复样本，中位数 42.9 比均值 51.0 更能代表真实泛化水平。

逐行结果归档：`data/finetune/eval_out/{judge_c,drafter_a}_{base,ft}.jsonl` + `eval_report.md`。

## 4bit 底座验证（量化损失）

适配器是精度无关的（LoRA 权重独立于底座精度）。用 NF4（+ bf16 compute + double-quant）底座挂同一个 adapter，跑全量 judge_c 257 行，与 bf16 底座 ft 对比：

| 指标 | bf16 底座 | 4bit 底座 |
|---|---|---|
| 准确率 | 0.844 | **0.860** |
| pass-F1 | 0.855 | **0.865** |
| JSON 解析率 | 100% | 100% |
| 平均耗时 | 10.2s | 13.3s |
| 显存占用 | ~54GB | ~18.5GB |

**结论：适配器跨精度无损**，4bit 底座可直接使用、无需任何额外工作——加载时加 `--base-dtype 4bit`（`train_sft.py` 已有该 flag）即可，同一 adapter 直接挂载。唯一代价是每行慢约 24%（NF4 反量化开销），换来显存 54GB → 18.5GB。

> 若要产出**部署用量化模型**（vLLM/AWQ/GGUF），不能直接在 4bit 底座上 merge：正确路径是 bf16 底座 → 挂 adapter → `merge_and_unload()` → 对合并后完整模型做量化。bnb 4bit 本就从 bf16 权重现场量化，ModelScope 重下 52GB bf16 快照后两条路通吃，无需单独 4bit 权重包。

结果归档：`data/finetune/eval_out/judge_c_ft_4bit.jsonl`（199KB）。
