# 验收读数：add-fleet-execution-loop

> 本文件只记**读数**，不重复需求文字。每条判据写「怎么判的、真读数是多少、注入后是否
> 转红」。凡是没有真读数的，明确写「未做」及其阻塞原因——不留「应该没问题」。
>
> 采集日期：2026-11-14。库：本地 PG 17.11 `:5432`（`law_bench` 走逐测试临时库，
> `law_bench_opscheck` 用于脚本实跑）。生产库只做过只读基线查询（§0.1）。

## 一、基线（只读，2026-11-13 生产 `law_bench`）

| 项 | 读数 |
|---|---|
| `domain_proposals` | 93 行 |
| ├ `extract:*` | 78 |
| ├ `fleet:*` | 12（含 1 条 `fleet:credential-probe/post_probe` 探针） |
| └ `agent:*` | 4 |
| `authoring_tasks` | 1 行（`agent:concept@legal`） |
| `domain_agent_runs` | 17 行，无 `origin`/`runner_ref` 列 |
| `distribution_consumers` | 2 行（`fd-wire`、`ontology-fleet-win`，均绑 legal） |
| `domains` | 4 |

**`fleet:` 来源去重（2026-11-14 复核）**：只有 **2 个**前缀组——
`fleet:fleet_1794335712751_wfa3ww`（**11 行**，唯一真舰队）与 `fleet:credential-probe`（1 行探针，
不是舰队、永不登记）。所以 §6.3 只需要**一条**登记，`ontology-fleet-win` 与
`fleet_1794335712751_wfa3ww` 就是同一支；`fd-wire` 那条消费者只拉不提交（产库里没有它的
`fleet:` 来源）。

**§6.2 的基线读数（2026-11-14 复核，只读）**：`register_fleet.py --schema` 的同一套查询在
产库上返回**零行**——六列（`authoring_tasks.assignee_kind/assignee_ref`、
`distribution_consumers.kind/fleet_ref`、`domain_agent_runs.origin/runner_ref`）与两条部分
唯一索引一个都没有。正对照证明不是打错库：`distribution_consumers` 有 2 行，列恰好是
`id,name,domains,token_hash,created_by,created_at,revoked_at`；`authoring_tasks` 有 1 行。
所以本变更**尚未部署**，正在跑的舰队不受影响。

**第二个信号（不碰库、不需要任何凭据）**：机器面「在不在」看 **404 还是 401**——
`/api/v1/distribution/` 前缀自己的 token 校验会先答 401，路由不存在才是 404。实测
（2026-11-14，`https://lawbench.finddatatech.cloud`）：

| 路径 | 现在 | 部署后应为 |
|---|---|---|
| `GET /api/v1/distribution/legal/ontology`（**老面，正对照**） | **401** | 401（证明这条前缀本来就通） |
| `GET .../work-orders` | **404** | **401** |
| `GET .../runs?runner_ref=…` | **404** | **401** |
| `GET .../proposals/outcomes?source=…` | **404** | **401** |

这条判据的价值在于它能区分「镜像没换」与「权限不对」：**仍是 404 就是镜像没换**，
此时去加放行或查令牌都是查错方向。两项一起看（列/索引 + 404→401）才算部署落地。

这条基线推翻了初稿「source 必须解析到一条已登记消费者」的假设（78 条提取产物会被全部
拒掉，而它们正是最大生产者），校验因此改为按前缀四类分流。

## 二、判据与读数

### 1. 提交方四类分流（§2）

| 判据 | 怎么判 | 读数 / 注入 |
|---|---|---|
| 九类结论穷举 | `tests/test_submitter_contract.py`（零 DB 依赖纯函数） | 36 条通过；把 `extract:` 在 HTTP 档放行后 **3 条转红** |
| `fleet:` 需登记 + 绑域 + 未吊销 | `tests/test_fleet_registration.py` 13 条 | 全绿；重复登记被拒并点名既有登记 |
| `extract:` 外部一律拒 | 函数级 36 条 + **路由级** `test_http_call_cannot_claim_an_extract_source` | 403 且**不留半行**；把路由 `via` 改成 `VIA_IN_PROCESS` 后该条转红、其余仍绿 |
| `agent:` / `user:` 只能是自己 | 路由级 2 条 | 冒用 403「只能以自己的身份提交」；本人 200 |
| 已登记舰队跨域 | 路由级 | 403「域不在绑定范围」（**不是**「未登记」——错的是域，得指对原因） |
| 判定落库 | `domain_proposals.submitter_verdict` | `ok` 落在行上；`list_outcomes`/legacy 计数都读这一列 |

