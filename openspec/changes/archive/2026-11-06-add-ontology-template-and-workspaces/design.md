# 设计：本体模板与领域工作区

总纲：`docs/knowledge-platform-blueprint.md`（P0）。本 change 只做地基：模板一等物 + 工作区 + 成员/角色 + 管理门页面。创作台（C2）、发布-拉取（C3）、RAG 通用化（C4）不在本 change。

## D1 模板即数据，不是代码

模板存 JSONB（`ontology_templates.schema`），不引入模板 DSL/代码生成。理由：

- 域包插拔契约（bench-platform）已保证内核领域无关；模板要做的是**结构声明**，不是行为；
- 词表类内容（实体类型/关系种类/档位词表）本质是受约束的枚举与字段定义，JSONB 足够，且迁就既有 `column_notes`/manifest 等 JSONB 先例；
- 未来若需更强校验，加 JSON Schema 校验器即可（演进位留出，本 change 不做）。

schema 结构（初版约定）：

```json
{
  "entity_types": ["company", "indicator", "..."],   // 必填
  "concept_structures": {"indicator": ["name", "unit", "frequency", "..."]},  // 必填
  "relationship_kinds": ["belongs_to", "..."],        // 必填
  "tier_vocabulary": ["raw", "bronze", "silver", "gold"],       // 必填
  "sensitivity_vocabulary": ["public", "internal", "confidential"],  // 必填
  "corpus_declaration": {"source_types": [...]},      // 声明级
  "rubric_refs": ["rubric-id-or-slug", "..."]
}
```

与 bench-platform 既有词表的对齐约束：`tier_vocabulary` 缺省值对齐四层互斥词表（`tiers.py`）；`sensitivity_vocabulary` 对齐知验台 `SENSITIVITY_LEVELS`。校验落在本模块，不改内核。

## D2 数据模型（幂等建表，四表）

> 机制对齐（apply 期实查）：本仓**无 Alembic、无迁移脚本**（`README.md:45`：「所有表以 `CREATE TABLE IF NOT EXISTS` 幂等创建，首次运行自动建表，无需迁移脚本」）。四表以 `WORKSPACE_SCHEMA` 常量声明于 `src/bench/workspace_store.py`，在 `src/eval/store.py::ensure_schema` 中 `conn.execute(WORKSPACE_SCHEMA)` 注册（沿 `BENCH_SCHEMA` 先例）；`tests/conftest.py::_ALL_TABLES` 同步登记四表以保测试隔离。原提案「一条迁移」为措辞偏差，行为契约不变。

```
ontology_templates   id, name, version, schema JSONB, created_by, created_at
                     —— 编辑即出新行（同 name 新 version），历史行不可变
domains              id, key(唯一), name, template_id → ontology_templates.id,
                     template_version, created_by, created_at
domain_members       id, domain_id, user_id, role, added_by, added_at, removed_at(NULL)
                     —— 角色变更=旧行补 removed_at + 新行（保留痕语义），user_id 对齐 web-auth 既有用户标识
domain_invitations   id, domain_id, role, token_hash, invited_by, expires_at,
                     accepted_at(NULL), accepted_by(NULL)
                     —— 令牌只存 hash（沿凭据脱敏纪律）
```

留痕策略：`domain_members` 追加式（不改写历史），满足 domain-workspace「成员管理留痕」需求；不另设审计表（量小，操作留痕就在成员表本体）。

## D3 角色合成执法点

- 平台级：沿用 `require_scope`（Logto scope claim），一行不改；
- 域级：新增 `require_domain_role(domain, min_role)` helper——查 `domain_members`（user_id + domain_id + removed_at IS NULL），角色序 `annotator < expert < lead`，`admin` 平台 scope 直通全权；
- 合成顺序：先平台 scope 后域角色（spec 双道执法场景），在路由依赖里按序调用；
- web-rbac「平台级角色只存在于 Logto」契约不动：`domain_members` 是**工作区成员记录**，不是平台角色表——design 显式记此边界，避免与该 requirement 文义冲突。

## D4 法律域追溯登记

不改任何法律域运行时行为：登记 = 插入一份「法律域模板」（词表从法律域包现状反提炼）+ 一条 `domains` 行绑定既有法律域键。模板词表初版以法律现状为准（条款/法条/合同类型等），P2 迁移时再校正。**登记是数据操作，非代码分支**——验收判据=全量既有测试绿。

## D5 管理门页面（Jinja，沿既有模式）

- 路由：`/admin/templates`（列表/新建/版本）、`/admin/domains`（列表/详情/成员/邀请），页脚复用既有分页/表单风格；
- 访问：`/admin/*` 全部要求 `admin` 平台 scope + 对应域角色合成（模板与全域管理 = admin 专属；域详情成员页 = 该域 lead 亦可见）；
- 导航：权限感知——非成员域与 admin 门不渲染（web-rbac delta 场景）；
- i18n：沿 web 既有双语模式。

## D6 非目标与风险

- 非目标见 proposal；特别注意：**实例化产物「承接词表内知识单元的能力」在 C1 只到域容器层**（域可被引用为 KU 归属），创作/编辑面是 C2；
- 风险①：user_id 语义——web-auth 的 `get_current_user` 标识与 Logto sub 的映射须在实现时核一次，避免两套用户键（既有先例：human-review 的 annotator identity）；
- 风险②：模板 schema 太自由导致 C2 创作台无从下手——本 change 把四类必填词表钉死为最小集，C2 只消费不扩展（扩展另立）。
