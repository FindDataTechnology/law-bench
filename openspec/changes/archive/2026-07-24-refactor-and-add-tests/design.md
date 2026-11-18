## Context

`chinese-contract-drafter` has three subsystems sharing one SQLite database (`db/evaluation_rules.db`):

- **Drafting pipeline** - `src/crew.py` (CrewAI sequential crew: intake → drafter → auditor, agents/tasks loaded from `src/config/*.yaml`), `src/llm.py` (per-role LLM factory), `main.py` (CLI).
- **Evaluation engine** - `src/eval/rubric.py` (load rubric/criteria, map to harvey-labs shape), `judge.py` (deepeval `GPTModel` at the Ark endpoint), `scoring.py` (one `GEval` per criterion, all-pass, `ThreadPoolExecutor`), `store.py` (persist runs + verdicts), `manage.py` (640-line CRUD for rubrics/criteria/prompts), `run.py` (CLI).
- **Web layer** - `src/web/app.py` (`create_app`, error handlers), `routes/api.py` (JSON API under `/api`), `routes/pages.py` (Jinja2 HTML flows), `models.py` (Pydantic).

Current pain: only `tests/test_manage.py` (manage CRUD, temp DB) and `tests/test_web_prompts.py` (`/api/prompts` against the **real** dev DB) exist. `manage.py` mixes three CRUD domains plus duplicated connection/validation helpers (`_connect` is duplicated in `manage.py` and `store.py`; `DEFAULT_DB` is defined in `rubric.py` and imported sideways). The web routes hardcode the default DB, so web tests cannot avoid mutating dev data. `main.py` parses `sys.argv` by hand with a fragile `sys.argv[1:-1]` heuristic. `scoring.evaluate_contract` already accepts an injectable `judge`, but no test exploits it.

Constraints: Python 3.12+, `uv`/`pyproject.toml`, pytest already in the `dev` group, `pythonpath = ["."]` already configured. Legal contract text must not leave the machine (`DEEPEVAL_TELEMETRY_OPT_OUT`), so tests must not call real LLMs.

## Goals / Non-Goals

**Goals:**
- Make every module unit-testable in isolation without network or dev-DB mutation.
- Split `manage.py` into focused, single-responsibility modules while preserving the `from src.eval import manage as M` surface.
- Centralize path/env configuration so DB path and repo root are defined once.
- Thread a DB dependency through the web layer so `TestClient` tests run against a throwaway DB.
- Reach full automated coverage of drafting, evaluation, and web subsystems.

**Non-Goals:**
- Changing any user-visible behavior, route, CLI command, or DB schema.
- Adding new product features or endpoints.
- Introducing a new test framework or a CI pipeline (out of scope; suite just needs to be runnable locally via `uv run pytest`).
- Performance optimization of the LLM/scoring path.
- End-to-end tests that call real LLMs (explicitly excluded by the hermetic-execution requirement).

## Decisions

### D1: Centralize config in `src/settings.py`
Create `src/settings.py` holding `REPO_ROOT`, `DEFAULT_DB` (moved out of `rubric.py`), `TEMPLATES_DIR`, `EXTRACT_SCRIPT`, and the per-subsystem required-env-var lists. `rubric.py`, `manage.py`, `store.py`, `crew.py`, `llm.py`, `judge.py`, and `routes/api.py` import from it.

**Why**: `DEFAULT_DB` is currently defined in `rubric.py` and imported by `manage.py` and `store.py`; `routes/api.py` re-derives `REPO_ROOT` from `DEFAULT_DB.parent.parent`; `crew.py` derives `TEMPLATES_DIR` independently. A single module removes three sideways dependencies and gives tests one place to read paths. Named `settings.py` (not `config.py`) because `src/config/` already exists as the CrewAI YAML data directory - a `config.py` file beside a `config/` package is import-ambiguous.
**Alternative considered**: keep `DEFAULT_DB` in `rubric.py` and just add a `settings.py` for the rest. Rejected - the DB path is the most-imported value and `rubric.py`'s job is loading criteria, not owning config.

