# Design: content-remediation

## Context

生产条款库在 cheap 集群 origin Postgres（`postgres.postgres.svc` ns `postgres`，库 `law_bench`），本地无直连路径；`.env` 的 `database_url` 指向本地空测试库。既有审计线 `scripts/audit_clauses.py` + `src/clauses/audit.py` 依赖中继三模型投票，而中继上 kimi-k3/deepseek-v4-pro 已失效（见 `output/content_audit_report_2026-09-15.md` 二-2），全量 LLM 审计当前不可跑。缺陷清单已由 2026-09-15 全量检测枚举到条款 id（`output/content_check_report.json`），治理可以从"发现"直接跳到"修复"。`src/clauses/tag_review.py` 的 `is_assembly_ready` 遍历 tag_review 全部键值，`_` 前缀元数据键（2026-08-17 导入写入）使判定永远为否。

## Goals / Non-Goals

**Goals:**

- 每个 Batch 独立可回退（before-snapshot + result 文件 + 可恢复的 rejected 状态），不执行任何 DELETE。
- 确定性规则优先，LLM 只用于 18+19 条小集合的改写草拟；伪影清理用高精度正则，不依赖网关恢复。
- 修改后的门控代码与数据迁移解耦：代码先上，数据清理后跑，各自可独立回退。

**Non-Goals:**

- 修复 token.finddatatech.cloud 网关的 glm-5.3-flash（另行 ops 处理，见报告二-1）。
- 158 条无 scenario 的孤儿池地域条款（不进组装，只影响 RAG；待网关恢复后走全量 LLM 审计）。
- 全量 missing_slot 审计、rubric/评估线改动、评估库 schema 变更。

## Decisions

### D1. 新增独立治理驱动，不复用 audit_clauses.py 的批处理
新写 `scripts/content_remediation.py`（检测逻辑复用 `scripts/content_check_offline.py` 的规则函数，抽取为共享模块），修复动作复用 `src/clauses/store.py:update_clause`、`src/clauses/tag_review.py:bulk_review`、`src/clauses/audit.py:region_lint`；tag_review 的清除/回滚走窄口径单列 UPDATE（`update_clause` 不支持 tag_review 字段）。
理由：audit_clauses.py 与三模型 LLM 流水线强耦合（分类→改写→验证三段都走中继），现在中继两只模型已死；治理是 id 清单驱动、确定性优先，混在一起会把两类回滚路径搅在一起。代价：多一个脚本，但它读的就是同一套 store/审核 API，没有第二套写入路径。

### D2. 生产库访问：SSH 隧道 + kubectl port-forward，不改部署
`ssh -L 15433:localhost:15433 cheap4` + cheap4 上 `kubectl port-forward -n postgres svc/postgres 15433:5432`，驱动用 `DATABASE_URL=postgresql://app:***@localhost:15433/law_bench` 覆盖 `.env`（沿用 self_iterate.py 的 `load_dotenv(override=True)` 约定）。
替代方案（否决）：打包 Job 进集群跑——要构建镜像、传 id 清单进 PVC，回退和审计反而复杂；隧道方案零部署改动，且写入天然经过同一个 psycopg 路径。

### D3. 快照与回滚布局
```
output/remediation/<batch-name>/
  manifest.json        # batch 范围、id 清单、执行时间、git sha
  before/<type>_<id>.json   # 修改前整行（body、tag_review、tags...）
  applied/<type>_<id>.json  # 修改后字段 + 缺陷类别 + 规则/模型来源
```
回滚：`python scripts/content_remediation.py --rollback <batch-name>` 逐条用 before 文件恢复 body 与 tag_review；去重的 rejected 通过 manifest 里记录的 id 重批准。沿用 `output/audit/` 的 result-file 约定但分 batch 目录，避免与将来恢复的 LLM 审计互相覆盖。

### D4. Batch 切分（爆炸半径从小到大，各自独立验收）
| Batch | 内容 | 依赖 LLM？ |
|---|---|---|
| b0-code | `tag_review.py`：`bulk_review` 改为合并写（保留 `_` 前缀溯源键），`is_assembly_ready`/`review_tag` 显式忽略/拒绝 `_` 维度（含单测） | 否 |
| b0-data | 74 条 tag_review 元数据键清除；验收：`_` 键清零、bulk_review 不再抹除溯源；#421/#423 缺 legal_topic 维度转待审（不自动批准） | 否 |
| b1 | P3 去重 65 组（复用既有 `--tier p3` 语义，纳入 batch 快照布局） | 否 |
| b2 | 18 条 scenario 地域条款改写（草拟可用免费 flash 或人工，逐条人工确认） | 小 |
| b3 | 伪影清理 ~600 条：正则先行（签署壳行、`___`、表格碎片），残余留待网关恢复 | 否（残余除外） |
| b4 | 零散：#7267 金额、3 条悬空法条尾缀、15 条残桩分拣 | 小 |

### D5. 伪影清理用确定性规则 + 白名单，不做模型改写
签署壳判定：整行匹配 `（签字|盖章|签章）/签订(地点|日期)|身份证号|邮编|联系方式` 等模式才删行；`___` 填空按上下文映射到既有 slot（份数→`{{contract_copies}}`）；表格碎片（`|---|`）整块删除并保留其前导句。
理由：模式集在 507+95+5 条样本上 precision 已目测足够，且每条都有 before 快照兜底；模型改写反而引入语义漂移风险。白名单保护 #3686 这类"签署信息在母版属正当章节"的情况——只清理进入了非签署章节的壳。

### D6. 门控修复不迁移数据格式
`_` 前缀键从门控里排除，但数据清理（b0-data）仍会物理删掉这些键——两步独立。若只上代码不清数据，74 条条款即刻恢复正确门控（元数据键被忽略）；数据清理是为了 dashboard/审核 UI 不再显示脏维度。
替代方案（否决）：把元数据迁到 `tags` JSONB——`validate_tags` 会静默丢未知键（audit.py 已知坑），需要动 tags schema，超出本变更。

## Risks / Trade-offs

- [正则误删正文行] → 白名单模式 + 先 dry-run 打印 diff + batch b3 首批限 50 条人工抽检后再放量；before 快照可逐条恢复。
- [工作机直写生产库] → 只走既有 `update_clause`/`bulk_review` 串行写路径；每 batch 前先只读跑一遍目标清单核对 id；不执行任何 DELETE/UPDATE 以外的 DDL。
- [公共只读 API 读副本传播延迟] → 逻辑复制异步，治理后中国侧最多滞后数秒~分钟，属正常传播，不做等待同步的操作。
- [窗口模型/人工改写的风格漂移] → b2/b4 每条改写走"草拟→人工确认→region_lint==0 验证"三步，不自动落库。
- [b0-code 上线与 b0-data 的顺序] → 代码先合入部署（否则数据清理后 dashboard 仍显示旧逻辑判定）；代码回退（git revert）不会破坏已清理的数据，二者兼容。

## Migration Plan

1. 合入 b0-code → Jenkins 构建新镜像 → `kubectl apply` 滚动（既有流程，见 `deploy/cheap-box/README.md`）。
2. 打开隧道（D2），只读验证连通与目标 id 清单。
3. 依次执行 b0-data → b1 → b2 → b3（首批 50 条抽检后放量）→ b4，每 batch：dry-run → 应用 → 验收（detector 复扫 + 受影响 scenario 各生成一份合同人工过目）。
4. 回退路径：数据问题用 `--rollback <batch>`；代码问题 git revert 重新部署；两者独立生效。