### 2. 运行台账分来源（§3）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 内核 = `kernel`、舰队 = `fleet` | `tests/test_external_run_writeback.py` 9 条 | `start()` 产 `origin=kernel`/`runner_ref=NULL`；`record_external_run` 产 `origin=fleet` |
| 幂等靠存在性检查 | 同 `runner_ref` 两次 | 行数 1；第二次 `created=False` 且结局/计数**未被改写**（`ok`/3 未被 `failed`/99 覆盖） |
| 结局出词表被拒 | 同上 | `running` / `done` / `""` 均 `ValueError`，不落行 |
| 回写不进质量比 | `quality.all_metrics` 前后对比 | 完全相等 |
| 两类同屏可辨 | `test_team_ledger_separates_the_two_origins` | 表头「外部执行方」在、`fleet:fleet_a/post_1#1` 完整显示；去掉两列表头后该条转红 |
| 回执可读回 | `tests/test_run_readback.py` 11 条 | 自己 1 行；别人的前缀 **403 而非空列表**；machine 档 403；吊销 403 |
| 并发重试不多出一行 | `test_a_lost_race_returns_the_winner_instead_of_a_duplicate` | 只蒙住**第一次**存在性检查（竞态的真实形状）→ 插入撞部分唯一索引 → 回读赢家、`created=False`、结局未被改写、行数 1 |
| 兜底索引只覆盖外部回写 | `test_the_partial_unique_index_covers_only_external_rows` | `indexdef` 含 `UNIQUE` 且含 `runner_ref IS NOT NULL`；内核 null 行连插 3 行不冲突 |
| 回执隔离判据 | 三处注入 | 去掉前缀判据转红 3 条、前缀改子串转红 1 条、去掉 fleet 种类检查转红 1 条 |
| 写面入参校验 | `test_fleet_loop_e2e.py` | `role` 为空 422「role 不能为空」；`task_id` 指到别域的工单 404；`counts` 非对象 / `artifact_refs` 非数组 422；**写坏的 JSON 422 而不是当空体**（当空体会让舰队以为 note 记上了）。关单空体仍合法（200） |

### 3. 工单三档（§1）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 三档正例 / 词表外被拒 / 未登记舰队被拒 / 跨域被拒 | `tests/test_work_orders.py` 18 条 | 全绿 |
| 认领排他 | 同一工单连续三次认领 | 一胜两负（`TaskAlreadyClaimed`），`transitions` 里只留一条认领记录 |
| 完成不写知识单元 | 前后 `knowledge_units` 行数 | 相等 |
| 归人缺口不派智能体 | `test_review_backlog_is_never_dispatched_to_an_agent` | `route=human`，`authoring_tasks` 零新增 |
| 归属表同源 | `team_roles.GAP_OWNER == {gap: kernel_role_for(gap)}` | 相等，且 `quality:review_lag → None` |
| 界面三档后果分开 | 工单页每行一句 | 「内核岗位下一轮执行」/「等待舰队认领」/「由人处理」三条都在；删掉那一行后转红 |
| 归人缺口界面不可选智能体 | 派单页 | 只有人这一档，页面无 `value="fleet"` / `value="kernel-role"` |
| 舰队下拉只列绑本域的 | 派单页 | `bound-fleet` 在、`other-fleet` 不在；去掉过滤后转红 |

### 4. 提案结局回流（§4）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 提交方读到自己被驳回的理由 | `tests/test_proposal_outcomes.py` 11 条 | `state=rejected`、`decision_note` 是**原文**「依据无法回源」 |
| 读不到别家的 | 同上 + 路由级 | 换来源 → 空；路由级 403「只能读取自己来源的结局」 |
| 同 digest 拒 / 换 digest 收 | 复用既有判据 | 不变 |
| 迁移计数 | `GET /api/v1/distribution/legacy-sources` | 仅平台管理员（非管理员 403）；`mode` 与实际档位一致 |

### 4b. 机器执行面（§1.11 / §3.5b）

| 判据 | 怎么判 | 读数 |
|---|---|---|
| 舰队只看到自己的未关闭单 | `test_a_fleet_sees_only_its_own_open_orders` | 4 张单里正好返回 2 张（`ontology` 待领、`knowledge` 已领）；已关闭的、派给人的、派给别支舰队的都不在 |
| 载荷字段齐 | 同上 | `id/target_kind/target_key/title/detail/created_at/status` 齐；已领的单带 `claimed_by` |
| 重复拉取零副作用 | 同上 | 载荷逐字相同；`authoring_events` 行数不变；状态不变 |
| 只放舰队凭据 | `test_the_order_pull_requires_a_fleet_token` | 无令牌 401；未绑定域 403 |
| 自己的重试幂等 | `test_the_whole_loop_over_http` | 同舰队再次认领 → 200 `created:false`，`transitions` 里仍只有 **1** 条认领；完成重试 → 200 `created:false`，仍只有 1 条完成事件 |
| 别的舰队仍冲突 | `test_another_fleets_claim_is_still_a_conflict` | 派给别支舰队的单，本舰队认领 403 |
| 完成重试不加事件 | `test_completing_twice_is_an_idempotent_hit` | 第二次 200 `created:false`，`done` 事件仍 1 条 |


