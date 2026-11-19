## Context

`src/eval/store.py::ensure_schema` 是所有表创建的单一入口：`RESULTS_SCHEMA`、`LAW_INFO_SCHEMA`、`CLAUSES_SCHEMA`、`TAG_DIMS_SCHEMA`、`PIPELINE_SCHEMA`、`INDUSTRY_STANDARD_SCHEMA`、`CONTRACT_ARTIFACTS_SCHEMA`、`API_EVAL_SCHEMA`、`GENERATION_JOBS_SCHEMA`、`API_KEYS_SCHEMA`、`REVIEW_TASKS_SCHEMA`，加上 bench kernel 的 `BENCH_SCHEMA` / `WORKSPACE_SCHEMA` / `LIBRARY_SCHEMA` 与 `_ADDITIVE_COLUMNS`。

它有三层缓存/保护，都是「让重复调用便宜」：

1. 进程内 `_ensured_dbs` 集合（每库一次 DDL）；
2. `_ensure_lock`（线程内串行）；
3. `SET lock_timeout = '3s'`（跨进程不互相堵死）。

第 3 层配了一个兜底：`except LockNotAvailable: _ensured_dbs.add(key)`。实测（见 proposal）这条兜底会把「一条 DDL 都没跑」的库标记成就绪，且此后永不重试。

## Goals / Non-Goals

**Goals**

- 让「建表成没成」由实测断言，不由异常被吞来断言。
- 锁超时仍然**不阻塞**调用方（并发首启不该 500）。
- 失败可观测，且区分「可重试的竞争」与「需要人看」。

**Non-Goals**

- 不改三层缓存的形状，不引入 advisory lock 或迁移框架。
- 不改任何表定义。
- 不处理"schema 版本比代码旧"的迁移问题（那是另一件事；本 change 只管引导是否完成）。

## Decisions

### D1 — 锁超时 → 不缓存 + 立刻实测一次

```python
except psycopg.errors.LockNotAvailable:
    log.warning("schema bootstrap for %s hit lock_timeout; will retry on next call", key)
    # fall through to the readiness probe, do NOT add to _ensured_dbs
```

然后走同一条就绪探测（D2）。若探测发现表齐（并发方建完了）→ 标记；不齐 → 不标记，本次调用继续（调用方可能只读已有表），下一次再试。

**为什么不直接抛错**：并发建表是正常竞争。抛错会让"两个副本同时冷启"变成一次可用性事件，而它本来只是一次多余的重试。

**为什么不加重试循环**：调用已经等了 3 秒；在请求路径上继续阻塞不是修复。把"这次没成"如实返回，下一次调用会再来——`ensure_schema` 本来就是每个 store 函数入口都会调的。

### D2 — 就绪 = 一组必需表实测存在

```python
_REQUIRED_TABLES = (
    "eval_runs", "eval_criteria_results", "compare_runs", "criteria", "rubrics",
    "prompts", "law_info", "clauses", "contract_artifacts", "api_keys",
    "review_tasks", "pipeline_runs", "tag_dims",
    "knowledge_units", "domains", "ontology_templates", "authoring_tasks",
    "domain_agent_runs", "distribution_consumers", "corpus_chunks",
)
```

一次往返：

```sql
SELECT t FROM unnest(%s::text[]) AS t WHERE to_regclass('public.' || t) IS NULL
```

返回空数组 = 齐了。非空 = 缺这些，不标记并 log。

**为什么列清单而不是"随便挑一张"**：只查一张表会让判据退化成"这张建好了就算好了"——正是本 change 要消掉的放松。清单必须与真实写入面一致，所以它旁边要写一句"新增表时同步此清单"，并且由 D3 的测试兜住（加一张表不加进清单，测试不会红——这是已知残余风险，见 Risks）。

**替代方案**：查 `information_schema.tables` 全量比对。否决理由：那要维护一份完整期望表清单，比"必须存在"的清单更难维护且更易误报（其它模块建的表不该让这里红）。

### D3 — 锁超时路径要有真实并发测试

现有 `test_ensure_schema_idempotent` 只测无竞争。新增：

```
test_lock_timeout_does_not_mark_ready:
  建一个空库 → 另一连接 LOCK TABLE 某表 ACCESS EXCLUSIVE
  → 调 ensure_schema（约 3s 后超时）
  → 断言 库不在 _ensured_dbs
  → 断言 必需表确实不存在
  → 放锁 → 再调 ensure_schema → 断言 这次齐了且被标记
```

这条测试的代价是要等 3 秒锁超时。可接受：它钉住的是一个静默失败的洞。

把它放进 `tests/test_store.py`（已有的 schema 测试家）。为了让测试不必真等 3 秒，`ensure_schema` 的 `lock_timeout` 可由环境变量覆盖（`SCHEMA_LOCK_TIMEOUT_MS`，默认 3000）——测试设 200ms。

### D4 — fixture 层加一道前置断言

`tests/conftest.py::_session_db_name` 在 `ensure_schema()` 之后立即断言 `review_tasks` 等必需表存在且**抛带引导语义的错误**。这不会修复 D1（那是生产修复），但保证测试失败时指向正确的地方。

## Risks / Trade-offs

- **[并发首启会多跑几次 DDL]** → 它本来就是幂等可重入的；多跑一次 `IF NOT EXISTS` 往返远便宜于静默半残。
- **[_REQUIRED_TABLES 与真实写入面漂移]** → 新增表时若忘记加进清单，判据会放松而不报警。缓解：清单旁写明纪律；**残余风险已记录**——真正的解法是让每个模块注册自己的必需表，那是更大的重构，不在本 change。
- **[锁超时日志在高压下变吵]** → 每条是 warning 且带库名；若真的高频，那是并发首启的频次问题（也值得知道），不是日志写多了。
- **[测试多 3 秒（或 200ms）]** → 用一个真实并发场景换掉一个静默失败的洞，值。

## Migration Plan

1. 改 `ensure_schema`（D1/D2）+ 加环境变量旋钮（D3）。
2. 加并发测试并确认它**在旧代码上红、新代码上绿**（这是本 change 唯一的验收硬证据）。
3. 加 fixture 前置断言（D4）。
4. 回滚：单文件逻辑，`git revert` 即回；无数据迁移。

## Open Questions

无。
