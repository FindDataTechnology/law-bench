## Context

知验台现有模板是一层平铺的 JSONB 行（`ontology_templates`），`src/bench/templates.py` 校验六个必填键。继承机制（`src/bench/inheritance.py`）已实现「子模板只增不删」与有效词表解析，但生产里零条继承边——`legal-domain` 与 `gov-domain` 都是单层，`publish_gov_template_v2.py` 是复制粘贴不是 extends。

同工作区里另有两套封闭词表：`fd-open-data-protocol` 的 30 实体类型 / 14 关系 / 30 概念族（已过 `fd-ontology-kernel` 符合性闸，在 `adapters.json` 在册），以及 ERP 侧的科目/维度/分录语义（54 条 `erp-*` 规格，权威在 `fd-erp-ledger-mcp/tool-surface.json`）。三者交集为空。

三个约束塑造了本设计：

1. `fd-open-data-protocol` 是可安装的 PyPI 包，其 golden digest 测试与 conformance adapter 都依赖「已发布 YAML 就是真源」。让它反向依赖服务端模板会把「装完即用」变成「连得上才能用」。
2. `ontology_publications` 的 manifest 形状不能动：`fd-wire` 生产在拉 `shape 2`（`legal` v1，digest `3586552a`），`fd-ontology-kernel` 的 golden 测试钉死了两种形状的字节。
3. `rubric_refs` 今天在 `src/bench/templates.py` 里零校验，`create_template` 直接写 `max(version)+1`。

## Goals / Non-Goals

**Goals:**

- 让「层」成为模板的一等属性，并让跨层只经 `aligned_with` 相接、不经 `extends`。
- 让 `rubric_refs` 从注释变成契约，让模板升版必须过 `no-worse` 门。
- 让模板成为 `eval-verdict-ledger` 的被评对象，从而 ERP / 金融两条确定性线可以独立闭环，全程不碰未销账的判官校准门（4.1）。
- 导入外部词表可重放、按内容幂等、上游缺失即硬失败。

**Non-Goals:**

- 不做字段级继承。`concept_structures` 是浅合并，子模板要增补父模板已有类型的字段只能整条重写。这是 v1 的显式边界，写进 spec 让读面如实呈现，不做成隐性行为。
- 不做词表自动合并（跨层或同层异权威）。`aligned_with` 只声明映射，不产生新的有效类型。
- 不改 `ontology_publications` 表、不改 manifest 形状、不动 `publish_domain()`。发布面的分层表达留到 `add-crosswalk-seam` 或更晚。
- 不把 ERP 的 25 个错误码、维度闭集、`boundary.py` 四条审计搬进模板。它们是断言面，不是词汇；搬进来就是第二份会 rot 的副本。
- 不新造评测门。四门三态沿用 `eval-verdict-ledger` 既有闭集。

## Decisions

### D1：层是模板字段，不是域路径

模板增加 `layer`（闭集 `foundation` / `observation` / `industry` / `domain`）。域路径（`legal/contract-review`）表达的是**组织树**，层表达的是**语义来源**。两者正交：一个行业域可以是 `industry` 层，它的子域仍是 `industry` 层；一个 `domain` 层模板可以有多个平级域。

**为什么不复用域路径当层**：路径已经被用于成员继承与命名空间（`inheritance.ancestors()`），把语义层塞进路径会让「子域」同时意味着「更具体的层」与「更细的组织划分」，而这两件事的约束完全不同（前者禁止跨层 extends，后者允许同级）。

**为什么不新增一张 `template_layers` 表**：层是模板的固有属性，独立成表只增加一次 JOIN，不增加任何能力。

### D2：跨层对齐用声明，不用合并

`aligned_with` 形状：

```json
"aligned_with": [
  {"target_template": "foundation-v1", "target_layer": "foundation",
   "type_map": {"company": "organization", "city": "place"}}
]
```

只声明映射，解析时**不合并对方词表**。合并会强迫一侧接受另一侧的生命周期：protocol 的 `company` 是观测对象（有 `symbols` 表、有 `identifiers` 表），知验台的 `organization` 是交易主体（有 `customer` 关系、有 `contracts`）。合并就必须在两者之间选一个权威，而两侧都能举出反例。

**替代方案**：把 `aligned_with` 做成 `extends` 的特例（跨层也走 merge）。否决理由：跨层 merge 之后，protocol 新增一个实体类型会自动出现在所有行业模板里，而行业专家没有同意过这个变更——这违反「模板是钉到具体版本的」既有约束。

### D3：外部权威用 `authority` 标记，`external` 模板只读

`authority: {kind: "platform"}` 或 `authority: {kind: "external", source: "fd-open-data-protocol", version: "2026.11"}`。`external` 模板的词表修改被拒绝，只有重新导入能产生新版本。

**为什么不做成「导入一次后变成本地可编辑」**：那样上游发版与本地编辑就会分叉，而分叉后没有机制判断「本地改了什么」。`external` 标记让「这个类型的权威在别处」成为可查询的事实，读面因此能回答「这个类型该找谁改」。

