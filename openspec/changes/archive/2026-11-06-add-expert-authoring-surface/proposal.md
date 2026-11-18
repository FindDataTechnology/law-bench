# 提案：专家创作与维护面（C2，P0/P1）

## Why

C1 落了模板与领域工作区，但平台还只有「组织面」（谁能进哪个域）没有「生产面」——领域专家进域后没有任何创作/维护本体的界面，本体内容只能靠脚本直插。总纲（`docs/knowledge-platform-blueprint.md`）明确「专家创作与持续维护」是平台的生产方式与成立前提；P1 柏讯域包全链（专家维护→发布→wire 拉取）也以此为前置。本 change 把创作台补上，让「邀请专家进域」到「专家真的在维护本体」闭环。

## What Changes

- **模板实例化创作台**：领域专家/负责人在成员域内按模板词表创作与维护本体知识单元（实体/概念/关系），写面走内核既有 KU 收口（`namespace`=域 key 实现域隔离，不新增身份存储）。
- **词表执法**：实体 kind 必须在域模板 `entity_types` 词表内、关系 kind 必须在 `relationship_kinds` 词表内，出表拒绝（模板即宪法）。
- **变更事件流**：创作台的每次增改删落 append-only 事件（操作者/前后状态/时间），沿 wire ontology 事件流模式，供审计与后续 diff/回滚（本 change 只落事件，不做 diff/回滚 UI）。
- **任务指派**：负责人可向域内成员指派创作/核验任务（轻量任务表：域内、指派对象、状态流转），专家的工作台按任务组织，贡献归因沿用事件流操作者。
- **工作台页面**（成员域内，非 admin 门）：我的任务列表、域内容浏览器（按模板词表分组）、实体/关系编辑表单、事件流查看。
- 非目标：发布与拉取契约（C3）、盲标/一致性（human-review 既有面不动）、模板词表的编辑（C1 已有 admin 面）、KU diff/回滚 UI（后续）、AI 辅助创作（后续）。

## Capabilities

### New Capabilities

- `expert-authoring`: 领域专家创作面——词表执法的实体/关系创作与维护、域隔离写作、变更事件流、任务指派与工作台

### Modified Capabilities

- `domain-workspace`: 增「域内内容隔离」需求的可观测面（创作台内容读写全部经域成员身份执法；既有租户隔离语义不变，只加创作台这一消费方）

## Impact

- **代码**：`src/bench/authoring.py`（新内核模块：词表执法校验 + 事件流 + 任务表操作，conn 注入风格）；`src/workspace_store.py` 扩 `WORKSPACE_SCHEMA`（`authoring_events`、`authoring_tasks` 两表，同幂等注册路径）；`src/web/routes/authoring.py`（新路由组）+ 工作台 Jinja 页 + i18n 双语；`tests/conftest.py` `_ALL_TABLES` 补两表。
- **依赖契约**：写面必须复用 `src/bench/store.py::upsert_knowledge_unit`（不绕过 KU 收口）；域隔离以 `namespace=domain.key` 承载，跨域读写沿用 C1 的 `require_domain_role` 执法。
- **既有行为**：C1 管理面零变化；human-review/promotion 面零变化；法律域注册数据零变化。
- **测试**：词表执法（出表拒）、域隔离写作（namespace 边界）、事件流完整性、任务流转、工作台 RBAC（专家可写/标注员只读/非成员 403）。
