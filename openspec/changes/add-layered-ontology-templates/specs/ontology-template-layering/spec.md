## Purpose

本体模板按层组织：每份模板声明自己属于哪一层、其词表的权威出处在哪，层内可继承、跨层只能对齐。这条能力让「同一个本体」在观测层（外部世界词表）、行业层（企业业务本体）、领域层（法律、政务）各自保持自己的权威与生命周期，同时保证消费方能判断两层的同名项是否同一件事。

## ADDED Requirements

### Requirement: 模板必须声明所属层且层是闭集

每份模板 SHALL 声明一个 `layer`，取值 MUST 在闭集 `foundation` / `observation` / `industry` / `domain` 内。层 SHALL 在模板的每个版本上都携带，且 SHALL NOT 在同一模板的后续版本间变更——换层 MUST 是新模板，MUST NOT 是升版。

未知层值 SHALL 在保存时被拒绝并列出闭集成员，MUST NOT 静默接受或以默认为某层。

#### Scenario: 未知层被拒
- **WHEN** 提交一份 `layer: "vertical"` 的模板
- **THEN** 保存被拒绝，错误列出四个合法层值，且不产生模板行

#### Scenario: 换层是新模板而非新版本
- **WHEN** 把一个 `industry` 层模板改为 `foundation` 层并保存
- **THEN** 操作被拒绝并提示须以新模板名创建；原模板版本链不变

#### Scenario: 层随版本保留
- **WHEN** 某 `industry` 模板从 v1 升到 v2
- **THEN** v2 的层仍为 `industry`，模板详情展示层不因升版变化

### Requirement: 层内可继承，跨层不可继承

模板 SHALL 允许 `extends` 指向另一模板的具体版本，继承其词表并按既有的「只增不删」规则合并。

**继承的判据是权威，不是层号。** `extends` 两端 SHALL 同属一种 `authority.kind`（`platform` / `external` / 未声明层的 `legacy` 伪权威）才允许合并；权威不同时 SHALL 拒绝，错误 SHALL 指明两端各自的层与权威，并指出正确做法。

这条按权威而非层号判定，是因为两者回答不同的问题：**层**排的是「多具体」（foundation → industry → domain），**权威**答的是「谁能发版」。foundation 层喂给 industry 层正是它存在的意义；真正不能合并的是「平台自有词表」与「外部包自有词表」——两者有各自的发布节奏，合并会强迫一侧接受另一侧的生命周期。

跨权威的语义关联 SHALL 以 `aligned_with` 声明表达，而不是继承。`aligned_with` SHALL 只声明「某类型与另一权威的某类型是同一概念」，MUST NOT 合并两侧词表，也 MUST NOT 使任一侧获得对方的类型。

#### Scenario: foundation 喂给 industry 是正常关系
- **WHEN** 一份 `platform` 权威的 `industry` 模板 `extends` 同样 `platform` 权威的 `foundation` 模板
- **THEN** 合并成功，有效词表为父层全部类型加子模板新增类型

#### Scenario: 外部权威不可被合并进平台词表
- **WHEN** 一份 `platform` 模板 `extends` 一份 `authority.kind=external` 的模板
- **THEN** 合并被拒绝，错误同时报出两端的权威并指出应改用 `aligned_with`

#### Scenario: 子模板必须列全继承项
- **WHEN** 子模板 `extends` 父模板但 `entity_types` 里没有列出父模板的某个类型
- **THEN** 合并被拒绝并点名该类型（防的是打错字把整个词表项悄悄丢掉）

#### Scenario: 跨层对齐不合并词表
- **WHEN** 观测层模板声明 `aligned_with: {target: foundation-v1, type_map: {company: organization}}`
- **THEN** 观测层模板的有效实体类型仍只有它自己的集合，`organization` 不出现在其词表中，别名映射可被读面查到

### Requirement: 模板必须声明词表权威出处

每份模板 SHALL 携带 `authority` 声明，指明其词表的权威源：`platform`（知验台自有，可在此编辑）或 `external`（外部包/协议持有，本平台只读）。`external` 权威 SHALL 携带来源标识与版本。

