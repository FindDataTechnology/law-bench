## Context

`db/evaluation_rules.db` holds three kinds of rows in one file: harbor reference rubrics (`source LIKE 'harbor:%'`, seeded only by `scripts/extract_harbor_rules.py`), local contract rubrics (`source = local`, seeded by `scripts/seed_contract_rubrics.py`), and evaluation-run data (`eval_runs`, `compare_runs`, …). The Docker image bakes the committed DB (which has all three) via `COPY db ./db`, and deployments mount a persistent volume at `/app/db`.

The deployed container shows 0 harbor rubrics because its PVC was initialized from a DB seeded with locals but never harbor-extracted (harbor is a local `uv tool`, absent from the image). Docker never overwrites an existing volume, and the in-container "Re-extract harbor" button fails because it shells out to a script that hard-exits when harbor is not installed. The web app does no schema/seed step on startup.

Harbor v0.20.0 (the latest PyPI release, and what is installed locally) ships exactly two rubric TOMLs with 13 criteria total; this rarely changes.

## Goals / Non-Goals

**Goals:**
- Harbor rubrics are always present in the running container, regardless of volume state or whether harbor is installed at runtime.
- The heal is idempotent and scoped to harbor rows; local rubrics and evaluation-run data are never modified or deleted.
- The "Re-extract harbor" button works in-container (no harbor install required).
- No new runtime dependency is added to the image.

**Non-Goals:**
- Automatically refreshing the bundled seed when a new harbor version is released (manual/CI follow-up).
- Splitting rubrics and eval-run data into separate databases/volumes.
- Changing the web API contract or the DB schema.
- Installing harbor in the image.

## Decisions

**Decision 1 — Bundle harbor's TOMLs in the repo (not install harbor in the image).**
*Alternatives considered:* (a) `uv tool install harbor` in the Dockerfile — keeps harbor as the live source of truth but bloats the image with a heavy toolchain for 13 rarely-changing criteria and adds a runtime dependency; (b) operational PVC reset only — immediate but loses eval-run data and recurs. *Chosen:* ship the two TOMLs (pinned to v0.20.0) under `src/eval/seed/harbor/`; the image already does `COPY src ./src`, so no extra plumbing. Lightweight, self-contained, deterministic.

**Decision 2 — Prefer the installed harbor package; fall back to the bundled seed.**
When harbor is installed (dev/CI), load criteria from the installed package and record its real version (`harbor:vX.Y.Z`) for freshness. When it is absent (container), load from the bundle and record `harbor:v0.20.0`. This keeps dev/CI authoritative while making the container self-sufficient.

**Decision 3 — Heal via a Dockerfile entrypoint, not an app lifespan.**
*Alternatives:* (a) FastAPI lifespan event gated by an env var set in the Dockerfile — pure Python, but risks side effects on `DEFAULT_DB` during `TestClient`-based tests unless carefully gated; (b) lazy heal on first read — spreads seeding logic across read paths. *Chosen:* a `scripts/docker-entrypoint.sh` that runs `python -m src.eval.harbor_seed --db /app/db/evaluation_rules.db` then `exec`s uvicorn. Runs only in the container; zero impact on tests or local dev; explicit and easy to reason about.

**Decision 4 — Move seeding logic into an importable `src/eval/harbor_seed.py`.**
The app (and tests) need to call the heal programmatically; the logic cannot stay in `scripts/` (not importable as a package). `scripts/extract_harbor_rules.py` becomes a thin CLI wrapper that re-exports the symbols tests already import via importlib (`create_schema`, `DEFAULT_DB`, `print_summary`, `project_root`, …), so `tests/conftest.py` and `tests/test_manage.py` are unchanged.

**Decision 5 — Scope the heal to `source LIKE 'harbor:%'` rows.**
The upsert matches existing harbor rubrics by `name AND source LIKE 'harbor:%'` and replaces only their criteria (mirroring the existing re-extract semantics). Local rubrics, prompts, and eval-run rows are never touched. `create_schema` is `CREATE TABLE IF NOT EXISTS`, so a fresh volume gets the schema without data loss elsewhere.

## Risks / Trade-offs

- **[Bundled seed drifts from upstream harbor]** -> Prefer the installed package when present (dev/CI stay fresh); pin the bundle version (`v0.20.0`) and surface the source origin in script stdout. A future `--sync-bundled` flag can refresh the bundle (out of scope).
- **[Heal writes to a mounted volume as non-root `appuser`]** -> The volume at `/app/db` is already owned by `appuser` (the app writes eval runs there today), so writes succeed.
- **[Re-extract button now exits 0 in-container even when a fresh harbor pull was expected]** -> Script stdout reports whether criteria came from the installed package or the bundled seed, so the origin is visible.
- **[Entry point masks a genuinely broken harbor install in dev]** -> Local dev does not use the entrypoint; the script still prefers the installed package when present, so a broken install is still observable locally.

## Migration Plan

1. Merge the change and build the new image (CI pushes it as usual).
2. Restart the deployed container with the existing PVC. The entrypoint heals the stale DB on boot: harbor rubrics are inserted; locals and eval runs are preserved. No volume reset or data migration needed.
3. *Rollback:* revert to the previous image. The healed DB remains valid for the old image (harbor rows are read-only display data; the old image simply reads them). No data was destroyed.

## Open Questions

- Should a `--sync-bundled` flag be added now to copy the installed harbor TOMLs into `src/eval/seed/harbor/` on demand? Deferred — the bundle is pinned to v0.20.0 and refresh is manual until harbor upgrades.
