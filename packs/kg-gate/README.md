# kg-gate — KG 车道验收判据 + 市场发布门（迁入版）

两类散落在生态里的「尺子」收拢为一个域包、两条 eval-suite：

- `kg-lane-acceptance` — KG 车道四条硬判据，吃**导入的图快照单元**（kind
  `graph-snapshot`）；
- `market-publish-gate` — 谦面 pack 发布门的判定内核，吃**发布规则输入单元**
  （kind `publish-rule`）。

零 LLM、零网络；兄弟仓只读引用、零复制正文数据。

## 真源（read-only）

| 迁移件 | 真源路径 |
|---|---|
| 判据①③④ 与判据②读数 | `<workspace>/fd-text-core/scripts/kg_graph_checks.py`（注意：**在 fd-text-core，不在 fd-legal-kg**；fd-legal-kg 无同名脚本，与 packs/gov 的勘察结论一致） |
| 判据④ 脏文号判读 | `<workspace>/fd-text-core/scripts/kg_statute_repair_names.py`（`is_dirty_name`/`docno_of`） |
| 判据② 语义文档 | `<workspace>/fd-text-core/fd_text_core/kg_lane/merge.py`（`normalize_docno_issuer`、`split_doc_number` 的 113/71 教训） |
| 发布门主判定 | `paas/lib/publish-tool-gate.js`（`toolGateErrors`/`declaredToolsByServer`/`toolFaceErrors`/`toolClosureErrors`/`namedMcpTools`） |
| registry 条目→serverInfo 映射 | `paas/registry-bridge.js`（`toolListNames`、`metadata.surface.commercial_tools`/`tools_commercial` 双字段） |
| 商业名单推导 | `<workspace>/scripts/export_surface_commercial.py::commercial_tools`（tool-surface manifest → 名集；分组级与工具级 level alike） |
| 闭合契约文字 | finddata `openspec/changes/archive/2026-10-11-pack-publish-surface-closure/`；`fd-wire/docs/registry-tool-snapshot-longterm.md` §十（发布门先判商业闭包、后判存在性） |

同址旁证：`fd-text-core/fd_text_core/kg_lane/eval.py` 是 KG 车道的**双口径
价值评测**（temporal/multihop 题 vs MCP 基线，逐题留人工 verdict 位），依赖
live MCP 服务与 KG 查询函数，且判定本质是人工评阅——不属于确定性数据通道，
**不迁移**（本包只迁 kg_graph_checks 的图 schema 判据）。

## KG 四条硬判据：算法要点与可离线边界

原脚本 `check_graph(db, gid)` 先连 FalkorDB 分页拉全部节点名
（`_all_names`：每页 5000、`ORDER BY n.uuid SKIP/LIMIT`——FalkorDB
resultset_size 默认 10000，单发查询会被静默截断，判据①④会只查前一万个节点
却报 PASS），再数边、数 law_id 节点。四条判据的确定性算法：

1. **判据① 条级分裂节点清零**：`_ARTICLE = 第[0-9零一二三四五六七八九十百千]+条(之[一二三四五六七八九十]+)?$`
   且条号前的前缀以 `_SUFFIX = (法,法典,条例,规定,办法,细则,解释,决定,通知,批复)` 之一结尾
   → 该节点是「法规名+条号」分裂节点（条级不入图 schema）。真源逐行移植。
2. **判据② 同名不同文号可分（113/71 口径）**：live 脚本只**打印**
   「行政单位财务规则*」节点组读数，不产布尔。布尔语义按 merge.py
   `split_doc_number` docstring 文档化为确定性判据：以「剥书名号 + 去括号
   文号 + NFKC 去空白」后的同名基分组，组内 ≥2 节点时要求全名两两不同、
   每个成员带自己的括号文号、文号互异（违反 = 同名实体被当成同一个/坍缩
   重复，即 113 号施行日挂到 71 号那类事故的 schema 形态）。这一**解释**
   是本包落的判读口径，不是原脚本 exit code 的一部分——如实声明。
