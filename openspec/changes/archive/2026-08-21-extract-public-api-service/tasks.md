## 1. Public app factory & docs lockdown

- [x] 1.1 Add `create_public_app()` in `src/web/public_app.py` that mounts only the public read-heavy router subset (`contract_context`, `contracts`, `samples`, `search`, `law_info`, `clauses`-read paths) and deliberately EXCLUDES `api`, `auth`, `generation`, `dashboard`, `pages`. Reuse the same constructor-level `dependencies=[Depends(get_current_user)]`.
- [x] 1.2 Gate the docs surface off on the public app: `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` so `/openapi.json`, `/api/docs`, `/redoc` return 404 from the public pod. Verify `/healthz` still returns 200 (exempt path, unchanged).
- [x] 1.3 Add a `PUBLIC_API=1` (or a separate ASGI entrypoint) switch so the same image can run either `create_app()` (origin) or `create_public_app()` (China) based on env. Wire the Dockerfile/entrypoint to pick the right factory.
- [x] 1.4 Add a focused test (`tests/test_public_app.py`) asserting: (a) `/api/contracts/sale` returns 401 without a key, 200 with a valid key; (b) a write/admin route like `POST /api/contracts/sale/generate-batch` or `/api/keys` is NOT registered (404, not 401); (c) `/openapi.json` is 404; (d) `/healthz` is 200 unauthenticated.

## 2. Read-replica-safe API-key verify (`last_used_at` guard)

- [x] 2.1 In `src/web/auth/apikey.py` `verify_key`, make the `last_used_at` touch best-effort: wrap the UPDATE in a try/except that swallows `OperationalError`/readonly-replica errors and logs at debug. A failed/non-propagating `last_used_at` write SHALL NOT cause `401` or `500` — the request proceeds on a verified key.
- [x] 2.2 Add a `READONLY_REPLICA` setting (env-driven, default `0`) so the `last_used_at` write is skipped entirely when the public pod is configured against a read-only replica (avoids per-request error noise). When unset/`0`, the original best-effort-write behavior is preserved on the origin.
- [x] 2.3 Add a test (`tests/test_apikey_readonly.py`): with `READONLY_REPLICA=1`, `verify_key` does NOT issue an UPDATE and a valid key still authenticates; with `READONLY_REPLICA=0` and the DB simulated read-only (mock raising on write), the request still succeeds.

## 3. Rate limiting (the abuse half of "防止恶意调用")

- [x] 3.1 Add a rate-limit middleware (in-process token-bucket keyed by API-key prefix or client IP for anonymous) gated behind a `RATE_LIMIT_*` setting, so it is active on the public pod and dormant on the origin. Keep it dependency-light (no Redis requirement — in-memory is fine for a single-pod public service).
- [x] 3.2 Document the gateway-level alternative in `design.md`/README: Caddy `rate_limit` (or equivalent) in front of the public pod is the preferred production posture; the in-process middleware is the fallback when no gateway is present.
- [x] 3.3 Add a test asserting an over-limit caller receives `429` with a `Retry-After` hint while a valid under-limit key gets `200`.

## 4. PostgreSQL read-replica (logical replication)

- [x] 4.1 Write `scripts/infra/setup_publication.sql` that runs on the ORIGIN: creates a replication role (`REPLICATION LOGIN`) and a `CREATE PUBLICATION law_bench_public` for the tables the public pod reads (`clauses`, `contract_artifacts`, `api_keys`, `rubrics`, `prompts`, `tag_dims`, `law_info`, `contract_types`, and any other read-path tables). Idempotent.
- [x] 4.2 Write `scripts/infra/setup_subscription.sql` that runs on the CHINA replica: `CREATE SUBSCRIPTION law_bench_sub CONNECTION 'host=... user=repl ...' PUBLICATION law_bench_public`. Document that the China box must be able to reach the origin's Postgres port for this one persistent connection (the open feasibility question).
- [x] 4.3 Document in `design.md` the fallback if the China box CANNOT reach origin Postgres: batch `pg_dump`/`psql` snapshot sync on a cron (option A), or a fully independent local DB seeded once and re-synced manually (option C). Mark which option is chosen once the user confirms reachability.
- [x] 4.4 Add a README section (`docs/public-api-deploy.md`) walking through: origin publication → China subscription → verifying `SELECT * FROM api_keys` on the replica matches origin.