### D2: Split `manage.py` into `db.py` + `errors.py` + `rubric_crud.py` + `prompt_crud.py`, keep `manage.py` as a re-export facade
- `src/eval/db.py` - `_connect(db_path)`, `_now_iso()`, `_is_harbor()`, `_renumber_criteria()`, and the row-to-dict helpers; imported by both the CRUD modules and `store.py` (which drops its own `_connect`).
- `src/eval/errors.py` - `ManageError`, `NotFoundError`, `HarborReadOnlyError`, `ConflictError`, `ValidationError`.
- `src/eval/rubric_crud.py` - rubric + criterion CRUD and read helpers.
- `src/eval/prompt_crud.py` - prompt CRUD and read helpers.
- `src/eval/manage.py` - becomes `from .rubric_crud import *` / `from .prompt_crud import *` / `from .errors import *` plus the existing `__all__`, so `from src.eval import manage as M` and `from src.eval.manage import ConflictError` keep working unchanged.

**Why**: 640 lines in one file mixes three CRUD domains and low-level helpers; splitting makes each piece independently testable and readable. The facade preserves the import contract the routes and existing tests depend on, so the split is zero-breakage.
**Alternative considered**: move callers to the new module paths and delete `manage.py`. Rejected - it forces edits across `routes/api.py`, `routes/pages.py`, `app.py`, and both test files for no behavioral gain. The facade is strictly safer.

### D3: Web DB dependency via FastAPI `Depends(get_db)`
Add a `get_db() -> Path` dependency (default returns `config.DEFAULT_DB`) and have every `routes/api.py` and `routes/pages.py` handler take `db: Path = Depends(get_db)` and pass it through to the manage functions (which already accept `db_path`). Tests override with `app.dependency_overrides[get_db] = lambda: tmp_db`.

**Why**: the routes currently call `M.list_rubrics_with_counts()` with no `db_path`, so they hit `DEFAULT_DB` (the dev DB) - which is exactly why `test_web_prompts.py` mutates real data. `Depends` is the idiomatic FastAPI seam and requires no change to the manage signatures (they already take `db_path`). The override is one line per test session.
**Alternative considered**: a module-level "current DB" variable the tests monkeypatch. Rejected - global mutable state is racy and fragile across tests; `Depends` is scoped per-request and overrideable per-app.
**Alternative considered**: env var `EVAL_DB_PATH` the tests set. Rejected - process-global, leaks across tests, can't run parallel sessions.

### D4: Deterministic fake judge for scoring tests
Add a `FakeJudge` test double (in `tests/_fakes.py`) subclassing deepeval's `DeepEvalBaseLLM`. `evaluate_contract(..., judge=FakeJudge(...))` then runs the real `GEval` aggregation/threading path with no network: `GEval.measure` calls the judge's `generate` (via `generate_with_schema`) instead of an LLM endpoint. The `FakeJudge` serves a fixed "evaluation steps" response on the `Steps` schema call and consumes an ordered verdict queue on the `ReasonScore` schema call (`True`=pass, `False`=fail, `"error"`=raise to simulate a judge-call failure). Per-criterion verdicts are keyed by criteria order, not by id: the deepeval model interface is criterion-agnostic (`generate(prompt, schema)` receives no criterion identity), so the test calls `evaluate_contract(..., max_workers=1)` to judge criteria in submission order, making the queue deterministic. A `model_name=None` setting exercises the `EVAL_MODEL` env fallback for `judge_model`.

`evaluate_contract` gains a `db_path=DEFAULT_DB` parameter (behavior-preserving) threaded into `load_criteria`, so scoring tests can run against the throwaway DB instead of the dev one.

**Why**: `evaluate_contract` already accepted `judge=None`; a `DeepEvalBaseLLM` fake is the spec-faithful seam ("fake judge passed into evaluate_contract", no `GPTModel` constructed) and exercises the real aggregation, threading, and result-shaping code. The ordered-queue + `max_workers=1` trade-off (vs. per-id verdicts) is the cost of deepeval's criterion-agnostic model interface.
**Alternative considered**: mock `GEval` entirely (a `FakeGEval` metric set via monkeypatching `scoring.GEval`). That would allow per-id verdicts and couple only to the attribute names scoring reads, but deviates from the "fake judge passed into evaluate_contract" contract. Rejected in favor of the model-level fake to honor the spec.

### D5: Replace `main.py` argv parsing with `argparse`
Rewrite `main.py` to use `argparse` with a single positional `request` and an optional positional `output` (`nargs="?"`). Preserves the documented `python main.py "<request>" [output.md]` form. Args are parsed before the env-var check so `--help`/usage work without env configured; `main(argv=None)` returns an exit code so tests can drive it directly. The crew kickoff is wrapped so tests can monkeypatch `ContractDraftingCrew`.

