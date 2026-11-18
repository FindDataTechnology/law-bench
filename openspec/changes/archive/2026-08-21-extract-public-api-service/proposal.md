## Why

The law-bench web app is a single FastAPI process on `23.144.68.246` (k3s, behind Caddy TLS at `lawbench.tokenvault.vip`) serving every surface — admin CRUD, generation pipelines, and read-only browse/search. We want to expose a **read-only public API to callers in China** from a separate pod on a China-based server, gated by API keys to prevent malicious/abusive use. The `lbk_` API-key channel (`src/web/auth/apikey.py`) and the app-wide `get_current_user` dependency already exist and are live, so the work is extraction + deployment + (optionally) DB replication — not new auth code. Doing it now keeps the public surface physically and politically separate from the write/admin origin, so a compromised key or a GFW-induced outage on the China box cannot reach the generation/admin paths.

## What Changes

- **New standalone service entrypoint** that mounts a *subset* of the existing routers (the read-heavy set: `contract_context`, `contracts`, `samples`, `search`, `law_info`, `clauses`-read) and deliberately excludes the write/admin/generation routers (`api` CRUD, `generation` modes D/E/F/G, `dashboard`, `auth` key-issuance).
- **Key-only auth posture for the public pod**: the constructor-level dependency is retained, but the China pod is configured to resolve identity via `X-API-Key` only — the session-cookie and Logto-JWKS Bearer paths are dormant because the China box does not run browser login and cannot be assumed to reach Logto's JWKS reliably across the border. Key *issuance* stays on the origin (`/api/keys` is not mounted on the public pod); the public pod only *verifies* keys.
- **Rate limiting** at the gateway (Caddy `rate_limit` or an in-process middleware) layered on top of the existing key auth — a key authenticates but does not throttle; the public endpoint needs both. This is the missing half of "防止恶意调用".
- **PostgreSQL read-replica on the China box** (chosen architecture, option B) fed by logical replication (`CREATE PUBLICATION`/`CREATE SUBSCRIPTION`) from the origin, so per-request DB reads are local rather than crossing the border. Includes a MinIO artifact sync job so the `samples`/`contracts` download paths serve from China-local storage.
- **`last_used_at` write-on-verify guard**: `apikey.py` currently writes `last_used_at` on every key verification. Against a read-replica this write either fails (replica is read-only) or doesn't propagate back. The verify path SHALL make this touch best-effort and SHALL NOT fail the request when the write cannot persist on the public pod.
- **Public pod deployment manifest** reusing the load-bearing DNS hardening from `deploy/deployment.yaml:27-42` (`dnsPolicy: None` + `dnsConfig` kube-dns-only + `hostAliases`) when the China box is itself a k3s node with the polluted `resolv.conf` `mesh.finddata.cn` search domain. (N/A if the China box is a plain host with clean DNS.)
- **Docs surface locked down on the public pod**: `docs_url=None, redoc_url=None, openapi_url=None` so `/openapi.json`/`/api/docs`/`/redoc` — currently public on the origin per the auth audit — do not leak the endpoint shape from the China box.
- **BREAKING (for the public pod only)**: the public pod does not mount `/auth/*` or `/api/keys`, so browser OIDC login and self-service key management are unreachable from the China host. This is intentional — keys are issued on the origin and handed to China callers out-of-band.

## Capabilities

### New Capabilities
- `public-api-service`: a standalone, China-deployed, read-only FastAPI service that mounts a subset of the existing routers behind API-key-only auth + rate limiting, reading from a Postgres read-replica and a synced MinIO corpus, with no Logto dependency and no write/admin/generation routes.

### Modified Capabilities
- `web-auth`: the `get_current_user` / `last_used_at` requirement gains a read-replica-safe variant — when the service runs against a read-only Postgres replica (the public pod), the `last_used_at` touch SHALL be best-effort and a failed/non-propagating write SHALL NOT cause `401` or `500`. The present-but-invalid-credential binding and the cookie→Bearer→API-Key order are unchanged on the origin.

## Impact

- **New code**: a `src/web/public_app.py` (or `create_public_app()` factory) selecting the public router subset + key-only auth + docs-off; a deployment manifest under `deploy/public/`; a logical-replication setup script and a MinIO sync script (or cron). No changes to the origin app's behavior.
- **Existing code touched**: `src/web/auth/apikey.py` `verify_key` path (best-effort `last_used_at`); possibly a flag on `create_app` to disable docs. Routers themselves are unchanged — they're re-mounted, not rewritten.
- **Dependencies/systems**: the China box needs a Postgres 15+ instance (replica), MinIO (or shared bucket mirror), Caddy (or equivalent) for TLS + rate limiting, and network reachability from the China box to the origin's Postgres for the *replication* connection (one persistent conn, not per-request) — the open feasibility question. The origin needs a `CREATE PUBLICATION` for the replicated tables and a replication-role Postgres user.
- **Sub-projects**: `contract-review-agent` / `fd-coding-law-bench-mcp` / `contract-generator` are unaffected — they talk to the origin or the DB directly, not the public pod.
- **Standing constraints preserved**: auth stays fail-closed (`check_auth_config()` refuses boot if env unset); API keys remain salted slow-hash with plaintext shown once; no password storage / no users table; the `dnsPolicy`/`hostAliases` block is replicated, not stripped.
