## ADDED Requirements

### Requirement: 取文档进本体只走内核写路径

从目录取一份文档 SHALL 通过内核创作接口（`authoring_create_unit`）写入一条文档类单位，MUST NOT 直接写 `knowledge_units`。单位键 SHALL 按该域的归一规则由文档标题构造；`attrs` SHALL 记录语料侧标识（库、来源、文档 id、块数、发布日、状态）与证据（至少一个 `chunk_id` 和一段逐字引用）。

#### Scenario: 取入一部法
- **WHEN** 成员对「中华人民共和国宪法」点击「取入本体」
- **THEN** 产生一条 `law` 单位，键为归一名，`attrs.corpus` 记下 `law-library`/`statutes`/`law_id`，并带该文档语料块的逐字引用作为证据

#### Scenario: 重复取入幂等
- **WHEN** 同一份文档被取入第二次
- **THEN** 不产生第二条单位；返回既有单位并标注「已在本体」

#### Scenario: 词表外类型被拒
- **WHEN** 域模板未声明该文档类型对应的实体类型
- **THEN** 写入被内核拒绝并报出允许的词表，不落半条数据

### Requirement: 条款切分是确定性的，且如实标记截断

对已取入的文档取条款时，系统 SHALL 用既有的条款识别规则（只认 `第N条`）在文档原文上**确定性切分**，每条单位 `body` SHALL 是条文原文（逐字，不概括、不改写），键 SHALL 为 `<law_key>#<clause_no>`，`attrs` SHALL 记录 `law_key`、`clause_no` 与承载它的 `chunk_id`。跨语料块的条文 SHALL 按语料顺序拼接；拼接不完整时 SHALL 标 `truncated=true` 并说明缺哪一段，MUST NOT 以完整形式呈现。

#### Scenario: 一条一块
- **WHEN** 「劳动合同法#第39条」的条文完整落在两个相邻块里
- **THEN** 产出一条 `clause` 单位，`body` 为两块的原文按序拼接，`truncated` 不为真

#### Scenario: 切不出条款
- **WHEN** 文档是单条式决定、正文没有任何 `第N条`
- **THEN** 返回 `clauses=0` 与原因 `no_clause_headers`，不产出任何条款单位

#### Scenario: 章节名不被当条款
- **WHEN** 正文出现「第二章　合同的订立」
- **THEN** 不产生条款单位

### Requirement: 批量取用有上限且说明跳过原因

单次取条款 SHALL 有上限（默认 200 条），达到上限 SHALL 报告 `capped` 与剩余条数。每次取用 SHALL 取「尚未在本体中的条款」，使重复点击持续收敛而 MUST NOT 反复重写同一批；已全部取用时 SHALL 报 `nothing_new`。批量写入 SHALL 具备事务性：任一条被内核拒绝时整批回滚，并报出被拒的那一条与原因，MUST NOT 写入一部分。

#### Scenario: 超限
- **WHEN** 某法有 300 条条款而单次上限是 200
- **THEN** 写入 200 条，返回 `capped=true` 与 `remaining=100`，由人再点一次

#### Scenario: 中途被拒
- **WHEN** 批次中某条条款键不合规则
- **THEN** 整批不落库，返回该条与拒绝原因

### Requirement: 取用后可支撑概念的定义关系

条款单位存在后，抽取产出的 `defines` 关系 SHALL 能以该条款键为合法端点；此前因端点不存在而被计为 `bad_endpoint` 的情形 SHALL 相应减少。该闭环 SHALL NOT 依赖抽取逻辑的改动。

#### Scenario: 概念挂上条款
- **WHEN** 某法第 585 条已取入本体，抽取产出「违约金调整 defines 合同法#第585条」
- **THEN** 该候选作为关系提案进入复核队列，而不是被计为端点缺失

### Requirement: 关系候选必须能指向别的文档的条款

关系端点的条款地址 SHALL 支持显式 `<文档名>#<第N条>` 形式，且 SHALL 落到与本地语料相同的键（`<law_key>#<第N条>`）。只写条文号时 SHALL 继续按当前语料块所属文档归属。该形式 SHALL 由提示词告知模型。

#### Scenario: 从案例抽出的概念挂到法典条文
- **WHEN** 语料块是一份裁判文书，候选给出 `defines`，to_name 为「<文档名>#<第585条>」且该条文已在本体
- **THEN** 关系作为提案进入复核队列，而不是被计为端点缺失

#### Scenario: 只写条文号仍按块归属
- **WHEN** 语料块属于某部法，候选只写「第十二条」
- **THEN** 键为该法下的条款，不会去猜别的文档
