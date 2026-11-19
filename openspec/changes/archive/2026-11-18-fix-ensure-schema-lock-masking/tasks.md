## 1. 修复引导语义

- [x] 1.1 `src/eval/store.py`：`ensure_schema` 的 `LockNotAvailable` 分支改为「不加入 `_ensured_dbs` + 一条带库名的 warning 日志 + 落到就绪探测」；验证：新增 `tests/test_store.py::test_lock_timeout_does_not_mark_ready` 在改动前红、改动后绿
- [x] 1.2 加 `_REQUIRED_TABLES` 清单与一次性批量存在性探测（`to_regclass`），就绪只能由「清单全在」断言；验证：删掉某张必需表后调用 `ensure_schema`，该库不被标记且日志点名缺表
- [x] 1.3 `lock_timeout` 改为可配（`SCHEMA_LOCK_TIMEOUT_MS`，默认 3000），使并发测试不必真等 3 秒；验证：设 200ms 时锁超时用例在 ~200ms 内结束
- [x] 1.4 确认无竞争路径零行为变化；验证：`tests/test_store.py` 全绿且 `test_ensure_schema_idempotent` 断言口径不变

## 2. 测试夹具指向正确的地方

- [x] 2.1 `tests/conftest.py::_session_db_name` 在建表后断言语义就绪，失败时报「schema bootstrap did not complete」而不是让后续 `TRUNCATE` 报 `UndefinedTable`；验证：人为破坏建表后跑任一 `seeded_db` 用例，错误文案指向引导
- [x] 2.2 复现原始故障组合作为回归：`uv run pytest tests/test_bench_calibration.py tests/test_run_cli.py`；验证：改动前失败的组合改动后全绿

## 3. 收尾

- [x] 3.1 全量回归绿（`uv run pytest tests`），且用例数不低于改动前；验证：pytest 汇总无 failed/error
- [x] 3.2 `docs/evaluation-system.md` 或 `INFRA-NOTES.md` 记一句：建表引导在锁竞争下的语义（可重试、不入缓存、实测断言就绪）；验证：文档评审
