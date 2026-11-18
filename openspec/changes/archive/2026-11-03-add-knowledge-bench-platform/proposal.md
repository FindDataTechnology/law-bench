## Why

寻数生态的评测尺子散落在五六个仓（fd-sentiment 的 gold/打分尺、fd-text-core 的检索评测、KG 车道验收判据、dashboards 的 finalize 闸门、fd-data-quality baselines），各仓的尺子都坏过且无人统一看护；柏讯（fd-wire）的 entity-layer spec 已明文「不做全量本体」，本体知识的沉淀、质检与展示处于无主状态。law-bench 仓内实际已存在一个领域无关的内核（语料库 → 组装 → rubric 评测 → 自愈 → 人工复核 → 微调飞轮），只是以法律垂类的面貌存在。把它原地演进为全域「知识沉淀 × 评测」平台（条线代号：知验台），是得到单一尺子源与知识工厂成本最低、且已被实战验证过的路径。

## What Changes

- **内核泛化**：`clause` 泛化为带 `kind` 的知识单元（clause/entity/relation/fact/indicator/qa-pair/answer…），rubric 评测引擎去法律化，`law_catalog` 降级为法律域包组件。承诺法律垂类**零行为回归**（全部既有测试逐字节等价通过）。
- **域包机制**：新增 domain-pack 插拔接口（内核/领域卡分离，照识律 pack 内核已验证的模式）；法律垂类重构为第一个域包。
- **双通道评测**：文本对象走 LLM-judge × rubric + 人工 gold；数据对象走确定性校验器（对账/基线/漂移）+ 数据 QA 金集（真实数据集构造问答，评「AI 是否把数读对」）；两通道共用 run/compare/trend 机器。
- **柏讯双向契约**：wire 实体/关系声明进入知验台审核流升格（raw→bronze→silver→gold），gold 回写带 `sensitivity`/`tier` 标记喂 ACL 与舰队；wire 是实体主键源，知验台不另存一份本体。
- **meta-eval**：judge 对 gold 的校准度量、尺子漂移检测常态化；第一个校准对象是仓内 all_pass 仅 31% 的现行判官。
- **开源切分**：公共仓保留内核 + 法律域包 + 域包接口；内部域包（柏讯连接器、内部语料、客户数据）进 law-bench-internal。公共仓 CI 加资产泄露扫描。
- 分阶段实施：P0 合流与奠基（两分支归一、内核抽取、开源切分）→ P1 双域验证（政务包、金融数据包）→ P2 柏讯贯通 → P3 全生态秤（迁移散落尺子、微调飞轮喂各线）。

## Capabilities

### New Capabilities

- `bench-platform`: 知验台内核与域包机制——知识单元类型化与溯源四层（gold/silver/bronze/raw 互斥 + 机器自评永不为真值守卫）、域包插拔接口、双通道评测（文本 judge 通道 + 数据确定性通道）、meta-eval（judge 校准与尺子漂移）、柏讯实体升格与回写契约、开源切分边界。

### Modified Capabilities

（无——本变更对既有能力承诺零行为回归；既有 spec 的需求面不改动，P0 重构以「既有测试逐字节等价」为验收闸。）

## Impact

- **代码**：`src/clauses`、`src/eval`、`src/contracts`、`src/law_catalog`、`src/web`、`fd-coding-law-bench-mcp`（37 工具面只增不减）；新增 `src/bench`（内核）与 `packs/`（域包目录）。
- **仓库**：公共仓边界收缩（内核 + 法律域包开源），law-bench-internal 承接内部域包与柏讯连接器；CI 新增泄露扫描。
- **外部接口**：读 fd-wire entity-layer API（实体/关系声明）；消费 fd-data-quality baselines、fd-sentiment gold 数据集；Postgres schema 幂等扩展（知识单元 kind、升格状态、QA 金集表）。
- **不破坏**：公共只读 API、MCP 工具面、Web 工作台对现有用户的行为；`*.finddatatech.cloud` 部署链（Gitee → Jenkins → Harbor → ArgoCD）不变。
