# 域提案箱提交契约（`POST /api/d/{domain_key}/proposals`）

> 面向本平台自己的自动化（本体舰队的提案岗）与域内专家。C5（`add-domain-first-workbench`）
> 的提交面；P2 起取代「把本体草案塞进下游动作审批队列」的老路。
> 判据不是「代码里删了旧调用」，而是一轮真跑后**两侧计数对照**（见文末）。

## 一句话

一条草案 = 一个**可核对的属性主张**。它进的是这个域的提案箱，等域负责人确认；
确认后经内核唯一写入路径落进 `knowledge_units`。起草者不是确认者。

## 请求

```
POST /api/d/{domain_key}/proposals
Content-Type: application/json
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `source` | 是 | 提交方的稳定身份，跨轮不变。四类前缀各有信任依据，见「来源校验」；**它和 `external_key` 一起构成幂等身份** |
| `kind` | 是 | 必须在**该域锚定的模板版本词表**内（实体类或关系类）。出表一律 400，不会「先收下再看看」 |
| `external_key` | 是 | 实体的业务键。关系类按 `{from_key}->{kind}:{to_key}` 约定；URL 里要百分号编码 |
| `body` | 是 | 条目正文（给人和检索看的自然语言） |
| `evidence` | 是 | **确认时的唯一判断材料**。非空字符串，或非空 JSON 对象/数组。`null`/空串/`{}`/`[]` 一律拒绝 |
| `impact` | 否 | 影响说明，给人读的补充 |
| `submitted_by` | 否 | 提交者署名；缺省取调用身份（`email` 或 `name` 或 `sub`）。**自提自确认禁令按它判** |

`evidence` 可以是任意形状（URL、摘录、结构化字段），本层不解释内容，只在两种场合用它：
给人看，以及算**规范化摘要**——`sha256(JSON, sort_keys=True, separators=(",",":"), ensure_ascii=False)`。
所以键顺序不影响判定，两个月后另一个进程算出来的「同一份依据」和今天一致。

**关系类提案的额外要求**：提案行没有独立的端点列，`from_key` / `to_key` 随 `evidence` 一起进来
（也接受 `from` / `to` 简写），确认时内核据此派生关系键。缺任一端点 → 400
`relationship 提案的 evidence 缺少非空的 from_key/to_key 端点`；`evidence` 不是对象 →
`relationship 提案的 evidence 必须是对象并携带 from_key/to_key`。实体类提案没有这条约束。

## 响应

```json
{"id": 42, "state": "pending", "external_key": "ai-corp", "evidence_digest": "9f2c…", "created": true}
```

- `200` —— 新建（`created: true`），或命中同键已存在的 pending 行（`created: false`，
  **幂等命中**：返回既有行，不新增、不报错）。调用方按 `created` 报「新增 / 幂等命中」，
  两件事必须能分开，否则一轮的条数对不上。
- `400` —— 语义拒绝，`detail` 是中文原话，直接可以进报告：
  - `提案必须携带依据` —— 缺 `evidence` 或给了空容器
  - `kind '<k>' 不在模板 v<n> 词表内：entity_types=[…], relationship_kinds=[…]` —— 出表 kind
  - `同键已驳回，需新证据` —— 该键被驳回过，且这次的 `evidence_digest` 与上次相同
- `403` —— `missing scope: content:write`（平台权限不足）或 `无该域权限`（不是本域 expert）。
- `401` —— 没有身份。
- `422` —— 请求体不是 JSON 对象。

## 谁能提交

两道闸按顺序执行：`require_scope("content:write")`（Logto 平台权限）→ `require_domain_role("expert")`
（本域成员，且角色 ≥ expert）。平台 `admin`/`*` 绕过域闸。

**给舰队接线时的硬要求**：提交凭据的身份必须在目标域里是 expert。`X-API-Key` 或 Bearer 都能用，
但它们只解决「平台权限」那一闸，域成员关系仍以 `domain_members` 为准 —— 换凭据不换成员关系。

## 来源校验

`source` 的前缀决定它凭什么叫人相信。**四类，四种信任依据**，判定集中在
`src/bench/submitters.py`（纯函数，零 DB 依赖），两个调用点（进程内 / HTTP）各自传对
`via`：

| 前缀 | 形状 | 信任依据 | 能否走外部 HTTP |
|---|---|---|---|
| `fleet:` | `fleet:<fleet_id>/<post_id>` | **登记 + 凭据**：`distribution_consumers` 里一条 `kind='fleet'`、未吊销、绑定目标域 | 能（唯一能的一类） |
| `extract:` | `extract:<model>:<prompt_version>` | **调用位置**：抽取流水线在进程内调用，没有凭据可验 | **不能**，外部一律 403 |
| `agent:` | `agent:<role>@<domain>` | **已铸身份 + 域成员**：身份里的域须等于目标域、是该域活跃成员，且等于本次请求的认证身份 | 能（但只能是它自己） |
| `user:` | `user:<identity>` | **已认证身份**：必须等于本次请求的认证身份 | 能（但只能是它自己） |

拒绝一律 **403**，`detail` 是可读原话（不是 400：请求本身没问题，是调用方无权以那个身份提交）：

| 结论 | 原文 | 什么时候 |
|---|---|---|
| `unregistered` | `来源未登记` | `fleet:` 没有这条登记 |
| `revoked` | `来源登记已吊销` | 登记存在但已吊销 |
| `domain_mismatch` | `域不在绑定范围` | 登记在，但没绑到这个域 |
| `pipeline_impersonation` | `该类来源仅限进程内调用` | `extract:` 从 HTTP 进来 |
| `agent_domain_mismatch` | `身份与域不一致` | 身份里的域 ≠ 目标域 |
| `agent_not_member` | `身份不是该域活跃成员` | 身份在别的域，或不是本域成员，或不是本次请求的身份 |
| `user_mismatch` | `只能以自己的身份提交` | 冒用别人的 `user:` |
| `malformed` | `来源形状不合法（…）` | 前缀对、结构不完整（如 `fleet:` 后没有 `<id>/<post>`） |
| `unknown_prefix` | `未知来源类别（可用：…）` | 没有四类前缀之一 |

**迁移窗口**：环境变量 `BENCH_SUBMITTER_MODE` 为 `lenient` 时，历史上被记成别的形状的来源
仍可入库，并把判定结果写进 `domain_proposals.submitter_verdict`。**但 `pipeline_impersonation`
在任何档位都拒绝**——宽松窗口放过的是「迁移没做完」，不是「伪造」。默认档是 `strict`。

新登记一个舰队用 `scripts/register_fleet.py`：`--from-observed` 只打印从
`domain_proposals.source` 观察到的 `fleet:*` 与当前登记状态（**这份清单不能直接 apply**，
探针来源也在里面，它不是一个舰队），`--apply` 需要环境里给出该舰队**现有的** token——
脚本不会发明凭据，那会把正在跑的舰队当场切断。

**如果那枚 token 已经在库里**（本变更之前登记的消费者全是 `machine` 档，其中就有真舰队），
`--apply` 走**原地升级**而不是新建：只改 `kind`/`fleet_ref`，`id`/`name`/`token_hash`/`domains`
一个字不动。这一点很要紧——吊销再重登记会发一枚新 token，等于在没有任何提示的情况下把
在跑的舰队切成未登记。升级拒绝三种情形：给的名字不是那条登记的名字（凭据属于谁就是谁）、
那枚 `fleet_ref` 已被另一条未吊销登记占用、目标登记已吊销。域绑定默认也不改；确认要改
加 `--set-domains`。

## 结局与回执读面

提交方必须能读到自己提交后发生了什么，否则「被驳回」只能靠下一轮撞去重才发现，而
**为什么被驳回**永远读不到。

```
GET /api/d/{domain_key}/proposals/outcomes?source=<你的 source>
GET /api/d/{domain_key}/runs?runner_ref=<你的 runner_ref>     # 会话面
GET /api/v1/distribution/{domain_key}/proposals/outcomes?source=…   # 机器面，X-Consumer-Token
GET /api/v1/distribution/{domain_key}/runs?runner_ref=…        # 机器面，X-Consumer-Token
```

- **结局**：按 `source` 读，返回该来源在**本域**的提案行（`state`、`decision_note` 是驳回理由
  原文，不重写不摘要）。读别人的来源 → 403 `只能读取自己来源的结局：<source>`；平台管理员例外。
  机器面同一条判据：`source` 不在自己登记的 `fleet:<fleet_ref>/` 前缀内即 403。
- **运行回执**：舰队回写一轮运行后，用 `runner_ref` 读回来确认它落库了（`count` + `runs`）。
  读别人前缀的 `runner_ref` → **403，不是空列表**——空列表会被读成「我的回写没落库」。
  机器面只放 `fleet` 种类的登记，且只返回 `fleet:<自己的 fleet_ref>/` 开头的轮次。
- **迁移计数**：`GET /api/v1/distribution/legacy-sources`（仅平台管理员）返回判定不为 `ok` 的
  来源分组与计数，以及当前档位。**这个数到 0 才允许把档位锁死在 `strict`**；`verdict` 为
  `null` 的是列不存在时写入的历史行，单独报出。

## 舰队执行面（机器凭据）

> **接哪台主机**：机器面只挂在**工作台（origin）应用**上——`https://lawbench.finddatatech.cloud`。
> 只读公开 pod 不挂这些路由（`src/web/app.py` 的挂载注释写明「not mounted on public_app」），
> 打公开主机只会拿到 404，而不是权限错误。这一条必须写清：404 会被读成「你们没实现」，
> 而实际是打错了门。

