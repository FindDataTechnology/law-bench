## Context

`src/` is the main project: a FastAPI web app (`src/web/`) sitting on top of a contract drafting/evaluation engine (`src/contracts/`, `src/clauses/`, `src/eval/`, `src/search/`, `src/validations/`). It runs in a shared venv with three sibling sub-projects (`contract-review-agent`, `contract-generator`, `fd-coding-law-bench-mcp`) that import `src.*` modules but are *not* in scope for this change.

Current state of the web layer (grounded in the explore phase):

- `src/web/app.py` registers 7 HTML routers inside a `try/except ImportError` that silently swallows missing-import failures (`app.py:133-147`), while `api`/`contract_context`/`generation` are included unconditionally — a fragile half-and-half split left over from an optional UI-build step.
- `src/web/routes/pages.py` still types its DB dependency as `db: Path` (~13 handlers), a SQLite-era residue. `get_db()` (`src/web/deps.py`) now returns a Postgres connection; `contract_context.py`/`generation.py` already use `db: Any`. The types lie.
- `src/docs/` is a *code package* (`__init__.py`, `slots.py`, `generator.py` — generation logic), colliding with the repo-root `docs/` markdown directory. Easy to misread.
- Two parallel `audit.py` files (`src/contracts/audit.py`, `src/clauses/audit.py`) with blurred responsibility boundaries.
- Repo clutter: ~20 one-shot debug scripts under `output/` (`_fix_*.py`, `_inspect_*.py`, `*_rollback.json`) + 20MB of artifacts; 6 duplicate SQLite DBs across `db/` and `data/` (`evaluation.db`, `evaluation_rules.db`, `lawbench.db`, `law_bench.db`, `app.db`) that are dead now that `settings.py` reads `database_url` (Postgres); 49 scripts under `scripts/` mixing keepers with historical `backfill_*`/`seed_*`/`retag_*`/`_*` throwaways; stray root files (`test_analysis.json`, 0-byte `prompts.md`, `extract_batch_results.py`, `.DS_Store`).

On auth: the web app has **no authentication today**. Every route — including write paths (`POST /api/rubrics`, `POST /{contract_type}/generate`, clause review) — is open. The user has a **self-deployed Logto** instance to serve as the identity provider, so this change adds auth *without* building a users table or touching password hashing: identity is delegated to Logto.

## Goals / Non-Goals

**Goals:**
- Land a clean `src/` structure baseline: explicit router registration, honest dependency types, resolved naming collisions, audited `audit.py` boundaries.
- Remove dead clutter (debug scripts, zombie SQLite DBs, stray root files) and archive historical migration scripts so `git status` and the tree stop lying about what's live.
- Add Logto-backed hybrid auth: browser sessions via OIDC code flow → httpOnly cookie; programmatic calls via `Authorization: Bearer <jwt>` (JWKS-validated) **or** `X-API-Key` (self-managed long-lived key). One unified `get_current_user` dependency resolves identity from any of the three channels into `request.state.user`.
- Keep the change reviewable in three phases (baseline commit → refactor → auth) so each is independently revertable.

**Non-Goals:**
- Refactoring the three sibling sub-projects (`contract-review-agent`, `contract-generator`, `fd-coding-law-bench-mcp`). They share the venv and may need caller-side changes after auth lands — called out in Impact, not done here.
- Splitting `src/web/i18n.py` (~50KB). It's large but not disordered; touching it risks regressions for no behavioral gain. Deferred.
- Building a users table, password storage, or any local identity store. Logto owns identity.
- Changing the CLI entry (`main.py`, CrewAI drafting). It doesn't go through the web layer.
- Modifying external API contracts of the engine modules (`src/contracts`, `src/eval`, `src/search`). Refactor is internal-structure only; no behavioral change.

## Decisions

### D1 — Phase ordering: baseline commit → refactor → auth
Phases are ordered so later work doesn't churn on earlier output. Auth needs to insert middleware and `Depends(get_current_user)` across all routers; doing that *before* the router-registration cleanup means auth code gets moved twice. Refactor first stabilizes `app.py`, then auth lands once.
- *Alternative considered:* auth-first (security urgency). Rejected — no reported active exposure, and the double-churn cost is real.

### D2 — Router registration: explicit includes, no try/except
Replace the `try/except ImportError` block (`app.py:133-147`) with explicit unconditional `include_router` for all 7 HTML routers, matching how `api`/`contract_context`/`generation` are already included. A missing router should fail loudly at startup, not 404 silently at request time.
- *Alternative considered:* keep try/except but log the ImportError. Rejected — logging a swallowed import error during a "UI build step" that no longer exists is just a worse crash.

### D3 — DB dependency type: a `DbConn` Protocol, not bare `Any`
Replace `db: Path` (pages.py) and the inconsistent `db: Any` (contract_context/generation) with a single `DbConn` Protocol in `src/web/deps.py` describing the borrowed-connection surface (`cursor()`, `commit()`, context manager). `Any` disables type checking; `Path` is an outright lie. A Protocol gives mypy/pyright a real target without coupling to `psycopg`'s concrete type (tests inject fakes).
- *Alternative considered:* import `psycopg.Connection` directly as the annotation. Rejected — couples the web layer's type signatures to the driver and breaks test fakes that currently rely on duck-typing.

