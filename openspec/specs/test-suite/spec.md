# test-suite Specification

## Purpose
Keep the test suite hermetic: no external network or LLM calls, no shared development database, deterministic fakes for judge services, and broad coverage of the evaluation engine, drafting pipeline, web layer, and CLI.

## Requirements

### Requirement: Hermetic Test Execution
The test suite SHALL execute without any external network or LLM calls and SHALL NOT read or mutate the development/shared PostgreSQL database addressed by `database_url`. Every test that needs a database SHALL operate against a throwaway per-test PostgreSQL database (or per-test schema) isolated from every other test. Every test that exercises LLM-judging behavior SHALL inject a deterministic in-process fake judge rather than calling the real model endpoint. The suite SHALL require a reachable local PostgreSQL instance to run database-backed tests, but SHALL NOT require Elasticsearch, MinIO, or OpenRouter (those are faked in tests).

#### Scenario: No external network required to run the suite
- **WHEN** the full test suite is run in an environment with no external network access but a local PostgreSQL is reachable
- **THEN** every test passes (or fails for assertion reasons), with no test hanging on or failing due to an unreachable LLM, Elasticsearch, MinIO, or OpenRouter endpoint

#### Scenario: The development database is never touched
- **WHEN** the full test suite runs against a project with a populated development PostgreSQL database
- **THEN** the row counts and contents of that development database are unchanged before and after the run

#### Scenario: Scoring is judged by an injected fake
- **WHEN** a scoring test evaluates a contract against a rubric
- **THEN** the judge is a deterministic fake object passed into `evaluate_contract` and no `GPTModel` is constructed

### Requirement: Shared Test Fixtures
The suite SHALL provide shared fixtures in `tests/conftest.py`: a seeded throwaway PostgreSQL database built from the real schema (loaded from `scripts/extract_harbor_rules.py`) with one harbor and one local rubric; a FastAPI `TestClient` whose `get_db` dependency is overridden to return a connection to that throwaway database; and a deterministic fake LLM judge whose per-criterion verdicts are configurable per test. The `get_db` override SHALL yield a PostgreSQL connection (not a filesystem `Path`).

The seeded database fixture SHALL confirm that the schema actually landed before seeding, and SHALL fail at **setup** with an explicit "schema bootstrap did not complete" error when it did not. A fixture that proceeds to `TRUNCATE` a table that was never created reports `UndefinedTable` against whatever the test happened to touch — the failure then points at the test instead of at the bootstrap, which is why this assertion belongs here.

#### Scenario: A test requests the seeded database fixture
- **WHEN** a test depends on the seeded-database fixture
- **THEN** it receives a connection to a fresh throwaway PostgreSQL database containing the real schema plus one `harbor:` rubric and one `local` rubric, isolated from every other test

#### Scenario: A test requests the app client fixture
- **WHEN** a test depends on the app-client fixture
- **THEN** it receives a `TestClient` whose web routes read and write the throwaway PostgreSQL database, not the development database

#### Scenario: A test requests the fake judge
- **WHEN** a test depends on the fake-judge fixture
- **THEN** it receives a judge factory whose verdicts can be preset per criterion (consumed in criteria order, with ``max_workers=1``), so a test can force an all-pass or a partial-fail run deterministically

#### Scenario: Schema bootstrap failure is reported as itself
- **WHEN** the session database is created but its schema did not complete (e.g. a lock wait timed out during table creation)
- **THEN** the fixture fails at setup naming the schema bootstrap, MUST NOT proceed to seed and surface `undefined table` from a later statement

### Requirement: Evaluation Engine Coverage
The suite SHALL cover `src/eval/` end to end: `rubric.py` (list/load, `KeyError` on unknown rubric, `ValueError` on rubric with no criteria); `store.py` (`ensure_schema` idempotency, `store_result` round-trip, `list_runs` ordering); `scoring.py` (all-pass aggregation, per-criterion result shape, a failing criterion producing `FAIL`, a judge-call error captured per criterion rather than sinking the run, `judge_model` fallback to `EVAL_MODEL`); `judge.py` (`_strip_litellm_prefix`, `RuntimeError` on missing env vars); and `manage.py` CRUD plus harbor-read-only guards (already present, retained and extended for the module split).

#### Scenario: All-pass scoring with an injected fake judge
- **WHEN** `evaluate_contract` is called with a fake judge that returns success for every criterion
- **THEN** the result has `all_pass = true`, `score = 1.0`, and `n_passed == n_criteria`

#### Scenario: A failing criterion fails the run
- **WHEN** the fake judge returns failure for one criterion of a multi-criterion rubric
- **THEN** the result has `all_pass = false`, `score = 0.0`, and exactly one criterion result with `verdict = "fail"`

#### Scenario: A judge-call error is captured, not fatal
- **WHEN** the fake judge raises on one criterion
- **THEN** that criterion's `reasoning` records the error and the run still completes with results for every criterion