舰队是机器，没有会话。下面四个写面与三个读面（共七个端点）都只用 `X-Consumer-Token`
（与拉取面同一枚，只存 sha256），**且只放 `kind='fleet'` 的登记**：

```
GET  /api/v1/distribution/{domain_key}/work-orders
POST /api/v1/distribution/{domain_key}/work-orders/{task_id}/claim
POST /api/v1/distribution/{domain_key}/work-orders/{task_id}/complete
POST /api/v1/distribution/{domain_key}/runs
GET  /api/v1/distribution/{domain_key}/runs?runner_ref=…
POST /api/v1/distribution/{domain_key}/proposals
GET  /api/v1/distribution/{domain_key}/proposals/outcomes?source=…
```

> **先有读面才有写面**：舰队不能认领它看不见的活。`GET work-orders` 是这条链的第一步，
> 少了它，「工单派给舰队」在机器侧等于不存在——面板是给人看的，台账页答的是「跑过什么」，
> 都不是「现在有什么等着我」。

| 端点 | 请求体 | 幂等 / 拒绝 |
|---|---|---|
| `work-orders`（GET） | 无 | **只读、零副作用**（不改状态、不写事件、不记拉取足迹）：只回**本舰队**（`assignee_kind='fleet'` 且 `assignee_ref` 等于自己）在**本域**的 `pending` / `in_progress` 工单。响应 `{"domain", "fleet_ref", "count", "work_orders": [{"id", "target_kind", "target_key", "title", "detail", "status", "created_at", "claimed_by"}]}`；`claimed_by` 是上次认领者（`null` = 没人动过），执行方要能分清「还没人领」与「我上一轮已经领了」。域不存在 **404** |
| `claim` | 无（工单号在路径里） | 排他：**别的舰队**认领 **409**；自己重试是幂等命中（200 + `created:false`）；不是派给本舰队的工单 **403** |
| `complete` | `{"note"?, "artifact_refs"?: [...]}` | 必须先认领（未认领 409）；已 `done` 的重试幂等（200 + `created:false`）；**不写知识单元** |
| `runs` | `{"runner_ref", "role", "outcome", "counts"?, "artifact_refs"?, "remaining"?, "detail"?, "task_id"?}` | 同 `runner_ref` 重放返回 `created: false` 且不改任何字段；结局不在四态 **422** |
| `proposals` | `{"source", "kind", "external_key", "body", "evidence", "impact"?}` | `source` 必须是自己登记的前缀（`fleet:<自己的 fleet_ref>/`），越界与 `extract:` / `agent:` / `user:` 一律 **403**；同键同依据重放 `created:false` |
| `proposals/outcomes` | 查询参数 `source` | 只读自己来源；别人的前缀 **403**（不是空列表） |

