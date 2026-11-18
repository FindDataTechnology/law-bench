# Tasks: polish-bench-workbench

## 0. brief 立面

- [x] 0.1 写 `.impeccable/surfaces/bench-workbench.md`：Mode=Operate、Direction contract（承接 Evidence Ledger）、管辖页组清单、Facts 边界（RBAC/路由/契约不动）与口径
- [x] 0.2 补设计 token 与可复用 partial（空态卡、错误卡、表单错误样式），确认不引新依赖
- [x] 0.3 搭本地 fixture + dev server 验证通路（截图工具链通）

## 1. 页组全量扫（每组四步：检视 → 清单评分 → 批量修 → 确认；可按组分片并发）

- [x] 1.1 dashboard（含 `/api/dashboard/stats` 呈现面）
- [x] 1.2 rubrics（列表/new/edit/detail）
- [x] 1.3 prompts（列表/编辑）
- [x] 1.4 compare（form/list/detail 评审矩阵页）
- [x] 1.5 contracts（列表/detail/generation）
- [x] 1.6 clauses（列表/detail/new/edit/review）
- [x] 1.7 law-catalog（audit/review/revisions）
- [x] 1.8 law-info + law references
- [x] 1.9 review（review_list / review_task 盲评流）
- [x] 1.10 samples
- [x] 1.11 search
- [x] 1.12 workbench/authoring（域工作台 home/browse/unit 表单——本体创作台）
- [x] 1.13 admin（templates/domains/members/invites/distribution admin）
- [x] 1.14 promotion（queue/发布流页）
- [x] 1.15 distribution（admin_*.html 发布管理）
- [x] 1.16 login 页
- [x] 1.17 copilot 岛挂载呈现（不碰岛内逻辑）

## 2. 跨组复核

- [x] 2.1 全局一致性终审：token 使用、间距节奏、状态色语义跨组一致
- [x] 2.2 双语键 diff 统一复核（zh/en 无缺键、无硬编单语）
- [x] 2.3 行为无关复核：无路由/权限/契约变更混入

## 3. 收尾

- [x] 3.1 验收报告 `reports/<date>-workbench-sweep.md`：逐组逐项计数（七项清单 × 17 组）
- [x] 3.2 `openspec validate polish-bench-workbench --strict` 过绿
