## Why

The deployed container's `/rubrics` page shows 0 harbor rubrics even though the image bakes them in. A stale PVC at `/app/db` (seeded with local rubrics before harbor extraction ever ran) shadows the image's correctly-seeded DB, and Docker never overwrites an existing volume. The image cannot self-heal: harbor is installed only as a local `uv tool` and is absent from the image, so the "Re-extract harbor" button (`POST /harbor/extract`, which shells out to `extract_harbor_rules.py`) fails in-container. Harbor rubrics must be present regardless of volume state or whether harbor is installed at runtime.

## What Changes

- Bundle harbor's two shipped rubric TOMLs (`task_quality`, `trial_behavior`) in the repo as seed data pinned to harbor v0.20.0.
- New importable module `src/eval/harbor_seed.py` (logic moved out of the script so the app/tests can call it): loads harbor rubrics from the installed harbor package when present, falling back to the bundled seed.
- `scripts/extract_harbor_rules.py` becomes a thin CLI wrapper that re-exports the symbols existing tests import; it exits 0 with the bundled fallback when harbor is not installed (previously exited non-zero).
- A Dockerfile entrypoint runs the seed on every container start before `uvicorn`, idempotently restoring harbor rubrics into whatever DB the volume presents.
- Harbor rubrics are scoped to `source LIKE 'harbor:%'` rows; local rubrics and eval-run data are never touched.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `evaluation-rules`: Harbor extraction no longer hard-fails when the harbor package is absent; it falls back to the bundled seed. A new requirement is added for idempotent startup self-heal of harbor rubrics from the bundled seed (scoped to harbor rows, preserving local rubrics and eval data). The "Harbor not installed" scenario changes from "fails with an error" to "falls back to the bundled seed".

## Impact

- **New files**: `src/eval/harbor_seed.py`; `src/eval/seed/__init__.py`, `src/eval/seed/harbor/__init__.py`; `src/eval/seed/harbor/task_quality.toml`, `src/eval/seed/harbor/trial_behavior.toml`; `scripts/docker-entrypoint.sh`; `tests/test_harbor_seed.py`.
- **Modified files**: `scripts/extract_harbor_rules.py` (thin wrapper; re-exports `create_schema`, `DEFAULT_DB`, `print_summary`, `project_root`, etc. for test compatibility); `Dockerfile` (entrypoint + `CMD`).
- **Unchanged**: `src/web/routes/api.py` (the Re-extract button keeps shelling out; it now also succeeds in-container via the fallback), the DB schema, and existing tests (the script still exposes `create_schema`).
- **Dependencies**: none added; harbor is still not installed in the image.
- **Operational**: on the next container restart the stale PVC self-heals — harbor rubrics appear without a volume reset or rebuild.