**提交这一格为什么必须在机器面上**：没有它，只持 token 的舰队能做活、能报数，却交不了
产物——「闭环」在最后一格要求一个人。`submitted_by` 由 `source` 派生、不读请求体
（机器只有一个身份）；确认仍只有会话面，所以自提自确认在机器道上**不可能**发生，而不是
靠两个人绕过去。

**反例（都是 403，都不是 200/空列表）**：拿自己的 token 报别人的 `source`；拿 token 报
`extract:`（它的可信依据是「流水线在网络上到不了」，不是一枚可泄露的凭据）；报 `agent:` /
`user:`（那两类必须以人的身份提交）。读别人的结局也 403——**空列表读作「什么都没发生」，
那是一句假话**。

### 参照实现：`scripts/fleet_client.py`

上面六个面有一个零依赖（仅标准库）的参考客户端，可直接照抄或 vendor 给接入方：

```bash
export LAWBENCH_BASE_URL=https://lawbench.finddatatech.cloud
export BENCH_FLEET_TOKEN=…        # 该舰队**现有**那枚；脚本从不打印它
export BENCH_FLEET_REF=fleet_…    # source 里 `fleet:` 之后、`/` 之前那一段

scripts/fleet_client.py orders   --domain legal
scripts/fleet_client.py claim    --domain legal --task-id 12
scripts/fleet_client.py run      --domain legal --post post_x --round 1 \
    --role concept --outcome ok --counts '{"drafts": 2}' --task-id 12
scripts/fleet_client.py submit   --domain legal --post post_x --kind company \
    --external-key corp-1 --body "第一家主体" --evidence '{"url": "https://e.test/1"}'
scripts/fleet_client.py outcomes --domain legal --post post_x
scripts/fleet_client.py complete --domain legal --task-id 12 --note "2 条草案"
```

