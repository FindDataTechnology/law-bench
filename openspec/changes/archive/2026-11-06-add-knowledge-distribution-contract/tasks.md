# 任务：add-knowledge-distribution-contract

## 1. 数据层与内核模块

- [x] 1.1 `src/bench/workspace_store.py` 扩 `WORKSPACE_SCHEMA`：`ontology_publications`（append-only，UNIQUE (domain_id, version) 与 (domain_id, digest)）+ `distribution_consumers`（token_hash 唯一、revoked_at 软吊销），`tests/conftest.py::_ALL_TABLES` 登记
- [x] 1.2 `src/bench/distribution.py`：manifest 构造（域 KU 全量投影、排除软删、模板版本与词表锚定、关系键沿 `relationship_external_key`、sensitivity 从 tags 读取缺省 null）+ 规范 JSON digest（sort_keys、排除时间戳/发布者/版本号）+ 空域拒绝——实现裁定：条目按 external_key 排序使 manifest 成内容纯函数（同内容异插入序同 digest）、fetch limit 100k 防静默截断、attrs 缺 from/to 大声报错
- [x] 1.3 发布：同 digest 幂等返回既有版本、version=max+1、快照与 changelog 整体冻结（append-only 无更新路径）
- [x] 1.4 changelog：与上一版键控 diff（added/removed/changed 字段级摘要）、首版 initial 清单、随快照冻结
- [x] 1.5 消费者操作：登记（明文只现一次、存 sha256）、绑定域组替换、吊销即时失效（幂等）

## 2. Web 拉取面

- [x] 2.1 `src/web/routes/distribution.py`：`GET /api/v1/distribution/{domain_key}/ontology`（X-Consumer-Token，不经 Logto——`_EXEMPT_PREFIXES` 放行 + 路由自做三态令牌鉴权），version 缺省最新、format json/yaml（PyYAML 只进路由层），载荷 8 键形状已在模块 docstring 钉死（fd-wire 消费契约）；admin 侧消费者管理页 + 域详情发布面板（复用 admin.py 既有 handler 增 publications 上下文，C1 行为零变化）
- [x] 2.2 鉴权三态：缺凭据 401 / 未登记 403「令牌未登记」/ 已吊销 403「令牌已吊销」/ 越域 403「该域不在绑定范围」各自报明；无发布 404；`app.py` include、不挂 public_app

## 3. 测试

- [x] 3.1 digest 稳定性：同内容异序构造同 digest、时间戳/发布者不影响 digest、异内容异 digest
- [x] 3.2 发布语义：版本单调、同 digest 幂等零新行、空域拒绝、快照后继续编辑不影响已发版本（逐字节一致）、软删项不入 manifest
- [x] 3.3 changelog：二版 added/removed/changed 字段级摘要、首版 initial、历史 changelog 不随后续发布改写
- [x] 3.4 拉取面：三态鉴权各自报明、json+yaml 双格式、指定历史版本 digest 一致、越域零泄露、零会话机器面实证
- [x] 3.5 bench-platform 修订零回归：升格-回写环既有测试（promotion/connector 面）全绿

## 4. 收口

- [x] 4.1 全量回归 + `openspec validate add-knowledge-distribution-contract --strict` 绿
- [x] 4.2 blueprint 台账更新（C3 状态）与 tasks.md 勾选对账；wire 侧姊妹 change 挂账提示