### D4 — `src/docs/` rename → `src/generator/`
The package `src/docs/` (code: `slots.py`, `generator.py`) collides with repo-root `docs/` (markdown). Move to `src/generator/` (or merge into `src/contracts/`). Decision: **`src/generator/`** — `slots.py` + `generator.py` form a coherent "contract generation" subpackage, and `src/contracts/` already has enough residents. Update all `from src.docs...` imports.
- *Alternative considered:* merge into `src/contracts/`. Rejected — `src/contracts/` mixes templates/data with logic already; adding more dilutes it.

### D5 — `audit.py` consolidation: split by object, not by file
Keep two audit modules but sharpen their contracts: `src/clauses/audit.py` audits the **clause library** (individual clause rows, tag hygiene, dedup); `src/contracts/audit.py` audits **assembled contract output** (section coverage, slot fill, coherence). Add module docstrings stating this boundary. No merge — the two audits operate on different granularity and merging would create a god-module.
- *Alternative considered:* merge into one `src/audit.py`. Rejected for the god-module reason above.

### D6 — Clutter policy: archive, don't delete, for migration scripts
Historical `backfill_*`/`seed_*`/`retag_*` scripts and `_*` throwaways move to `scripts/archive/` (git-tracked) rather than being deleted. They document how the current DB state was produced; deleting makes that history unrecoverable without `git log -p` archaeology. `output/` debug scripts (`_fix_*.py`, `_inspect_*.py`, `*_rollback.json`) *are* deleted — they were one-shot scratch, already served their purpose. Zombie SQLite DBs are deleted only after a grep confirms zero live references (not just `settings.py`; check `scripts/`, `tests/`, `src/eval/`).
- *Alternative considered:* delete everything unused. Rejected for scripts (irreversible provenance loss); accepted for `output/` scratch (low value, easy to regenerate).

### D7 — `.gitignore` hardening
Add: `__pycache__/`, `*.egg-info/`, `output/contracts/` (artifacts, not the dir itself if code lives there — verify), `.DS_Store`. Commit the ignore, then `git rm --cached` the already-tracked files that match. This is a one-time hygiene pass; ongoing hygiene is the ignore file's job.

### D8 — Auth architecture: Logto OIDC + local `api_keys` table (the user's "方案C")
Three identity channels resolve to one `request.state.user`:
1. **Browser**: OIDC authorization-code flow. `/auth/login` redirects to Logto; `/auth/callback` exchanges the code, stores the user in a signed httpOnly session cookie (itsdangerous or Starlette `SessionMiddleware` with a secret from env). `/auth/logout` clears cookie + redirects to Logto end-session.
2. **Bearer JWT**: `Authorization: Bearer <jwt>` — Logto-issued access token, validated against Logto's JWKS (`/.well-known/jwks.json`, cached with refetch-on-unknown-kid). For machine-to-machine / short-lived token callers.
3. **API Key**: `X-API-Key: <key>` — self-managed long-lived key. Stored as `key_hash` (never plaintext) in a new `api_keys` table (`key_hash`, `user_id`, `scopes`, `created_at`, `last_used_at`, `revoked_at`). Users generate/revoke keys via `/api/keys`.

`get_current_user` checks cookie → Bearer → X-API-Key in order, populates `request.state.user` (a small dataclass: `sub`, `name`, `email`, `scopes`, `channel`). `require_scope(scope)` wraps `get_current_user` for fine-grained checks.

