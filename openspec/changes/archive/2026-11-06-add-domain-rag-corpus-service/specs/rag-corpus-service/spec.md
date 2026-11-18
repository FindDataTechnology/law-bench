# rag-corpus-service Specification（delta）

## Purpose

按域 RAG 语料服务：每域可登记自己的语料源（MinIO 桶+前缀）与 ES 索引，摄取按声明写入该域索引，检索按域隔离并经域成员授权。多领域平台的 RAG 承载面。总纲见 `docs/knowledge-platform-blueprint.md`（C4，P2）。

## ADDED Requirements

### Requirement: 域语料登记

每个领域 SHALL 可登记一份语料配置：ES 索引名、语料源清单（MinIO 桶+前缀列表）、嵌入模型声明位（缺省全域配置）；配置落 `rag_corpora` 表（域唯一约束）；登记与管理 SHALL 走 admin 面（`admin` 平台 scope）+ 该域 lead 合成执法；未登记语料的域 SHALL 无摄取与检索面（空集如实）。

#### Scenario: 登记新域语料
- **WHEN** 平台管理员为某域登记索引名与语料前缀
- **THEN** `rag_corpora` 落行，该域的摄取与检索面激活

#### Scenario: 未登记域如实
- **WHEN** 查询/摄取一个未登记语料的域
- **THEN** 返回空集与「未登记」如实标记，不报错不越权建索引

### Requirement: 域化摄取

摄取 SHALL 按域声明执行：从该域语料源拉取文档、分块、嵌入后写入**该域专属 ES 索引**（索引名与登记一致）；不同域的索引 SHALL 互相隔离（A 域摄取的内容不出现在 B 域索引或检索结果中）；摄取 SHALL 幂等（同语料重复摄取不产生重复块）。

#### Scenario: 两域隔离
- **WHEN** A、B 两域各自摄取各自的语料后分别检索
- **THEN** A 域检索结果仅含 A 域内容，B 域同理，零交叉

#### Scenario: 幂等摄取
- **WHEN** 同一域同语料重复摄取
- **THEN** 不产生重复块（重复文档按内容键去重或重建式替换）

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