`source` / `runner_ref` 由 `fleet_ref` + `--post` 拼出，**不接受手写前缀**（手写前缀就是
冒用的入口）。退出码分档：`0` 已接受、`1` 被服务端拒绝（附原话，重试无用）、`2` 没通
（配置或网络，修好可重试）。`--dry-run` 打印将要发出的请求、凭据显示为 `<redacted>`，
可放在子命令前后任意位置。

### 与壹座现有身份的关系（接入前先读这一段）

壹座侧已经有一套 **Logto 服务账号**（`svc-fleet-core-1` 等，用于平台/consent/计量那条链）。
知验台的机器面**不需要**它：这里的凭据是 `distribution_consumers` 上的一枚
`X-Consumer-Token`，**不走 Logto、不要 access token、不弹 consent**。

两套凭据解决的是两件事，别混：

| | 壹座服务账号（Logto） | 知验台消费者凭据 |
|---|---|---|
| 承载 | 人的身份代理（代表某个 org 调用平台） | **一条舰队登记**（`kind='fleet'` + `fleet_ref`） |
| 归因 | 审计到具体服务账号 | 归因到 `fleet:<fleet_ref>/`，台账与提案都读它 |
| 有效期 | 需要定期重铸 | 长期，除非被吊销（`revoked_at`） |

所以接入只多一件事：**把那枚已有 token 放进环境变量**，而不是再申请一个新的身份。
若某支舰队尚未登记，`scripts/register_fleet.py` 的原地升级路径能为它补上 `kind`/`fleet_ref`
而不换凭据（见上文）。

**认领之后失联怎么办**：认领是排他的，所以一张单被领走后不会自动回到待领。执行方
中途挂掉时，这张单停在 `in_progress`，由域负责人在控制台**取消**（取消后该缺口可
重新派单）；执行方不能自行重新认领（会拿到 409，那不是失败而是「这张单已经在你名下」）。
这一条要写在接线说明里：把 409 当故障去无限重试，只会刷日志而不解决问题。

授权读的是 `assignee_kind` + `assignee_ref`，**不是显示名**：两支舰队可以把名字都叫
`ontology-fleet`，只有登记引用能分清谁被派了活。`runner_ref` 必须形如
`fleet:<自己的 fleet_ref>/<post_id>#<round>`——拿别人的 ref 回写是 403，不是「记到别人
名下」。

三个写面存在的理由：只有会话路由时，非人档的工单只有域负责人能推动，那**不是**舰队在
认领。没有这三个口，「等待舰队认领」就描述了一件永远不会发生的事。

## 幂等与重试纪律

- 幂等身份 = `(domain, source, external_key, state='pending')`，由部分唯一索引兜底。
  同一身份重复提交**只有一行**，后到的请求拿到同一行。
- 被驳回的行是**历史**，不是身份：同键可以重提，但**必须换依据**（digest 不同）。
  同依据重提是 400 —— 换不换证据是人的判断，不该由轮次机械地重试。
- 对端 401/403/5xx/超时：调用方记失败、草案留在本地产物里等下一轮，**不得**记成「已提交」。

## 确认与驳回（同域负责人）

- `POST /d/{domain_key}/inbox/{id}/confirm` —— lead 及以上。写入走 `authoring.upsert_knowledge_unit`，
  同时写 `domain_proposal_events`（pending→confirmed）。**重复确认幂等**。
- `POST /d/{domain_key}/inbox/{id}/reject` —— lead 及以上，理由必填（缺理由 400 `驳回必须写明理由`）；
  写事件（pending→rejected）。
- 自提自确认：`submitted_by == 当前操作身份` 时确认 403。平台 admin 例外，但事件 note 会明确写上
  `[admin-override] confirmed by admin over the submitter '<sub>'` —— 豁免留痕，不是静默放行。

## 两侧计数对照（切换判据）

舰队提案岗切到本提交面后，一轮真跑必须同时满足：

1. 知验台 `legal` 域提案箱新增 N 条 `pending`（或按幂等命中少于 N），且控制台 `/d/legal/inbox` 可见；
2. 下游动作审批队列的本体类提案**增量为 0**（与切换前基线比）。

历史行不迁移、不删除：已确认的历史提案是审计记录。

## 不做什么

- 不提供「按内容自动选域」：域 key 来自岗位配置（`BENCH_PROPOSAL_DOMAIN`），猜错域是最难发现的一类错误。
- 不做双写（既进本提案箱又进下游队列）：双写会让「谁的确认算数」永远悬着。
- 提案本身不执行任何动作，因此不携带动作类字段（`tool_risk`、账号/工作区目标等）。
