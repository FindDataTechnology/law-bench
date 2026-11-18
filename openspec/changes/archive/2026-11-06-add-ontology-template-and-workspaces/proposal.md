# 提案：本体模板与领域工作区（P0 平台奠基）

## Why

知验台要成为多领域知识生产、质量与分发平台（总纲见 `docs/knowledge-platform-blueprint.md`），但今天它没有「领域本体模板」这个一等物——新增一个领域没有可复用的骨架；也没有领域工作区——无法以邀请制把不同行业的专家按域组织起来长期维护内容。多角色是这个平台成立的前提（用户定调），而现有 web-rbac 只有平台级权限面，缺领域租户与领域角色。P0 是后续一切（创作台 C2、发布-拉取 C3、RAG 通用化 C4）的地基。

## What Changes

- **领域本体模板一等物**：模板 = 三件套打包（本体 schema：实体类型词表/概念结构/关系种类/档位与 sensitivity 词表；语料模板声明；审核 rubric 引用），带版本；模板实例化开域，内核零改动（域包插拔契约不破）。
- **领域工作区（一域一租户，已裁）**：每个领域一个工作区，成员/任务/内容/发布流完全隔离；跨域共享只经内核机制。
- **邀请制成员与领域角色**：平台管理员/领域负责人/领域专家/审核标注员四级角色；管理员发起邀请（令牌制），受邀者经既有 Logto OIDC 登录绑定后入域；fail-closed——未授权跨域访问一律拒绝。
- **web-rbac 领域化扩展**：权限模型增领域作用域（domain-scoped permissions），per-route 执法与权限感知导航覆盖新面。
- **管理门页面**（Jinja，沿既有 web 模式）：模板列表/详情、域列表/详情、成员管理、邀请流。
- 非目标：专家创作台（C2）、发布与拉取契约（C3）、RAG 服务通用化（C4）、法律存量资产迁移入域包（P2）、bench-platform「主键源」条款修订（随 C3）。

## Capabilities

### New Capabilities

- `ontology-template`: 领域本体模板——模板 schema、版本化、实例化为域、与内核 KU/域包机制的对接约束
- `domain-workspace`: 领域工作区——租户隔离、邀请制成员、领域角色、成员管理行为契约

### Modified Capabilities

- `web-rbac`: 新增领域作用域权限需求（domain-scoped roles/fail-closed 跨域拒绝/权限感知导航覆盖领域面）

## Impact

- **代码**：`src/bench/`（新增 `templates.py`、`workspaces.py`，沿用 `packs.py`/`store.py` 模式）；`src/web/routes/`（新增管理门路由）+ `src/web/templates/`（新 Jinja 页面）；DB 迁移新增 `ontology_templates`、`domains`、`domain_members`、`domain_invitations` 四表。
- **既有行为**：法律域现有功能零变化（法律域包的模板实例化是追溯性登记，不改运行时行为）；web-rbac 现有平台级权限语义不变，只增域级。
- **测试**：模板 CRUD/版本、实例化、成员/角色/邀请全流程、跨域 fail-closed、管理页访问控制。
- **依赖**：无新外部依赖；身份继续走 shared-logto-idp + web-auth 既有会话。
