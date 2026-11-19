## Why

`src/eval/store.py::ensure_schema` 在 `lock_timeout`（3 秒）命中 `LockNotAvailable` 时，把该库**标记为已建表**然后继续：

```python
except psycopg.errors.LockNotAvailable:
    # Another process holds the lock; schema should already exist from
    # previous runs, so just mark as ensured and continue.
    _ensured_dbs.add(key)
```

这行注释在城市传说上是成立的（"别人已经在建了"），但它假设了一个**没有验证过**的前提：另一个进程**确实**在建、并且**建完了**。当两个进程同时首次触达一个新库时，两边都拿到锁超时，两边都把自己标记为 ensured，而 DDL 一条都没执行——本进程随后所有写入都撞 `UndefinedTable`，而且**再也不会重试**（`_ensured_dbs` 命中即返回）。

实测复现（2026-11-18，本机 15432）：

```
持 ACCESS EXCLUSIVE 锁 → ensure_schema() → 3s 锁超时被吞
→ _ensured_dbs 含该库（自称已建表）
→ SELECT to_regclass('public.review_tasks') → False
```

这不是测试环境的怪癖，而是**任何并发首启都踩得到**的生产缺陷：多副本同时起、进程重启与新请求并发、批量建库。失效时没有信号——进程不崩、日志只有一条被吞的异常，直到第一次写入才在远处炸，而现场已经离开案发点。

测试只是把它暴露得更频繁：`conftest` 的会话库 + 每测试一次性 DB 会连续建 20+ 个库，3 秒锁窗口被反复撞上，于是 `test_bench_calibration.py` 与 `test_run_cli.py` 的任意组合都能复现（它们在干净树上同样复现，与 `add-eval-verdict-ledger` 无关）。

## What Changes

- **锁超时不再等价于成功**：`ensure_schema` 在 `LockNotAvailable` 时 SHALL NOT 把该库标记为已建表。它 SHALL 区分两种情形：
  - **本次 DDL 已提交**（并发方先跑完了，我们的 DDL 因 `IF NOT EXISTS` 变成 no-op）→ 可以标记；
  - **本次 DDL 未执行**（锁超时）→ MUST NOT 标记，且 MUST 让调用方知道「这一次没建成」。

- **锁超时的对外语义是「稍后重试」，不是抛错**：并发建表是正常竞争，不该让第一个请求 500。`ensure_schema` SHALL 允许调用方继续（不做 DDL 也能读到已存在的表），但 MUST NOT 缓存"已完成"状态，使下一个请求重新尝试。

- **失败必须可见**：锁超时 SHALL 留下一条可观测记录（一条 warning 级日志，带库名与原因），MUST NOT 静默。今天它连日志都没有，这是它藏了这么久的原因。

- **表缺失要能被前置判出**：追加一道轻量校验——`ensure_schema` 在声明"该库已就绪"之前 SHALL 确认一组必需表确实存在（一次 `to_regclass` 批量查询即可，成本 1 次往返，且只在首次每库发生）。判据不成立时 SHALL NOT 标记，并按上一条处理。

## Capabilities

### New Capabilities

- `schema-bootstrap-liveness`: 建表引导的失败语义契约——「锁等待超时」与「并发方已建好」必须可区分、可观测、可重试；「已就绪」只能由实测表存在来断言，MUST NOT 由异常被吞来断言。

### Modified Capabilities

- `test-suite`: `seeded_db` / `_session_db_name` 的隔离契约补充一条——fixture 建库后 SHALL 确认 schema 真的落地（否则测试会在错误层失败：报 `UndefinedTable` 于测试想测的东西上，而不是报"建库没成功"）。

## Impact

- **代码**：`src/eval/store.py`（`ensure_schema` 的锁超时分支 + 就绪校验）。这是**所有**表创建的单一入口（`RESULTS_SCHEMA` … `API_KEYS_SCHEMA` … bench kernel 的 `BENCH_SCHEMA`/`WORKSPACE_SCHEMA`/`LIBRARY_SCHEMA`），改一处分母覆盖全部。
- **测试**：为锁超时路径新增一个真实并发用例（持锁 → 调 `ensure_schema` → 断言未标记 + 表确实不存在 + 放锁后重试成功）。现有 `tests/test_store.py::test_ensure_schema_idempotent` 覆盖的是无竞争路径，不改。
- **既有行为**：无竞争路径零变化；并发路径从「静默半残」变为「先重试、实在不行报因」。
- **依赖**：无。这是纯修复，不依赖任何在途 change。
- **风险**：把锁超时从「静默通过」改为「不缓存」会让并发首启多跑几次 DDL。缓解：这本来就是这个函数的设计（可重入、幂等），多跑的成本是一次 `IF NOT EXISTS` 往返；比起静默半残，这个代价是必付的。
