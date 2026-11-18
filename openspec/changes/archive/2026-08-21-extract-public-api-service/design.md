## Context

The law-bench web app is one FastAPI process (`src/web/app.py`, `create_app()`) on `23.144.68.246` (k3s, behind Caddy TLS at `lawbench.tokenvault.vip`, NodePort 30820). It serves every surface in one binary: admin CRUD (`api`), generation pipelines (`generation` modes D/E/F/G), dashboard, the HTML chrome (`pages`), and the read-heavy browse/search/sample surfaces (`contract_context`, `contracts`, `samples`, `search`, `law_info`, `clauses`).

Auth is already app-wide and multi-channel: a single constructor-level dependency `dependencies=[Depends(get_current_user)]` (`app.py:98`) resolves identity via cookie → Bearer JWT (Logto JWKS) → `X-API-Key`, present-but-invalid is binding (401, no fallthrough). The `lbk_` API-key channel (`src/web/auth/apikey.py`: 16-char indexed prefix + salted `pbkdf2_sha256` slow-hash, `api_keys` table, soft-delete) is live. So "add an apikey to prevent malicious calls" is *not* a new-auth problem — the channel exists; the remaining work is **extraction, deployment, and (optionally) DB replication**, plus the one missing half: rate limiting (a key authenticates but does not throttle).

External dependencies the origin reaches: Postgres (`10.43.138.128`, locally `localhost:15432`), MinIO (`http://23.144.68.246:30900`, bucket `scraw-law-contracts`), Logto (`logto.tokenvault.vip`), and the LLM relay (`http://154.94.237.22:3000/v1`). The origin deployment carries load-bearing DNS hardening (`deploy/deployment.yaml:27-42`: `dnsPolicy: None` + `dnsConfig` kube-dns-only + `hostAliases`) — without it, pods resolve `.svc.cluster.local` to the `mesh.finddata.cn` black-hole `8.218.137.223` and hang at startup (memory `prod-deploy-dns-pollution-fix`).

The auth audit (memory `api-auth-audit-and-nodeport-decision`) found one residual exposure on the *origin*: the auto-generated docs surface (`/openapi.json`, `/api/docs`, `/redoc`) is public because FastAPI's docs routes do not inherit app-level `dependencies`. The NodePort 30820 is intentionally left public per user decision (whitelist later).

Stakeholders: the user (wants a China-facing public API pod with key gating), the origin ops (must add a Postgres publication + replication role, zero behavior change on origin), and China callers (receive `lbk_` keys issued on origin, out-of-band).

## Goals / Non-Goals

**Goals:**
- Expose a **read-only** public API surface from a separate pod on a China-based server, authenticated by `X-API-Key`, rate-limited, with no write/admin/generation routes reachable.
- Keep the **origin's behavior unchanged** — no refactor that alters origin request/response semantics.
- Reuse the existing auth layer, routers, and service-layer query functions verbatim — re-mount, don't rewrite.
- Make the public pod **Logto-independent**: it does not run browser login and must not depend on reaching Logto's JWKS to boot or serve.
- Replicate the load-bearing DNS hardening when the China box is itself a k3s node with the polluted `resolv.conf`.
- Lock the docs surface on the public pod (`docs_url=None` etc.) so the endpoint shape does not leak from China.

**Non-Goals:**
- Locking the docs surface on the **origin** — that is a separate, already-noted follow-up (memory `api-auth-audit-and-nodeport-decision`); this change only hardens the public pod.
- Closing NodePort 30820 or changing Caddy's origin dial target — deferred by user decision.
- Building a browser UI on the China box — the public surface is a JSON + download API, keyed.
- Any change to `contract-review-agent` / `fd-coding-law-bench-mcp` / `contract-generator` — they talk to the origin or DB directly, not the public pod.
- A write path from China back to origin (revocations, key issuance) — keys are issued on origin and handed to China callers out-of-band; this is explicitly out of scope for v1.

## Decisions

### D1. Separate `create_public_app()` factory, not a flag on `create_app()`
The public app is structurally different from the origin: different router subset, no Logto startup check, docs off, key-only posture. Encoding that as boolean flags on `create_app(public=True, docs=False, logto=False, routers=[...])` couples two apps' concerns through one parameter list and makes every origin change risk flipping a flag. A separate `src/web/public_app.py` with `create_public_app()` is clearer and keeps the origin factory untouched.

**Alternative considered:** `create_app(include=["contract_context","contracts",...], docs=False)` — rejected because the Logto-reachability startup hook (`_verify_auth_startup` → `logto.verify_reachable()`) and `check_auth_config()` (which `AUTH_REQUIRED_VARS`-gates on `LOGTO_*`) are baked into `create_app()`; a flag would still need to skip them, which is the same complexity in a worse place.