## 5. MinIO artifact sync

- [x] 5.1 Write `scripts/infra/sync_minio_artifacts.py` (or shell `mc mirror`) that mirrors the `scraw-law-contracts` bucket's `artifacts/` prefix from origin MinIO (`23.144.68.246:30900`) to the China-local MinIO. Idempotent (content-addressed keys make re-runs cheap).
- [x] 5.2 Make the `samples`/`contracts` download paths honor a `MINIO_PUBLIC_HOST` setting so the public pod reads from the China-local MinIO, not the origin. Confirm the presigned/download URL logic in `src/contracts/artifacts.py` `download()` still works against a different `minio_host`.
- [x] 5.3 Document a cron cadence (e.g. hourly `mc mirror`) and note that newly stored artifacts are not visible on the China box until the next sync tick — acceptable for a read-only public mirror.

## 6. Public pod deployment manifest

- [x] 6.1 Create `deploy/public/deployment.yaml` modeled on `deploy/deployment.yaml` but: image = the same `law-template` image with `PUBLIC_API=1` env; no `seed-db` initContainer (replica is the source, not the bundled SQLite); secrets via a new `law-bench-public` SecretRef (separate `database_url` pointing at the replica, `READONLY_REPLICA=1`, `RATE_LIMIT_*`, MinIO pointing at China-local).
- [x] 6.2 Copy the DNS-hardening block verbatim (`dnsPolicy: None` + `dnsConfig` kube-dns-only + `hostAliases` pinning `logto.tokenvault.vip`/`lawbench.tokenvault.vip`) — ONLY if the China box is itself a k3s node inheriting the polluted `mesh.finddata.cn` resolv.conf. If the China box has clean DNS, document that this block is omitted and why (do NOT strip it blindly on a polluted node).
- [x] 6.3 Create `deploy/public/service.yaml` (ClusterIP/NodePort) and a Caddy/ingress fragment with TLS + `rate_limit` for the China-facing domain. The public domain is a NEW host (not `lawbench.tokenvault.vip`).
- [x] 6.4 Keep `/healthz` as the liveness/readiness probe target (unchanged). Ensure the probe path remains exempt from auth and from rate limiting so it doesn't get 429'd.

## 7. Key issuance stays on origin (no public key management)

- [x] 7.1 Confirm `create_public_app()` does NOT mount the `auth` router, so `/auth/*` (OIDC login) and `/api/keys` (issue/list/revoke) are unreachable from the China host. Add an assertion/test that these paths return 404 on the public app.
- [x] 7.2 Document the operational flow in `docs/public-api-deploy.md`: keys are issued on the origin (`POST /api/keys` after browser login), the `api_keys` row replicates to the China replica via logical replication, and the key is handed to the China caller out-of-band. Revocation on the origin propagates to the replica (soft-delete `revoked_at`).

## 8. Documentation & standing-constraint verification

- [x] 8.1 Write `docs/public-api-deploy.md` covering: router subset, key-only posture, read-replica + MinIO sync, deployment manifest, rate limiting, and the reachability decision (A/B/C) once the user confirms whether the China box can reach origin Postgres.
- [x] 8.2 Verify standing constraints hold: auth remains fail-closed (`check_auth_config()` refuses boot if env unset on the public pod too); API keys remain salted slow-hash with plaintext shown once (only on origin); no password storage / no users table introduced; `dnsPolicy`/`hostAliases` block replicated (not stripped) on a polluted-node China box. Add a checklist to the deploy doc.
- [x] 8.3 Run the full test suite and confirm: (a) origin app behavior is unchanged (no regression in the 54+ test files); (b) the new public-app/apikey-readonly/rate-limit tests pass. Smoke the prod origin at `https://lawbench.tokenvault.vip` to confirm no behavior change there.
