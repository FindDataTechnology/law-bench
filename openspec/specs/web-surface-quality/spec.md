# web-surface-quality Specification

## Purpose
工作台呈现质量治理：以一份 Operate surface brief 管辖全部模板渲染页，把既有逐点打磨收敛为可验收的全量基线。边界铁律：只动呈现层，RBAC/双语/路由/数据契约零行为变更。

## Requirements

### Requirement: Operate surface brief 管辖

工作台 SHALL 以 `.impeccable/surfaces/bench-workbench.md`（Mode=Operate）为呈现质量权威工件：Direction contract SHALL 承接既有 "The Evidence Ledger" 设计系统（不另起炉灶），Facts 节 SHALL 声明呈现层边界（RBAC 闸、路由、数据契约不动）与页面可声明事实口径。页面打磨与后续呈现层改动 SHALL 以该 brief 为验收依据。

#### Scenario: brief 先行

- **WHEN** 任一模板页开始本轮打磨
- **THEN** brief 已存在且该页在 brief 的管辖清单内，打磨依据可指名

#### Scenario: 边界声明可执行

- **WHEN** 打磨 diff 涉及路由、权限判定或数据契约
- **THEN** 该 diff 出局（Facts 边界驳回），呈现层改动不越界

### Requirement: 全量扫覆盖与状态基线

`src/web/templates/` 全部模板渲染页组（dashboard、rubrics、prompts、compare、contracts、clauses、law-catalog、law-info、review、samples、search、workbench/authoring、admin、distribution、promotion、login、copilot 岛）SHALL 逐组通过统一清单：loading/empty/error 三态齐全；空态如实呈现真实空数据（不摆拍、不假填充）；错误可报因（非裸 500 文案）；表单 label 完整、焦点可见、对比度达基线；980px 单列在窄屏不破版；zh/en 双语键完整（`web-i18n` 口径不回退）。API-only 路由（无模板）不在覆盖面。

#### Scenario: 页组验收逐组可计数

- **WHEN** 全量扫完成出验收报告
- **THEN** 报告按页组逐组列出清单各项通过/修复状态，计数完整、无「整体良好」式模糊结论

#### Scenario: 空态诚实

- **WHEN** 某列表页数据为空（如无 rubric、无 review 任务）
- **THEN** 页面呈现真实空态与下一步引导，不显示假示例数据

#### Scenario: 双语不回退

- **WHEN** 打磨改动涉及文案
- **THEN** zh/en 两语键同步存在，无新增硬编单语字符串

### Requirement: 有界验证纪律

打磨 SHALL 遵循有界流程：每页组一次批量检视（桌面+移动截图，落 `.impeccable/review/`）→ 一次批量修复 → 至多一轮确认；确认后 SHALL 停止，不进入无限打磨循环。

#### Scenario: 确认轮有顶

- **WHEN** 某页组完成一轮确认
- **THEN** 该页组出清 fallout 清单并停轮，未清项如实记入报告缺口而非继续第四轮

### Requirement: 零行为变更边界

本轮 SHALL NOT 改变：RBAC 判定与导航可见性逻辑（`web-rbac`）、路由与端点行为、数据契约、认证流（`web-auth`）、公共 API 面（`public-api-service`）。呈现层 diff SHALL 可通过「行为无关」复核（同输入同输出，仅呈现差异）。

#### Scenario: 行为无关复核

- **WHEN** 全量扫 diff 汇总复核
- **THEN** 无路由/权限/契约变更；任何触碰这三者的改动已在过程中被回退
