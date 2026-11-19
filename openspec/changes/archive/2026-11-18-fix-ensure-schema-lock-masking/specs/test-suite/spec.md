## MODIFIED Requirements

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
