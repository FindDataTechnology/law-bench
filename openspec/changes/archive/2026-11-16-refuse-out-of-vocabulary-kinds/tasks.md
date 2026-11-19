# 任务：词表外 kind 的预检

## 1. 库层

- [x] 1.1 `src/bench/proposals.py`：新增 `class KindNotInVocabulary(ValueError)`，
      文档字符串写明它是「词表裁决」而不是「数据坏了」，且子类化 `ValueError` 是为了让
      确认路径与既有调用方的 `except ValueError` 逐字不变。
- [x] 1.2 `_lane_for_kind`：只在「kind 不在任一张**非空**词表里」这一支抛
      `KindNotInVocabulary`；模板缺失 / schema 非 dict / 两张词表都空仍抛裸 `ValueError`
      （判不出，正解是修服务端数据）。
- [x] 1.3 `preflight_targets`：先捕 `KindNotInVocabulary` → 抛
      `ProposalTargetExists("kind_not_in_vocabulary", …)`，`detail` 点名 kind、模板版本与
      两张词表，`hint` 给两条正当路径；随后仍是 `except ValueError: return`。
      同时改掉函数文档字符串里「kind 越界不预检」那段——它今天已不成立。

## 2. 抽取面

- [x] 2.1 `src/bench/extraction.py`：`skipped` 加 `kind_not_in_vocabulary: 0`，注释写清它与
      `bad_kind` 的分工（包声明词表 vs 域锚定模板词表，两张表可以不一致）。
- [x] 2.2 提交处捕 `ProposalTargetExists` 的分支加这个桶。

## 3. 用例

- [x] 3.1 `tests/test_domain_proposals.py`：
      - 词表外 kind 被拒（409 理由 + 无提案行）；
      - **成对**：词表内 kind 照常进箱（证明拦的是词表而不是「所有提交」）；
      - ~~模板无词表时不拦~~：**撤掉**，那个状态造不出来（`validate_template_schema` 要求两个
        词表键必填且非空），硬插 SQL 造它等于让夹具替我说话。见 design D2。
- [x] 3.2 `tests/test_fleet_loop_e2e.py`：真 HTTP 一条，断言 409 的 `reason` 字段。
- [x] 3.3 抽取桶：断言 `run()` 的报告里**有** `kind_not_in_vocabulary` 这个键（防 KeyError）。
      **不**断言它会自增——那一侧提交前已按同一张模板词表预筛，这一类在抽取路径上不可达；
      写一条「计数会增加」的用例只能靠伪造提交来摆场景，那是夹具替我说话。

## 4. 验证

- [x] 4.1 红证：把 1.3 的捕获删掉，3.1 的第一条必须转红（证明它真的在测新规则）。
- [x] 4.2 全量回归（`nohup` 后台，跨会话存活）：**2192 passed / 60 skipped / 0 failed**（681s）。
      首轮 2189 passed + **3 failed**，三条全是本次规则把既有夹具从「静默可提交」翻成「拒」，
      处置记在 §4.4。
- [x] 4.3 `openspec validate refuse-out-of-vocabulary-kinds --strict` 绿。

## 5. 落地

- [x] 5.1 只 `git add` 本变更涉及的文件（避开另一会话的 `evidence/`），`-F` 提交 **`7aefe0d`**
      并推送真源；`openspec validate --strict` 绿。
- [x] 5.2 导出公开面完成：先 `-s ours` 合回导出快照 **`5012ebf`**（public 的独有提交只有
      `2e65580`，它是 `714c677` 的导出快照、而该提交在真源历史里 ⇒ 树不变、不丢内容），
      再导出 **`16212b8`**（6 files / +161 −15，`deploy/` 未碰）并推 gitee。
      **这条现在是常态**：每次导出都会给公开面加一个真源没有的提交 ⇒ 下一次导出前必先合回。
      判据不是「有没有冲突」，而是「public 独有提交是否都带 `exported-from` 且指向真源历史」。
- [x] 5.3 归档完成（2026-11-16 02:27）：备份到 `/tmp/openspec-backup-20261116-022722`；
      `openspec archive --yes` 报 `Totals: + 0, ~ 1, - 0, → 0`——与 delta 的 1 条
      MODIFIED 逐项对齐（若这条写的是 `+1` 就说明 delta 被当成了 ADDED）。归档后
      `openspec validate fleet-submitter-contract --type spec --strict` 绿，主 spec 里
      这条 requirement 现在有 6 个 Scenario（原 5 个名字逐字保留 + 新增 1 个）。

## 4.4 三条被新规则翻红的既有夹具（判据不变，夹具按真实成因重排）

