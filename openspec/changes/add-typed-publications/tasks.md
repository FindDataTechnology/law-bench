# Tasks: add-typed-publications

> 依赖：`add-fleet-execution-loop` 的消费者登记（`kind='fleet'`）。
> 铁律：既有 `publish_domain()` 与 `GET /api/v1/distribution/{domain}/ontology` 的行为、载荷字段集、digest 计算**一行不改**；测试要断言它们逐字节不变。

## 0. 前置

- [ ] 0.1 取证：生产 `law_bench` 上既有 `ontology_publications` 的版本数与 digest 清单（判据＝真实行），作为「本体契约未被改动」的基线
- [ ] 0.2 读 `packs/legal/asset_catalog.py` 与 `domain_assets.register_providers`，把发布投影契约写成 `docs/asset-publication-contract.md`（字段、排序键、形状版本、示例）
- [ ] 0.3 DDL：`asset_publications`（`domain_id`, `asset_kind`, `version`, `digest`, `shape_version`, `manifest`, `changelog`, `published_by`, `published_at`；唯一 `(domain_id, asset_kind, version)` 与 `(domain_id, asset_kind, digest)`，append-only）与 `asset_pull_events`（消费者、域、种类、版本、时间）；进 `ensure_schema`
- [ ] 0.4 `tests/test_boot_schema.py` 扩：空库跑 boot 后两表就位、重复执行幂等

## 1. 种类注册与投影

- [ ] 1.1 `src/bench/publication_kinds.py`：`register_kinds()` / `list_kinds()` / `resolve(kind)`；契约与 `domain_assets` 的 provider 同形（自包含 SELECT + `label_key` + `sort_key` + `shape_version`）
- [ ] 1.2 未注册种类在两处（发布、拉取）都拒绝并列出已注册种类；MUST NOT 返回空清单
- [ ] 1.3 `packs/legal/asset_catalog.py` 增 `rubric` 与 `sample` 的发布投影（取该域书架上该种类的条目，投影键 + 名称 + 内容摘要）
- [ ] 1.4 内核纯度测试：`src/bench/publication_kinds.py` 不出现任何行业字符串；未装 pack 时 `list_kinds()` 为空而进程正常启动

## 2. 发布

- [ ] 2.1 `src/bench/distribution.py` 新增 `publish_asset_kind(conn, *, domain_key, asset_kind, published_by)`：取投影 → 调既有 `canonical_digest()` → 版本单调 → 幂等 → changelog
- [ ] 2.2 digest 复用断言：单测里对同一份投影内容分别调 `publish_asset_kind` 的内部构造与 `canonical_digest`，两次 digest 逐字节相等
- [ ] 2.3 形状版本位于载荷之外、不进 digest；单测：只改 `shape_version` 时 digest 不变、载荷内声明变化
- [ ] 2.4 空内容拒绝：该种类零条目时发布被拒并报明，不产生空版本
- [ ] 2.5 幂等：同内容再发布返回既有版本，行数不变
- [ ] 2.6 变更日志：新增 / 删除 / 变更三类条目，变更带字段级摘要；首版记初始清单
- [ ] 2.7 发布不影响归属：单测断言发布前后 `domain_assets` 行数与该资产的归属域集合不变

## 3. 拉取面

- [ ] 3.1 `src/web/routes/distribution.py` 新增 `GET /api/v1/distribution/{domain_key}/{kind}`（`kind` 走注册表解析，非 `ontology` 才走新路径；`ontology` 保持原路由优先级不变，避免遮蔽）
- [ ] 3.2 三态鉴权复用既有实现（不复制一份）：401 / 未登记或吊销 403 / 越域 403
- [ ] 3.3 拉取足迹：成功才写 `asset_pull_events`；失败与未匹配不写
- [ ] 3.4 单测：成功拉取留足迹、越域 403 不留足迹、吊销 403 不留足迹、未注册种类 400 并列出可用种类
- [ ] 3.5 回归断言：`GET /api/v1/distribution/{domain}/ontology` 的响应字段集合与 digest 与基线逐字节一致

## 4. 控制台

- [ ] 4.1 发布区列三类（本体 / 尺子 / 金集），各自版本、digest、发布时间、历史列表；缺数据的种类显示自己的空态
- [ ] 4.2 发布按钮按种类分开，MUST NOT 一次发布三类
- [ ] 4.3 消费层显示按种类的最近拉取足迹

## 5. 验收

- [ ] 5.1 真库演练：legal 域发布 `rubric` 一版，用已登记消费者拉取，比对 digest
- [ ] 5.2 回归：本体发布/拉取/幂等/换底 digest 五条既有场景全绿
- [ ] 5.3 `openspec validate add-typed-publications --strict` 绿
- [ ] 5.4 `acceptance.md`：逐条判据 + 真库读数

## 6. 挂账

- [ ] 6.1 RAG 语料发布（蓝图三类的第三类）——语料有独立生命周期与体积问题，另立
- [ ] 6.2 跨域合并发布——无业务需求
- [ ] 6.3 把 `ontology_publications` 统一进 `asset_publications`——明确不做，理由见 proposal 末节
