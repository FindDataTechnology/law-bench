# web-rbac Specification（delta）

## Purpose

在既有 scope 执法模型上增领域作用域：平台级 scope（Logto 唯一真源，不变）与域内角色（工作区成员记录）在执法时合成，权限感知导航覆盖领域管理面。

## ADDED Requirements

### Requirement: 领域作用域权限合成

受管理的领域路由 SHALL 在既有 `require_scope` 平台执法之外叠加域内角色检查：先平台 scope 后域角色，两道均过方放行；域内角色的唯一真源 SHALL 为工作区成员记录（本变更引入），平台级 scope 的真源 SHALL 仍为且仅为 Logto（「平台级角色只存在于 Logto」的既有契约不因本变更改变）；无域成员身份的已认证用户访问域资源 SHALL 拒绝（fail-closed）。

#### Scenario: 双道执法
- **WHEN** 已认证用户持 `content:write` 平台 scope 且为成员域专家，请求修改该域内容
- **THEN** 请求通过平台 scope 检查并通过域角色检查，操作执行

#### Scenario: 平台 scope 不足以越过域检查
- **WHEN** 已认证用户持 `content:write` 但对目标域无任何成员身份
- **THEN** 请求在域检查处被拒

### Requirement: 权限感知导航覆盖领域面

UI 导航 SHALL 按有效权限呈现领域入口：用户 SHALL 仅看到其具成员身份的域；平台管理门（模板/全域成员/邀请）SHALL 仅对持 `admin` 平台 scope 的身份可见；无权限入口 SHALL NOT 渲染，而非渲染后拒绝。

#### Scenario: 导航按域过滤
- **WHEN** 仅 A 域成员的用户查看导航
- **THEN** 导航呈现 A 域入口与平台通用项，B 域与平台管理门不出现