**替代方案**：导入时把词表复制进模板并标记为 `platform`。否决理由：这正是现有 `register_legal_domain.py` 的做法（从 pack 手工蒸馏再写死），也是 `publish_gov_template_v2.py` 手动 append 的原因——每次上游变化都要人到脚本里改一行。`external` 标记把这件事变成一次重放。

### D4：`rubric_refs` 校验放在保存与实例化两处，只校验前者不阻断保存

保存时：解析失败**不阻断保存**（模板可以先是草稿），但把未解析项记录下来并在详情页显示。
实例化时：任一未解析即拒绝。

这个不对称是刻意的。强制「保存即须全部可解析」会让模板编辑无法分步进行（先写词表、再挂尺子）；而实例化是域真正开始用它的时刻，那一刻没有尺子就永远算不出自己有没有变差。

**空 `rubric_refs`**：允许保存，禁止实例化为正式域。`add-layered-ontology-templates` 不改动域的草稿态机制（今天没有），因此实现上「空尺子模板不可实例化」等价于「实例化直接拒绝」，草稿态留作后续能力的口子。

### D5：升版门在 `create_template` 的调用侧，不在函数内部

`create_template` 保持现状（写新版本），门的判定放在**调用它的服务层**，因为门需要读结论台账（一个跨模块查询），而 `create_template` 目前是纯 DB 写函数、不读其他模块。

**为什么不把门塞进 `create_template`**：那会让底层写函数依赖 `verdicts` 模块，而 `verdicts` 又依赖 `src.eval.store`——引入循环依赖的风险，且会让 `tests/test_bench_templates.py` 里每个用例都要准备结论台账。

**替代方案**：新开 `promote_template()` 函数作为唯一合法升版入口，`create_template` 降为内部函数。否决理由：`create_template` 已经被脚本与服务层多处调用，改签名是跨模块改动，收益不抵成本；用调用侧门禁 + 一个测试断言「所有升版调用点都经过门」更小。

### D6：`subject_kind` 扩闭集，判定逻辑不搬

`verdicts.py` 的 `subject_kind` 今天是自由字符串。改为闭集 `{"pack", "judge", "template"}`，扩项是加法。台账仍然只收「结果 + 分类标签」，判定留在各线自己的实现里——这条边界在 `verdicts.py` 的模块自述里写得明确，本设计不越界。

### D7：模板缺口路由到舰队，聚合键是模板名

`GAP_ROUTE` 增加 `quality:template` → `fleet`。`dispatch.py` 现有的去重逻辑按 `target_key`（pillar）收敛，模板缺口的 `target_key` 取模板名 + 缺口 key，使同一模板的同一缺口只产生一张工单。

**为什么不是 `kernel:builder`**：模板改进需要判断（哪些类型该加、哪些尺子该挂），而内核七岗是确定性的。`FLEET_ROUTE` 常量早已定义但零个 gap 用它——这是本变更第一次真的用上它。

## Risks / Trade-offs

- [浅合并限制暴露给用户] → 读面在子模板增补父层已有类型时明确报「当前版本不支持字段级增补，需整条重写」，并给出该类型的父层定义原文供参照。不静默丢弃增补。
- [外部导入产生大量模板] → 导入脚本按 `(source, version)` 幂等，同一上游版本重复导入不产生新行。测试钉住「连跑两次版本数不变」。
- [`no-worse` 门对模板要什么输入，各层不同] → 门只吃「覆盖度或审计结果」这个抽象分数，由各层的尺子适配器产出：ERP 取 `erp-solution-readiness` 的覆盖矩阵分数，金融取 gold 集通过率，foundation 取结构闸的通过项数。适配器不进内核，落 `packs/<layer>-base/` 或该域自己的 pack。
- [升版门被绕过——有人直接调 `create_template`] → 一个测试断言：全仓所有 `create_template(` 调用点必须经过 `promote_template_via_gate`（或显式标注 `# gate-bypass: <理由>`，仅允许初始化脚本使用）。这是静态检查，成本低。
- [层成为新的必填键，存量模板全部不合规] → 迁移脚本为 `legal-domain` / `gov-domain` 打上 `domain` 层、`platform` 权威；迁移是新增字段不是改结构，旧版本行补默认值。
- [「一个本体」对外口径冲突] → 本变更不修改对外规格；Impact 已挂账，`solution-package` 与 `collateral-solution` 的措辞修改走独立变更。

## Migration Plan

1. 迁移：为既有两份模板全部版本补 `layer: "domain"` 与 `authority: {kind: "platform"}`（新增字段，不改既有键）。
2. 落四份新模板：`foundation-v1`（platform）、`external-world-2026.11`（external，导入）、`enterprise-base v1`（extends foundation-v1）、`finance-market v1`（extends foundation-v1）。
3. `legal-domain` 保持平铺不动（它是 `domain` 层，本就不该 extends `foundation`——`clause`/`law` 不是通用类型）。
4. 回滚：新增字段与新增模板行都是加法；回滚 = 删除新增模板行 + 清空新增字段，既有模板恢复到本变更前逐字节一致（用 `sqlite3`/`pg_dump` 单表比对验证）。

## Open Questions

- 层是否需要「复合层」（如 `industry/erp`）？当前四个平面层够用；等到出现第二家 ERP 厂商要独立成层时再答，不影响本变更的 spec 与任务拆分。