### D2. Route-level allowlisting, not router-level — split the mixed router
"Mount a subset of routers" is too coarse: `contract_context.py` is mostly read (GET `/api/contracts`, `/{type}`, `/slots`, `/laws`, `/tags`, `/clauses`) but also contains **`POST /api/contracts/{type}/generate`** (assembles + writes a DOCX/PDF). Mounting the whole router re-exposes the write path — defeating the "compromised key can't reach generation" goal. `generation.py` is uniformly write (all 6 routes) → excluded wholesale; `api.py` is CRUD → excluded; `dashboard.py` is admin → excluded; `auth.py` is key-issuance/OIDC → excluded.

For the one mixed router (`contract_context`), **split its write route out** behind a separate router object (e.g. move `POST /generate` into `generation.py` as a sibling, or a new `contract_context_write.router`), behavior-preserving on the origin (origin includes both; public includes only the read router). This is a small, mechanical refactor with a regression guard (the existing `test_contract_context_api.py`).

**Alternative considered:** public app re-declares thin read handlers calling the same service-layer functions — rejected because it duplicates route declarations and drifts from the origin's OpenAPI shape; splitting the router keeps one source of truth.

**Public router set (read-only):** `contract_context` (reads only), `contracts` (browse + `GET /api/contracts/artifacts/{id}/download`), `search`, `law_info`, `clauses` (read endpoints only — if `clauses.py` has write routes, split likewise). The HTML `samples` page and `pages` chrome are **not** mounted (they require templates/static/base.html and are not part of an API surface); the JSON artifact-listing can be exposed via the `contracts` router's existing endpoints if a browse API is needed.

### D3. Key-only auth posture — skip Logto startup checks, keep the shared dep
The public pod reuses `get_current_user` unchanged (cookie → Bearer → API-key order, present-but-invalid binding). In practice on the public pod: no Logto-issued cookie ever arrives (no browser login), and a presented Bearer would try JWKS fetch → fail → 401 (acceptable; no caller sends Bearer to the public pod). The `X-API-Key` path is the live channel.

**The load-bearing nuance:** `create_app()`'s `_verify_auth_startup` calls `check_auth_config()` (raises `ConfigError` if any `LOGTO_*` in `AUTH_REQUIRED_VARS` is unset) **and** `logto.verify_reachable()`. On the China box the public pod has no `LOGTO_*` and cannot reach `logto.tokenvault.vip` → both checks fail → **CrashLoopBackOff**. So `create_public_app()` MUST omit that hook and substitute a `check_public_auth_config()` that verifies only: `DATABASE_URL` reachable, `api_keys` table present, and (for the dormant cookie path to not crash on import) `AUTH_SESSION_SECRET` set. It MUST NOT call `logto.verify_reachable()`.

**Alternative considered:** ship `LOGTO_*` to the China box and let the JWKS fetch best-effort-fail per request — rejected because it makes boot depend on a cross-border DNS/TLS fetch (exactly the `mesh.finddata.cn`-class fragility the DNS block was added to avoid) and serves no purpose when no browser flow runs.

### D4. Read-replica (option B) — logical replication + MinIO sync
Per-request DB reads from China crossing the border to origin Postgres is fragile (latency, GFW). The chosen architecture is a **Postgres read-replica on the China box** fed by logical replication (`CREATE PUBLICATION` / `CREATE SUBSCRIPTION`) — one persistent replication connection (origin → China) instead of per-request crossings. MinIO artifacts sync via `mc mirror` cron (or MinIO site replication) so `GET /api/contracts/artifacts/{id}/download` serves from China-local storage (`minio_host` → China MinIO).

Replicated tables: `api_keys` (verify-only on the public pod), `contract_artifacts`, `clauses`, `tag_dims`, `contract_types` (file-backed, but mirror anyway), `law_info`, and whichever tables the read routers query (`rubrics`/`prompts` only if their read endpoints are exposed). Writes (key issuance, artifact creation) happen on origin and flow to the replica.

**Alternatives considered:**
- **A. Thin proxy** (public pod calls origin DB per-request): lowest ops cost, but every DB hop crosses the border and exposes Postgres publicly — rejected as too fragile and too smelly.
- **C. Fully independent** (own DB, own MinIO, own data, diverges from origin): no border dependency but double infra and data drifts — the public API would serve stale clauses/artifacts with no sync path. Rejected unless the China box is fully air-gapped from origin.

B is the recommendation; A and C are fallbacks gated on the open reachability question (D-Open-1).