- [x] 4.4.1 `test_the_same_claim_from_two_producers_is_one_row` 与
      `test_different_evidence_for_the_same_key_stays_two_rows` 用 `kind="concept"` 提交，
      而夹具模板词表是 `company`/`indicator` ⇒ **那两条提案本来就永远确认不了**，只是以前
      没人拦。这两条测的是**去重语义**（同键同依据一行 / 异依据两行），`kind` 只是标签，
      改成 `indicator`，断言一字未动。
- [x] 4.4.2 `test_ontology_batch_review.py::test_partial_failure_does_not_roll_back`
      故意用 `kind="spaceship"` 造「确认时失败」的行——正是「**入口拒绝让检查器夹具不可构造**」
      那一族（同 `an-entry-refusal-makes-the-checker-fixture-unconstructible`）。它测的是
      **批量确认一条失败不拖垮整批**，而那条路径在生产里仍然可达：行在箱里待着的时候模板
      收窄，或它本身就是加本规则之前就存在的旧行（生产 #86/#90/#94 正是）。所以改成
      「先合法入箱，再 `UPDATE` 该行 kind」——世界变化而非绕过被测入口。
- [x] 4.4.3 三条都不能走的错路：删掉这些用例（去重与批量确认都是活路径）、给预检开旁路
      （两面口径就分叉）、把夹具改成直接 INSERT 提案行（绕过被测入口）。

## 6. 收口后订正（2026-11-16 03:0x，只读核对生产）

- [x] 6.1 **提案里那句「legal 域 14 条 pending 里 3 条 `n:1`」把两个域混成一个，数字要按域拆**。
      实测（`domain_proposals join domains`，全库 pending 共 13 条，只落在两个域）：

      | 域 | 锚定词表（模板版本） | pending | 新预检会拒 |
      | --- | --- | --- | --- |
      | `legal` | 实体 `[clause,law,concept]` / 关系 4 种（legal-domain v2） | 6：`entity`×3（83-85）、`company`×1（95）、`n:1`×1（86）、`clause`×1（97） | **5** |
      | `data-ontology` | 实体 `[dataset,entity,field,concept]` / 关系 `[n:1,1:n,m:n,has_field,references]`（v1） | 7：`entity`×5（88-93）、`n:1`×2（90/94） | **0** |
      | `gov` | `[agency,document,policy,concept]` | 0 | — |

- [x] 6.2 这两处**都是好消息，方向相反**：① `data-ontology` 那 7 条一条都不该被拒——`entity` 是它的
      合法实体类型、`n:1` 是它的合法关系类型（**同一个 kind 名字在两个域里一个是合法词、一个不是，
      这正是判据必须读「该域锚定的模板」而不能用全局词表的实证**）。② `legal` 那 6 条里 5 条永远确认
      不了（确认走同一张表，照样抛），只有 `#97 clause` 落得下去——所以这个域的评审队列 83% 是僵尸行，
      而 `#95 company` 也是其中之一（前一笔记「误伤面 0」只查了**键重复**，没查 kind 归属）。
- [x] 6.3 **预期行为，不是本轮引入的破坏**：本变更只判**新提交**，这 13 行一行不动（它们已是既成事实）。
      要清这批存量得走拒绝流程（人的动作），不是靠预检。

## 上产留痕（2026-11-16）

- [x] 9.1 **本变更曾经「归档但不在产」**（同族于 `refuse-unlandable-proposals`）：真源推了、公开面导了、
      归档了，而在役 pod 的 `/app/src/bench/proposals.py` 里 `kind_not_in_vocabulary`
      **一次都 grep 不到**。原因不是测试红，是 canonical 出片通道死了——`FindDataTechnology`
      私有 CI 额度 2006/2000 耗尽，`image` 作业的 annotation 写着「jobs not started because
      recent account payments have failed」。
- [x] 9.2 上产路子：通用池 `testaction002/build-pool`（`fd-build-snapshot`，快照 `720ae6f`＝源
      `945b80b`，digest `sha256:43497b00…`）→ 临时 `SMOKE_MODE=skip`（跑完**立刻还原成 boot**；
      裸 boot 会报 `ConfigError: database_url is not set`）→ `skopeo --raw` 确认 ccr 已有该 tag
      → 清单抬 tag（`9db582c`）→ 导出 gitee（`a50ec89`）→ Argo selfHeal 同步
      （`rev=a50ec899 health=Healthy`）。
- [x] 9.3 判据是 pod 内的字符串，不是「Job 绿」：`proposals.py` 35568→43620 B，
      `kind_not_in_vocabulary`×1、`endpoints_missing`×2、`key_already_live`×2、
      `ProposalTargetExists|preflight_targets`×2。公网面同时复核：law-bench 端点 200 / 798 B，
      与仓内 `line-manifest.json` 逐字节相同。