### 4c. 既有登记原地升级（§2.5，2026-11-14 补）

产库读数暴露了一个真缺口：`distribution_consumers` 里 `ontology-fleet-win` 是**真舰队**，
但它登记在 `machine` 档——新镜像一落地，它的 `fleet:*` 提交会判成「未登记」，而**没有任何
办法修**：`register_consumer` 只新建（撞 `name` 与 `token_hash` 两条唯一约束），吊销重登记
又会发一枚新 token，等于把在跑的舰队当场切断。补的是 `distribution.promote_consumer_to_fleet`
＋脚本里的升级分支。

| 判据 | 怎么判 | 读数 / 注入 |
|---|---|---|
| 只动两列 | `test_promotion_locates_by_credential_and_changes_only_two_columns` | `kind`/`fleet_ref` 变，`id`/`name`/`token_hash`/`domains` 逐字相等 |
| 升级后立刻可提交 | 脚本测试同条尾部发 `fleet:<ref>/post_1` | `submitter_verdict='ok'`（升级的全部意义） |
| 按凭据定位即授权 | 脚本测试（不给 `--name`） | 定位到那条行、升级成功 |
| 改名被拒 | `test_promotion_refuses_a_name_that_is_not_the_stored_one` | 1 + 「属于登记」；行仍是 `machine` |
| 凭据与名字不匹配被拒 | `test_promotion_refuses_when_the_given_name_is_not_the_credential_owner` | `ValueError`「凭据与提供的 token 不一致」 |
| `fleet_ref` 被占被拒 | `test_promotion_refuses_a_fleet_ref_another_registration_already_claims` | 1 + 「占用」；两条行都没变 |
| 已吊销被拒 | `test_promotion_refuses_a_revoked_registration` | 1 + 「已吊销」 |
| 域不一致默认拒 | `test_promotion_refuses_to_change_domains_silently` | 1 + 提示 `--set-domains`；加该开关后同 id 行域改为 `knowledge` |
| 幂等重跑 | `test_promoting_twice_says_nothing_to_change` | 第二次 0 + 「nothing to change」，行数仍 1 |
| dry run 不撒谎 | `test_promotion_dry_run_reports_the_upgrade_and_writes_nothing` / `test_a_name_taken_by_another_credential_is_refused_before_anything_is_written` | 前者「would PROMOTE」且不写；后者**不 apply 也拒**（说「会登记」的 dry run 比没有更坏） |

| 别人的前缀 403 | `test_a_token_cannot_submit_under_another_fleets_source` | 403「机器面只能以自己的身份提交」，`domain_proposals` 行数 0 |
| `extract:` / `agent:` / `user:` 三类都拒 | `test_a_token_cannot_submit_an_extract_or_agent_source` | 三类各 403，零行 |
| 无凭据 401 | `test_machine_submission_requires_a_fleet_token` | 401「缺少机器凭据：X-Consumer-Token 请求头」 |
| 重放幂等 | `test_the_whole_loop_over_http` 第 ⑤ 步 | 第二次 200 + `created:false` 且 id 与首次相同 |
| 结局自己读得到、别人的 403 | `test_a_fleet_reads_only_its_own_proposal_outcomes` | 自己 200；别人的前缀 403「只能读取自己来源的结局」 |
| **参考客户端打得通真路由** | `test_the_reference_client_speaks_to_the_real_app`（把它自己的 `urlopen` 接到 ASGI 上，六步全走 `Client`） | 拉单 → 认领（重试 `created:false`）→ 回写 → 读回 `count=1` → 提交 `created:true` → 负责人确认 → 结局 `confirmed` → 关单 `done` |
| 真 403 变成 `Refused` | `test_the_reference_client_turns_a_403_into_a_refusal` | `Refused` 里带 `403` 与服务端原话（退出码 1，不是崩、不是当成功） |
| 这套测试会红 | 注入：把 `PREFIX` 改成 `/api/v1/distributions` | 闭环那条**当场断**（`1 failed`），改回即绿 |
| 公开面**没有**机器面 | `tests/test_public_app.py::test_the_fleet_machine_surface_is_not_registered`（七条路径逐个断言 **404 而不是 401**） | 全 404；注入：把 `distribution.read_only_router` 挂到 `create_public_app` 上 → **当场断**，还原即绿 |
| 迁移的 `--schema` 能红 | `tests/test_register_fleet_script.py`（空库 / 删索引两条） | 空库 8 项全 ✗ 且 EXIT=1；删掉 `distribution_consumers_fleet_ref_uk` 后该项 ✗ |

