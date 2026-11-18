# text-retrieval 域包

文本检索评测域包（**数据重、尺子重**）：迁入 fd-text-core 引擎级检索评测尺——标注查询集契约（二值 + 分级相关性 qrels 两形态）、nDCG@k / hit@k / MRR 纯函数跑分器、双指纹（数据集指纹 + 配置指纹）趋势机与跨次回归判定。指标层零 LLM、零网络、零 embedding 调用。

## 与 fd-text-core 原尺子的关系

**迁入 ≠ 取代：等价复核完成前，fd-text-core 原仓尺子仍为真源。** 本包把契约与跑分逻辑逐行迁入为包内实现（运行时 **不 import** `fd_text_core` 任何代码，零跨仓代码依赖）；标注集**正文数据不复制进本仓**（`adapters.py` 的默认目录常量只作只读路径引用，可用 `FD_TEXT_CORE_DATASETS_DIR`/`FD_TEXT_CORE_REPO` 环境变量或显式 `datasets_dir=` 参数覆盖，机器上没有原仓时显式传目录即可，默认不依赖）。迁入即单一真源——原仓为其**历史真源，直至其入口 deprecation**；本仓 `tests/test_retrieval_eval.py` 的等价双跑（见下）给出零漂移证据。

## 真源资产（只读，一字节不改）

| 原仓文件（`/Users/chengsishi/finddata/fd-text-core/`） | 内容 | 本包对应物 |
|---|---|---|
| `fd_text_core/eval/dataset.py` | 标注查询集契约：`Grade`/`Query`（二值 `expect_doc_id` 与分级 `expect` 两形态并存）、`Dataset`、`DatasetError`（缺 `why`/缺 `_provenance.how_targets_chosen` 即拒绝）、**数据集指纹 = 文件字节 sha256 前 16 位** | `adapters.py`（逐条同校验语义；`datasets_dir` 由硬编码改为可注入） |
| `fd_text_core/eval/runner.py` | **nDCG@k**（2^g−1 增益、按 document_id 去重保首现、IDCG=0 返 0）、hit@k/MRR 聚合、`EvalReport`（`saturated`/`hybrid_not_worse` 判定）、**配置指纹**（embedding 模型/维度/provider/rrf_k/融合权重 + 垂域切块策略段）、`compare_with_previous`（两指纹+k+variant 全同才判回归，任一不同即 `not_comparable`） | `scorer.py`（逐行照迁；检索后端由 `search` 回调注入——注入点即原件调 `querylib.hybrid_search` 处，度量与被度量同路径的 design D5 精神不变） |
| `fd_text_core/eval/store.py` | 落库与趋势：`store_run`（写原仓 `eval_runs`）、`latest_previous`（按域+variant 隔离）、`check_expects_exist`（在库校验） | `scorer.py` 落库腿（law-bench 形态：照 `src/bench/calibration.run_calibration` 风格写通用 `eval_runs`——`channel='data'`（确定性通道）、`unit_kind='retrieval'`、双指纹/k/variant 以机器可读片段入 summary、每通道一条 criteria 诊断行；读回腿还原成原件 `compare_with_previous` 的 previous 行形态，趋势判定跑同一个纯函数） |
| `fd_text_core/migrations/versions/0006_eval_runs.py`、`0008_eval_ndcg_variant.py` | 原表 DDL：双指纹列、nDCG 三列、variant 隔离（守门集/难题集不可互比） | 语义由本平台 `eval_runs` 通用列承接（`variant_label`、summary 片段）；原 DDL 只读引用 |
| `fd_text_core/eval/datasets/{gov,papers,screenplay}/` | 真实标注集（gov 另有 `hard` 分级难题集：18 条全分级 qrels） | **不复制**——等价双跑只读取用；缺失时相应用例 skip（有意的：不造数据） |

## 指标是纯函数吗——是

给定 ranked 文档 id 序列 + qrels（`Grade` 元组）即出分：`ndcg_at_k`、hit@k/MRR 聚合、两个指纹函数、`compare_with_previous` 全部无 IO、无网络。唯一非纯的腿是原件 `run_eval` 内部对 `querylib.hybrid_search` 的检索调用（需要被测引擎）与 `store.py` 的 SQL 腿——迁入形态把检索调用改为注入、把 SQL 腿改接本平台表。