3. **判据③ 规模统计**：nodes/edges/statute_layer_nodes（law_id 非空者）
   枚举重算 + 条级属性覆盖读数（statute 层中带 `article_no` 属性者）；
   迁入版把「声明数 vs 重算数一致」作为快照完整性判据（live 版只读回、
   不对账——对账是迁入版的加严）。
4. **判据④ 脏文号清零**：`docno_of`（名字末尾括号内容）先过
   `_DOCNO_LIKE = 第\s*[0-9〇零一二三四五六七八九十百]+\s*号` 形态闸门
   （防「(附:…)」合法附注被削成半句，实测误判 1 例），再
   `normalize_docno_issuer(dn) != dn`（「财政部中华人民共和国财政部令第71号」
   类重复机关名 → 取最后一次「中华人民共和国」起后缀；容忍缺字形「华人民
   共和国」；幂等）。真源逐行移植。

**可离线/需 live 的切分**：判据算法全部确定性、吃快照即可跑；live 部分是
「从 FalkorDB 分页枚举节点名/边数/law_id 计数」——原脚本需要活图库
（host/port + LEXKG_FALKORDB_* 凭据），迁入版**吃快照不吃图**。脏文号**修复**
执行（`kg_statute_repair_names.py` 的 DETACH DELETE + 重建图 + 嵌入）需
PG + FalkorDB + embedder，不在本包（只迁其判读函数）。

**快照来源如实报告**：fd-text-core / fd-legal-kg 全仓 grep
`split_article_nodes`/`*checks*.json`/`*snapshot*.json` 均无已导出的真实图
统计 JSON（判据输出走 `--json-out` 到临时路径，未入库）。因此
`tests/fixtures/kg/*-synthetic.json` 三张快照是**合成的最小图**（正例 +
判据①④反例 + 判据②反例），节点名/文号/law_id 全为构造值，文件自带
`"source": "synthetic"` 声明；它们证明判据能正确裁决真/假形态，**不代表
任何真实图的健康度**。真实图上线后，同 schema 的快照可由原仓
`kg_graph_checks.py --json-out` 扩展产出后直接导入（kind/判据不变）。

## 市场发布门：真实判定逻辑与离线边界

真实发布门（paas `gateway/packs.js` 发布路由）的消费序列：
`toolFaceErrors`（每个 mcpServers 引用必须非空 allowTools 或
fullSurface+reason）→ `toolClosureErrors`（技能正文点名的
`mcp__<server>__<tool>` 必须落在该引用 allowTools 内）→
`toolGateErrors(manifest, serverInfo, {probe})`——**先商业闭包**：声明的
每个工具叶名（pack 级 allowTools ∪ 各角色 resources.mcpTools）必须 ⊆ 该
registry 条目 `metadata.surface.commercial_tools` 名单，越界即拒（`continue`，
与探活结果无关）；条目是 pre-enrichment 计数形态（只有 `tools_commercial`、
无名集）时**跳过闭包并记 observable note，不猜测**；非 registry 条目
（local-binding 引用）豁免。**后存在性**：对 `tool_list` 快照缺名时做一次
有界 live probe（快照滞后兜底，business-mcp 9/24 教训），probe 不可用时
拒绝但措辞是「unresolved rather than absent」并给出重报/刷新快照的可操作
指引——绝不把「探不到」说成「不存在」。

**可离线内核**：以上全部除两处运行时依赖外都是纯函数——迁入
`packs/kg-gate/checks.py`：`declared_tools_by_server`、
`named_mcp_tools`、`tool_face_errors`、`tool_closure_errors`、
`tool_gate_errors`（probe 缺席分支，错误/便签文案与真实 JS **逐字一致**）、
`server_info_from_entry`（registry-bridge 双字段映射 + counts-only 哨兵
合成）、`commercial_tools`（export_surface_commercial 的名单推导）。

