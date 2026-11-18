# 任务：add-ontology-template-and-workspaces

## 1. 数据层

- [x] 1.1 幂等建表：新增 `ontology_templates`/`domains`/`domain_members`/`domain_invitations` 四表（`WORKSPACE_SCHEMA` 常量 + `ensure_schema` 注册 + `conftest._ALL_TABLES` 登记；design D2 结构与索引；`domains.key` 唯一；`domain_members` 追加式含 `removed_at`）
- [x] 1.2 `src/bench/templates.py`：模板 CRUD——三件套 schema 必填校验（四类词表 + 语料声明）、tier/sensitivity 词表对齐内核既有词表、编辑出新版本且历史行不可变
- [x] 1.3 `src/bench/workspaces.py`：域生命周期——实例化（模板存在且合法、落域与模板版本绑定）、成员/角色追加式变更（留痕：操作者/前后角色/时间）、邀请令牌生成与接受（一次性、过期、只存 hash）
- [x] 1.4 `require_domain_role` 执法 helper：平台 scope → 域角色两道序贯；`admin` 直通；角色序 `annotator < expert < lead`（design D3）

## 2. Web 面

- [x] 2.1 管理门路由：`/admin/templates`（列表/新建/版本历史）+ `/admin/domains`（列表/详情/成员管理/邀请生成），`admin` 平台 scope 把门（design D5）
- [x] 2.2 Jinja 页面五张：模板列表/模板详情/域列表/域详情/邀请接受页，双语 i18n
- [x] 2.3 导航权限感知：非成员域与平台管理门不渲染（web-rbac delta 场景）；受邀者从邀请链接进登录流再回绑定（沿既有 Logto OIDC 回调）
- [x] 2.4 领域路由统一接 `require_domain_role`：跨域拒绝报「无该域权限」非 404

## 3. 法律域追溯登记

- [x] 3.1 法律域模板反提炼（词表取自法律域包现状）+ `domains` 追溯行绑定既有法律域键（纯数据操作，design D4）
- [x] 3.2 回归证明：全量既有测试套件绿、断言口径不变

## 4. 测试

- [x] 4.1 模板：三件套校验（缺词表拒实例化）、版本化（就地改写出新版、实例锚定创建版本）
- [x] 4.2 工作区：实例化开域内核零改动、成员追加式留痕、邀请全流程（接受即失效/过期拒绝/重复使用拒绝）
- [x] 4.3 权限合成：双道执法（scope 过域角色拒/域角色过 scope 拒）、admin 直通、fail-closed 跨域拒绝语义、导航按域过滤
- [x] 4.4 跨域隔离：非成员读域资源被拒、域间内容检索互不可见

## 5. 收口

- [x] 5.1 `openspec validate add-ontology-template-and-workspaces --strict` 绿
- [x] 5.2 blueprint 台账更新（C1 状态）与 tasks.md 勾选对账（教训：归档前必须拿测试对账 tasks.md 勾选）
