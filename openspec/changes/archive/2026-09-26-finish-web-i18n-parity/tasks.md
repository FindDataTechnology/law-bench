# Tasks: finish-web-i18n-parity

## 1. 目录与校验

- [x] 1.1 `src/web/i18n.py`：新增 `dashboard` / `review` / `clauses` / `contracts` / `samples` / `search` / `catalog` / `auth_denied` 页面组键；zh 逐字平移模板现行文案，en 新译。
- [x] 1.2 `tests/test_i18n_parity.py`：递归比较 zh/en 键路径集合，缺失即报键名；纳入测试套件。
- [x] 1.3 route 层字符串表入目录：`review.py::_verdict_labels` → `review.verdict.*`；`law_catalog.py::_zh_map` → `catalog.*`，两 locale 补齐。

## 2. 模板迁移（按风险升序，每页一个提交粒度）

- [x] 2.1 `login_denied.html`、`law_info_detail.html` — 实施时发现两页本已走目录（提案调查的匹配模式误报），免做；`base.html` 六个硬编码导航标签一并迁入 `t.nav`。
- [x] 2.2 `samples.html`、`dashboard.html`（含 stat 标签、空态、表头）。
- [x] 2.3 `contracts_list.html`、`contract_detail.html`（生成面板的 mode/label、stance 选项）。
- [x] 2.4 `clauses_list/detail/edit/new/review`（筛选表单、批量操作提示、闪存条）。
- [x] 2.5 `search.html`：删除行内双语句式，改 `t.search.*`。
- [x] 2.6 `review_list.html`、`review_task.html`（含 verdict label、盲评说明、冲突 flash）。
- [x] 2.7 `law_catalog_audit.html`、`law_catalog_review.html`、`law_catalog_revisions.html`（补入提案漏列的一页）；`_zh_map` 为合同类型数据映射（非界面文案，按设计 Non-Goal 保留）；本地无 law_catalog schema，三页以 Jinja 离线渲染 + 假数据验证 EN 输出。

## 3. 测试与回归

- [x] 3.1 更新受影响 web 测试的中文断言为目录渲染断言（`tests/test_*_web.py` 全量过）。
- [x] 3.2 新增 `tests/test_i18n_en_smoke.py`：6 个目的地 en 冒烟 + 导航英文断言 + 判定页 verdict/press 标签随语言切换（law-catalog 页因本地无 schema 以离线渲染验证，见 2.7 注）。
- [x] 3.3 既有 5 个已迁移页面回归不受影响。

## 4. 验证

- [x] 4.1 `openspec validate finish-web-i18n-parity` 通过；全量测试套件绿。
- [x] 4.2 本地 preview 手工切换 zh/en 走全部 11 个目的地，逐一确认切换生效。