> 这一格是本轮补的**最后一个缝**：三个机器写面让舰队能领单/执行/报数，产物却仍只能走
> 会话提交——而会话要求一个能代表人的凭据（D7 已否决）。e2e 里原来靠 `svc-fleet` 服务账号
> 走那一步，「闭环」因此在最后一格上仍要求一个人。现在提交与结局读都走 `X-Consumer-Token`，
> 服务账号成员已从夹具里删除；确认仍只有会话面，所以自提自确认在机器道上**不可能**发生。

### 5. 闭环（§6.4 离线那半 / §7.1）

`tests/test_fleet_loop_e2e.py`：**一条测试全走真实 HTTP**，不调内核函数（除造世界）：

```
缺口存在 → 派单给舰队(303) → 舰队领单(200, in_progress)
        → 自领重试(200, created=false) → 回写运行(created=true) → 重放(created=false, 结局未被改写)
        → 回执读回(count=1) → 提案入箱(200, created=true，**机器面**)
        → 重放(created=false, 同一 id) → 负责人确认(303, 无 err)
        → knowledge_units 出现该键(1 行) → 缺口消失 → 结局可见(confirmed，**机器面**) → 关单(done)
        → 四份证据齐（done 工单 1 / runner_ref 运行 1 / confirmed 提案 1）
```

五个只测「不该通的路」：别的舰队领单 403、`machine` 档消费者 403、跨舰队 `runner_ref`
403、越界 `source` 提交 403（含 `extract:`/`agent:`/`user:`）、读别人结局 403；另有结局
出词表 422 且零行。

注入（各转红一条）：去掉工单归属校验 → 跨舰队那条红；去掉 `runner_ref` 归属 → 跨舰队
回写那条红；把机器面收窄成只放 `machine` 档 → **整条闭环当场断在领单**；去掉 `source`
前缀判据 → 越界提交那条红并多落一行。

> **两处「原任务漏了」**：① 会话路由把非人档当「不是我的」，所以「等待舰队认领」这句话
> 在只有会话路由的世界里**永远不会发生**；② 补了 claim/complete/runs 之后产物仍只能走
> **会话**提交，于是闭环在最后一格要求一个人——那正是 D7 否决的「服务账号会话」。所以本轮
> 又补了 `POST /api/v1/distribution/{key}/proposals` 与 `.../proposals/outcomes`：提交与
> 结局读都用同一枚 token，`source` 必须是自己登记的前缀。
> 复核仍是域负责人（`lara`, lead）的会话身份：机器凭据没有确认入口，所以自提自确认在机器
> 道上**不可能**发生（不是靠两个人绕过去）。同一个会话身份既提又确认时仍被拦（实测 `err=1`
> 「提案人不得自提自确认」）——这条不是障碍，是判据。

### 6. 回退演练（§6.5，本地真库四步）

| 步 | 命令 | 读数 |
|---|---|---|
| ① strict 下看遗留 | `register_fleet.py --legacy` | `enforcement mode: strict`；2 组：`extract:qwen:2025-10` 3 行（**无判定**）、`user:someone@example.com` 1 行（`user_mismatch`） |
| ② 切宽松 | `BENCH_SUBMITTER_MODE=lenient` 提交两条 | `fleet:fleet_unregistered/post_9`、`mirror:legacy-shape` **都入库** |
| ③ 计数可读 | 同 ① | 4 组：多出 `unregistered` 1 行、`unknown_prefix` 1 行 |
| ④ 翻回 strict | 再提交同样两条 | 两条都被拒（`unregistered` / `unknown_prefix`）；宽松期写入的 2 行仍在，`origin`/`runner_ref`/`kind`/`fleet_ref` 四列都在 |

同时验证了另一条真实的升级形态：本地 `law_bench` 停在**变更前**的库结构，脚本给出
`UndefinedColumn` → EXIT=2 并提示「先跑启动步骤把列建出来」；`ensure_schema` 之后
EXIT=0 并报 `tasks: 0`。

## 三、全量回归与两条非本 change 的失败

