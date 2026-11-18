## MODIFIED Requirements

### Requirement: Rubric and Criterion Storage

The system SHALL store evaluation rubrics and their criteria in a PostgreSQL database addressed by the `database_url` environment variable. Each rubric SHALL have a name, context, source, source_path, and description. Each criterion SHALL belong to exactly one rubric and SHALL have a name, description, guidance, and ordinal. The combination of rubric and criterion name SHALL be unique.

**This change adds domain ownership**: each rubric SHALL belong to exactly one domain (`domain_id`); a rubric with no domain SHALL NOT be creatable. Rubrics SHALL be inheritable: a child domain SHALL see its parent domain's rubrics as effective (read-only) standards, and MAY fork one, in which case the fork SHALL record the parent rubric it derives from plus a human-readable difference summary. Scoring and run statistics SHALL be attributed to the domain that owns the rubric used.

#### Scenario: Store a harbor rubric with its criteria
- **WHEN** the extraction script runs against harbor's `default-rubric.toml` for the legal domain
- **THEN** a `task_quality` rubric row is stored with `source = harbor:v0.20.0`, `context = check`, `domain_id` = the legal domain, and `source_path` pointing at the harbor TOML file
- **AND** each of its 11 criteria is stored with name, description, and guidance

#### Scenario: Query criteria of a rubric
- **WHEN** a caller queries criteria by rubric name within a domain
- **THEN** all criteria for that rubric are returned ordered by `ordinal`

#### Scenario: 子域继承父域 rubric
- **WHEN** 子域 `legal/contract-review` 查看可用评测标准
- **THEN** 父域 `legal` 的 rubric 出现在「继承自父域」分组中，可用但不可在本域编辑

#### Scenario: fork 必须留差异
- **WHEN** 子域对某父域 rubric 发起 fork 并修改了其中 2 条判据
- **THEN** 新 rubric 记录 `derived_from` 指向父域 rubric，并保存本次差异摘要（哪几条判据被改、改成什么）

## ADDED Requirements

### Requirement: Rubric 与域的解析一致性

评测执行 SHALL 按「域的有效 rubric 集合」解析：该域自有 rubric 优先，其次沿父域链继承；同名 rubric 在子域存在时 SHALL 以子域为准。评测运行记录 SHALL 保存实际使用的 rubric 与其所属域，使「某域最近一次评测」可被确定地回答。

#### Scenario: 同名以子域为准
- **WHEN** 子域存在与父域同名的 rubric 且发起评测
- **THEN** 采用子域那条，运行记录标明的 rubric 所属域为子域

#### Scenario: 按域统计运行结果
- **WHEN** 查询某域的评测历史
- **THEN** 只返回该域（含从其父域继承的 rubric）产生的运行，不混入兄弟域的结果