#### Scenario: Store round-trips a run and its verdicts
- **WHEN** `store_result` persists a result dict and `list_runs` is then called
- **THEN** the run appears with matching `score`, `all_pass`, `n_passed`, and `n_criteria`, ordered newest first

### Requirement: Drafting Pipeline Coverage
The suite SHALL cover `src/llm.py` (env-driven config, defaults for temperature/max_tokens, a clear error when a role model env var is missing) and `src/crew.py` (`_templates_reference` loading seed templates, crew assembly producing agents and tasks) without performing an LLM kickoff.

#### Scenario: get_llm applies role defaults
- **WHEN** `get_llm("DRAFTER")` is called with `DRAFTER_MODEL` set and no temperature override
- **THEN** the returned LLM uses the configured model and the default temperature

#### Scenario: Missing role model raises a clear error
- **WHEN** `get_llm("DRAFTER")` is called without `DRAFTER_MODEL`
- **THEN** a dedicated configuration error is raised (not a bare `KeyError`)

#### Scenario: Template reference loads seed templates
- **WHEN** `_templates_reference()` runs with templates present
- **THEN** it returns a non-empty string containing one block per `templates/*.md` file

### Requirement: Web Layer Coverage
The suite SHALL cover the JSON API (`src/web/routes/api.py`) for rubrics and criteria (create, read, update, delete, reorder; harbor read-only -> 403, duplicate name -> 409, invalid input -> 400, unknown name/id -> 404), the HTML page flows (`src/web/routes/pages.py` form submissions and flash redirects), and `src/web/app.py` (`create_app` wiring, static/template mounts, and the `ManageError`-to-HTTP-status handler mapping including the 500 fallback). All web tests SHALL run against the throwaway database via the dependency override.

#### Scenario: Creating a harbor rubric via the API is forbidden
- **WHEN** a `PATCH` or `DELETE` is sent to a harbor rubric's API route
- **THEN** the response status is 403

#### Scenario: A duplicate local rubric name conflicts
- **WHEN** two `POST /api/rubrics` use the same name
- **THEN** the second response status is 409

#### Scenario: An HTML create form redirects with a flash
- **WHEN** a valid rubric create form is POSTed to the page route
- **THEN** the response is a redirect to the new rubric's detail page carrying a success message

#### Scenario: ManageError subclasses map to their HTTP statuses
- **WHEN** each `ManageError` subclass is raised during a request
- **THEN** the response status matches the registered mapping (`NotFoundError` 404, `HarborReadOnlyError` 403, `ConflictError` 409, `ValidationError` 400, and any other `ManageError` 500)

### Requirement: CLI Coverage
The suite SHALL cover the `main.py` drafting CLI and the `src/eval/run.py` evaluation CLI: argument parsing, the `--list-rubrics` / `--list-runs` listings, missing-required-argument errors, and output-file writing - all without performing real LLM calls (services monkeypatched where needed).

#### Scenario: The drafting CLI writes the result to a file
- **WHEN** `main.py` is invoked with a request and an output path, and the crew kickoff is monkeypatched to return fixed text
- **THEN** the output file is created containing that text

#### Scenario: The eval CLI lists rubrics without scoring
- **WHEN** `src/eval/run.py` is invoked with `--list-rubrics` against a seeded throwaway database
- **THEN** it prints the rubric names and exits 0 without calling the judge

#### Scenario: Missing required CLI args errors cleanly
- **WHEN** `main.py` is invoked with no arguments, or `src/eval/run.py` is invoked without `--contract`/`--rubric`
- **THEN** it prints a usage message and exits non-zero

### Requirement: Backward-Compatible Refactor
The behavior-preserving refactor SHALL preserve every existing public surface: `from src.eval import manage as M` SHALL continue to expose the same names (`M.create_rubric`, `M.list_prompts`, the error classes, etc.); every HTTP route path and method SHALL be unchanged; and the `python main.py "<request>" [output.md]` and `python -m src.eval.run` command interfaces SHALL be unchanged. The existing `tests/test_manage.py` and `tests/test_web_prompts.py` SHALL continue to pass (the latter moved onto the hermetic fixture).

#### Scenario: The manage facade re-exports the split modules
- **WHEN** a caller does `from src.eval.manage import create_rubric, list_prompts, ConflictError`
- **THEN** all three names resolve to the same callables/classes they did before the split

#### Scenario: Existing manage tests still pass after the split
- **WHEN** `tests/test_manage.py` is run after the module split
- **THEN** every test passes without editing the test file's assertions

#### Scenario: The drafting CLI interface is unchanged
- **WHEN** `python main.py "起草一份服务协议" out.md` is run (with kickoff monkeypatched)
- **THEN** it accepts the request and output path in the same positional form as before the argparse rewrite
