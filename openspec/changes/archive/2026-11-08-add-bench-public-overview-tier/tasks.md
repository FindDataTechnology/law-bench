# Tasks: add-bench-public-overview-tier

## 1. 摸底与豁免机制确认

- [x] 1.1 读 `src/web/public_app.py` exempt-path 短路实现与 `/healthz` 豁免注册点，确认豁免清单的 app 级注入方式（D1）
- [x] 1.2 读 `src/web/deps.py` `get_current_user` 确认 exempt 判定精确匹配语义（非前缀）
- [x] 1.3 读 `src/web/rate_limit.py` 确认 per-IP 桶 API 与现有默认配额档

## 2. 概览端点实现

- [x] 2.1 新建 `src/web/routes/public_overview.py`：载荷组装（`as_of` = 发布状态快照时间；`ontology_versions` 读 `knowledge-distribution` 发布版本记录；分层计数复用 promotion 统计；不建新表）
- [x] 2.2 载荷字段最小化审查：无语料正文、无客户身份、无内部主机/凭据字段
- [x] 2.3 降级路径：读库失败 → 503 `{"error", "reason"}`；不回退缓存
- [x] 2.4 `public_app.py`：挂载 router + 豁免清单注册精确路径 `/api/public/overview`；套 per-IP 限流；origin `app.py` 不注册豁免

## 3. 测试

- [x] 3.1 匿名 200 载荷契约测试（含 legal v1 版本/digest/counts 结构、无正文断言）
- [x] 3.2 豁免不蔓延测试：sibling 路径（`/api/public/overview/x`、`/api/contracts`、`/samples`）匿名一律 401
- [x] 3.3 origin app 同路径匿名 401 测试（豁免未注入）
- [x] 3.4 豁免清单缺条目 → 默认 401（fail-closed）测试
- [x] 3.5 限流测试：超限 429 + `Retry-After`；持 key 同样受限
- [x] 3.6 降级测试：库不可达 503 报因、`as_of` 不取当前时钟
- [x] 3.7 digest 与分发面发布版本对账测试

## 4. 门与收尾

- [x] 4.1 `openspec validate add-bench-public-overview-tier --strict` 过绿
- [x] 4.2 公共 hygiene 门（`scripts/check_public_hygiene.py`）过——新代码无内部资产泄漏
- [x] 4.3 部署注记：公共 pod 滚版（argocd 既有线）；下游 `add-bench-chain-website` 的 Caddy 同源代理以本端点为准
