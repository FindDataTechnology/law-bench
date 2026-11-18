## 1. Centralize configuration

- [x] 1.1 Create `src/settings.py` exporting `REPO_ROOT`, `DEFAULT_DB`, `TEMPLATES_DIR`, `EXTRACT_SCRIPT`, `ConfigError`, and per-subsystem required-env-var lists (intake/drafter/auditor, eval judge)
- [x] 1.2 Re-point `src/eval/rubric.py`, `src/eval/store.py`, `src/crew.py`, and `src/web/routes/api.py` to import paths from `src/settings.py` (remove `DEFAULT_DB` definition from `rubric.py` and the `REPO_ROOT` re-derivation in `api.py`)
- [x] 1.3 Run the existing test suite (`uv run pytest`) and confirm it is still green with no behavior change

## 2. Extract shared eval internals

- [x] 2.1 Create `src/eval/errors.py` with the `ManageError` hierarchy (`ManageError`, `NotFoundError`, `HarborReadOnlyError`, `ConflictError`, `ValidationError`)
- [x] 2.2 Create `src/eval/db.py` with `_connect`, `_now_iso`, `_is_harbor`, `_renumber_criteria`, and the shared row-to-dict helpers
- [x] 2.3 Re-point `src/eval/manage.py` internals and `src/eval/store.py` to import from `db.py`/`errors.py`; delete the duplicated `_connect` in `store.py`
- [x] 2.4 Run the existing suite and confirm green

## 3. Split manage.py CRUD (keep facade)

- [x] 3.1 Create `src/eval/rubric_crud.py` containing the rubric + criterion read/write helpers and validation (`create_rubric`, `update_rubric`, `delete_rubric`, `add_criterion`, `update_criterion`, `delete_criterion`, `reorder_criteria`, `list_rubrics_with_counts`, `get_rubric_detail`, `get_rubric_by_id`)
- [x] 3.2 Create `src/eval/prompt_crud.py` containing the prompt read/write helpers and validation (`list_prompts`, `get_prompt`, `get_prompt_by_id`, `create_prompt`, `update_prompt`, `delete_prompt`)
- [x] 3.3 Reduce `src/eval/manage.py` to a re-export facade: `from .rubric_crud import *`, `from .prompt_crud import *`, `from .errors import *`, plus the existing `__all__`
- [x] 3.4 Run `tests/test_manage.py` unedited and confirm every test still passes (no edits to its assertions)

## 4. Test fixtures

- [x] 4.1 Create `tests/_fakes.py` with a `FakeJudge` that impersonates the `model=` passed to `GEval` and sets `success`/`reason`/`error`/`evaluation_model` per a configurable verdict map
- [x] 4.2 Create `tests/conftest.py` with: a seeded throwaway-DB fixture (real schema from `scripts/extract_harbor_rules.py` + one harbor + one local rubric), an app-client fixture that overrides `get_db` to the throwaway DB, and the fake-judge fixture
- [x] 4.3 Move `tests/test_web_prompts.py` onto the app-client fixture so it no longer mutates `db/evaluation_rules.db`; keep its assertions

## 5. Web layer DB dependency + tests

- [x] 5.1 Add a `get_db() -> Path` FastAPI dependency (default returns `config.DEFAULT_DB`) in `src/web` (e.g. `src/web/deps.py`)
- [x] 5.2 Thread `db: Path = Depends(get_db)` through every `routes/api.py` handler and pass it as `db_path` to the manage calls
- [x] 5.3 Thread `db: Path = Depends(get_db)` through every `routes/pages.py` handler and pass it as `db_path` to the manage calls
- [x] 5.4 Add `tests/test_web_api.py` covering rubric + criterion routes: create/read/update/delete, reorder, and the error mappings (harbor read-only -> 403, duplicate name -> 409, invalid input -> 400, unknown name/id -> 404)
- [x] 5.5 Add `tests/test_web_pages.py` covering HTML form submissions (rubric + criterion + prompt create/update/delete) and their flash redirects, plus the harbor-extract page route (monkeypatched)
- [x] 5.6 Add `tests/test_app.py` covering `create_app`, static/template mounts, and the `ManageError`-to-HTTP-status handler mapping including the 500 fallback for unmapped `ManageError`

## 6. Evaluation engine unit tests

- [x] 6.1 Add `tests/test_rubric.py` covering `list_rubrics` and `load_criteria`, including `KeyError` on unknown rubric and `ValueError` on a rubric with no criteria
- [x] 6.2 Add `tests/test_store.py` covering `ensure_schema` idempotency, `store_result` round-trip (run + per-criterion verdicts), and `list_runs` ordering (newest first)
- [x] 6.3 Add `tests/test_scoring.py` using `FakeJudge`: all-pass aggregation, single-fail -> `FAIL`/`score=0.0`, error-per-criterion captured not fatal, `judge_model` fallback to `EVAL_MODEL`, and the result-dict shape
- [x] 6.4 Add `tests/test_judge.py` covering `_strip_litellm_prefix` (with and without `openai/` prefix) and `RuntimeError` on missing env vars
- [x] 6.5 Add `tests/test_db.py` covering the extracted `db.py` helpers (`_connect` row factory + foreign keys, `_is_harbor`, `_renumber_criteria` contiguity)

## 7. Drafting pipeline tests + llm error

- [x] 7.1 Tighten `src/llm.py` to raise `ConfigError` (from `src/settings.py`) when `{ROLE}_MODEL` is missing, instead of a bare `KeyError`
- [x] 7.2 Add `tests/test_llm.py` covering env-driven model selection, temperature/max_tokens defaults, and the missing-model error
- [x] 7.3 Add `tests/test_crew.py` covering `_templates_reference` (non-empty, one block per `templates/*.md`) and crew assembly (agents/tasks populated) without an LLM kickoff

## 8. CLI tests + main.py argparse

- [x] 8.1 Rewrite `main.py` to use `argparse` with a single positional `request` and an optional positional `output` (`nargs="?"`); preserve the documented `python main.py "<request>" [output.md]` interface and the env-var checks
- [x] 8.2 Add `tests/test_main_cli.py` covering output-file writing (kickoff monkeypatched), the usage/missing-args error path, and env-var-missing handling
- [x] 8.3 Add `tests/test_run_cli.py` covering `--list-rubrics` and `--list-runs` (no judge call), missing-required-args error, and scores-JSON output-file writing (evaluate_contract monkeypatched)

## 9. Backward-compat verification + finalize

- [x] 9.1 Add a facade test asserting `from src.eval.manage import ...` exposes the expected public names (CRUD functions + error classes) after the split
- [x] 9.2 Run the full suite (`uv run pytest`) and verify hermetic execution: no network calls, `db/evaluation_rules.db` unchanged before/after
- [x] 9.3 Update `pyproject.toml` test config only if needed (e.g. testpaths); confirm all tests green and the suite passes from a clean checkout
