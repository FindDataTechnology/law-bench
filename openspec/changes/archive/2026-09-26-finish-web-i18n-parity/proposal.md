## Why

顶栏的 zh/en 语言切换只在 5 个目的地（评分规则、提示词、对比、法律法规、法规索引）真实生效；其余 6 个目的地（仪表板、人工审查、条款库、合同模板/详情、合同样本、搜索）正文是硬编码中文，law-catalog 两页与登录拒绝页同样旁路。评审结论（`.impeccable/critique/2026-09-26T07-23-57Z__src-web-templates.md` P1 问题 4）：一个看得见却静默失效的控件比没有更糟——它在侵蚀其它反馈的可信度。zh/en 双语是 DESIGN.md 明文承诺（"bilingual zh/en parity on every screen"），应当补完而不是砍掉。

## What Changes

- 把全部剩余硬编码中文模板迁移到 `src/web/i18n.py` 目录：`dashboard`、`review_list`、`review_task`、`clauses_list/detail/edit/new/review`、`contracts_list`、`contract_detail`、`samples`、`search`、`law_catalog_audit`、`law_catalog_review`、`login_denied`、`law_info_detail`。
- 中文文案原样入目录（不改写文案本身）；英文补齐对应键。
- `review.py` 的 `_verdict_labels`、`law_catalog.py` 的映射表等 route 层硬编码字符串一并入目录。
- `search.html` 的行内双语句式统一改为目录驱动。
- 增加目录奇偶校验测试：两个 locale 的键集合一致，防止再次单侧漂移。

## Capabilities

### New Capabilities
<!-- 无。 -->

### Modified Capabilities
- `web-i18n`
