# Design: polish-bench-workbench

## Context

工作台已是服务端渲染 Jinja2 + "Evidence Ledger" 设计系统（flat、980px 单列、zh/en parity、RBAC scope-gated nav、fail-closed OIDC）。既有 60+ UI change（web-rbac、web-i18n、no-gloss restyle 等）逐点立过规矩，但缺一份面级 brief 与全量基线。本 change 用 impeccable 的 Operate 方法补面级治理。

## Goals / Non-Goals

- Goals：brief 立面；全页组过清单；状态/a11y/响应式基线拉齐；验收可计数。
- Non-Goals：不引入 SPA/前端框架重写；不动 RBAC/i18n 契约；不动 copilot 岛的功能逻辑（assistant-ui 是独立 React 岛，本轮只管其挂载呈现与暗色/移动适配）。

## Decisions

### D1. 打磨单位 = 模板页组，不按组件拆
工作台是服务端渲染，模板即页面。清单以 `src/web/routes/*` 的页面路由组为粒度（~15 组 + login + copilot 岛），每组独立 checkbox、独立验收——这正是 AGENTS.md 并行子代理偏好的分片单位（每组一个子代理可并发）。

### D2. 清单即 spec 的 Scenario 展开
critique + audit 清单固定七项：三态齐全 / 空态诚实 / 错误报因 / 表单 label / 焦点与对比度 / 窄屏不破版 / 双语键完整。七项全部落进 spec，报告逐组逐项计数——没有「整体良好」。

### D3. CSS 策略：Evidence Ledger 内做变体，不引新依赖
所有打磨走既有设计 token（间距/字号/状态色），缺的 token 先补 token 再用；不引 Tailwind/组件库。空态、错误卡、表单错误样式做成可复用的模板 partial，避免 15 组各写一套。

### D4. copilot 岛边界
`assistant-ui`（CopilotKit 浮岛，admin-only）本轮只验收挂载呈现（不遮内容、移动端收起、加载态），岛内交互逻辑不动——它有独立的 `copilotkit-frontend` spec 管辖。

### D5. 有界纪律落到任务结构
每组任务固定四步：检视截图 → 清单评分 → 批量修 → 确认轮（至多一次）。主代理汇总跨组报告，不做第四轮。

## Risks / Trade-offs

- 15 组并发打磨的风格漂移 → D3 的 partial/token 策略 + 主代理终审全局一致性。
- 模板改动碰 `web-i18n` 键 → 双语键检查入清单；键文件 diff 在主代理侧统一复核。
- 截图验证依赖真实登录态 → 各组子代理用本地 fixture 数据跑 dev server，不上生产。

## Migration Plan

纯呈现层 diff，无迁移。验收报告落 `reports/<date>-workbench-sweep.md`。

## Open Questions

- 无。
