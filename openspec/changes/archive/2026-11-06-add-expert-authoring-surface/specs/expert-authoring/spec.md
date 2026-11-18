# expert-authoring Specification（delta）

## Purpose

领域专家创作面：在成员域内按模板词表创作与维护本体知识单元，写面走内核 KU 收口、域隔离以 namespace 承载、每次变更落事件流、工作按任务组织。总纲见 `docs/knowledge-platform-blueprint.md`（C2）。

## ADDED Requirements

### Requirement: 词表执法创作

领域专家/负责人在其成员域内 SHALL 可创作与维护本体知识单元（实体、概念、关系）；实体 kind SHALL 限定于该域模板 `entity_types` 词表、关系 kind SHALL 限定于 `relationship_kinds` 词表，出表写入 SHALL 被拒绝并报明词表约束；写面 SHALL 复用内核 KU 收口（`upsert_knowledge_unit`），SHALL NOT 另建第二套本体存储。

#### Scenario: 词表内创作成功
- **WHEN** 领域专家按域模板词表内的 kind 提交一条实体
- **THEN** KU 以该域 namespace 落库，tier 初始为 raw，操作者进入溯源

#### Scenario: 出表 kind 拒绝
- **WHEN** 提交的实体 kind 不在域模板 `entity_types` 词表内
- **THEN** 写入被拒绝，报明该域允许的词表，不产生任何 KU 或事件

### Requirement: 域隔离写作

创作台的全部内容读写 SHALL 以域为边界：KU 以域 key 为 namespace 落库，跨域读写沿用领域工作区执法（非成员 fail-closed）；任何域的内容 SHALL NOT 出现在无该域权限的响应中。

#### Scenario: 隔离写作
- **WHEN** A 域专家创作实体并随后在 A 域工作台浏览
- **THEN** 内容仅存在于 A 域 namespace 下；B 域成员的任何请求中不出现该内容

### Requirement: 变更事件流

创作与维护的每次增改删 SHALL 落 append-only 事件（op、target、before/after、操作者、时间、经手面），事件 SHALL 不可改写不可删除；创作台 SHALL 提供按内容聚合的事件查看；事件写入与内容写入 SHALL 同事务（事件失败则整个写入失败）。

#### Scenario: 变更留痕
- **WHEN** 专家修改一条实体的描述
- **THEN** 产生一条 update 事件，before/after 携带完整前后状态与操作者；原内容历史不受影响

#### Scenario: 事件不可篡改
- **WHEN** 检查事件表写路径
- **THEN** 无任何更新/删除事件行的代码路径（append-only 唯一写法）

### Requirement: 任务指派与工作台

领域负责人 SHALL 可向域内成员指派创作/核验任务（目标内容或词表条目、说明、状态：pending→in_progress→done/取消）；成员的工作台 SHALL 按任务组织（我的任务、域内容浏览、编辑入口、事件流查看）；任务状态流转 SHALL 留痕（谁在何时置为何态）。

#### Scenario: 指派到完成
- **WHEN** 负责人向某专家指派一条实体创作任务，专家在工作台领取并完成后置 done
- **THEN** 任务状态流转全程留痕，产出内容与任务关联可查

#### Scenario: 非成员不可见工作台
- **WHEN** 无域成员身份的已认证用户访问该域工作台
- **THEN** 请求被拒（fail-closed），该域任务与内容零暴露
