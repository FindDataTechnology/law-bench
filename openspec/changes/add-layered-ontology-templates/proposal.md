## Why

「完整本体模板」今天不存在，因为**知验台的模板只能装一层**。生产里仅有的两份模板（`legal-domain`、`gov-domain` v2）都是平铺单层，词表只有 2–3 项；而工作区里真实的语义资产分布在三个互不相认的权威上：

- 观测词表：`fd-open-data-protocol` 的 30 个实体类型 / 14 个关系 / 30 个概念族，已过 `ontology-kernel` 符合性闸（`fd-ontology-kernel/adapters.json` 在册）；
- 行业本体：ERP 的客户/供应商/商品/科目/分录（54 条 `erp-*` 规格）、金融的指标与行情；
- 领域本体：法律 `clause`/`law`、政务 `concept`。

三者的交集是空的——`clause`、`law` 不在 protocol 的 30 类里，`company`、`organization` 不在任何知验台模板里。**两个都声称是「本体」的封闭词表，今天没有一个共同的词。** 共享符合性闸只验机制不验内容，所以这个空交集从未被判过红。

后果在两处具体可见：

1. **模板不可评**。`rubric_refs` 在 `src/bench/templates.py` 里 grep 零命中——模板声明「我用哪些尺子」今天是一句注释。没有尺子集就算不出「这个模板有没有变差」，缺口矩阵与结论台账之间因此没有连接点。
2. **升版无闸**。`create_template` 直接写 `max(version)+1`。今天没有任何机制阻止发布一个更差的模板版本，而 `eval-verdict-ledger` 的 `no-worse` 门早已在 spec 里定义好了。

为什么现在做：ERP 与经济金融的尺子全部是确定性的（`boundary.py` 四条 AST 审计、`sentiment-gold-v9` 105 条人工金标、`data-qa-goldset`），**这两条线的模板评估与自迭代可以完全绕开一直未销账的 LLM 判官校准门（`add-judge-misread-remediation` 4.1）**。不是绕过问题，是问题不在路径上。再晚，等法律线的 provisional 结论先长成默认口径，分层模板就没有干净的起点。

## What Changes

- **本体模板分为层，层是一等属性**。模板 schema 增加 `layer` 声明（`foundation` / `observation` / `industry` / `domain`，闭集），并增加两条跨层声明：`aligned_with`（同层异权威、同名即同义，一条声明替代 N 条逐项对照）与 `authority`（该层词表的权威出处标识）。
- **四份基础/行业模板落地**：
  - `foundation-v1`（`foundation` 层，知验台自有）：`organization` / `person` / `place` / `item` / `document` / `event` / `agreement` / `measurement` 八个通用类型，四个关系 `part_of` / `member_of` / `about` / `located_at`；
  - `external-world-2026.11`（`observation` 层，**只读导入** protocol 的 30 类 / 14 关系 / 30 概念族，权威标识指向协议版本）；
  - `enterprise-base v1`（`industry` 层，`extends foundation-v1`）：ERP 侧客户/供应商/商品/仓库/员工/科目/分录/发票/采购单/收付款；
  - `finance-market v1`（`industry` 层，`extends foundation-v1`）：金融侧标的/报价/持仓/指标观测。
- **角色不是类型**。`customer` / `vendor` / `employee` 以关系表达（`sells_to` / `supplies` / `employed_by`），实体本身是 `organization`。同一家公司在 Salesforce、金蝶、知验台三侧指向**同一个** `organization` 键，各挂一条角色关系——这是 crosswalk 不退化成立的前提。
- **`rubric_refs` 从注释变成契约**：模板保存与实例化时，每条引用必须解析到该域可用的 rubric；解析不到即拒绝。没有尺子的模板不可实例化。
- **模板升版带门**：升版前必须取到该模板尺子集的最近一条结论；尺子 digest 相等时跑 `no-worse`；`fail` 与 `inconclusive` 都拒绝升版且如实报因。
- **模板成为结论台账的被评对象**：`subject_kind="template"` 与既有四门/三态接口对齐，不改 `src/bench/verdicts.py` 的判定逻辑（台账只收结果与分类标签）。
- **缺口路由补一类**：`GAP_ROUTE` 增加 `quality:template` → `fleet`（今天 `FLEET_ROUTE` 已定义但零个缺口路由到它，需要判断的模板改进无处可派）。

## Capabilities

### New Capabilities

- `ontology-template-layering`: 模板的层属性、层内 `extends` 与跨层 `aligned_with` 的判定规则、权威出处声明、只读导入层的可重放与版本对齐，以及「层不可被继承边跨越」这条硬约束。
- `template-readiness-gate`: 模板的可评性契约——`rubric_refs` 必须解析（无尺子不可实例化）、升版必须通过 `no-worse` 门、`inconclusive` 不得放行、模板作为 `subject_kind="template"` 进入结论台账。

### Modified Capabilities

- `ontology-template`: 模板 schema 由「六键 + 可选 extends」扩为「六键 + 可选 extends + 层属性 + 跨层声明」；继承校验从「仅校验子模板增量」扩为「分层后按层校验有效词表」。
- `domain-quality-metrics`: 六项质量比之外增加「模板可评性」一项（该域锚定模板的 `rubric_refs` 解析率），并把「模板未声明尺子」作为一种独立缺口报出，而不是计为通过。
- `eval-verdict-ledger`: 明确 `subject_kind` 闭集加入 `template`，并把 `no-worse` 门对模板对象的输入（尺子 digest + 覆盖度/审计结果）写进契约；判定实现仍归本能力之外。

## Impact

- **代码（law-bench-internal）**：
  - `src/bench/templates.py`：`REQUIRED_SCHEMA_KEYS` 之外新增层属性与跨层声明的结构校验；`rubric_refs` 解析闸。
  - `src/bench/inheritance.py`：`merge_schema` 增加层一致性检查（`extends` 两端层必须相同；跨层必须走 `aligned_with`）；`resolve_template_schema` 解析 `aligned_with` 但**不合并**对方词表（合并会强迫一侧接受另一侧的生命周期）。
  - `src/bench/verdicts.py`：`subject_kind` 闭集加入 `template`（词汇表扩项，不改判定）。
  - `src/bench/dispatch.py`：`GAP_ROUTE` 增加 `quality:template`。
  - `src/bench/estate.py`：质量视图增加模板可评性一项。
  - `scripts/import_protocol_ontology.py`（新）：只读导入 protocol 词表为 `external-world-<version>` 模板。
  - `scripts/register_*_template.py`（新，四个）：`foundation-v1` / `enterprise-base` / `finance-market` / `legal-domain` 回填 `extends`。照 `register_legal_domain.py` 的幂等 + `--dry-run` 形状。
- **契约/文档**：`docs/knowledge-platform-blueprint.md` §三 需要补分层口径；`docs/domain-template-layers.md`（新）说明层、继承、跨层声明与导入重放。
- **对外口径**：`openspec/specs/solution-package/spec.md:9` 与 `collateral-solution/00-方案说明.md:20` 的「一个本体」需改为「一个本体契约，分层词表」。**这是本次变更之外的一笔独立规格修改**，本 change 不做，但在 Impact 中显式挂账，避免两处口径继续分叉。
- **依赖**：无新第三方依赖。导入脚本读 `fd-open-data-protocol` 的 YAML（本地路径或已安装包），不新增运行期依赖。
- **风险**：`concept_structures` 是浅合并（`inheritance.py:84-92`），子模板不能给父模板已有类型增补字段——v1 明确不做字段级继承，子模板需整条重写该类型。这条限制写进 spec 的「已知边界」，不做成隐性行为。
