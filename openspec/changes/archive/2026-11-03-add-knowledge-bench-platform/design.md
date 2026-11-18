## Context

仓内现状（盘上实证）：内核六原语已存在且经 V4 全量评测实战——语料库（标签+三级溯源+审核工作流）、标签驱动组装、rubric×criteria 多 judge 评测（限流永不污染 verdict）、LangGraph 自愈管线、盲标注/一致性/gold 导出、微调飞轮（gold/silver/bronze/raw 四层互斥 + `assert_not_ground_truth` 单点守卫 + 判官先于起草的 D4 闸门）。领域专有物集中在：`data/clause_seeds`、`src/law_catalog`、`src/eval` 中的法律引用组件、rubric/提示词种子。

外部约束：fd-wire entity-layer spec 明文「不做全量本体」，本体深化无主；生态评测资产散落五仓且坏过（fd-sentiment 两把尺子先后失效）；law-bench 为 MIT 公开仓（github FindDataTechnology/law-bench），内部仓 law-bench-internal 已存在；现行判官 all_pass 仅 31% 且 `docs/evaluation-system.md` 自认结构性误读；`PRODUCT.md` 载明当前用户假设为 solo operator。

仓库合流前提（已定案）：正身为本地 10-31 拷贝（HEAD bc09c01，gitee 公开线，origin 干净）；SMB 拷贝（law-bench-server，HEAD 2f3125e）降级为资产供体——其 `.git/config` 内嵌 gitee 明文 token，挑入资产必须走白名单，凭据类文件（`.env`、`ssh-config.json`、任何 config/密钥）永不入公共仓。

## Goals / Non-Goals

**Goals:**
- 内核/域包分离：内核零领域命中（CI 断言），法律垂类成为第一个域包，新增领域不改内核
- 双通道评测共用 run/compare/trend/复核机器；数据通道确定性、永不调 judge
- 与 wire 的单向升格 + 带档回写契约；wire 主键源，无双主
- 尺子单一真源：生态散落评测资产分批迁入为域包 eval-suite；meta-eval 常态化
- 开源切分 fail-closed（CI 泄露扫描）

**Non-Goals:**
- 不吞并 wire 的图谱存储与 KG 车道（FalkorDB 留原位，知验台消费快照与判据）
- 不重写 wire 服务台/控制台客户面展示
- 不做通用本体推理引擎（沉淀以审核流 + 引用可核为准，不引入图谱推理框架）
- 不一次性迁移所有评测资产（按域包分批，每批独立 change）
- 不在本变更内做多角色 RBAC 重做（P2 前内部团队使用，单列后续 change）

## Decisions

**D1 · 原地演进，不另起新仓。** 六件内核原语已实战验证，另起仓等于重写已对的机器。备选（新仓重建）被否：迁移成本高且丢失 V4 评测史的可追溯性。验收闸：泛化重构以「法律垂类既有测试逐字节等价通过」为硬判据，不达不合入。

**D2 · 双通道评测。** 文本通道复用现行 judge 机器；数据通道为确定性校验器注册表（域包声明行数/期数/对账/漂移/基线检查），与文本共用 run/compare/trend 但每条记录如实标注通道。备选（统一 LLM 通道评数据）被否：数据正确性不容模型幻觉，「限流不得污染 verdict」的既有纪律延伸为「数据通道永不调 judge」。数据 QA 金集为本通道旗舰载体：题目绑定真实数据集与期望结果，评「AI 是否把数读对」。

**D3 · 工厂/柜台分工。** wire 是供给与服务台（柜台），知验台是知识工厂与质检站。实体升格 = 单向拉取 wire 声明 → 机器预标注（bronze）→ 人工核验（gold）→ 带档回写（sensitivity/tier 供 ACL 与舰队消费）。备选（本体迁入知验台统一存储）被否：wire 的实体身份与数据集绑定是其控制台与引擎的运行时依赖，双写必漂移；wire 保持主键源，知验台身份键全量引用 wire。

**D4 · 域包形态照识律 pack 内核模式。** 域包 = 声明文件（kind 集/适配器/rubric 包/eval-suite/校验器）+ 资产目录。该模式在 lex 已实证「改一条红线只改一处、加领域不动内核」。内核领域无关以 CI 断言固化（内核源码树检索领域常量零命中）。

**D5 · 开源切分 fail-closed。** 公共仓=内核+域包接口+法律域包；内部仓=柏讯连接器+内部语料+gold 集+客户数据。CI 泄露扫描（内部路径引用/凭据形态/客户样本 → 构建失败不产镜像）。donor 资产白名单制：SMB 拷贝中仅 `contracts/`、`paper/`、README 差异经审挑入，一律不整目录搬运。

**D6 · 资源投向。** 不限量资源的最优去向是人力与标注而非算力：①gold 标注吞吐（复核是飞轮唯一瓶颈）；②judge 校准实验（盲标一致性、置信分档加权——fd-sentiment 已验证「置信≥0.70 可加权」方法论）；③域包工程（数据接入+rubric 工程+QA 金集构造，是边界清晰可并行的单元）。

## Risks / Trade-offs

- [判官不可信（31% all_pass、结构性误读）] → meta-eval 先行且 spec 已硬约束「未校准 judge 不得作 gold 信号源」；修结构性误读列为 P1 硬任务，先于任何域包宣称 gold 产出
- [泛化面回归] → 零行为回归闸 + 单 PR 串行合入（可整体 revert）+ 既有断言口径不得改动
- [开源切分遗漏] → CI 泄露扫描 fail-closed + donor 白名单 + 合流时逐文件审查（不整目录拷贝）
- [双主漂移] → wire 主键源、知验台零身份存储、回写幂等键 = wire 实体键、回写失败不误标成功
- [数据 QA 金集构造成本高] → 起步从 dashboards 既有对账/finalize 判据与 fd-data-quality baselines 改写，不全量新造
- [多角色需求低估] → P2 前限内部团队；复核流水线小队化单列 change

## Migration Plan

1. **P0 合流**：donor 白名单挑入（contracts/、paper/、README 差异）→ 提交正身仓
2. **P0 内核抽取**：`kind` 字段幂等加列（可空回填，回滚无破坏）→ clause 泛化为知识单元 → `law_catalog`/种子迁入 `packs/legal` → 全量测试逐字节等价闸
3. **P0 开源切分**：内部仓承接内部资产 → 公共仓瘦身 → CI 泄露扫描上线 → 走既有 Gitee → Jenkins → Harbor → ArgoCD 链发布
4. **P1–P3**：政务包、金融数据包、wire 贯通、尺子迁移在本 change 内按阶段任务组推进；若单 change 过于庞大，可拆分继承本 spec 的子 change（tasks.md 相应迁移勾选）
5. **回滚策略**：P0 每步单 PR；回归闸未过即整体 revert；schema 变更全部幂等可空，无破坏性迁移

## Open Questions

- 条线对外名称（「知验台」为内部代号，对外命名待定）
- law-bench-internal 的远端归属与访问控制细节（gitee/github、成员面）
- P1 两域包（政务 / 金融数据）的实施先后序（并行可调，不影响设计）
