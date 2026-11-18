## Why

`src/` has accumulated SQLite-era leftovers (dead DBs, stale `db: Path` types), fragile router registration (silent `try/except ImportError` swallowing missing routes), a name collision (`src/docs/` the code package vs root `docs/` the markdown), and no authentication on a web app that now writes contracts, runs evals, and exposes MinIO artifact downloads. The in-flight `add-contract-generation-modes` work also needs a clean baseline before either refactor lands. This change pays down that debt in two bounded phases — internal cleanup (no behavior change) then Logto-backed auth — so each is independently reviewable and revertable.

## What Changes

- **Commit baseline (Phase 0)**: land the in-flight `add-contract-generation-modes` changes (7 untracked + 11 modified files) onto a clean commit point. Reconcile the `tasks.md` (0/25 checked) against the known-done feature.
- **Router registration**: remove the `try/except ImportError` block (`src/web/app.py:133-147`) that silently drops 7 HTML routers on import failure; include all routers explicitly so a missing route surfaces instead of vanishing. **BREAKING** for any caller that depended on the optional-UI build mode.
- **Dependency typing**: replace `db: Path` SQLite-era residue in `pages.py` and friends with `db: Any` (or a `Connection` protocol), aligning with `contract_context.py`/`generation.py` which already use `Any`.
- **Name collision**: relocate `src/docs/` (the code package: `slots.py`, `generator.py`) — merge into `src/contracts/` or split out as `src/generator/`, removing the collision with root `docs/`.
- **Audit ownership**: draw a clear boundary between `src/contracts/audit.py` and `src/clauses/audit.py`; merge or split so each has one job.
- **Delete clutter**: remove one-off debug scripts in `output/` (`_fix_*.py`, `_inspect_*.py`, `*_rollback.json`) and root-level strays (`test_analysis.json`, empty `prompts.md`, `extract_batch_results.py`, `.DS_Store`). Add `output/` artifacts, `__pycache__`, `*.egg-info`, `.DS_Store` to `.gitignore`.
- **Archive (not delete) history**: move `scripts/backfill_*`, `seed_*`, `retag_*` and leading-underscore probes (`_p2_*.py`, `_probe_models.py`, `_regression_gate.py`) to `scripts/archive/` to preserve data-migration history.
- **Remove dead DBs**: after confirming no live references, delete the 6 duplicate SQLite files across `db/` and `data/` (Postgres is already the source of truth per `settings.py`).
- **Logto auth (Phase 2)**: add OIDC authorization-code flow for browsers (Logto login → `/auth/callback` → httpOnly session cookie) and programmatic access via `Authorization: Bearer <jwt>` (Logto-signed, JWKS-verified) or `X-API-Key`. New `src/web/auth/` package (`logto.py`, `session.py`, `apikey.py`, `deps.py`) and `src/web/routes/auth.py`. Apply `Depends(get_current_user)` to all routers; exempt `/healthz` and `/auth/*`. **No password handling, no users table** — identity delegated to Logto.
- **API key storage (open question)**: either Logto-native access tokens (no table) or a thin `api_keys` table (`key_hash`, `user_id`, `scopes`, `created_at`, `last_used_at`) for user-generated long-lived keys. Recommended: the table (2b), matching the "APIKey" intent. User to confirm.
- **BREAKING**: all currently-open web endpoints (contracts, generation, clauses, dashboard, eval, compare, harbor, search, contract-context) will require authentication after Phase 2. Callers (including sub-projects sharing the venv) must carry a key or be internally exempted.

## Capabilities

### New Capabilities
- `web-auth`: Authentication and session management for the FastAPI web app — Logto OIDC browser login, session cookie, Bearer JWT and API-key programmatic access, and a unified `get_current_user` dependency injected across all routers.

### Modified Capabilities
<!-- No existing spec-level behavior changes; src/ has no prior auth spec. Leave empty. -->

## Impact

- **Code**: `src/web/app.py` (router registration + auth wiring), `src/web/routes/*.py` (dependency typing fix + auth dep on every router), `src/web/deps.py`, `src/web/models.py` (auth request models), new `src/web/auth/` package, new `src/web/routes/auth.py`, `src/contracts/` & `src/clauses/` (audit ownership + `src/docs/` relocation), `.gitignore`.
- **Data**: one new migration for `api_keys` table (Phase 2, option 2b only); deletion of 6 stale SQLite files.
- **Dependencies**: likely add `itsdangerous` or rely on `starlette` Session middleware for cookie signing; OIDC discovery via existing httpx/requests. No new heavy framework.
- **Sub-projects (shared venv, out of scope but affected)**: `contract-review-agent` and `fd-coding-law-bench-mcp` if they call `src/web` HTTP APIs must carry an API key or be internally exempted. `fd-coding-law-bench-mcp`'s MCP server is believed to connect to DB directly (not over HTTP) and should be unaffected — to be verified during Phase 2.
- **Tests**: 54 test files; after Phase 2 many endpoints 401 without auth. `conftest.py` (already modified) needs auth-fixture injection. Dedicated test-fixup task.
- **CLI**: `main.py` (CrewAI drafting, no web) is untouched by auth.
- **Open inputs needed from user**: Logto endpoint, OIDC `client_id`/`client_secret`, JWKS URI; and the 2a-vs-2b API-key decision.