`database_url=law_bench .venv/bin/python -m pytest tests/ -q` 首次 **2105 passed / 59 skipped / 2 failed**（12:29）；
定性并处置后（下面两条），排除环境性的那一条再跑一次：
**2118 passed, 59 skipped, 1 deselected, 0 failed**（3:43，含机器读面、入参校验、并发兜底、重试幂等与计数器读法用例）。

补完原地升级、机器提交面、参考客户端与「种类」列之后的最终一轮（2026-11-14 09:53）：
**2144 passed, 59 skipped, 1 deselected, 0 failed**（12:33）。逐步增量：升级面 11 条 →
`--from-observed` 认 machine 行 1 条 → 机器提交/结局 4 条 + 参考客户端 9 条 + 管理页 1 条。

| 失败 | 定性 | 依据 |
|---|---|---|
| `test_contract_artifact_storage.py::test_generate_stored_real_minio` | **环境**：本机没有 MinIO | `nc -z 127.0.0.1 9000` → closed；单独跑该测试挂到 180s 超时（EXIT=124）。测试自身写着「unreachable 就 skip」，但客户端没有超时设置，所以是挂死而不是跳过。未碰任何 storage 代码 |
| `test_dispatch.py::test_closing_a_task_reopens_the_gap_for_dispatch` | **本 change 的契约变更**，已改测试 | 它从 `pending` 直接 `to=done`；§1.4/§1.10 明确「完成必须先认领」。改成 claim→complete，并把「未认领直接完成被拒」也钉在该测试里。改后 10 条全绿 |

## 四、未做项与阻塞
| 项 | 状态 | 阻塞 |
|---|---|---|
| §6.2 生产库真身核对（六列在真 pod 上就位） | **已过（2026-11-14 15:5x）** | 判据是 `register_fleet.py --schema`（六列 + 两条部分唯一索引，缺项逐条 ✗ 并给修法，EXIT=1）。**0/8 → 8/8**：部署前逐条 `MISSING`，滚到 `sha-38ba5c4` 后六列两条索引全 `ok`（索引按**形状**判：`UNIQUE` 在、`fleet_ref`/`runner_ref` 在，不只是名字在）。pod 启动日志 `boot: schema ensured on database 'law_bench'`，`Application startup complete`，`RESTARTS=0`（失败即 crash-loop 这条设计有效）。三面同期从「不存在」变「在」：`work-orders` 404→**401**、`runs?runner_ref=…` **401**、`proposals` GET **405**／POST **401**（405 比 401 更强——路径在、只是那面只收 POST；旧读数 404 是路由根本没挂）；正对照 `ontology` 保持 **401** |
| §6.3 生产登记 | **已完成 2026-11-14（走的不是原定那条路）** | 原路被三条现场事实堵死：① 平台 `BENCH_CONSUMER_TOKEN` 是 47 位 `lbk_`、指纹在 `distribution_consumers` 查不到——它是**提案面**凭据，机器面只认 `X-Consumer-Token`；② `ontology-fleet-win` 的消费者明文只在登记那一刻显示过一次（`distribution_pull_events` 全表 1 行、创建后 10 秒的探针）；③ `register_consumer` 撞 name/token_hash 两条唯一约束。于是补两条受控路径：`--promote-by-name`（原地升级、**不需要凭据**，因为升级不动 `token_hash`）与 `--rotate-token`（就地换一枚、明文只打印一次）。实跑：`id=2 machine→fleet`、`fleet_ref=fleet_1794335712751_wfa3ww`、凭据未动；随后轮换并把新值写入 `platform-secrets.BENCH_FLEET_TOKEN`（22→23 键，未打印明文）；线上 `work-orders` → 200 + 该 fleet_ref，无凭据 → 401（curl 与 gitee/main 上的客户端产物各测一次）。翻硬判据改用生产同一函数求值（真舰队 `ok`、探针 `unregistered`），因为产库 93 行判定全 NULL——lenient 窗口一行都没记过 |
| §6.4 跨仓真跑 | **四行都在，但第四行的签字人不是人（见下）** | 工单 id=3（fleet 指派、done）、运行 id=18（`origin=fleet`、`runner_ref=fleet:…/post_acceptance#1`）、提案 #95/#96（机器面、`submitter_verdict=ok`——产库第一行 非 NULL 判定）、单元 `knowledge_units` id=7576（`legal`/`国债`）。六个机器面全部线上实测。**必须点明的过程事故**：我本意只用 `actor="fleet:probe"` 验证「确认闸拦不拦」，而闸当时只判 `is_agent`（只认 `agent:` 前缀）⇒ 它**通过了**：提案 #96 被确认、内核写出 id=7576、审计 `operator="fleet:probe"`（原 `gov/国债` id=7569 未动）。没有删行「清理历史」（那等于伪造更干净的审计），而是补洞：`agent_ids.MACHINE_PREFIXES`＋`is_machine`，`confirm` 两道闸改用它，新增 `test_agent_ids.py`（含与 `submitters.PREFIX_*` 的一致性钉）与 `test_a_fleet_identity_cannot_sign_a_confirmation`（退回旧口径即红）。**因此这一行是「机制通、治理不干净」**，待负责人裁定：保留 id=7576 与那条 operator（并接受一次演员不对的签字），或由人以自己的身份重做一轮干净的闭环 |
| §8.1–8.3 | 明确不做 | 直接调度 / 优先级计费 / 舰队侧客户端，均超出本 change |