No users table, no password hashing — Logto is the sole identity source. The `api_keys` table stores *only* hashed keys + the Logto `sub` they belong to; user profile is never cached locally (resolved per-request from the JWT/cookie, or looked up against Logto's userinfo endpoint for API-key calls).

- *Alternative considered (2a)*: pure Logto — API callers use Logto-issued access tokens, no `api_keys` table. Rejected because the user explicitly chose "混合 Cookie+APIKey" (方案C); 2a forces every API caller to do a Logto token exchange, which doesn't match "long-lived API key" semantics. 2b is the literal implementation of what was chosen.
- *Session store*: Starlette `SessionMiddleware` (in-process, signed cookie) over server-side sessions. The web app is single-process behind uvicorn; if it scales to multi-process, revisit with Redis sessions. Called out in Risks.

### D9 — Auth injection: app-level `dependencies`, not per-router
`create_app()` adds `dependencies=[Depends(get_current_user)]` at the `FastAPI(...)` constructor level so every route inherits it without per-router edits. `/healthz` and `/auth/*` routes opt out by overriding the dep to a no-op or by mounting `auth.router` *before* the global dep is applied (FastAPI applies constructor deps to routers included after the constructor — verify ordering). This is the lowest-churn way to blanket-protect the app.
- *Alternative considered*: per-router `Depends`. Rejected — 50+ routes, easy to miss one; a constructor-level dep with an explicit allowlist is safer.

## Risks / Trade-offs

- **[Sibling sub-projects break on auth]** `contract-review-agent` and `fd-coding-law-bench-mcp` may call `src/web` HTTP routes. After auth lands, unauthenticated calls 401. → Mitigation: before Phase 2 merge, grep both sub-projects for `httpx`/`requests` calls to `localhost:8010` / the web port; provide an API key or an internal-exempt loopback rule. `fd-coding-law-bench-mcp`'s MCP server is believed to connect to Postgres directly (not HTTP) — verify before assuming unaffected.
- **[Tests 401 en masse]** 54 test files; many hit routes without auth. `conftest.py` is already modified (in-flight baseline). → Mitigation: `conftest.py` installs an auth bypass for the test app (inject a stub `get_current_user` via `app.dependency_overrides`), so existing tests keep passing without each carrying a token. New auth-specific tests use real tokens.
- **[Logto config unavailable]** OIDC `client_id`/`client_secret`/JWKS URI come from the user's Logto deployment. Without them, Phase 2 can't be wired live. → Mitigation: implement behind env-gated config (`LOGTO_ISSUER`, `LOGTO_CLIENT_ID`, `LOGTO_CLIENT_SECRET`, `LOGTO_JWKS_URI`); the app boots without them (auth disabled, dev mode) and fails closed in prod when a route is hit without auth configured.
- **[Session cookie invalidation on restart]** Starlette `SessionMiddleware` signs with `SECRET_KEY`; rotating it logs everyone out. → Mitigation: document `SECRET_KEY` as a stable deploy secret; never auto-generate per-restart.
- **[Router ordering vs constructor deps]** If `auth.router` is included *after* the global `Depends`, FastAPI may still apply the dep to auth routes. → Mitigation: verify in a focused test (`/auth/login` returns 302, not 401); if affected, exclude via an `auth.router` with its own `dependencies=[]` override or a `get_current_user` that no-ops on `/auth/*`.
- **[Zombie DB deletion is irreversible]** Deleting `db/*.db` before confirming zero references breaks whatever still reads them. → Mitigation: `grep -rn` each DB filename across `src/`, `scripts/`, `tests/`, `*.yaml`, `.env*`; only delete files with zero hits; keep any hit file.
- **[`output/` may hold more than scratch]** `output/_create_gap_fill_clauses.py` etc. look like scratch, but confirm none is imported. → Mitigation: `grep -rn "from output" / "import output"` before deleting the directory's `.py` files.

## Migration Plan

**Phase 0 — baseline commit (revert point):**
1. Verify `add-contract-generation-modes` tasks.md: memory says "done & green" but openspec shows 0/25. Reconcile — either check off tasks or note the discrepancy in the commit message.
2. Stage the in-flight modified + untracked files; commit as a single baseline. Do not include refactor or auth work here.

**Phase 1 — refactor (independently revertable):**
1. D2 (router registration) → D3 (DbConn type) → D4 (src/docs rename) → D5 (audit docstrings) — code changes, each verified by the existing test suite staying green.
2. D6/D7 (archive + gitignore + delete scratch/zombie DBs) — repo hygiene pass.
3. Commit Phase 1 as one or two commits (structure, then hygiene). Run full suite.

**Phase 2 — auth (behind env-gate):**
1. Add `api_keys` migration (the only new table).
2. Implement `src/web/auth/{logto,session,apikey,deps}.py` + `src/web/routes/auth.py`.
3. Wire `get_current_user` at constructor level in `app.py`; add `/healthz`+`/auth/*` exemption.
4. Fix `conftest.py` with the test-auth bypass.
5. Auth-specific tests; full suite green.
6. Provide env vars from user's Logto; smoke-test login/callback/logout + API key gen/use.

**Rollback:** Each phase is a commit (or small set). Reverting Phase 2 restores the open API; reverting Phase 1 restores the messy-but-working structure; Phase 0 baseline is the floor.

## Open Questions

1. **API Key: 2a (Logto-native) vs 2b (local `api_keys` table).** Design assumes 2b (the user's stated 方案C). Confirm before Phase 2 implementation — 2a removes the only new table but changes caller semantics.
2. **Logto connection details**: endpoint/issuer, OIDC `client_id`/`client_secret`, JWKS URI, redirect URI host (web app's external URL). Needed to wire Phase 2 live; Phase 2 can be built env-gated without them.
3. **`add-contract-generation-modes` tasks.md reconciliation**: check off the 25 tasks (if genuinely done) or carry the gap forward. Affects whether Phase 0 commits a "complete" or "in-progress" baseline.
4. **`fd-coding-law-bench-mcp` transport**: confirm the MCP server connects to Postgres directly (not via `src/web` HTTP), so auth doesn't break the Claude Code tool integration. If it *does* call HTTP, it needs an API key.
5. **Session store**: Starlette signed-cookie (single-process) vs Redis-backed (multi-process). Assume signed-cookie for now; revisit if the deploy runs >1 uvicorn worker.
