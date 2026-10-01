# 法规目录副本与引法审计 Runbook

`link-law-catalog-audit` 的操作手册：目录副本的刷新、名称解析的重跑、引法审计的产出，以及 web 复核队列的使用。设计与规格见 `openspec/changes/link-law-catalog-audit/`。

## 架构速览

```
法规库 PG (law_db.laws, 权威目录)  ──导出──▶ RustFS  ──下载──▶ law-bench PG
   id 即 Qdrant payload.law_id                              law_catalog.laws（只读副本）
                                                                    ▲
条款库 clauses.law_refs (《...》派生列, 只读) ──解析阶梯──▶ law_catalog.clause_law_refs
                                                            │
                                            审计报告 docs/law_citation_audit_report.md
                                            + web 复核队列 /law-catalog/review
```

- 解析结果存 `law_catalog.clause_law_refs`，**绝不写回 `clauses.law_refs`**（该列由条款体派生，编辑即重算）。
- 判定只用 `status` 列：`已废止`/`失效` → 引用已废法律；`已修改` → 单列；NULL/脏值 → 兜底。
- **`expiry` 列的实义是施行日期**（实测合同法 publish 1999-03-15 / expiry 1999-10-01），任何判定禁止使用。
- `law_id` 在 JSONL/Qdrant 里是字符串；本副本用 PG 原生 BIGINT，未来接 law-api 时在消费边界统一按字符串比较。

## 一次性准备

pg_trgm 扩展（trigram 解析档与相似度索引需要；缺失时解析降级——全部未命中进复核队列，其余功能不受影响）：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- 若 DATABASE_URL 用户无权限，由管理员执行一次
```

## 目录刷新（法规库侧有增量后）

一键方式（导入 → 名称级解析+审计 → 条文级解析，约 5 分钟）：

```bash
scripts/refresh_law_catalog.sh /path/to/laws_export.jsonl
```

分步方式（与上面等价）：

1. **法规库侧导出**（在法规库 PG 上）：

   ```sql
   \copy (SELECT id,title,category,publish,expiry,status,src_db,content_status FROM laws ORDER BY id)
         TO '/tmp/laws_export.jsonl' WITH (FORMAT csv) CSV HEADER;
   ```

   （或任意能产出 JSON/JSONL 的方式；导入脚本两者都认。）

2. **上传 RustFS**：放 `laws-export` 桶，如 `catalog/laws_export-YYYYMMDD.jsonl`，经 `https://file.finddatatech.cloud` 可取。

3. **law-bench 侧导入**：

   ```bash
   python scripts/import_law_catalog.py --file /tmp/laws_export.jsonl --seed-aliases
   # imported 21746 laws (max_id=74584) ...
   ```

   全量替换语义：导入失败旧副本不动，成功则与导出完全一致。**基线对账**：首次导入应约 21,746 行 / max_id≈74,584（2026-09-24 快照，lawv2 13,930 / flk 3,239 / law 4,577）。
   不要从 `law_fixed.db`（SQLite 源）搬：行号 ≠ PG id，且缺 flk 增量。

## 解析与审计

```bash
# 全量解析（幂等，可随时重跑；不改条款任何字段）
python scripts/law_citation_audit.py --resolve-only

# 解析 + 报告（默认写 docs/law_citation_audit_report.md）
python scripts/law_citation_audit.py

# 只重渲染报告（不重跑解析）
python scripts/law_citation_audit.py --report-only
```

报告头带目录快照标识（行数/max_id/导入时间），可追溯；`resolved_via` 分 `exact/alias/trigram/unresolved`，模糊命中的可信度一眼可辨。连续两次运行、语料与目录未变时，结果与计数完全一致。

## 复核队列（web）

- `/law-catalog/audit`：审计总览 + 已废止/已修改明细（链接到条款）。
- `/law-catalog/review`：未解析名称 × 出现次数，附 trigm 候选；动作：
  - **确认映射**（候选按钮或手填 law_id）→ 写入别名表 `source='review'`，下次解析 `resolved_via=alias`；
  - **标记不匹配** → `source='non_match'`，移出复核队列，不伪造关联。
- 动作只写别名表，**不触碰条款正文与 `law_refs`**。写权限需 `content:write` scope。

## 已知边界

- 别名表冷启动：内置种子（`src/law_catalog/alias_seed.py`，九民纪要、各司法解释简称等）只兜常见写法；目录里不存在的目标标题会落到复核队列，不猜测。
- pg_trgm 缺失时 trigram 档降级为未解析（全部进复核队列），exact/alias 档不受影响。
- `law_catalog.laws` 是只读镜像，与法规库的同步是上面的人工刷新流程，不做自动同步。

## 法语义检索（第二批 integrate-law-semantic-search）

law-bench 通过法规库计量 API 获取法规语义检索与全文，自身**零向量配置**（模型/维度/Qdrant 全在网关后）。

### 配置面（三个环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LAW_API_BASE_URL` | `https://law-api.finddatatech.cloud/v1` | 网关入口 |
| `LAW_API_KEY` | 空 | APISIX key-auth 的 key；**空 = 功能整体关闭、零请求** |
| `LAW_SEARCH_ENABLED` | false | 总开关，与 key 双重门控 |

可选 `LAW_API_MIN_INTERVAL`（默认 0.12s）：批量解析时对 10 r/s 限流的主动礼让。

### 开通三步（法规库项目侧）

Lago 建客户 → APISIX 发 key → meter-map 加映射（见法规库项目 `cluster/consumer-onboarding.md`）。key 回填到 law-bench 的部署 secret 后生效。

### 冒烟与使用

- 进程启用后首次调用前自动跑一次固定查询冒烟（`民法典 离婚后子女抚养费`），失败记 ERROR 并本进程降级，不阻断起草。
- 任何网关故障（网络/超时/401/429）一律静默降级为空结果，起草/评测永不被法规检索拖垮。
- 条文级解析：`python scripts/resolve_article_citations.py`（`--dry-run` 只看不写；需 key）。
  结果入 `law_catalog.clause_article_refs`，outcome 四类分开：resolved / unresolved_name / fetch_failed / out_of_range。

## 引法修复（remediate-repealed-citations）

废止引法的确定性修复：承继映射 → dry-run 过目 → 经 `update_clause` 应用（唯一写路径，manual=true）→ 闭环验证。全程留痕：`law_catalog.citation_revisions`（查询面，`/law-catalog/revisions` 页可看）+ `output/remediation/<batch>/` 快照（回滚面）。

```bash
python scripts/remediate_citations.py seed                        # 重建承继映射（显式对 + 地方占位）
python scripts/remediate_citations.py dry-run --batch r1 [--type sale] [--json]  # 计划（diff+证据+跳过）
python scripts/remediate_citations.py apply --batch r1 [--type sale]             # 应用+记录+快照+验证
python scripts/remediate_citations.py noaction                    # r0：已修改留档
python scripts/remediate_citations.py rollback --batch r1 [--clause-id N]        # 从 before 快照恢复
python scripts/remediate_citations.py verify                      # 闭环：已废数应=占位数
```

消费导出：`export-paper`（统计聚合）、`export-finetune --batch r1`（修正对 → `data/finetune/citation-fixes/`）。修复统计见 `docs/law_citation_remediation_stats.md`。

当前基线（2026-09-26 r0/r1 完成后）：ok 1,509 / 已废 7（4 部地方废规占位，待人工确认承继后 seed 转正再跑）/ 已修改 17 / 兜底 612。