**Why**: the current `sys.argv[1:-1]` / `sys.argv[-1]` logic silently mis-detects the output file whenever the request contains spaces and isn't quoted, and it cannot produce a clean usage message. `argparse` gives consistent UX with `run.py` (which already uses it) and testable error paths. A single positional `request` is used (not `nargs="+"` remainder) because argparse greedily assigns all positionals to a `nargs="+"` arg before a `nargs="?"` arg - the documented usage already expects a single quoted request.
**Alternative considered**: leave `main.py` alone and only test the happy path. Rejected - the parsing bug is real and the user asked to refactor the whole project.

### D6: Clearer `llm.py` error
Raise a small dedicated exception (`ConfigError` defined in `src/settings.py`) when `{ROLE}_MODEL` is missing, instead of the raw `KeyError` from `os.environ[...]`.

**Why**: a bare `KeyError: 'DRAFTER_MODEL'` is a poor user experience; a typed error with a message pointing at `.env` matches the pattern already used in `judge.py` (`RuntimeError` with guidance).
**Alternative considered**: keep `KeyError`. Rejected - the test-suite spec requires "a dedicated configuration error (not a bare `KeyError`)".

## Risks / Trade-offs

- **[Facade drift]** The `manage.py` facade could diverge from the split modules if someone adds a function to a CRUD module but forgets to re-export it. -> Mitigation: the facade uses `from .rubric_crud import *` (honoring each module's `__all__`) plus an explicit `__all__` for the facade; a test asserts the facade exposes the expected public names (covered by the Backward-Compatible Refactor spec).
- **[Web dependency threading is invasive]** Adding `Depends(get_db)` to ~25 route handlers is a large mechanical diff with merge-conflict potential. -> Mitigation: do it in one dedicated commit; the route paths/methods don't change; the existing prompt tests (moved to the override) plus new rubric/criteria/page tests guard the wiring.
- **[Fake judge couples to deepeval internals]** `FakeJudge` must mimic the `GEval` attributes `scoring.py` reads; if `scoring.py` starts reading new attributes, the fake silently returns defaults. -> Mitigation: keep the fake minimal and document the contract in `conftest.py`; the scoring tests assert the exact output dict shape, so a mismatch surfaces as a test failure.
- **[Test DB seeding depends on `extract_harbor_rules.py`]** `conftest.py` loads the schema by importing that script, so a schema change there changes test fixtures. -> Mitigation: this is the same approach the existing `test_manage.py` uses (single source of truth for the schema); acceptable and already proven.
- **[Scope]** "Refactor the whole project" is broad; the refactor touches most of `src/`. -> Mitigation: behavior-preserving moves only, facade keeps imports stable, tests written alongside each move so regressions are caught immediately.

## Migration Plan

1. Add `src/config.py`; re-point imports (no behavior change). Run existing tests.
2. Extract `errors.py` and `db.py`; re-point `manage.py` internals and `store.py`. Run existing tests.
3. Split `manage.py` into `rubric_crud.py` + `prompt_crud.py`; leave `manage.py` as the re-export facade. Run existing tests (must pass unedited).
4. Add `tests/conftest.py` (seeded DB, app-client override, fake judge); move `test_web_prompts.py` onto the override.
5. Thread `Depends(get_db)` through `routes/api.py` and `routes/pages.py`; add `test_web_api.py`, `test_web_pages.py`, `test_app.py`.
6. Add unit tests for `rubric.py`, `store.py`, `scoring.py`, `judge.py`, `llm.py`, `crew.py`, `db.py`.
7. Rewrite `main.py` to argparse; add CLI tests for `main.py` and `run.py`.
8. Tighten `llm.py` error; add its test.

**Rollback**: each step is an independent commit; revert to the last green commit if a step breaks. No DB migration, no deploy - this is a local-only refactor + tests, so rollback is trivial (git revert).

## Open Questions

- Should the fake judge live in `tests/conftest.py` or a separate `tests/_fakes.py`? Lean toward `tests/_fakes.py` for reuse/clarity; confirm during implementation.
- Whether to add a coverage threshold config (`--cov-fail-under`) to `pyproject.toml`. Out of scope unless the user wants CI gating; default to not adding it.
