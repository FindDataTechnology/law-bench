# Proposal: polish-bench-workbench

## Why

bench 工作台（FastAPI + Jinja2，"The Evidence Ledger" 设计系统）底子厚但从未按 impeccable 立过操作面规矩：60+ 个 UI change 逐点打磨过，却没有一份统一的 surface brief，各页状态完备度、空态诚实度、a11y 基线不齐。用户拍板「全量一次扫」：给工作台立 Operate brief 并对全部模板页逐组 critique/audit/打磨。同场战役：介绍站（根 change `add-bench-chain-website`）会把外部目光第一次引到工作台页面上。

## What Changes

- 立操作面 surface brief：`.impeccable/surfaces/bench-workbench.md`（Mode=Operate，Direction contract 承接既有 Evidence Ledger 设计系统，Facts 禁编造清单）。
- 全量扫：`src/web/templates/` 全部模板渲染页组（dashboard、rubrics、prompts、compare、contracts、clauses、law-catalog、law-info、review、samples、search、workbench/authoring、admin、distribution、promotion、login、copilot 岛）逐组过 critique + audit 清单并打磨。
- 状态完备：每页 loading/empty/error 三态齐全；空态如实（无内容显示真空态，不摆拍）；错误页报因。
- a11y 与响应式基线：表单 label、焦点可见、对比度、980px 单列在窄屏不破版。
- 有界验证纪律：每组一次批量检视（桌面+移动）→ 一次批量修 → 至多一轮确认。
- **零行为变更**：RBAC 闸（`web-rbac`）、双语 parity（`web-i18n`）、路由与数据契约全部不动——打磨只在呈现层（模板 + CSS + 前端微交互）。

## Capabilities

### New Capabilities

- `web-surface-quality`: 工作台呈现质量治理——surface brief 管辖、全量扫覆盖与验收、状态/a11y 基线、有界验证纪律、零行为变更边界。

### Modified Capabilities

<!-- 无：web-rbac / web-i18n / 各 web-* spec 的需求保持权威，本 change 不修改其要求 -->

## Impact

- `src/web/templates/**`：全模板组打磨（呈现层）。
- `src/web/static/**`：CSS 与静态资产微调。
- 不动 `src/web/routes/**` 的路由与权限逻辑；不动 `web-auth`/`web-rbac`/`web-i18n` 契约。
- 验收产物：`.impeccable/surfaces/bench-workbench.md`、`.impeccable/review/` 截图、`reports/<date>-workbench-sweep.md`。
