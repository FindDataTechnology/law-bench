## MODIFIED Requirements

### Requirement: 评测结论必须指名对象与尺子

每条评测结论 SHALL 是一条可查询记录，至少包含：**被评对象地址**（`subject`：种类 + 键 + 版本）、**尺子地址**（`ruler`：种类 + 键 + digest）、通道、门、结局、逐条证据、判官身份（若走判官通道）、产生时间与产生者。

被评对象地址的版本 SHALL 能区分同一对象的不同代（同一份 pack 的 v3 与 v4 不是同一对象）；对象无内生版本时 SHALL 以其内容指纹或不可变快照标识充任，MUST NOT 留空或以「最新」代替。尺子地址 SHALL 携带与发布面同一份实现算出的 digest，MUST NOT 由本能力另写一份 digest 逻辑。

一条结论缺少对象地址或尺子地址时 SHALL 被拒绝写入，错误 SHALL 指明缺哪一项；MUST NOT 以空值落库后再由读面猜测。

被评对象的种类 SHALL 可取 `template`，用于本体模板作为被评对象。本能力 SHALL 导出该种类标识为常量，使「模板升版门」不必在代码里散落字符串字面量。

种类的取值集合 MUST NOT 收窄为闭集：既有 `docs/evaluation-system.md` 将其定义为「任意」，且生产里已有 `judge`（判官校准）与 `knowledge-units`（数据检查）两种取值；关集合会打死既有写入路径，而收益只是让一个字符串早一点报错。

#### Scenario: 缺对象地址拒绝写入
- **WHEN** 评测调用方未提供被评对象地址或版本为空
- **THEN** 写入被拒并指明缺项，台账不产生该行

#### Scenario: 同一对象的两代可区分
- **WHEN** 同一 pack 的 v3 与 v4 各有一条结论
- **THEN** 两条记录的对象地址不同，按对象聚合趋势时不会被合成一条线

#### Scenario: 尺子 digest 与发布面一致
- **WHEN** 某 rubric 已经由发布面发布并持有 digest
- **THEN** 以该 rubric 评出的结论所记 digest 与发布面返回的 digest 逐字节相等

#### Scenario: 既有对象种类零回归
- **WHEN** 以 `subject_kind="knowledge-units"` 写入一条数据检查结论
- **THEN** 写入成功，不因新增 `template` 种类而被拒

#### Scenario: 模板作为被评对象
- **WHEN** 对 `enterprise-base` v1 跑一次覆盖度评估并写入结论
- **THEN** 台账出现一行 `subject_kind=template`、`subject_key=enterprise-base`、`subject_version=v1`，其尺子地址由该模板 `rubric_refs` 解析结果派生
