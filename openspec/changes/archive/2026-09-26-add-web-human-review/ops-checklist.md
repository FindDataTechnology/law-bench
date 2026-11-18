# add-web-human-review —— 运维与手工验收清单

本地 `pytest` 全绿只证明逻辑（跑在 fake 上），不证明部署。远程标注员要真正能用，
必须完成下面第 1 节的 Logto 与环境变量配置；第 2 节是日常操作顺序；第 3 节是验收勾选表。

---

## 1. 部署前置：Logto 与环境变量

> 背景知识见 `deploy/cheap-box/web-rbac-logto.md`（RBAC 总说明）。本节只补本改动新增的
> `review:annotate` 权限。授权模型不变：**没有应用侧角色表**，Logto 角色就是权限包，
> 访问令牌的 `scope` 声明即授权真相。

### 1.1 在 Logto 建权限与角色

1. **API Resource** → 该资源（indicator 必须与 `LOGTO_API_RESOURCE` 逐字节一致）→
   *Permissions* → 新增权限 `review:annotate`（只填名称，描述可选）。
2. *Roles* → 新建角色 `lawbench-annotator` → *Permissions* → 选该 API Resource →
   勾选 `review:annotate`。
   - 建议**同时**勾 `content:read`：标注员需要看合同文本上下文，且默认
     `AUTH_ADMITTED_SCOPES` 只认 `content:read,content:write,admin`——只授
     `review:annotate` 的账号会在 `/auth/callback` 被准入闸门拒掉（403 无权访问页）。
     若出于最小权限不想给 `content:read`，则必须按 1.2 的备选方案改 `AUTH_ADMITTED_SCOPES`。
3. **Assign roles**：给每位远程标注员建账号（或邀请），赋 `lawbench-annotator`。
   - 标注员**不要**给 `lawbench-admin` / `content:write`：判官污染告警（见第 2 节）依赖
     标注员与模型判定相互独立，能改数据的账号会让这条 QC 信号失去意义。

### 1.2 环境变量（`deploy/deployment.yaml` 的 env）

| 变量 | 现值 | 本改动要求 | 说明 |
|---|---|---|---|
| `LOGTO_SCOPES` | `openid profile email content:read content:write admin` | **追加** `review:annotate` | `/authorize` 请求的 scope 集合。**不追加则令牌里根本没有该 scope，判定 POST 一律 403**——这是最容易漏的一步。该值在模块导入时读取，**必须重启 / 重新部署 pod 才生效**。 |
| `AUTH_ADMITTED_SCOPES` | `content:read,content:write,admin` | 默认不变（前提：标注员已授 `content:read`） | 备选方案：若标注员只授 `review:annotate`，改为 `content:read,content:write,admin,review:annotate`。该值每次请求实时读取，无需重启。 |
| `AUTH_ADMISSION_MODE` | `enforce` | 不变 | 首次上线可临时置 `warn` 观察准入日志，验证通过后再翻回 `enforce`（与总说明的灰度顺序一致）。 |

冒烟脚本的 scope 断言是**子集**检查（`scripts/smoke_prod.sh` 逐个 `want` 比对），
追加 `review:annotate` 不会让它变红；若要额外断言新 scope 已被请求，可用：

```sh
SMOKE_EXPECT_SCOPES="content:read content:write admin review:annotate" scripts/smoke_prod.sh
```

### 1.3 数据前置

抽样对象是**已完成、含逐条判定结果的评测运行**（`eval_runs` + `eval_criteria_results`）。
被评测运行的圈选（哪几次运行进评审批）必须先定下来——这与论文口径的
「V4 权威运行导出」是同一个前置，两者都未完成前，第 2 节只能在小样本上试跑。

---

## 2. 日常操作顺序：抽样 → 标注 → 导出

### 2.1 抽样建批（在能连库的机器上）

```sh
# 先看候选运行（按 rubric / 时间列出，N 为条数上限）
python scripts/finetune/web_review_seed.py --list-runs 20

# 按候选结果钉住 run id，分层抽样建批（每合同类型 3 条、双人标注）
python scripts/finetune/web_review_seed.py \
  --batch-id v4-validity-2026q3 \
  --batch-type validity \
  --rubric-regex '^contract_' \
  --run-ids 101,102,103 \
  --per-type 3 \
  --annotators 2

# gold 策展批次（展示模型判定与理由，产出可作 ground truth 的标注）
python scripts/finetune/web_review_seed.py \
  --batch-id v4-gold-2026q3 --batch-type gold_curation \
  --run-ids 101,102,103 --per-type 5 --annotators 2
```

