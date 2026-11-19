## 1. crosswalk 单元与校验

- [x] 1.1 新建 `src/bench/crosswalk.py`：三种关系种类闭集、端点两形态校验、`validate_crosswalk(attrs) -> list[str]` 纯函数；验证：新增 `tests/test_bench_crosswalk.py`，`relation="equivalent"` 被拒且列出三值、`external_id` 缺 `system` 被拒、`ontology` 形态合法通过
- [x] 1.2 方向派生：给定对端查询反向映射，不写反向行；验证：用例断言反向查询返回本端且 `knowledge_units` 行数在查询前后不变
- [x] 1.3 `role_of` 方向语义固定（角色实体 → 目标实体）；验证：用例断言 `customer:acme --role_of--> organization:acme-corp` 校验通过，反向提交被拒

## 2. 提案路径与低置信挂起

- [x] 2.1 `src/bench/proposals.py` 接受 `kind='crosswalk'`，端点闭合校验（对端为 `ontology` 形态时端点须存在，否则按 `endpoint_open` 拒）；验证：用例提交缺端点候选被拒并计入 `endpoint_open`，不进入复核队列
- [x] 2.2 缺 `confidence` 按低置信处理（fail closed）；验证：用例提交无 confidence 的提案并确认后状态为「待复核」，不计入映射覆盖率
- [x] 2.3 自提自确认拒绝；验证：用例同一身份提交并确认被拒

## 3. 三态证据与兼容读面

- [x] 3.1 `connectivity` 三态校验 + 过期判定（域级阈值，未配置则不过期并注明）；验证：`tests/test_bench_crosswalk.py` 三用例——缺 live 报未接通、证据过期退回缺失、三态齐备可声明接通
- [x] 3.2 兼容读面 `GET /api/d/{domain}/crosswalks/connectivity/{system}` 返回与 `connector-status.json` 同形结构；验证：用既有 8 个 provider 的本地文件造一份 fixture，断言读面输出与文件逐字段一致
- [x] 3.3 存量导入脚本（幂等）：把 8 个 provider 的三态证据写成 crosswalk 行的 `connectivity`；验证：连跑两次 KU 行数不变，字段逐字段与源文件一致

## 4. 边界：crosswalk 不是关系

- [x] 4.1 关系图谱遍历、端点闭合校验、参照完整率三处排除 `kind='crosswalk'`；验证：用例建 10 关系 + 20 crosswalk，断言参照完整率分母为 10、从实体出发的遍历结果不含 crosswalk 对端
- [x] 4.2 关系的端点校验不放宽；验证：用例建一条端点在本域不存在但有 crosswalk 指向的关系，断言仍被拒且错误说明端点不存在
- [x] 4.3 读面两个查询分开（关系 vs 映射），返回结构不同且映射查询带关系种类/对端形态/复核状态；验证：路由测试断言两个响应的键集合不同

## 5. 质量比与缺口

- [x] 5.1 `estate.py` 增加「映射覆盖率」：按实体计数、只计已复核且未过期；验证：`tests/test_bench_estate.py` 两用例——10 实体 4 有映射显示 4/10、唯一映射待复核的实体不计入分子
- [x] 5.2 两类缺口独立报出：`quality:crosswalk_stale` 与 `quality:crosswalk_unconfirmed`；验证：用例构造同时含 3 条过期与 5 条未复核，断言报两项独立计数不合并
- [x] 5.3 两类缺口路由到 `fleet`，聚合键「域 + 外部系统」，重复派单报「已指派」；验证：用例断言路由结果与重复派单行为

## 6. 协议侧对齐声明

- [x] 6.1 `fd-open-data-protocol` 新增 `vocabulary/alignment/foundation.yaml`（`company → organization`、`city → place` 等映射），不改六个既有词表文件；验证：`git diff --stat` 只显示新增文件；既有 golden digest 测试全绿
- [x] 6.2 读取该声明的入口函数（只读，无副作用）；验证：单元测试断言声明可解析、未声明时返回空集而不是抛错

## 7. ERP 侧切换（跨仓）

- [x] 7.1 `fd-erp-vertical-templates` 的 `connector-status.json` 生成器改为「先读知验台兼容读面，不可达时回退本地」，回退时输出标注 `source: local-fallback`；验证：本地单测两种路径（可达/不可达）各一例，不可达时输出含 `local-fallback`
- [x] 7.2 回退时不得静默使用过期数据：本地文件超过域级有效期时输出 `stale: true`；验证：单测构造过期本地文件，断言输出含 `stale: true` 且不报「已接通」

## 8. 验收

- [ ] 8.1 全量回归：`uv run pytest tests` 全绿（含 `tests/test_bench_crosswalk.py` 与既有 `test_bench_pack_domain_free.py`）
- [ ] 8.2 两侧同片验收：选一个真实外部系统（金蝶或 Shopify），在知验台与 `fd-erp-vertical-templates` 各查一次同一实体，两侧输出逐字段比对一致；验证：比对结果落盘到 `openspec/changes/add-crosswalk-seam/evidence/`
- [ ] 8.3 一条真链：舰队提名一条 crosswalk → 域负责人确认 → 状态为待复核（低置信）→ 复核后计入映射覆盖率 → 覆盖率在质量视图变化可见；验证：库里 KU 行、事件行、质量视图读数三处一致
