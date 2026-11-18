## 1. Bundle harbor rubric seed data

- [x] 1.1 Create `src/eval/seed/__init__.py` and `src/eval/seed/harbor/__init__.py` (empty package markers)
- [x] 1.2 Copy harbor's `cli/quality_checker/default-rubric.toml` verbatim to `src/eval/seed/harbor/task_quality.toml` (11 criteria)
- [x] 1.3 Copy harbor's `analyze/prompts/analyze-rubric.toml` verbatim to `src/eval/seed/harbor/trial_behavior.toml` (2 criteria)

## 2. Importable seeding module

- [x] 2.1 Create `src/eval/harbor_seed.py` and move `SCHEMA`, `create_schema`, `_ensure_column`, `load_criteria`, `upsert_harbor_rubric`, `print_summary`, `HARBOR_RUBRICS`, `find_harbor_package`, `get_harbor_version` out of `scripts/extract_harbor_rules.py`; `find_harbor_package` returns `None` (no `SystemExit`) when harbor is absent
- [x] 2.2 Add `BUNDLED_SEED_DIR`, `BUNDLED_HARBOR_VERSION = "v0.20.0"`, and point each `HARBOR_RUBRICS` entry's `source_path` at its bundled TOML filename
- [x] 2.3 Add `load_harbor_rubrics()` returning `[(rubric, criteria, source)]`: use installed harbor + real version when `find_harbor_package()` returns a path, else the bundled TOMLs + `harbor:v0.20.0`
- [x] 2.4 Add `ensure_harbor_rubrics(db_path=DEFAULT_DB)` that connects, calls `create_schema`, upserts every harbor rubric via `load_harbor_rubrics()`, commits, closes, and returns a summary including the source origin (`"installed"` or `"bundled"`)
- [x] 2.5 Add a `__main__` argparse CLI (`--db`) that calls `ensure_harbor_rubrics()` + `print_summary` and exits 0

## 3. Refactor the extraction script

- [x] 3.1 Reduce `scripts/extract_harbor_rules.py` to a thin wrapper that imports from `src.eval.harbor_seed`
- [x] 3.2 Re-export `create_schema`, `DEFAULT_DB`, `print_summary`, `project_root`, `HARBOR_RUBRICS`, `upsert_harbor_rubric`, `load_criteria` as module attributes so `tests/conftest.py` and `tests/test_manage.py` keep working via importlib
- [x] 3.3 `main()` prints the source origin (installed harbor vs bundled seed), calls `ensure_harbor_rubrics(args.db)`, prints the summary, and exits 0 even when harbor is not installed

## 4. Container startup self-heal

- [x] 4.1 Create `scripts/docker-entrypoint.sh` that runs `.venv/bin/python -m src.eval.harbor_seed --db /app/db/evaluation_rules.db` then `exec`s `uvicorn src.web.app:app --host 0.0.0.0 --port 8010`
- [x] 4.2 Update `Dockerfile`: `chmod +x` the entrypoint and replace the `CMD` with `["./scripts/docker-entrypoint.sh"]`
- [x] 4.3 Confirm `.dockerignore` does not exclude `src/eval/seed/` or `scripts/docker-entrypoint.sh`

## 5. Tests

- [x] 5.1 Add `tests/test_harbor_seed.py::test_ensure_heals_empty_db`: empty tmp DB -> `ensure_harbor_rubrics()` -> schema present, 2 harbor rubrics, 13 criteria, `source = harbor:v0.20.0`
- [x] 5.2 Add `test_ensure_idempotent`: run twice -> counts unchanged, no duplicates
- [x] 5.3 Add `test_ensure_preserves_local_and_eval`: pre-seed a local rubric + an `eval_runs` row -> after heal, both are unchanged (scoped to harbor rows)
- [x] 5.4 Add `test_load_uses_bundled_when_harbor_absent`: monkeypatch `find_harbor_package` -> `None`; `load_harbor_rubrics()` returns criteria sourced `harbor:v0.20.0`

## 6. Verification

- [x] 6.1 `uv run pytest` is green (existing tests unaffected + new tests pass)
- [x] 6.2 `uv run python -m src.eval.harbor_seed --db /tmp/empty.db` then `sqlite3 /tmp/empty.db "SELECT name, source FROM rubrics WHERE source LIKE 'harbor:%';"` returns 2 rows
- [x] 6.3 `uv run python scripts/extract_harbor_rules.py --db /tmp/empty2.db` exits 0 with harbor rubrics present (simulates container with no harbor installed)
- [ ] 6.4 `docker build -t law-template .` succeeds; running the image serves `/api/rubrics` with the 2 harbor rubrics *(DEFERRED to CI: docker is not installed locally. Container self-heal behavior verified via the stale-volume CLI simulation — a locals-only DB healed to 2 harbor rubrics / 13 criteria with `origin=bundled` and locals preserved — plus `test_ensure_preserves_local_and_eval`.)*