**Deferred（如实标注，不造假）**：

1. `registryServerIndex` 的 `/api/servers` 活栈 fetch（网络 + registry
   运行时）——迁入版吃 fixture 里的 registry_index 快照；
2. `probeMcpToolNames` 的 live MCP tools/list 探活（网络）——迁入版永远走
   真实门的 probe 缺席分支，存在性缺名得到真实门同款「unresolved」拒文，
   不会得到「live 确认存在」的放行；**这是迁入版比真实门更严的一处，
   已如实标注**；
3. `export_surface_commercial.py` 的写入端（registry PATCH）——只迁推导。

**双跑零漂移**：`tests/test_kg_gate.py::TestGateDualRun` 在 node 可用且
`<workspace>/paas/lib/publish-tool-gate.js` 可读时，对同一组
(manifest, index) 输入同时跑真实 JS 门（`toolGateErrors(m, serverInfo, {})`，
无 probe、零网络）与本包 Python 内核，逐字段比对 errors/notes（含文案）
与三个纯函数的返回结构，断言零漂移；node 或 paas 仓缺席时如实 skip。

**live 双跑收账（2026-11-05，close-wire-real-loop 6.x）**：对生产 registry
真实条目（29 条，只读拉取）双跑——6 例聚焦（真实闭包合法/越界/counts-only
哨兵/无 surface/本地引用豁免/存在性缺名）+ 61 例全域扫（29 条目×各自变体）
**全部逐字段 AGREE**。此前 add-knowledge-bench-platform 6.2 的
NOT EQUIVALENT 定谳为 fixture 假象：registry 未 seed 真实条目时原 JS 对
index 缺席条目放行、内核 fail-closed；真实数据下两侧行为一致。裁决：内核
保留 fail-closed 加严语义（比原门更严的一处维持如实标注），零漂移以
`evidence/2026-11-05-publish-gate-dualrun.json` 实证收账。

## 与 packs/gov 的关系（防重复计数）

`packs/gov/checks.py` 的模块 docstring 已把 KG 四判据**降级**迁移为政务
registry「元数据图」的逐单元对账（①→identity-format、③→column-coverage/
primary-key/date-anchor、④→category-vocabulary/organization-binding/
scraw-pairing；② 明确略过——registry 无文号实例）。本包是**另一条腿**：
对真实图形态（节点名清单快照）跑原判据语义的完整四条，kind、namespace、
单元、eval-suite 全部独立，与 gov 的 `gov-registry-consistency` 不重叠、
不互相计数。引用而不复制：gov 的降级判据保持原样，本包不重新解释它。

## 单元与 checker 清单

kind `graph-snapshot`（namespace `kg-gate`，external_key=快照 `graph` 名）：
`split-article-zero`（①）、`same-name-diff-docno-separable`（②）、
`scale-stats-consistent`（③）、`dirty-docno-zero`（④）。

kind `publish-rule`（external_key=用例 `case` 名）：`commercial-closure`
（闭包腿独立投影）、`tool-declaration-gate`（face ∪ closure ∪ 门全序列）。

fixture 6 份：3 图快照（clean / ①④ drift / ② collapsed）+ 3 发布规则
（clean / internal 越界 / counts-only）。反例的存在性腿缺失与
local-binding 豁免场景在测试里由 clean 单元变异构造（同 fixture schema）。

`run_data_eval(conn, kind=..., db_path=conn)` 聚合落
`eval_runs(channel='data', unit_kind=kind, judge_model='deterministic')` +
每条 (unit, checker) 一行 criteria——clean 单元全 PASS、合成反例单元如实
FAIL（score/max 记进聚合行，不做「洗绿」）。

## 跑法

```bash
cd <workspace>/law-bench
uv run pytest tests/test_kg_gate.py -q -m "not external"
```
