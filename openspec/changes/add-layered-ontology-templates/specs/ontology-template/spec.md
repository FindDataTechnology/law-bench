## MODIFIED Requirements

### Requirement: 模板三件套与 schema 完整性

平台 SHALL 以结构化记录承载领域本体模板，模板 SHALL 包含三件套：本体 schema（实体类型词表、概念结构定义、关系种类词表、知识档位 tier 与 sensitivity 词表）、语料模板声明（语料源类型与组织约定，声明级，不含语料本身）、审核 rubric 引用（可指向既有 rubric 库条目）。本体 schema 的四类词表 SHALL 为必填；缺失任一必填项的模板 SHALL NOT 可被实例化。

**继承约束**：模板 SHALL 可声明 `extends`（指向另一模板的某个具体版本），继承其四类词表与概念结构。继承后子模板 SHALL 只能**增补**词表项，SHALL NOT 删除或重命名父模板的项；同一词表项在父子冲突时 SHALL 以子模板为准并在模板详情中标注覆盖来源。实例化前 SHALL 校验**继承后的有效词表**完整（而非仅校验子模板自身的增量）。

**分层约束**：模板 SHALL 另声明 `layer`（闭集见 `ontology-template-layering`）与 `authority`（`platform` 或 `external`）。`extends` 两端 SHALL 同层，跨层继承 SHALL 被拒绝；跨层语义关联 SHALL 只能以 `aligned_with` 声明且不合并词表。`authority: external` 的模板 SHALL NOT 接受词表就地修改。

#### Scenario: 合法模板可保存并展示
- **WHEN** 平台管理员提交含完整四类词表与语料声明的模板
- **THEN** 模板保存成功并出现在模板列表，详情页可读全部三件套内容

#### Scenario: 缺词表模板拒绝实例化
- **WHEN** 对一个缺少档位词表的模板发起实例化
- **THEN** 实例化被拒绝并报明缺失项，不产生域

#### Scenario: 子模板只增不删
- **WHEN** 子模板 `extends legal-domain v1` 但尝试移除父模板的实体类型 `clause`
- **THEN** 模板保存被拒绝并报明「继承项不可删除」

#### Scenario: 继承后的有效词表
- **WHEN** 子模板在父模板基础上新增实体类型 `claim`
- **THEN** 以子模板实例化的域，其有效实体类型为父模板全部类型 + `claim`，且模板详情标出 `claim` 为本域新增

#### Scenario: 缺层声明拒绝保存
- **WHEN** 提交一份没有 `layer` 的模板
- **THEN** 保存被拒绝并报明缺失的层声明

## ADDED Requirements

### Requirement: 模板声明的作用域与可读性

模板详情 SHALL 展示其层、权威出处、继承链（若有）与跨层对齐声明。继承链 SHALL 标出每一跳的模板名与版本，使读者能回答「这个类型是从哪一层来的」。

模板的层与权威 SHALL 可被机器读面按域查询，MUST NOT 只能从模板详情页目视读取。

#### Scenario: 详情展示分层来源
- **WHEN** 查看一份 `extends foundation-v1` 的行业模板详情
- **THEN** 详情标出层为 `industry`、权威为 `platform`、继承链含 `foundation-v1`，并逐项标出哪些类型来自父层

#### Scenario: 机器读面可查层与权威
- **WHEN** 以域为参数调用模板元数据读面
- **THEN** 返回层与权威标识，无该域时如实报无而不是返回空对象
