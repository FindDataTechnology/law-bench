# finance-data 域包

金融数据域包（**数据重、文本轻**）：首批资产是公告情绪金标语料（`kind=fact`，来自 fd-sentiment gold-v9 的只读适配）与其上的确定性数据 QA（checker 契约 + 首批数据 QA 金集题目）。

## 与 fd-sentiment 原尺子的关系

**迁入 ≠ 取代：4.6 等价复核未完成前，fd-sentiment 原仓尺子仍为真源。** 本包只做语料适配与确定性 QA，不复刻、不改动原仓的打分逻辑；金标档位语义以 `fd-sentiment` 仓的标注规则表（`scripts/build_gold_set.py` 的 `RULES`）与 `fd_sentiment/models.py` 的五档词表为准。等价复核（openspec change `add-knowledge-bench-platform` 任务 4.6）完成并确认两边同尺后，才谈得上把评测入口迁到本平台。

## 资产来源（三仓，均只读，一个字节不改）

数据文件**不复制进本仓**：适配器在运行时从兄弟仓路径读取，`packs/finance-data/adapters.py` 的模块常量 `SENTIMENT_REPO` 指向默认路径，环境变量 `FD_SENTIMENT_REPO` 可覆盖。

| 兄弟仓 | 用到的入口文件 | 在本包中的对应物 |
|---|---|---|
| `<workspace>/fd-sentiment` | `gold/gold-v9.json`（金标数据，105 条）；打分器 `fd_sentiment/scoring.py`（`score_document`）；评测/校准 `fd_sentiment/evaluate.py`；金标构建与重标 `scripts/build_gold_set.py`、`scripts/relabel_gold_set.py` | `adapters.py` 语料适配（gold-v9 → knowledge_units）；`checks.py` 的五档词表/方向口径 |
| `<workspace>/fd-data-quality` | `CONTRACTS.md`（文件驱动重灌契约：值域/键唯一/格式校验、FAIL 不得重灌）；`baselines/*.yaml` | `checks.py` 的确定性 checker 语义（显式允许集、字段契约先行） |
| `<workspace>/dashboards` | `data_plane.py` 的 `finalize()` 出片闸门与对账判据（声明值必须与实际数据一致，否则 FATAL） | `checks.py` 的 `build_data_qa_goldset`（判据改写为可执行 QA 题目） |

## kind 说明（如实）

- 当前入库 **只有 `kind="fact"`**：gold-v9 的 105 条人工金标标注（`doc_id` 唯一、`tier='gold'`、`namespace='finance-data'`）。每条 attrs 保留原文件字段（`expected_band` 强度档位、派生三分类 `direction`、`as_of` 公告日、`text_sha256`/`text_chars` 原文锚点）——gold-v9 本身**没有金额字段、也不含公告原文**（原文留在 fd-sentiment 的下载谱系里），适配器如实映射、不造数，故 pack.yaml `kinds: [fact]`、暂无 `indicator`。

## 确定性 checker（`checks.py`，import 即注册）

| checker | 契约语义 | 出处 |
|---|---|---|
| `band-vocabulary` | `expected_band` ∈ 五档词表 | fd-data-quality 值域校验 |
| `band-direction-consistency` | `direction` ∈ 方向词表且与档位推出的方向一致（声明值互相对账） | dashboards finalize 对账判据 |
| `text-fingerprint-sha256` | `text_sha256` 为 64 位小写十六进制 | fd-data-quality 格式校验 |
| `text-chars-positive` | `text_chars` 为正整数（文本非空非占位锚点） | fd-data-quality 契约 |
| `doc-id-identity` | `attrs.doc_id` 非空且等于 upsert 键 `external_key` | fd-data-quality 键一致 |
| `as-of-iso-date` | `as_of` 为可解析 ISO 日期 | fd-data-quality 格式校验 |
| `amount-anchor-parseable` | 如有金额字段（`amount_yi`）必须可解析为数值或 None（gold-v9 无此字段，当前全为 None-通过；钉住未来扩展的契约） | fd-data-quality 契约 |

`run_data_eval(conn, kind="fact", ...)` 逐单元跑全部 checker，落 `channel='data'` 的 `eval_runs`（`rubric_name='data-checks:fact'`）与逐 checker 的 criteria 行。

## 数据 QA 金集（首批题目）

`checks.build_data_qa_goldset(records)` 把 dashboards `finalize` 的对账判据改写成结构化题目：每题针对某条 fact（`unit_key` = doc_id），带

- `field` / `expected`——期望检查点，取值全部来自实际加载到的 gold-v9 真值（档位、方向、指纹、长度锚点）；
- `judge`——判定函数引用名（`checks.JUDGE_FUNCS` 中可执行：`band-equals` / `direction-equals` / `text-fingerprint-format` / `text-chars-equals`）。

首批生成规则：每个出现过的档位一题、每个出现过的方向一题、首条样本的指纹格式与长度锚点各一题（gold-v9 上共 10 题）；生成完全确定，可重复。

## 测试

`tests/test_finance_data_pack.py`：monkeypatch `FD_SENTIMENT_REPO` 指向真实兄弟仓（存在即用真数据，105 条）；另用 `tests/fixtures/finance/broken-gold/` 的**残缺文件**（非金标数据，仅用于错误路径）验证「加载失败如实抛错」。注意：若本机没有 `<workspace>/fd-sentiment`，依赖真实金标的用例会 skip——这是有意的：本包不复制数据文件，也就不在仓内编造假金标。