### 本次发布实录（2026-11-14，六个可复核的坐标）

发布这条链在第 1 项上死过一次（私有额度耗尽），第 1 项的写法又错过一次（把 gitee 上的
`image.yml` 当成 GitHub Actions 会跑的东西），所以把实际走通的每一步连同回滚点写死在这里：

| 步骤 | 值 |
|---|---|
| 真源提交 | `8f53376`（tag 抬升）/ 其上的 `214ff4b` 只吸收公开仓祖先关系、零内容变化 |
| 快照仓提交 | `law-ai-official/law-bench-images@38ba5c4`，`BUILD-INFO.json` 记 `baseCommit=de357116b` |
| 出片 run | `43560510231`：`test` / `law-template` / `law-render` 三个 job 全 success，两镜像各铸 `sha-38ba5c4` |
| 镜像可见性 | `skopeo inspect --raw` 在 **hkccr 与 ccr 两处**都拿到同一 manifest digest `466555…`——relay 回填是**核过的**，不是等出来的 |
| 清单提交 | 导出提交 `e130922`（`exported-from: 214ff4b741…`），只动 `deploy/deployment.yaml` 一个文件、两处引用同片 |
| Argo | `law-bench` app 从 `265328c` 走到 `e130922`，`Synced`；新 pod `law-bench-65cfd69c9f-g6pfc` `Running/ready/RESTARTS=0` |
| 回滚 | 把同一 Deployment 两处改回 `sha-afb4e71`（导出路径走真源，不手写发布面） |

两处流程上的坑（都改了脚本，不是绕过）：
- **`merge_law_bench.sh` 的试算在一棵空树上跑**：双远端克隆里 `git checkout main` 是歧义的
  （`fatal: 'main' matched multiple (2) remote tracking branches`），而克隆用了 `--no-checkout`
  ⇒ 检出失败后工作树仍为空，试算照样打印「变更 2014 个文件，未解冲突 0 个」。改成
  `checkout -B main origin/main`。
- **`die "… $anchor（命中 …"` 在 macOS 上必崩**：自带 bash 3.2 把紧跟其后的全角括号**首字节**
  吃进变量名（`anchor\xef: unbound variable`），bash 5 上不现形。改成 `${anchor}`，并扫过
  `scripts/*.sh` 确认只此一处。

### 出片链路（核实过的事实，供执行的人直接用）

1. **镜像**：`.github/workflows/image.yml` 在 **`law-bench-internal` 的 `main` 分支 push** 时构建
   `law-template`（hkccr → cheap-3 relay → ccr）。所以镜像版本 = 该仓某个 main 提交的 `sha-<7>`。
2. **schema 随启动落地，且失败即 crash-loop**：`scripts/docker-entrypoint.sh`（`PUBLIC_API!=1` 分支）
   在 `exec uvicorn` 之前跑 `python -m src.eval.bootstrap` → `ensure_schema` →
   `WORKSPACE_SCHEMA`（六列与两条索引都在这里）。半套 schema 不会被端出去。
3. **清单与 Argo**：`argocd/application.yaml` 的源是**公开仓** `gitee.com/FindDataTechnology/law-bench.git`
   的 `main`、`path: deploy`。也就是说**出片要动公开仓的 `deploy/deployment.yaml`**（这是发布决定，
   不是对齐动作）；本仓同名文件的 tag 目前与线上一致（`law-template:sha-afb4e71`）。
4. **公开 pod 不跑 DDL**（`PUBLIC_API=1` 分支直接 uvicorn），它的库是复制来的 dump——所以
   `--schema` 要在 **origin 库**上跑，公开库缺列属正常、且新机器面也没挂在公开 pod 上。

### 出片通道现在是坏的（2026-11-14 实测，与本 change 无关但挡住 §6.2）

