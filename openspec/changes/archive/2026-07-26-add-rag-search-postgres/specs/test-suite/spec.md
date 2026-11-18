# test-suite Specification (delta)

## MODIFIED Requirements

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

#### Scenario: A test requests the seeded database fixture
- **WHEN** a test depends on the seeded-database fixture
- **THEN** it receives a connection to a fresh throwaway PostgreSQL database containing the real schema plus one `harbor:` rubric and one `local` rubric, isolated from every other test

#### Scenario: A test requests the app client fixture
- **WHEN** a test depends on the app-client fixture
- **THEN** it receives a `TestClient` whose web routes read and write the throwaway PostgreSQL database, not the development database

#### Scenario: A test requests the fake judge
- **WHEN** a test depends on the fake-judge fixture
- **THEN** it receives a judge factory whose verdicts can be preset per criterion (consumed in criteria order, with ``max_workers=1``), so a test can force an all-pass or a partial-fail run deterministically
