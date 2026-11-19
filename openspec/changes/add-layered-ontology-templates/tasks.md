## 1. 模板分层字段与校验

- [x] 1.1 在 `src/bench/templates.py` 增加 `LAYERS` 闭集常量与 `layer` / `authority` / `aligned_with` 的结构校验；验证：新增 `tests/test_bench_template_layers.py`，未知层值 `vertical` 被拒且错误列出四个合法值，缺 `layer` 被拒，`authority.kind` 非 `platform|external` 被拒，三个用例全绿
- [x] 1.2 `authority: external` 的词表就地修改被拒；验证：同测试文件，编辑 external 模板的 `entity_types` 返回拒绝且错误提示「须重新导入新版本」，旧版本行逐字节不变（DB 前后快照比对）
- [x] 1.3 层随版本保留、换层被拒；验证：同测试文件，v1→v2 层不变；把 `industry` 改 `foundation` 并保存被拒且提示须新模板名
- [x] 1.4 角色双写校验：同层同时声明 `customer` 类型与指向 `organization` 的 `customer` 关系被拒；验证：用例断言错误点名两项，仅声明关系时校验通过

## 2. 层内继承与跨层对齐

- [x] 2.1 `src/bench/inheritance.py` 的 `merge_schema` 增加层一致性检查：`extends` 两端层不同即 `InheritanceError`，错误同时报出两端层名；验证：`tests/test_bench_template_layers.py` 中跨层 extends 用例失败且错误含两个层名，同层 extends 用例通过
- [x] 2.2 `resolve_template_schema` 解析 `aligned_with` 但**不合并**目标模板词表；验证：用例断言观测层模板的有效实体类型集合等于自身集合（`organization` 不出现），且 `aligned_with` 映射可被读函数取到
- [x] 2.3 对齐关系读函数（给定类型返回跨层对齐类型与来源模板版本）；验证：用例断言已声明时返回映射与版本、未声明时返回空而不是猜测

## 3. rubric_refs 契约

- [x] 3.1 保存路径解析 `rubric_refs`，未解析项记录但不阻断保存；验证：用例声明一条不存在的 rubric，模板保存成功且详情数据含未解析项
- [x] 3.2 实例化路径校验，任一未解析即拒绝并逐条点名；验证：用例实例化被拒，错误正文含该 rubric 标识，且不产生域行
- [x] 3.3 空 `rubric_refs` 可保存但不可实例化；验证：用例保存成功、实例化被拒且提示须先声明尺子

## 4. 升版门与结论台账

- [x] 4.1 `src/bench/verdicts.py` 的 `subject_kind` 改为闭集 `{pack, judge, template}`；验证：`tests/test_bench_verdicts.py` 新增用例，`subject_kind="blueprint"` 被拒且错误列出闭集含 `template`，`template` 写入成功
- [x] 4.2 新增 `promote_template_via_gate()`：取该模板尺子集的最近一条结论，digest 相等时按 `no-worse` 判定；`fail` 与 `inconclusive` 均拒绝升版并报因，「无可比历史」放行并标记立基线；验证：四个用例（变差拒绝 / 判不出来拒绝 / 立基线放行 / 尺子 digest 变更按立基线处理）
- [x] 4.3 升版调用点静态断言：全仓 `create_template(` 调用点必须经过门函数，或用 `# gate-bypass: <理由>` 显式豁免；验证：新增 `tests/test_bench_template_gate_bypass.py`，人为加一个未标注的调用点使测试失败

## 5. 质量视图与派单路由

- [x] 5.1 `src/bench/estate.py` 增加第七项质量比「模板可评性」（解析率，分母 0 时报「不可评」而非 0%/100%）；验证：`tests/test_bench_estate.py` 用例覆盖 3/4、空尺子、全解析三种情形
- [x] 5.2 「模板不可评」作为独立缺口报出，不因本体柱/语料柱非空而消失；验证：用例构造本体与语料均非空但模板无尺子的域，断言矩阵该域标红且缺口名可读
- [x] 5.3 `src/bench/dispatch.py` 的 `GAP_ROUTE` 增加 `quality:template` → `fleet`；验证：用例断言该缺口路由结果为 `fleet`，重复派单报「已指派」并返回既有工单标识

## 6. 四份模板落地

- [x] 6.1 `scripts/register_foundation_template.py`：写入 `foundation-v1`（`foundation` 层 / `platform` 权威），八个通用类型 + 四个关系；验证：`--dry-run` 打印计划且不写库，真跑后模板存在、幂等重跑不产生新版本
- [x] 6.2 `scripts/import_protocol_ontology.py`：只读导入 `fd-open-data-protocol` 词表为 `external-world-<version>`（`observation` 层 / `external` 权威），按 `(source, version)` 幂等；验证：连跑两次版本数不变；上游目录不可读时退出码非零且点名缺失文件、不写任何行
- [x] 6.3 `scripts/register_industry_templates.py`：写入 `enterprise-base v1` 与 `finance-market v1`，均 `extends foundation-v1`（`industry` 层）；验证：两份模板有效词表 = foundation 全部 + 各自新增，无重复项，模板校验通过
- [x] 6.4 存量迁移：为 `legal-domain` / `gov-domain` 全部版本补 `layer: "domain"` 与 `authority: platform`；验证：迁移前后原六键逐字节一致（单表 dump 比对），两域实例化行为无变化（既有测试全绿）

## 7. 验收

- [ ] 7.1 全量回归：`uv run pytest tests` 全绿，无跳过的新增用例
- [ ] 7.2 一条真链：`enterprise-base v1` 生成一条 `subject_kind=template` 的结论 → 升版 v2 经过门 → 结论入台账 → `register_retest` 登记复测工单；验证：库里四份证据（模板 v2 行、结论行、升版记录、工单行）都能查到
- [ ] 7.3 生产冒烟：部署后 `bash scripts/smoke_prod.sh` 绿，模板列表页可见四份新模板且详情标出层与权威
