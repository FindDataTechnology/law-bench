# bench 工作台全量扫验收报告（2026-11-07，polish-bench-workbench）

 impeccable 有界流程：brief 立面 → 17 组逐组打磨（5 个并行分片）→ 中央归并（i18n 27 键 + CSS 追加）→ 一次批量截图检视（16 页 × 桌面 1280 + 移动 390）→ 一次批量修 → 一轮确认。

## 覆盖与验收环境

- 检视环境：sweep 临时库（law_bench_sweep）+ 假 LOGTO + 真 server（brief 验证通路，src/ 零改动）；空库 = 全站真实空态，正是清单第 2 项的验收环境。
- 截图：`.impeccable/review/<page>/{desktop,mobile}.png`（dashboard、rubrics、prompts、compare、contracts、clauses、law-info、samples、search、admin_domains、admin_distribution、admin_templates、law_catalog_audit、law_catalog_revisions、review_list；login_denied 为静态页免截）。
- 16 页 × 2 视口全部 200 且 **h_overflow = 0**。

## 逐组七项清单结论（17 组）

| # | 组 | 结果 | 要点 |
|---|----|------|------|
| 1 | dashboard | 通过 | stats 失败态新增报因卡（不再 0 值冒充）；窄屏表滚动补齐 |
| 2 | rubrics | 通过 | 空态卡+写者 CTA；评分项表单 label 补齐 |
| 3 | prompts | 通过 | 空态卡；表单 label 现状即达 |
| 4 | compare | 通过 | 空规则下拉诚实禁用项；矩阵错误 error-card |
| 5 | contracts | 通过 | 空态 partial；generation 表单 9 处 label 补齐；slots 空态 |
| 6 | clauses | 通过 | **筛选空/真空两态拆分**（原筛选空说谎）；404 error-card；clause_edit 嵌套表单修复（HTML 非法→删除钮错提交编辑端点，呈现层对齐） |
| 7 | law-catalog | 通过 | 空态+label+对比度；revisions 表入 panel |
| 8 | law-info | 通过 | 分组空态（真空/筛选空）；404 error-card |
| 9 | review | 通过 | 盲评表单 label+radiogroup 语义；两表入 panel |
| 10 | samples | 通过 | label 关联修复；其余现状即达 |
| 11 | search | 通过 | 新增空结果态；错误卡；结果 pre 换行防溢出 |
| 12 | workbench/authoring | 通过 | 双层真空态（词表空/内容空）+创作引导；表单 label 补齐 |
| 13 | admin | 通过 | 全部表单 for/id；空词表补「（无）」；btn-danger 惯例 |
| 14 | promotion | **零覆盖（spec 豁免）** | JSON API 无模板页；如需真页面属新增 scope 另立 change |
| 15 | distribution | 通过 | 消费者空态卡+登记表单展开；未绑域「（无）」 |
| 16 | login | 通过 | login_denied 七项现状即达（零改动） |
| 17 | copilot 岛挂载 | 通过 | 挂载 loading/failed chip（onerror 看守，不再卡假加载态）；岛内逻辑 D4 边界不动 |

## 中央归并

- i18n：27 个新键（S1-S5 报告）落入 `src/web/i18n.py` zh/en 双目录；`test_i18n.py` 30/30 过；zh/en 键集一致性断言 True。
- CSS：`style.css` 追加三段（`form .grid2` 双列密度、`.crit-actions` 窄屏换行、`.filter-form` 裸子元素窄屏堆叠）——全部呈现层、桌面布局不动。
- [4]-fix 波发现一处 **先于本轮即存在** 的渲染缺陷并修复：`POST /clauses/extract` 精简 context 重渲触发 `UndefinedError` → 500（模板侧防御性缺省，route 未动）。

## 批量检视 → 修复 → 确认

- 检视发现：admin_domains 移动端表单 label/input 参差（`.filter-form` 裸子元素 flex-end）→ 窄屏堆叠规则修复 → 确认轮通过（label 贴 input、零溢出）。
- 全部 16 页零横向溢出；停轮，无第四轮。

## 行为无关复核

- 路由/RBAC/数据契约/i18n 键文件结构零变更（键只增不改）；全仓测试基线：**1324 passed, 60 skipped**（与本轮前一致）。
- 如实缺口（不进第四轮）：① 路由层 flash detail 部分英文原文（.py 边界）；② dashboard 路由层 DB 异常仍整页 500（需全局 500 页，本轮边界外）；③ clause create/update 服务端校验错误无就地报因位（.py 边界）；④ copilot 岛内 vendored 资产未构建（正常缺省），chip 态需资产构建后实测。
