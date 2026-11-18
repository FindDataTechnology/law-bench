# Design: finish-web-i18n-parity

## Context

`src/web/i18n.py` 是唯一翻译源（现有规范 "Single Translation Source"）；`resolve_locale` 中间件已向所有模板注入 `t`/`label_for`/`tr`。约 14 个模板只用了 `t.nav.brand`（title 品牌），正文硬编码中文；route 层还有 `review.py::_verdict_labels`、`law_catalog.py::_zh_map` 两处字符串表。

## Goals / Non-Goals

- Goals：语言切换在每个目的地真实生效；zh/en 目录键集合强制一致；中文文案逐字平移不改写。
- Non-Goals：不翻译数据值（条款正文、法条标题、rubric 名称——数据本就是中文）；不做语言偏好持久化策略变更；不新增第三个 locale；不动 DESIGN.md 视觉。

## Decisions

### D1: 按页面分组入目录，键名跟既有命名法

沿用现有结构（`nav/h1/col/form/btn/empty/detail/hint/badge`），每页一组顶层键（如 `dashboard.*`、`review.*`、`clauses.*`、`catalog.*`）。中文从模板逐字平移；英文新译，风格与现有 en 文案一致（简洁、操作动词开头）。

### D2: route 层字符串表搬进目录

`_verdict_labels(batch_type)` 改为从目录读（键如 `review.verdict.validity.pass` / `review.verdict.gold.approved`），route 只留 batch_type → 键前缀的映射。`law_catalog.py` 的 `_zh_map` 同理，并为 en 提供对应标签。

### D3: search.html 行内双语改目录

现有「中文 / English」双句式删除，改 `t.search.*`；查询参数与行为不变。

### D4: 目录奇偶测试

`tests/test_i18n_parity.py`：递归比较两棵 locale 树的键路径集合，diff 出缺失键。这是结构校验，不校验译文质量。

### D5: 模板迁移顺序与回归

迁移顺序按风险从低到高：login_denied / law_info_detail / samples / dashboard / contracts / contract_detail / clauses* / search / review* / law_catalog*。每迁一页，既有 web 测试同步更新断言（若有按中文断言的用例改为断言目录键渲染结果）。`tr()` 已支持带参格式化，flash 类文案直接复用。

## Risks / Trade-offs

- en 译文由本次变更首次引入，未经母语审校——可接受：内部工具、单人操作，后续可改。
- 目录体积增长（每页 ~10–30 键）——现状目录已内联每页 HTML（评审已提示），如体积成为问题另行优化（gzip 后增量很小），不阻塞本变更。
- 大量模板同时改动，回归面广——用页面分组提交 + 全量 web 测试兜底。

## Migration Plan

纯模板/目录层变更，无 schema、无部署依赖。合并即生效。

## Open Questions

无。
