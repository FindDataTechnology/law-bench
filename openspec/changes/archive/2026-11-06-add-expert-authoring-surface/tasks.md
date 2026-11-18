# 任务：add-expert-authoring-surface

## 1. 数据层与内核模块

- [x] 1.1 `src/bench/workspace_store.py` 扩 `WORKSPACE_SCHEMA`：`authoring_events`（append-only，索引 (domain_id, unit_kind, unit_key) 与 (domain_id, created_at)）+ `authoring_tasks`（status 词表 + `transitions JSONB DEFAULT '[]'`），`tests/conftest.py::_ALL_TABLES` 同步登记
- [x] 1.2 `src/bench/authoring.py` 写入口：域存在性校验 → 模板词表执法（entity_types/relationship_kinds 出表拒）→ `upsert_knowledge_unit`（namespace=域 key、tier=raw、provenance.operator/via）→ 同事务落事件；op 判定以写前存在性为准（design D6 风险③）——apply 期兑现：`upsert_knowledge_unit` 增 `commit: bool = True`（缺省不变），authoring 三条写路径 `commit=False` 后 `_commit_with_event` 单次提交，事件失败 KU 写入同事务回滚（含 psycopg CheckViolation 真失败路径测试）
- [x] 1.3 关系键约定：`external_key = f"{from_key}->{kind}:{to_key}"` 常量与 docstring 钉死（C3 复用伏笔，design D2/D6 风险①）；`attrs` 存结构化 {from, to}
- [x] 1.4 删除语义：事件流记 delete + KU `tags["deleted"]=true`（零内核改动），浏览面过滤已删项
- [x] 1.5 任务操作：指派（lead）/领取与状态流转（expert，pending→in_progress→done/cancelled）/`transitions` append 留痕

## 2. Web 工作台

- [x] 2.1 路由组 `src/web/routes/authoring.py`：`/workbench/{domain_key}` 五个面（概览/浏览/编辑/事件/任务），RBAC 按 design D4（读 annotator 起、写 expert 起、指派 lead 起，两道序贯）
- [x] 2.2 Jinja 页 + i18n 双语（`workbench.*` 命名空间）；导航「我的域」每域加工作台入口；出表 kind 浏览 404
- [x] 2.3 词表驱动的表单：实体/关系表单的 kind 下拉来自域模板词表，关系表单结构化选择 from/to

## 3. 测试

- [x] 3.1 词表执法：词表内创建成功（raw 起步、operator 入溯源）、出表 kind 拒绝且零 KU 零事件、域不存在拒绝
- [x] 3.2 域隔离写作：A 域创作仅落 A namespace、B 域成员任何请求零见 A 内容、跨域写 403
- [x] 3.3 事件流：create/update/delete 三 op 留痕（before/after 完整）、事件与内容同事务（事件失败写入回滚）、append-only（无更新路径）
- [x] 3.4 任务：指派→领取→完成全程 transitions 留痕、annotator 指派被拒、非成员工作台 403
- [x] 3.5 工作台 RBAC：读/写/指派三档角色边界 + admin 直通

## 4. 收口

- [x] 4.1 全量既有测试零回归 + `openspec validate add-expert-authoring-surface --strict` 绿
- [x] 4.2 blueprint 台账更新（C2 状态）与 tasks.md 勾选对账
