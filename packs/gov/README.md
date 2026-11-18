# gov — 政务数据域包（数据/元数据重、文本可选）

平台第三个域包（OpenSpec change `add-knowledge-bench-platform`，P1 任务 4.4）。
定位：**纯确定性数据校验包**——把政务公文爬虫的 registry 元数据当作可对账的
fact 集，走 `src/bench/data_checks.py` 的 data 通道（channel='data'，
judge_model='deterministic'），**零 LLM、零判官、零网络**，与判官校准
（gold_judge / calibration）完全无关；pack.yaml 不声明 `gold_judge`。

## 资产来源（兄弟仓只读，一字节不改、不复制进本仓）

- 源仓：`/Users/chengsishi/finddata/fd-cn-gov`（公文爬虫/registry；可经环境
  变量 `FD_GOV_REPO` 覆盖路径，`adapters.py` 每次调用重读）。
- 数据文件（已核实存在，2026-11-03）：
  `fd_cn_gov/registry/registry.json`，四个 section 的真实条数：

  | section | 条数 | 内容 |
  |---|---|---|
  | `sources` | 11 | 公文目录抓取源（id/name/label/url/category/category_label/description/config） |
  | `datasource_columns` | 57 | 列 schema（table_name/column_name/column_type/is_primary_key/is_nullable/source_field/semantic_type/unit/description） |
  | `scraw_configs` | 11 | 抓取配置（与 sources 按 name+url 1:1 配对） |
  | `organizations` | 11 | 主办机关（code/name_zh/name_en/metadata{type,url}） |

- **如实说明（重要）**：任务背景预期「区域/日期/标题/类别/文号」的公文目录
  fact 集；盘上的 registry.json 实为**源注册表**（爬哪些机关档案、按什么列
  schema 爬），title/date/文号只是**列定义**（如
  `{"column_name":"date","column_type":"date","semantic_type":"date"}`），
  **没有逐件公文的实例与正文**。因此：
  - 一个抓取源 = 一个 `kind='gov-fact'` 知识单元（11 条入库）；
  - `external_key` 用文内真实稳定键 `sources.name`（如 `mee_gsgg_archive`，
    已验证 11 源唯一），未用组合键；
  - `body` = 源 label/description 文本（registry 无正文，README 如实记录）；
  - `tier='silver'`：官方目录元数据 + 机器可对账事实，未经人工逐条核验，
    不夸大为 gold。
- 同目录另有 `registry.db`（SQLite），是同一 registry 的镜像（sources 11 /
  datasource_columns 57 / scraw_configs 11 三表）；v1 只读 JSON 通道。

## KG 车道验收判据迁移状态

判据脚本**已找到、真实存在**（不在 fd-legal-kg，而在 **fd-text-core**——
任务记忆的偏差如下，附证据路径）：

- `/Users/chengsishi/finddata/fd-text-core/scripts/kg_graph_checks.py`：四条
  硬判据——①「法规名+条号」分裂节点清零、②同名不同文号实体可分（113/71
  口径）、③规模统计（节点/边/条级属性）、④脏文号（重复机关名）清零。
- 配套判据实现：`/Users/chengsishi/finddata/fd-text-core/scripts/kg_statute_repair_names.py`
  的 `is_dirty_name`（文号形态 `第N号` 卡口 + 机关名归一对账）。
- `fd-legal-kg` 本体（非图判据）：`fd_legal_kg/ontology.py` 是 7 类实体的
  schema 约束；`fd_legal_kg/evalrunner.py` 是双口径人工评阅跑分器（网络 +
  人工 verdict），均非确定性验收闸。

**迁移方式（v1，降级实现）**：原脚本连 FalkorDB 图查询（网络依赖，本平台
离线不可跑），故提炼其**确定性判据语义**，落到对 registry「元数据图」
（sources→datasource_columns / organizations / scraw_configs 的引用关系）的
逐单元对账 checker（`checks.py`）：

| 原 KG 判据 | gov v1 迁移对应 |
|---|---|
| ① 分裂节点清零 | `identity-format`（external_key==source_name、snake_case、`_archive` 后缀、正 id、非占位 label/description） |
| ② 同名不同文号可分 | **不迁移**：registry 无文号实例，无可比对对象（如实略过，不造假） |
| ③ 规模统计/覆盖度 | `column-coverage`（声明列数==实际列数、列名源内唯一、类型/语义/可空性落在受控词表）、`primary-key-exists`（每源恰一主键）、`date-anchor-present`（每源必声明 date 列） |
| ④ 脏值清零 | `category-vocabulary`、`organization-binding`（机关 code 大写且源名以 `<code>_` 起头）、`scraw-pairing`（抓取配置 name+url 与源对账一致）、`url-https-format` |

加载器（`adapters.py`）另做**文件完整性级**引用可解检查：列行的
`datasource_id` 必须指向真实源、`table_name` 必须等于源名，悬空引用直接
`ValueError` 拒绝整文件（不是静默丢行）——这是判据①「清零」的另一半。

## kinds / checkers 清单（import `packs.gov.checks` 即注册，kind='gov-fact'）

`identity-format`、`url-https-format`、`category-vocabulary`、
`organization-binding`、`column-coverage`、`primary-key-exists`、
`date-anchor-present`、`scraw-pairing` —— 8 个纯确定性 checker。

## zhengxin（fd-zhengxin）接入状态：未接入（如实）

盘上核实：`/Users/chengsishi/finddata/fd-zhengxin` 是 API 服务仓
（`server/fd_zhengxin_api`），V-Dem/MARPOR 只出现在
`reference_mcp.py` / `locate.py` 对**远程 MCP 端点**
（`FDZX__REFERENCE_BASE_URL`）的调用注释里，**没有任何可只读加载的本地指标
数据文件**。按「不为凑数造假数据、零网络」约束，v1 不做 zhengxin kind。

## 用法

```python
from packs.gov import adapters, checks  # checks import 即注册 checker
adapters.load_gov_registry(conn)        # 只读加载 11 源，幂等可重跑
from src.bench.data_checks import run_data_eval
run_data_eval(conn, kind="gov-fact", db_path=conn)  # 落 channel='data' 汇总 + 逐 checker criteria
```

测试：`uv run pytest tests/test_gov_pack.py -q -m "not external"`
（真实 sibling 数据优先；sibling 仓缺失时真实数据用例 skip，不造假）。