- `--per-type 0` 表示不限量（全取）。
- `--seed` 默认 `20260921`，抽样确定性可复现；同一 `--batch-id` 重复执行是**幂等**的
  （`UNIQUE (batch_id, eval_criteria_result_id, slot)` 兜底），补跑不会产生重复条目。

### 2.2 标注（标注员在浏览器里）

1. 标注员用 Logto 账号登录 `https://lawbench.finddatatech.cloud`，导航栏进 **人工审查**（`/review`）。
2. 批次页给出各批进度；进入待办队列后逐条判定：
   - **validity 批**：**盲评**——页面不含模型判定与理由，只给合同文本、条款与判据，标注员选
     `pass` / `fail` 并填备注。同一批次里已由本人判定过的条目不再出现在其待办中（槽位隔离）。
   - **gold_curation 批**：展示模型判定与理由，标注员选 `approved` / `rejected` / `skipped`。
3. 提交后即落库并锁定该槽位；重复提交同一条会提示已被谁判定（条件更新
   `WHERE status='pending'`，不会覆盖先到的判定）。

### 2.3 统计与导出（标注完成后）

```sh
# 只统计、不导出：看每人决策数、双人吻合率与 Cohen's κ、人-判官一致率
python scripts/finetune/web_review_export.py --batch-id v4-validity-2026q3

# 导出 gold（仅 gold_curation 批的 approved 条目）
python scripts/finetune/web_review_export.py \
  --batch-id v4-gold-2026q3 --export \
  --out data/finetune/judge-c/judge_c_gold.web.jsonl
```

看两个数：

- **双人 κ**：低（如 < 0.4）说明判据本身有歧义，先改 rubric 措辞再扩量，别急着当金标。
- **人-判官一致率 ≥ `--judge-agreement-warn`（默认 0.98）且决策数 ≥ 5**：报告会打
  **疑似机器代打**告警——标注员可能直接照抄模型判定，此时 κ 与一致率都不再是独立证据。
  需人工回访该标注员，或换人重标。

**关于 gold 文件**：导出前每条都会过下游同一个 `validate_quadruple` 闸门。评测侧的表
（`criteria` 只有 name/description/guidance）不带法条引用，因此 `legal_base` 与
`reasoning.citation` 组装为空——这类条目**不会**写进 gold 文件，而是落到
`judge_c_gold.web.jsonl.incomplete.jsonl` 工作清单并打印原因；**gold 文件在没有可晋金条目时
根本不创建**（一个空的 gold 文件会误放行飞轮闸门）。工作清单的用法与 2b 的 `review/done/`
一致：人工补齐法条来源与正文后即可晋金。

导出文件每条带 `reviewer=human` 溯源（`annotated_by` / `batch_id` / `slot` / `reviewed_at` / `note`）。
**BRONZE 永不作 ground truth**，只有通过 `validate_quadruple` 的条目才是 gold。

---

## 3. 手工验收勾选表

部署后逐项走一遍（勾选后本改动才算完成）：

- [ ] `scripts/smoke_prod.sh` 绿；若用了 `SMOKE_EXPECT_SCOPES`，确认新 scope 出现在
      authorize URL 中（证明运行中的镜像确实请求了 `review:annotate`）
- [ ] 解码某标注员的**访问令牌**（浏览器 dev tools / jwt.io），`scope` 声明里含
      `review:annotate`——这是 403 的第一排查点
- [ ] **未登录**访问 `/review` → 302 跳 `/auth/login`（不是 500、不是 403）
- [ ] **无 `review:annotate` 的已登录用户**（如 viewer）能打开 `/review` 列表（read 路由只要求登录），
      但对某条任务提交判定 → 403（write 路由要求 scope）
- [ ] **盲评有效性**：validity 批的待判页面上搜索不到模型判定 / 理由文本（页面上只有合同与判据）
- [ ] 标注员提交一条判定 → 页面显示已判定；其待办队列中该条消失
- [ ] 同一条任务换另一个标注员账号打开 → 仍可独立判定（双人槽位互不覆盖）
- [ ] 同一账号重复提交同一条 → 提示已被判定，不产生覆盖
- [ ] `web_review_export.py` 输出的统计数与实际提交数一致；导出条目中
      `provenance.reviewer == "human"`、`provenance.annotated_by` 为真实标注员身份、
      `tier == "gold"` 仅出现在 approved 条目上；无合法条的条目出现在
      `.incomplete.jsonl` 而非 gold 文件

## 4. 回滚

纯新增：新表 `review_tasks`、新路由、新模板、新脚本，未改动既有授权路径。
回滚方式为回退镜像；`review_tasks` 表可留在库中（无外键指向它，不影响既有功能），
如需彻底清理再 `DROP TABLE review_tasks`。已提交的标注数据在回滚后仍可用
`web_review_export.py` 直接读库导出。