#### D4-fallback. When the China box CANNOT reach origin Postgres (task 4.3)

Logical replication (option B) needs **one persistent TCP connection** from the China subscriber to the origin's Postgres port. If GFW / network topology makes that connection unreliable or impossible (the open question D-Open-1 resolves to "no"), the read-replica story falls back to one of two shapes — the **router/auth/rate-limit decisions are unaffected; only data freshness changes**:

- **Fallback A — batch `pg_dump`/`psql` snapshot sync on a cron.** A scheduled job on the origin (or a bridge host that can reach both) runs `pg_dump --data-only --table=api_keys --table=contract_artifacts ...` (the publication's 8-table set) and pipes the snapshot to the China box's Postgres via `psql`, on a cadence (e.g. hourly). Cheaper than logical replication (no persistent connection, no replication slot to manage), and resilient to an intermittently-severed border link — a missed tick just makes the replica staler by one cadence. The cost is **stale reads between ticks**: a freshly-issued key is not verifiable on the China box until the next dump lands (minutes). A `sync_minio_artifacts.py`-style script (task 5.1) is the MinIO analogue. This is the **recommended fallback** when B is ruled out — it keeps the public pod's `DATABASE_URL` pointing at the China-local Postgres (no per-request border crossing) and just trades real-time freshness for batch cadence.
- **Fallback C — fully independent local DB, seeded once and re-synced manually.** The China box runs its own Postgres + MinIO, seeded once from an origin snapshot, and re-synced manually (ad-hoc `pg_dump`/`mc mirror` runs when the operator decides the replica is too stale). No border dependency at all, but **data drifts silently** between syncs — the public API serves stale clauses/artifacts and a freshly-revoked key stays valid on the China box until the next manual sync. Only acceptable when the China box is fully air-gapped from the origin; otherwise fallback A's automated cadence strictly dominates C.

**Which is chosen** is gated on the user's confirmation of reachability (D-Open-1). Once confirmed, this section is marked with the chosen option and the deploy doc (`docs/public-api-deploy.md`) records it. Until then, **both `setup_publication.sql` and `setup_subscription.sql` are written and committed** (tasks 4.1/4.2) so option B is ready if the answer is "yes"; if "no", fallback A's cron job is a thin script reusing the same `pg_dump` table list, sketched in `docs/public-api-deploy.md`.

### D5. `last_used_at` write-on-verify must become best-effort
`apikey.verify_key()` touches `last_used_at` on every key check. Against a read-only replica the `UPDATE` either errors or doesn't propagate. The verify path SHALL wrap that write in try/except, log best-effort, and **SHALL NOT** fail the request (no 401/500) when the write cannot persist. This is a behavior change *scoped to the public pod* (origin keeps the real touch). If `last_used_at` freshness matters for revocation forensics, a v2 can add a fire-and-forget touch-back to an origin endpoint — out of scope for v1.

### D6. Rate limiting at the gateway, keyed on the resolved identity
A key authenticates; it does not throttle. The public endpoint needs both. **Caddy `rate_limit`** (or equivalent) at the China edge, bucketed per `X-API-Key` prefix (or per source IP for unauthenticated 401s), is the recommended layer — keeps the app simple and survives app restarts. If the China box does not run Caddy, an in-process FastAPI middleware (token bucket on the resolved `request.state.user` key prefix) is the fallback.

**As-built (task 3.1):** the in-process fallback is `src/web/rate_limit.py` — a `TokenBucketLimiter` installed as the **outermost** HTTP middleware (before auth, so an invalid-credential caller still consumes a token — a cred-spray is throttled regardless of validity), keyed by the raw `X-API-Key` prefix (`k:<prefix>`) or the client IP (`i:<ip>`, honoring `X-Forwarded-For`). It is env-gated behind `RATE_LIMIT_ENABLED` (default `"0"`): dormant on the origin (byte-for-byte unchanged) and active only on the public pod (`RATE_LIMIT_ENABLED=1`, `RATE_LIMIT_RPS`/`RATE_LIMIT_BURST` tune the bucket). `/healthz` is exempt so probes never 429 a healthy pod (task 6.4). A gateway-level limiter (Caddy `rate_limit` / Nginx `limit_req`) in front of the pod remains the **preferred** production posture; this in-process limiter is the no-gateway fallback so an abusive caller is never unthrottled even bare-metal.

**Alternative considered:** rely only on key revocation for abuse control — rejected; revocation is reactive, a hostile party with one valid key can hammer the box before it's noticed.

### D7. Deployment manifest reuses the DNS block conditionally
If the China box is a k3s node with the polluted `resolv.conf` (the same `mesh.finddata.cn` search domain), the public pod manifest (`deploy/public/deployment.yaml`) MUST replicate `dnsPolicy: None` + `dnsConfig` (kube-dns `10.43.0.10` only) + `hostAliases` pinning verbatim. If the China box is a plain host with clean DNS, that block is N/A and a docker-compose/systemd unit suffices. Two manifest variants or a runtime probe — decided by D-Open-2.

## Risks / Trade-offs

- **[Replication lag → stale reads]** A key issued on origin isn't verifiable on the public pod until logical replication applies it (seconds to minutes under GFW pressure). A newly issued key called immediately from China → 401 until it lands. → Mitigation: document the propagation window; advise testing a fresh key against the origin first; the `api_keys` table is small so replication is fast in steady state.
- **[GFW intermittently severs the replication connection]** The one persistent origin→China Postgres connection can stall, leaving the replica increasingly stale. → Mitigation: logical replication auto-reconnects; add a lag monitor (alert if `pg_stat_subscription` lag exceeds N minutes); fall back to nightly `pg_dump` batch sync if real-time is required.
- **[last_used_at staleness]** Revoked keys' last-used time on the replica is inaccurate (the touch is best-effort/skipped). → Accepted for v1; forensics can fall back to the origin's `api_keys.last_used_at`.
- **[DNS block applied to a non-k3s China host breaks boot]** Copying `deploy/public/deployment.yaml` with the k3s `dnsConfig` onto a plain host with no kube-dns would fail DNS entirely. → Mitigation: pick the manifest variant by D-Open-2; never blindly apply the k3s manifest.
- **[Write route accidentally re-exposed]** A future read router that gains a write route would be mounted on the public pod unless the allowlist is re-checked. → Mitigation: the public app's router allowlist is an explicit, commented list; add a test asserting no `POST`/`PUT`/`DELETE`/`PATCH` route is mounted on `create_public_app()`.
- **[Docs still public on origin]** This change locks docs only on the public pod; the origin's `/openapi.json`/`/api/docs` remain public (memory `api-auth-audit-and-nodeport-decision`). → Accepted; origin docs lockdown is a separate follow-up.
- **[MinIO sync lag → fresh artifact not downloadable from China]** A newly stored artifact on origin isn't on the China mirror until the sync runs. → Mitigation: document sync cadence; the artifact-listing endpoint can note `available_in` fields if needed.

## Migration Plan

1. **Origin prep (zero behavior change):** `CREATE PUBLICATION law_bench_public FOR TABLE api_keys, contract_artifacts, clauses, tag_dims, ...;` + a `REPLICATION`/`LOGIN` Postgres role; refactor `contract_context.py` to split `POST /generate` out (origin includes both routers; regression tests must stay green).
2. **Build the public app in-repo:** `src/web/public_app.py` (`create_public_app()`), the `check_public_auth_config()`, the `last_used_at` best-effort guard, the docs-off flags, the write-route-not-mounted test. Validate locally against the origin DB (read-only) to prove router subset + key auth + docs-off.
3. **Stand up the China box:** Postgres subscriber (`CREATE SUBSCRIPTION ... CONNECTION 'origin:15432'`), MinIO mirror (mc/site-replication), Caddy (TLS + rate_limit), the public pod image. Set `minio_host` → China MinIO, `DATABASE_URL` → China replica.
4. **Verify:** issue a `lbk_` key on origin → wait for replication → call a public read endpoint with the key → 200; call a write endpoint (`POST /generate`) → 404 (not mounted); hammer the box → rate limit trips; `/openapi.json` → 404; `/healthz` → 200 (still exempt).
5. **Rollback:** tear down the China pod + `DROP SUBSCRIPTION` + stop MinIO sync. The origin is untouched (no behavior changed in step 1); rollback is purely infra.

## Open Questions

- **D-Open-1 (the gate):** can the China box establish one persistent Postgres replication connection to the origin (`23.144.68.246:15432` / the k3s service)? If **yes** → option B proceeds as designed. If **no** → fall back to C (fully independent, nightly `pg_dump` sync) — the design's router/auth/rate-limit decisions hold; only the data-freshness story changes.
- **D-Open-2:** is the China box a k3s node (reuse the DNS block verbatim) or a plain host (clean DNS, docker-compose/systemd)?
- **D-Open-3:** rate limiting at the gateway (Caddy) or in-process middleware? (Caddy preferred if the China box runs Caddy.)
- **D-Open-4:** does the public surface need a browse API (JSON artifact listing) in addition to per-artifact download, given the HTML `/samples` page is not mounted?