权威为 `external` 的模板 SHALL NOT 接受词表就地修改：任何改动 MUST 以重新导入一个新版本模板的方式发生，且 MUST 保留来源标识与版本。这是「协议是 PyPI 包、装完即用」与「模板是服务端记录」两种生命周期不互相绑架的唯一保证。

#### Scenario: 外部权威模板不可就地改词表
- **WHEN** 管理员尝试编辑一份 `authority: external` 模板的实体类型列表
- **THEN** 保存被拒绝并提示须重新导入新版本

#### Scenario: 重新导入产生新版本并保留来源
- **WHEN** 以协议的新发布版本重新导入观测层模板
- **THEN** 产生一个新版本，其 `authority.source` 与 `authority.version` 为新值，旧版本的词表逐字节不变

#### Scenario: 平台权威模板可编辑
- **WHEN** 管理员编辑一份 `authority: platform` 模板并保存
- **THEN** 产生新版本，其他域对该模板的锚定不变

### Requirement: 外部词表导入必须可重放且按内容幂等

从外部词表（当前为 `fd-open-data-protocol` 的已发布 YAML）导入模板 SHALL 是一条可重放的操作：同一份上游内容重复导入 MUST 命中幂等（不新增版本）；上游内容变化时 MUST 产生一个新版本并记录上游版本标识。

导入 SHALL 只读上游，MUST NOT 修改上游文件、MUST NOT 向上游写入任何内容。上游不可读时 MUST 硬失败并报明缺哪份文件，MUST NOT 产出一份空词表模板。

#### Scenario: 重复导入幂等
- **WHEN** 对同一协议版本连续导入两次
- **THEN** 第二次不新增模板版本，接口报「与既有版本一致」

#### Scenario: 上游变更产生新版本
- **WHEN** 协议发布新增了实体类型后重新导入
- **THEN** 产生新版本，新类型出现在其有效词表中，旧版本不受影响

#### Scenario: 上游缺失即失败
- **WHEN** 上游词表目录不可读
- **THEN** 导入以非零状态结束并点名缺失的文件，不写入任何模板行

### Requirement: 角色以关系表达而非新增实体类型

「客户」「供应商」「员工」这类身份 SHALL 以关系种类表达，指向一个通用实体类型（如 `organization`），MUST NOT 各自成为独立的实体类型。

这条约束的理由是跨系统对齐：同一家公司在不同外部系统中的记录需要收敛为同一个实体键，各自挂一条角色关系；若各自是类型，外部对齐就必须在类型之间做，而类型之间的映射没有稳定的落点。

模板 SHALL NOT 在同一层内同时存在以同一实体命名的类型与其角色关系（例如同时有 `customer` 类型与 `customer` 关系指向 `organization`）——这种双写 MUST 被模板校验拒绝并点名冲突的两项。

#### Scenario: 角色关系合法
- **WHEN** 一份行业模板声明 `organization` 类型与 `supplies`、`sells_to` 关系
- **THEN** 模板校验通过

#### Scenario: 类型与角色双写被拒
- **WHEN** 模板同时声明 `customer` 实体类型与指向 `organization` 的 `customer` 关系
- **THEN** 校验失败并点名这两项

### Requirement: 分层词表的有效集合必须可被读面完整回答

域实例化时 SHALL 按锚定模板的层解析其有效词表，且有效词表 SHALL 与模板声明逐项一致（不含被拒项、不静默补项）。读面 SHALL 能回答「某域的有效类型来自哪一层」，并 SHALL 区分「本层新增」与「父层继承」。

层间对齐关系 SHALL 可被读面查询：给定一个类型，读面 SHALL 能返回它在其他层声明过的对齐类型（若有），以及该对齐声明的来源模板版本。

#### Scenario: 有效词表分层可见
- **WHEN** 查看一份 `extends foundation-v1` 的行业域
- **THEN** 其有效类型列表标出哪些来自 `foundation`、哪些是本层新增

#### Scenario: 对齐关系可查
- **WHEN** 查询 `organization` 的跨层对齐
- **THEN** 读面返回观测层声明过的对应类型与其来源模板版本，未声明时返回空而不是猜测

#### Scenario: 已知边界显式呈现
- **WHEN** 子模板需要为父模板已声明的类型增补字段
- **THEN** 读面明确说明当前版本不支持字段级增补，需整条重写该类型，而不是静默丢弃增补
