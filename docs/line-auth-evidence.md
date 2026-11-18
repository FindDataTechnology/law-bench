# LawBench（law-bench-internal 真源）线的授权与凭据证据

本文件是 `line-manifest.json` 被剥离的自由文本的**仓内**留存。原因：清单会随
`/.well-known/line-manifest.json` **匿名公开**（公开面由本真源的镜像供给，公开仓
law-bench 的清单只是副本），而规格（`openspec` 的 `line-manifest` 能力）规定清单
字符串键只能落在一个闭集里——闭集之外的自由文本（典型是 `note`）一律判违规。
下列内容含环境变量名、模块与行号、门实现位置，故只留在仓库内，不进公开载荷。

对外可见的那部分是产品语义：LawBench 合同智能 MCP——条款语料与装配 / 合同生成 /
法条引用 / 验证审查（commercial 面）+ 评测/rubric/对比/自愈/语料治理（internal 面）。

## 被剥离的 note（原文逐字，按清单路径索引）

### `<root>`

LawBench 合同智能 MCP（54 工具，24 个非只读）：条款语料与装配 / 合同生成 / 法条引用 / 验证审查（commercial 面）+ 评测/rubric/对比/自愈/语料治理（internal 面）。本仓是**真源**（公开仓 law-bench 只收导出提交）。`surfaces.admin=false`：internal 面（评测/rubric/语料治理）不由 scope 控制，而是启动期 `MCP_TOOL_DENYLIST` 物理摘除工具（server.py:101-125 `apply_tool_denylist`；点名不存在的工具会响亮退出）——所以它不是「管理面」，不能声明 `line:admin`。

### `identity`

本仓做**单串共享访问令牌**校验：`MCP_HTTP_TOKEN` 必填，缺则拒绝启动（server.py:166-170，「refusing to serve an unauthenticated MCP endpoint」）；`_TokenGuard` 恒时比对三种头来源（`X-Authorization` > `Authorization` > `X-API-Key`，server.py:39-99）。另有 `X-API-Key` 的 API 面门（api/middleware.py:29-32，`api_key_enabled` 才生效）。无断言兑换端点，jit_policy=off。

### `auth_tracks[]`

`MCP_HTTP_TOKEN` 一把共享钥匙（server.py:166-170 + `_TokenGuard` server.py:75-99）：摘掉平台后仍可直连 stdio/http 消费本线，故是回退轨。限制同其它线：全客户共用、不承载客户身份。直连 stdio 时不校验（stdio 由调用进程的信任边界保护）。

### `auth_tracks[]`

目标态：客户拿词元钥匙直打本线。今天只有与 `MCP_HTTP_TOKEN` 相等的串能过门。

### `billing`

本仓零计费代码（grep `sub2api` 无命中）：按调用扣费发生在网关/registry 的词元平面，不在本线代码里。本仓只记 agent_metrics（tools/agent_metrics.py 的调用指标），不是余额。