## 双指纹是什么——照实迁入

1. **数据集指纹**：标注集 JSON **文件字节**的 sha256 前 16 位（格式/缩进变化也算变——宁可多报「不可直接比较」不漏报，原仓 design D3）。
2. **配置指纹**：影响检索结果的引擎侧配置摘要的 sha256 前 16 位——`embedding_model`/`embedding_dim`/`provider_only`/`rrf_k`/`rrf_w_keyword`/`rrf_w_vec`（环境变量，默认值同原件）+ 垂域段（strategy 类名、strategy_params、cjk/t2s/tsv_config；无垂域注册信息时 `strategy=<unregistered>`，同原件 KeyError 分支）。
   趋势机判回归的门槛：**两指纹 + k + variant 全同**才可比；任一不同即明确输出「不可直接比较」并点名变化项，绝不静默比较两个不可比数字。

## kind / eval_suites 说明（如实）

- `kinds: [retrieval-query]`——迁入的评测对象是「带分级相关性标注的检索查询」；本包**不**把标注集灌入 `knowledge_units`（正文数据留在原仓/fixture，灌库属后续任务，不在 6.1 的迁入范围，不做的事不假称做了）。
- `eval_suites: [text-retrieval-ndcg]`——落库腿的 `rubric_name` 前缀即此 suite id（`text-retrieval-ndcg:<domain>`）。

## 等价双跑做到哪一层（tests/test_retrieval_eval.py）

**做到了：跑分链全层（指标函数 + 契约解析 + 聚合 + 双指纹 + 趋势判定）逐值零漂移**——用 importlib 以独立包名 `fdtext_legacy` 加载**未经修改的**原仓 `dataset.py`/`runner.py`（不触发原包 `__init__`——其 import 链要 `psycopg_pool`，本机 law-bench 环境没有），在同一进程内对同一输入双跑断言逐值相等：

- 数据集指纹：4 份真实标注集（含 gov `hard` 分级集）逐文件相等；
- 契约解析：真实集加载后逐条查询/分级/口径字段相等；
- `ndcg_at_k`：真实 qrels × 确定性排列的 ranked 结果（含切块重复、截断、k 边界、空标注）逐 case float 相等；
- `run_eval` 全链：检索后端以**同一个确定性 stub** 注入两侧（含 chunk 重复、degraded 收集、`check_expects` 回调），`to_dict()` 整份相等；
- 配置指纹：`<unregistered>` 分支与注入同一 vertical 描述符两种形态、以及改环境参数后，两侧相等且随 env 联动；
- `compare_with_previous`：no_baseline / not_comparable（标注集/配置/k/variant 变化）/ regression / ok 各场景输出相等。

**没做到双跑的腿（如实记录，原因）**：
- **真实检索执行**（原件 `querylib.hybrid_search`）：需 fd-text-core 的 PG（含 pgvector/tsvector 语料）+ S3 + 嵌入凭据，本环境没有其库——所以「旧址最后一次真实语料跑分数字」无法在本机复现比对；本双跑比的是**尺子本身**（同一检索输出喂两把尺子逐值相等），不是比历史数字。
- 原件 `store.check_expects_exist` / `store_run`（读写原仓 `eval_runs` 专表）：同上需原仓 PG；本平台落库腿改用通用 `eval_runs` 表（写法照 calibration），其正确性由本仓落库-读回测试自证，不构成对原件的「复刻实现」（读回后喂回原件同款 `compare_with_previous` 纯函数判趋势）。
- `scripts/eval_retrieval.py` 的 CLI 壳：进程级脚本，迁入的是其调用的库层逻辑。

## 测试

- `tests/test_retrieval_eval.py`：`validate_pack` 过闸；上述等价双跑（原仓缺失时相应 skip——不造数）；趋势落库腿（合成集 `tests/fixtures/retrieval/datasets/textdemo/` + 确定性 ranked fixture `tests/fixtures/retrieval/ranked/`）：同数据集跑两次 → `eval_runs` 两行（`channel='data'`、`unit_kind='retrieval'`、双指纹入 summary、variant 隔离）→ 读回「上次」判趋势 `ok`；改 k 再跑 → `not_comparable` 且趋势仍可查。