`gh run list --workflow=image.yml`：**94 失败 / 6 成功**，最后一次成功 **2026-11-03 22:30**，
最后一次真实跑完（有 step、耗 712s）是 **11-05 22:25**；**11-05 22:38 起 93 笔全部在 3–5 秒内死**
（`steps: []`，`build-push` 一律 skipped）。失败注解原文：

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans' section in your settings

`fd-build-channel status`（2026-11-14T11:30）给出的真实原因不是「支付失败」，而是**额度耗尽**：

| 账号 | 用量 / 额度 | 状态 |
|---|---|---|
| `FindDataTechnology`（本仓所在） | **2006 / 2000** | ⛔ 已耗尽（私有 CI 全停；公开仓不受影响） |
| `testaction003` | 69 / 2000 | 剩 1931 min |
| `law-ai-official` | 529 / 2000 | 剩 1471 min |

**为什么 11 天没人发现**：Argo 只在 `deploy/deployment.yaml` 的 tag 变化时才滚，而 tag 一直是
`sha-afb4e71`（11-03 那片），所以产线一切正常、所有健康判据都绿——**冻结的是「下一次发布」，
不是「现在正在跑的服务」**。这一类「通道自己死了」不在任何现有闸的判据里
（`check_image_referencers.py` 查 tag 一致性、`fd-image-coherence-gate.py` 查同片，都不查
「最近一次构建成功没有」）。

**处置（两条，任选）**：① 等月初额度重置，或把本仓 CI 换到还有余额的账号池
（`fd-build-snapshot` + `BUILD_NAMESPACE/BUILD_IMAGE`，T2 通道）；② 用本目录 `Jenkinsfile`
出片——但那是 **in-cluster Harbor**（`100.64.0.8:30880/law-bench/law-template`），不是产线拉的
`ccr.ccs.tencentyun.com`，走这条路要同时改清单的镜像地址。**注意**：无论哪条，产线要滚还得改
**公开仓**的清单 tag（见第 3 条）。

**部署落地怎么核（两项一起看，都只读）**：① `register_fleet.py --schema` 从 0/8 变 8/8；
② 三条机器面从 **404 变 401**（老面 `.../ontology` 一直是 401，是这条前缀通不通的正对照）。
只看到 401 不见 8/8 说明镜像换了但库没落地（会 crash-loop，所以几乎不会出现）；
只见 8/8 不见 401 说明库是别处跑的 DDL，镜像还没换。

### 发布面的真实形状（2026-11-14 核对，含一条订正）

**出片线是 `law-ai-official/law-bench-images`（T2 私有快照仓），不是「公开仓自有免费 CI」**
——这条我先前的记录是**错的**，2026-11-14 实核后订正如下：

| 我先前写的 | 实际 |
|---|---|
| 「公开仓自己也有一条 `image.yml`，跑在免费公开线上」 | `FindDataTechnology/law-bench`（public，763 文件，最后推送 **11-09**）**根本没有 `.github/workflows/`**：`gh run list -R …/law-bench --workflow=image.yml` → `HTTP 404: workflow image.yml not found on the default branch`。`image.yml` 只存在于 **gitee** 那棵树（1947 文件）里，而 GitHub Actions 不在 gitee 上跑 |
| 「推公开仓 main 同时完成出片 + 让 Argo 读到新清单」 | 推 gitee 只完成**第二件**（Argo 盯 gitee `deploy/`）。出片要走 `fd-build-snapshot` |

**真实通道**：`fd-build-channel status` 把阶梯写得很直白——T1「公开仓直出」要求**公开**仓里
有 `image.yml`，本仓没有；实际在跑的是 **T2 私有快照仓**（`law-ai-official/*-images` 模式，
每账号 2000 min/月）。产线现用那片 `law-template:sha-afb4e71` 就是这条线 **2026-11-11 04:45**
出的；该线最近一次成功是 **2026-11-12 03:20 `1e90e56`**，之后无 run（不是坏，是没人推）。

**命令与代价**：`fd-build-snapshot <干净 clone> -R law-ai-official/law-bench-images --ref main`
→ 快照提交（本次 `38ba5c4`，`BUILD-INFO.json` 记源真 sha `de357116b`）→ 该仓 `image.yml`
先跑 `test` 再建 `law-template` + `law-render`，只有 **digest 变了**才铸 `sha-<快照提交 7 位>`。
**tag 指向快照仓的提交，不指本仓**——所以清单 tag 与内部提交之间靠 `BUILD-INFO.json` 与导出
提交 message（`export(internal): 从真源导出 <内部 sha>`）两条指针接起来，不是靠 tag 本身。
`--ref` 是必填：工具拒绝「拿 origin 默认分支当安全默认」（无 ref 直接拒，实测）。
`law-ai-official` 当日用量 529/2000，本次构建前剩 1471 min。

