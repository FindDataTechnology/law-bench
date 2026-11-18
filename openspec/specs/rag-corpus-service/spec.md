# rag-corpus-service Specification

## Purpose

按域 RAG 语料服务：每域可登记自己的语料源（MinIO 桶+前缀）与 ES 索引，摄取按声明写入该域索引，检索按域隔离并经域成员授权。多领域平台的 RAG 承载面。总纲见 `docs/knowledge-platform-blueprint.md`（C4，P2）。

## Requirements

### Requirement: 域语料登记

每个领域 SHALL 可登记一份语料配置：ES 索引名、语料源清单（MinIO 桶+前缀列表）、嵌入模型声明位（缺省全域配置）；配置落 `rag_corpora` 表（域唯一约束）；登记与管理 SHALL 走 admin 面（`admin` 平台 scope）+ 该域 lead 合成执法；未登记语料的域 SHALL 无摄取与检索面（空集如实）。

**本变更修改为**：语料的单位 SHALL 从「域」上移为「库」（见 `shared-corpus-library`）。域 SHALL 通过订阅库获得语料，SHALL NOT 再登记自己的检索索引；`rag_corpora` SHALL 降级为兼容投影（由订阅推导得出），不再作为写入面。检索后端的类型 SHALL 由库声明，当前支持 `pgvector`；未声明后端的库 SHALL 拒绝创建。管理入口 SHALL 从「admin 域详情页」改为「域工作区的知识库区 + 库管理面」。

#### Scenario: 登记新域语料
- **WHEN** 平台管理员为某域登记索引名与语料前缀
- **THEN** `rag_corpora` 落行，该域的摄取与检索面激活

#### Scenario: 未登记域如实
- **WHEN** 查询/摄取一个未登记语料的域
- **THEN** 返回空集与「未登记」如实标记，不报错不越权建索引

#### Scenario: 域通过订阅获得语料
- **WHEN** 管理员为域 `legal` 订阅 `law-library` 的全部源
- **THEN** 该域的摄取与检索面激活，检索范围为该库全部源

#### Scenario: 未订阅域如实
- **WHEN** 查询/摄取一个未订阅任何库的域
- **THEN** 返回空集与「未订阅语料」如实标记，不报错也不回落到任何默认库

### Requirement: 域化摄取

摄取 SHALL 按域声明执行：从该域语料源拉取文档、分块、嵌入后写入**该域专属 ES 索引**（索引名与登记一致）；不同域的索引 SHALL 互相隔离（A 域摄取的内容不出现在 B 域索引或检索结果中）；摄取 SHALL 幂等（同语料重复摄取不产生重复块）。

**本变更修改为**：摄取 SHALL 按**库**执行一次（一库一套物理向量），写入该库声明的后端；每块 SHALL 携带作用范围标记与溯源元数据。域隔离 SHALL 由检索侧按订阅范围过滤实现，SHALL NOT 通过「每域一份物理索引」实现。摄取仍 SHALL 幂等（同源重复摄取不产生重复块），且 SHALL 在同一库内对同一文档的旧版本做替换而非追加。

#### Scenario: 两域隔离
- **WHEN** A、B 两域各自摄取各自的语料后分别检索
- **THEN** A 域检索结果仅含 A 域内容，B 域同理，零交叉

#### Scenario: 幂等摄取
- **WHEN** 同一域同语料重复摄取
- **THEN** 不产生重复块（重复文档按内容键去重或重建式替换）

#### Scenario: 一库一次摄取，多域共享
- **WHEN** `law-library` 的源完成摄取，两个子域都订阅了其中同一源
- **THEN** 该源只被向量化一次，两域检索到同一批块

#### Scenario: 幂等与替换
- **WHEN** 同一文档更新后重新摄取
- **THEN** 该文档的旧块被替换，库内不出现同一块的重复副本

### Requirement: 域化检索与授权

检索 API SHALL 支持域参数（缺省 legal 保持既有调用逐字兼容）；检索 SHALL 仅在被请求域的已登记索引上执行，结果仅含该域内容；检索 SHALL 经域成员授权（域内任一角色可读 + 平台 scope 两道序贯，非成员 fail-closed 拒绝）；管理面不受此限（admin 直通）。

#### Scenario: 域参数检索
- **WHEN** 带合法域参数与凭据检索
- **THEN** 结果仅来自该域索引

#### Scenario: 非成员检索拒绝
- **WHEN** 无该域成员身份的已认证用户请求该域检索
- **THEN** 请求被拒（fail-closed），该域内容零暴露

#### Scenario: 旧调用兼容
- **WHEN** 不带 domain 参数调用 `/api/search`
- **THEN** 行为与既有语义逐字一致（legal 域、可匿名时照旧——沿用现有路由的豁免语义不变）

### Requirement: 索引命名与后端边界

（新增约束）库的物理命名 SHALL 遵循 `lib_<library_key>` 约定并在库内唯一；同一个 embedding 维度 SHALL 由库声明且不可在运行期变更（维度不一致 SHALL 拒绝写入并要求显式重建）。跨库联合检索 SHALL NOT 在本版实现——一次检索 SHALL 只作用于一个库。

#### Scenario: 维度不一致拒绝
- **WHEN** 库声明的嵌入维度与实际产出维度不一致
- **THEN** 摄取被拒绝并报明维度冲突，已写入数据不受影响

#### Scenario: 跨库检索不支持
- **WHEN** 调用方请求同时检索两个库
- **THEN** 请求被拒绝并提示按库分别检索
