# knowledge-distribution Specification（delta）

## Purpose

平台与消费者的唯一细线：版本化发布（digest+changelog）、消费者登记、机器拉取面。松耦合铁律——消费者拉取快照落本地独立处理，平台不依赖消费者反向实时输入。总纲见 `docs/knowledge-platform-blueprint.md`（C3）。

## ADDED Requirements

### Requirement: 版本化发布

领域负责人（或平台管理员）SHALL 可将其成员域的本体内容发布为不可变版本快照：单调发布版本号、digest（规范 JSON 的 sha256，键序归一、排除生成时间戳）、全量 manifest（模板版本锚定、实体与关系全量、排除软删项）；同 digest 重复发布 SHALL 幂等（静默返回既有版本，不产生新行）；快照发布后 SHALL 不可改写不可删除；变更事件流与发布流水 SHALL 可对账（发布的每条内容可回指其事件史）。

#### Scenario: 发布产生可拉取版本
- **WHEN** 领域负责人对其域执行发布且域内有词表内实体与关系
- **THEN** 产生新发布版本（版本号单调、digest 稳定、manifest 含实体与关系全量并锚定模板版本），软删项不出现在 manifest

#### Scenario: 同内容重复发布幂等
- **WHEN** 内容零变更时再次执行发布
- **THEN** 返回既有版本与既有 digest，不产生新快照行

#### Scenario: 空域发布拒绝
- **WHEN** 对没有任何词表内内容的域执行发布
- **THEN** 发布被拒并报明域内无内容，不产生空版本

### Requirement: 变更日志

每次新发布 SHALL 相对上一发布版本产生 changelog（新增/删除/变更三类条目，实体与关系逐条，变更条目含字段级差异摘要）；首版 changelog SHALL 记为初始清单；消费者可经拉取面获取任一版本的 changelog。

#### Scenario: 二版携带差异
- **WHEN** v1 发布后专家新增一条实体并修改一条关系，负责人发布 v2
- **THEN** v2 changelog 含 1 条新增实体条目与 1 条变更关系条目（字段级摘要），v1 changelog 保持初始清单不变

### Requirement: 消费者登记与机器凭据

平台管理员 SHALL 以登记制准入消费者（名称、绑定域列表、机器令牌——仅存 sha256 哈希，明文只在创建时展示一次）；消费者 SHALL 只能拉取其绑定域的已发布版本；令牌 SHALL 可吊销（吊销即时失效）；凭据纪律沿平台既有脱敏规则（日志与错误永不携带明文）。

#### Scenario: 登记与吊销
- **WHEN** 管理员为消费者 wire 登记绑定域 legal 并签发令牌，随后吊销该令牌
- **THEN** 吊销前该令牌可拉取 legal；吊销后同令牌请求被拒（403 如实报「令牌已吊销」）

### Requirement: 机器拉取面

平台 SHALL 提供机器通道拉取端点（`GET /api/v1/distribution/{domain_key}/ontology`，头 `X-Consumer-Token`），支持指定版本或缺省最新，json/yaml 双格式（`format` 参数，缺省 json）；载荷 SHALL 含 domain、模板版本锚定、发布版本与 digest、实体与关系全量（含 tier/sensitivity 标记与关系结构化 from/to）；鉴权 SHALL 三态如实区分：无凭据 401、令牌未登记或已吊销 403（报明）、令牌有效但域不在其绑定范围 403（报明）；拉取面 SHALL NOT 依赖 Logto 交互会话。

#### Scenario: 消费者拉取最新版
- **WHEN** 已登记消费者以有效令牌请求其绑定域的最新本体
- **THEN** 收到 200 载荷（发布版本、digest、实体与关系全量含档位标记），格式为请求的 json 或 yaml

#### Scenario: 指定历史版本
- **WHEN** 消费者请求 v1 而当前已到 v2
- **THEN** 收到 v1 快照内容与 v1 digest，与 v1 发布时的 digest 逐字节一致（快照不可变）

#### Scenario: 越域拉取拒绝
- **WHEN** 绑定域仅 legal 的消费者令牌请求 domain_key=fin
- **THEN** 403 报明该域不在绑定范围，fin 的任何内容零出现

### Requirement: 发布面向词表执法的契约锚

发布 manifest 中的实体与关系 SHALL 携带发布时的域模板版本锚定；关系键 SHALL 沿用创作面的确定性键约定（`{from_key}->{kind}:{to_key}`），使消费者可据以重建身份对齐；模板词表或键约定的变更 SHALL 出新发布版本而非就地改写历史快照。

#### Scenario: 消费者侧身份重建
- **WHEN** 消费者解析 manifest 中的关系条目
- **THEN** 依据关系键约定与结构化 from/to 可重建两端身份，无需第二套身份解析逻辑