**订正一条我先前的错判**：`openspec/changes/**` **不是**整体排除。公开仓里这个目录有
**502 个文件**——89 个已归档 change 里 **83 个已公开**，另有 1 个在途 change
（`add-domain-first-workbench`，10 个文件）也已公开；`evidence/` 也有 6 个文件公开。真正取舍是
**逐目录选择性的**：6 个已归档 change（如 `2026-11-05-close-wire-real-loop`、
`2026-11-11-add-image-build-fallback`）与 `add-judge-misread-remediation` 至今只在内部。
**结论：这份取舍规则无法从树里推出来**（它不是「某目录全排」），所以导出这一步要由它的
所有者执行，或先把规则写明——我不该拿「按目录排除」去替它。

**本 change 的发布增量**（`9bcbaaad1..HEAD`，72 个文件）：**51 个**是产品代码/测试/文档
（`src/bench/*` 8 个、`src/web/*` 8 个、`tests/*` 24 个、`scripts/*` 3 个、`docs/*` 3 个、
`openspec/specs/domain-run-ledger` 1 个、`.gitignore`），其余 21 个在
`openspec/changes/`、`evidence/`、`line-manifest.json`、`ontology-adapter.json`、
`knowledge-surface.yml` 之下。`check_public_hygiene.py` 在整棵树上通过（2014 个受跟踪文件、零命中）。

## 五、这一轮最该记住的三条

1. **「看起来闭合」的闭环最容易骗人**：数据面区分了来源，界面还合着说；会话路由拒绝
   了非人档，却没有任何机器入口能让舰队自己认领。两处都不是报错，都是静默。
2. **裸中文串不能证明页面渲染了它**：`base.html` 嵌着整份 `window.__LOCALE__`。判据
   必须先剥掉那段脚本（`_rendered()`），否则注入不转红也看不出区别——我自己先写错过
   一次，是注入没红才发现的。
3. **同一句话对不同档不能说**：「已派出」对内核岗位是真的（下一轮就跑），对舰队是假
   的（要等它认领）。文案级的错误会让值班的人催错对象、或者不催。

## 六、归档须知（写在这里，因为归档那天最容易漏）

### 6.1 归档时应打印的合计

按逐文件实测，delta 共 **14 条 requirement**：

| capability | ADDED | MODIFIED |
|---|---|---|
| `domain-work-order`（**新**） | 5 | 0 |
| `fleet-submitter-contract`（**新**） | 4 | 0 |
| `domain-run-ledger` | 2 | 1 |
| `domain-estate-console` | 0 | 1 |
| `knowledge-distribution` | 0 | 1 |
| **合计** | **11** | **3** |

`openspec archive add-fleet-execution-loop` 之后应看到 `Totals: + 11, ~ 3, - 0, → 0`。
数字对不上就是有 delta 段被静默丢弃（每个文件每个操作只能有一个段，多写的那个会被丢且仍报成功）。

### 6.2 两个新 capability 的 Purpose 会在归档时变成 `TBD`

`domain-work-order` 与 `fleet-submitter-contract` 在 `openspec/specs/` 下还不存在，
归档会新建它们并把 Purpose 写成 `TBD - created by archiving change …`——`--strict` 下
这就是失败。归档后立刻改主规格（CLI 自己指示的例外），建议文案：

- `openspec/specs/domain-work-order/spec.md`：
  「一张工单从派到收的完整生命周期：类型化指派人、认领与完成两个显式转移、按执行方可见的机器读面，以及决定「这活归谁」的显性分诊表。它存在的理由是：派单在只有自由文本指派人时，没有任何东西会把活送到执行方手里。」
- `openspec/specs/fleet-submitter-contract/spec.md`：
  「外部提交方凭什么被相信：四类来源（舰队 / 抽取流水线 / 自铸智能体身份 / 交互式的人）各自的信任依据、登记与凭据的绑定、以及未登记/已吊销/跨域/冒用身份时对调用方说清是哪一种。它存在的理由是：来源从「一个曾经出现过的字符串」变成「一条可吊销的登记」，或一条可核对的已认证身份。」

### 6.3 归档后逐个校验本次触及的 capability

`openspec validate <cap> --type spec --strict`，五个都跑：`domain-work-order` /
`fleet-submitter-contract` / `domain-run-ledger` / `domain-estate-console` /
`knowledge-distribution`。

若只有**别的在途 change** 的 capability 红，点名即可，不属这次归档的范围。
