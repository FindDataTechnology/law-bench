# 提案：知识发布-拉取分发契约（C3，P1）

## Why

C1/C2 落了平台的地基与生产面，但平台还没有「分发」：专家维护的本体内容出不了平台，消费者（wire 是第一个）拿不到版本化快照。总纲（`docs/knowledge-platform-blueprint.md`）的分发契约是平台与消费者的唯一细线——版本化发布（digest+changelog）+ 拉取 API + 松耦合铁律；P1 交付判据「wire 拉到 v1 本体快照并落库」直接依赖本 change。同时，现行 `bench-platform` spec「wire 为实体身份主键源」条款与总纲裁定的权威源翻转（bench=发布本体权威源，wire=seed 原料源+拉取方）不能共存，须随本 change 显式修订。

## What Changes

- **发布（publish）**：领域负责人/平台管理员将域的本体内容（KU 按域聚合，排除软删项）发布为不可变版本快照（单调版本号 + digest（规范 JSON sha256，沿 wire 0049 模式）+ changelog（相对上一版的 +1/-1/改动摘要））；同 digest 静默幂等；发布快照不可改写不可删除。
- **消费者登记（consumers）**：平台管理员登记消费者（名称、绑定域、机器凭据哈希——`X-Consumer-Token` sha256 只存哈希，沿 C1 邀请令牌纪律）；消费者只能拉取其绑定域的已发布版本。
- **拉取 API（pull）**：机器通道 `GET /api/v1/distribution/{domain_key}/ontology`（头 `X-Consumer-Token`），支持指定版本或缺省最新，json/yaml 双格式，载荷含 domain/template 版本/发布版本/digest/实体与关系全量；无凭据/未登记/域不匹配一律 fail-closed 401/403 如实区分。
- **主键源条款修订（bench-platform）**：「wire 为实体身份主键源（知验台不另存本体身份）」修订为「wire 为 seed 原料源；已发布本体的权威源是平台」；升格-回写环语义保留（seed 喂入+质量闸），gold 回写 wire 的场景降为「面向 seed 源的档位回写」。
- **非目标（本仓）**：wire 侧拉取客户端与本地落库是 fd-wire 仓的姊妹 change（本 change 只保证拉取面契约稳定可被消费）；RAG 语料发布（C4）；金集发布（后续）；拉取面缓存/限流（后续按需）。

## Capabilities

### New Capabilities

- `knowledge-distribution`: 发布-拉取分发契约——版本化发布、消费者登记、机器拉取面、digest 幂等与 fail-closed 鉴权

### Modified Capabilities

- `bench-platform`: 「柏讯实体升格契约」需求修订——身份权威源从 wire 翻转为平台（wire 降为 seed 原料源），升格回写环语义保留

## Impact

- **代码**：`src/bench/workspace_store.py` 扩两表（`ontology_publications`、`distribution_consumers`）；`src/bench/distribution.py`（新内核模块：digest/发布/快照读取/changelog，沿 wire 0049 模式与 authoring 的词表执法风格）；`src/web/routes/distribution.py`（拉取 API，机器凭据不走 Logto 会话）；`tests/conftest.py::_ALL_TABLES` 补两表。
- **既有行为**：C1/C2 全部面零变化；human-review/promotion 零变化；升格-回写环（wire-connector 消费侧）零变化——本 change 只增发布-拉取，不动 connector。
- **测试**：digest 稳定性（键序/浮点/时间戳排除）、发布幂等与版本单调、快照不可变、changelog 正确性、消费者鉴权三态（无凭据 401/未登记 403/域不匹配 403）、payload 完整性（实体+关系+模板版本锚定）。
- **依赖**：发布内容锚定 C2 的 KU namespace 约定与关系键模板（`{from}->{kind}:{to}` 是消费者侧身份对齐的契约锚）。
