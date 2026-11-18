# Public API Service — Deployment Guide

Operational walkthrough for the China-facing read-only public API pod extracted
from the law-bench origin. This doc is the single source of truth for how the
public pod is stood up, kept in sync, and verified. It is built up incrementally
across the `extract-public-api-service` change; sections marked *(pending)* are
filled by later tasks.

## 1. Architecture at a glance

The **origin** (`src/web/app.py`, `create_app()`) serves everything on
`lawbench.finddatatech.cloud`. The **public pod** (`src/web/public_app.py`,
`create_public_app()`) is a separate FastAPI process from the **same image**
(selected at boot by `PUBLIC_API=1` in `scripts/docker-entrypoint.sh`) that
mounts only the read-heavy router subset, locks the docs surface off
(`/openapi.json` → 404), runs key-only auth (no Logto dependency), and reads
from a **China-local Postgres read-replica + China-local MinIO** mirror so no
per-request border crossing is needed.

| Concern | Origin | Public pod |
|---|---|---|
| Factory | `create_app()` | `create_public_app()` |
| Routers | all 11 | `contract_context`(read), `contracts`, `samples`, `search`, `law_info`, `clauses`(read) |
| Auth | cookie → Bearer JWT → X-API-Key | same dep, **X-API-Key is the live channel** |
| Logto | required (JWKS at boot) | **not required** (`check_public_auth_config`) |
| Docs | public (separate follow-up) | locked (`docs_url=None` ...) |
| Rate limit | dormant (`RATE_LIMIT_ENABLED=0`) | active (`RATE_LIMIT_ENABLED=1`) |
| DB | origin primary | China read-replica |
| MinIO | origin | China-local mirror |

## 2. Data sync — Postgres read-replica (option B: logical replication)

*(Fallback shapes A/C when the China box cannot reach origin Postgres are
documented in `openspec/changes/extract-public-api-service/design.md`
§D4-fallback — see below for the option-B walkthrough.)*

### 2.1 Origin side — publication + replication role

Run **on the origin** Postgres (the law-bench primary):

```sh
# Set the replication role's password OUT-OF-BAND (never commit it).
# The SQL creates the role password-less; set it here via psql -v so the
# secret does not live in the repo.
psql "$DATABASE_URL" \
    -v repl_password="$LAW_BENCH_REPL_PASSWORD" \
    -f scripts/infra/setup_publication.sql
# NOTE: setup_publication.sql creates the role WITHOUT a password (the
# placeholder ALTER is a no-op). Set the password separately:
psql "$DATABASE_URL" -c "ALTER ROLE law_bench_repl PASSWORD '$LAW_BENCH_REPL_PASSWORD';"
```

`setup_publication.sql` is idempotent: it creates the `law_bench_repl`
(`REPLICATION LOGIN`) role if absent, and (drop-then-)creates the
`law_bench_public` publication `FOR TABLE` the 8 read-path tables:
`api_keys`, `contract_artifacts`, `clauses`, `tag_dims`, `law_info`, `rubrics`,
`criteria`, `prompts`. Re-running after adding a table = edit the `FOR TABLE`
list + re-run (the `DROP PUBLICATION` makes the list the single source of
truth).

**Verify on the origin after apply:**

```sql
SELECT * FROM pg_publication_tables WHERE pubname = 'law_bench_public';
-- should list the 8 tables above.
SELECT rolname, rolreplication, rolcanlogin FROM pg_roles
WHERE rolname = 'law_bench_repl';
-- rolreplication = t, rolcanlogin = t.
```

### 2.2 China side — subscription

Prerequisites: the origin publication exists (2.1) **and** the China box can
reach the origin's Postgres port (the open question `design.md` D-Open-1). If
it cannot, skip this file and use fallback A (cron `pg_dump`) — see §2.4.

Run **on the China replica's** Postgres:

```sh
psql "$CHINA_DATABASE_URL" \
    -v origin_host="$ORIGIN_PG_HOST" \
    -v repl_password="$LAW_BENCH_REPL_PASSWORD" \
    -f scripts/infra/setup_subscription.sql
```

`setup_subscription.sql` creates the local tables (same DDL as origin's
`ensure_schema`/`harbor_seed`, `IF NOT EXISTS` so re-runnable) and a
`law_bench_sub` subscription that opens one persistent replication connection to
the origin's `law_bench_public` publication, with `copy_data=true` (initial
table sync on subscribe) and `enabled=true` (starts streaming immediately).

> **Replace the two placeholders in `setup_subscription.sql` before running:**
> `<origin-host>` (origin Postgres endpoint reachable from China, likely
> `23.144.68.246` on port `15432` via the k3s NodePort, or a DNS name that
> resolves from the China box) and `<repl-password>` (the `law_bench_repl`
> password set in §2.1). Or pass them as `psql -v` variables.

### 2.3 Verify the replica matches origin

After the initial sync (`copy_data=true`) lands, confirm the replica's row
counts match the origin — the load-bearing table is `api_keys` (the public pod
verifies keys against this):

```sql
-- On the ORIGIN:
SELECT count(*) FROM api_keys;            -- e.g. 42
SELECT count(*) FROM contract_artifacts;   -- e.g. 724
SELECT count(*) FROM clauses;

-- On the CHINA replica:
SELECT count(*) FROM api_keys;             -- must match origin
SELECT count(*) FROM contract_artifacts;  -- must match origin
SELECT count(*) FROM clauses;
```

Replication lag is visible via:

```sql
SELECT * FROM pg_stat_subscription;              -- one row, received_lsn advancing
SELECT * FROM pg_stat_subscription_stats;        -- insert/update/delete counts (PG14+)
```

A freshly-issued key on the origin is **not verifiable on the China pod until
logical replication applies it** (seconds in steady state; minutes under GFW
pressure). Advise testing a fresh key against the origin first. The `api_keys`
table is small, so replication is fast once the connection is healthy.

### 2.4 Fallback A — cron `pg_dump` snapshot (when China cannot reach origin PG)

If the answer to D-Open-1 is "no" (the China box cannot hold a persistent
Postgres connection to the origin), drop the subscription and run a batch
snapshot sync on a cron instead. Same 8-table set as the publication:

```sh
# On the origin (or a bridge host that can reach both), hourly:
pg_dump "$ORIGIN_DATABASE_URL" \
    --data-only \
    --table=api_keys --table=contract_artifacts --table=clauses \
    --table=tag_dims --table=law_info --table=rubrics --table=criteria --table=prompts \
    --clean --if-exists \
    | psql "$CHINA_DATABASE_URL"
```

`--clean --if-exists` makes the restore idempotent (drops + recreates rows). A
missed tick just makes the replica staler by one cadence — no replication slot
to manage, no persistent connection to sever. The cost is stale reads between
ticks (minutes); acceptable for a read-only public mirror.

## 3. MinIO artifact sync

The public pod's read/download paths (`GET /api/contracts/artifacts/{id}/download`,
the `/samples` browse page) stream docx/pdf bytes from MinIO. So that no
per-request border crossing happens, the public pod reads from a
**China-local MinIO mirror** instead of the origin. Two pieces:

1. **`MINIO_PUBLIC_HOST` (task 5.2)** — when set (a full URL, e.g.
   `http://china-minio:9000`) on the public pod's env, `src/contracts/artifacts.py`
   `_client()` builds its Minio client against that China-local endpoint
   (`MINIO_PUBLIC_ENDPOINT`/`MINIO_PUBLIC_SECURE`) instead of the origin
   `MINIO_ENDPOINT`/`MINIO_SECURE`. Credentials still come from the shared
   `minio_root_user`/`minio_root_password` env (on the public pod those are the
   China MinIO's creds), so only the endpoint host is overridden. When unset
   (origin), `MINIO_PUBLIC_*` falls back to the origin `MINIO_*` values, so
   origin behavior is byte-for-byte unchanged — there is no split code path to
   maintain.

2. **`scripts/infra/sync_minio_artifacts.py` (task 5.1)** — mirrors the
   `scraw-law-contracts` bucket's `artifacts/` prefix from the origin MinIO
   (`23.144.68.246:30900`) into the China-local MinIO. Content-addressed keys
   (`artifacts/{contract_type}/{artifact_id}.{ext}`) make re-runs cheap: an
   object already present with matching size is skipped, so a cron tick that
   finds nothing new is a handful of `HEAD` requests, not a full re-copy.

### Endpoint posture (who uses which MinIO endpoint)

| Consumer | Endpoint | Why |
|---|---|---|
| origin app pod | `http://minio.minio.svc.cluster.local:9000` (k8s secret `law-bench-minio`) | in-cluster service URL — no TLS hop, no Caddy/ACME dependency in the app's own data path |
| external tools / China mirror sync | `https://file.token118.com` (US-box Caddy → `127.0.0.1:30900`) | S3 API over TLS for cross-border consumers; anonymous listing is correctly `AccessDenied` |
| browser file browsing | `https://file-console.token118.com` (US-box Caddy → `127.0.0.1:30901`, needs a DNS A record → `23.144.68.246`) or directly `http://23.144.68.246:30901` | the MinIO **console** (web UI) is a separate service from the S3 API; `file.token118.com` serves XML S3 responses, not a page |

The MinIO deployment carries
`MINIO_SERVER_URL=https://file.token118.com` and
`MINIO_BROWSER_REDIRECT_URL=https://file-console.token118.com` so the console's
login/redirect flow works behind the domain. `src/settings.py` rejects a
scheme-less `minio_host` / `MINIO_PUBLIC_HOST` at boot (`ConfigError`), so a
value like `file.token118.com` (no `https://`) fails fast instead of
producing an empty endpoint that 500s per request.

### 3.1 Run the mirror (hourly cron)

```sh
# Hourly on (or reachable from) the China box. Reads creds from env.
# Origin creds: minio_root_user / minio_root_password / minio_host
# Local creds : MINIO_LOCAL_USER / MINIO_LOCAL_PASSWORD / MINIO_LOCAL_HOST
python scripts/infra/sync_minio_artifacts.py \
    --origin-host http://23.144.68.246:30900 \
    --local-host http://localhost:9000

# Dry-run (list what would be copied, copy nothing):
python scripts/infra/sync_minio_artifacts.py --dry-run
```

A cron line (hourly, off the :00 mark):

```cron
7 * * * *  /usr/bin/env MINIO_LOCAL_HOST=http://localhost:9000 \
    MINIO_LOCAL_USER=$CHINA_MINIO_USER MINIO_LOCAL_PASSWORD=$CHINA_MINIO_PASS \
    python /app/scripts/infra/sync_minio_artifacts.py >> /var/log/minio-sync.log 2>&1
```

`mc mirror` is the equivalent one-liner if the MinIO `mc` CLI is installed on
the China box:

```sh
mc alias set origin   http://23.144.68.246:30900 "$ORIGIN_USER" "$ORIGIN_PASS"
mc alias set china    http://localhost:9000      "$CHINA_USER"  "$CHINA_PASS"
mc mirror --overwrite origin/scraw-law-contracts/artifacts china/scraw-law-contracts/artifacts
```

### 3.2 Sync-lag note

Newly generated artifacts land on the **origin** MinIO first (the public pod
has no generate routes mounted, so it never writes). They are **not visible on
the China box until the next sync tick** — up to one cron interval of staleness
(burst-bound on the mirror, not the read path). This is acceptable for a
read-only public mirror whose job is serving previously-generated contracts, not
reflecting an origin write within the second.

The `contract_artifacts` *rows* (metadata, slots, body_hash) arrive via
Postgres logical replication (§2) in near-real-time, but the *binary docx/pdf
objects* are in MinIO and need this separate mirror. So a freshly-generated
contract may briefly show up in the `/samples` listing (the row is replicated)
but 404 on download (the object isn't mirrored yet) until the next tick. The
gap is bounded by the cron cadence; hourly is a reasonable starting point.

Per-object failures do **not** fail the run — a flaky border link should not
abort the sync of the objects that *are* reachable; the next tick retries the
misses. Only a total failure (origin MinIO unreachable) exits non-zero, so
monitor the cron exit code for that.

## 4. Deployment manifest

`deploy/public/deployment.yaml` — modeled on the origin `deploy/deployment.yaml`
but with the public-pod posture:

- **Image:** the *same* `harbor.local/law-bench/law-template` image (no separate
  build); `PUBLIC_API=1` env selects `create_public_app()` in
  `scripts/docker-entrypoint.sh`.
- **No `seed-db` initContainer, no `db` PVC:** the public pod's data source is
  the replicated China Postgres (option B, §2) or the cron-`pg_dump` snapshot
  (fallback A) — either way rows arrive via replication, not from `/app/db`.
  Contrast the origin's `seed-db` initContainer copying the bundled SQLite.
- **`law-bench-public` SecretRef:** SEPARATE from the origin's `law-bench-*`
  secrets so the China pod never reads origin creds. Populate with:
  `database_url` (China replica DSN), `AUTH_SESSION_SECRET` (so the dormant
  cookie path does not fail open — required by `check_public_auth_config`),
  `minio_root_user`/`minio_root_password` (China-local MinIO creds),
  `MINIO_PUBLIC_HOST` (China-local MinIO endpoint, task 5.2). **No `LOGTO_*`
  vars** — the public pod has no Logto dependency.
- **Env:** `PUBLIC_API=1`, `READONLY_REPLICA=1` (skip `last_used_at` writes),
  `RATE_LIMIT_ENABLED=1` (+ `RATE_LIMIT_RPS`/`RATE_LIMIT_BURST`).
- **Probes:** `/healthz` liveness+readiness (unchanged from origin). Exempt from
  auth (`get_current_user` skips `/healthz`) AND from rate limiting
  (`rate_limit` `_EXEMPT_PATH`) so probes never get 401/429 on a healthy pod.

`deploy/public/service.yaml` — **ClusterIP** by default (the pod is fronted by
the Caddy gateway, which terminates TLS and applies the gateway-level
`rate_limit`). No raw NodePort exposed — the public surface is exactly one host
through one entry point. If you are NOT running Caddy in front on the China
box, switch `type` to `NodePort` with a **new** port (do NOT reuse the origin's
`30820`; the two pods must stay independently addressable). The origin's
`deploy/service.yaml` (NodePort 30820) is untouched.

`deploy/public/Caddyfile` — TLS + gateway `rate_limit` for the NEW China-facing
domain (not `lawbench.finddatatech.cloud`). Per-IP throttle (10 rps, burst 20 —
mirrors the in-process defaults so both layers agree). `/healthz` is exempt at
the gateway too (mirrors the in-process `_EXEMPT_PATH`). Requires the Caddy
`rate_limit` module; if your build lacks it, drop the block and rely on the
in-process limiter (`RATE_LIMIT_ENABLED=1`).

### 4.1 DNS-hardening block (conditional — task 6.2)

The origin's `deploy/deployment.yaml` carries `dnsPolicy: None` + kube-dns-only
`dnsConfig` + `hostAliases` pinning `auth.finddatatech.cloud` →
`124.220.7.175` (chengsi nginx → xinru fd-logto) and
`lawbench.finddatatech.cloud` → `103.236.89.212` (cheap1's Caddy edge; the origin
moved to the cheap cluster on 2026-08-31). This block is **load-bearing on a
polluted node** (one whose resolv.conf inherited the wildcard
`mesh.finddata.cn` search domain — every name resolves to `8.218.137.223`,
so `postgres.postgres.svc.cluster.local` hangs at `connect()` →
CrashLoopBackOff).

Replicate the `dnsPolicy: None` + `dnsConfig` block **verbatim on the China pod
ONLY IF the China box is itself a k3s node inheriting that polluted resolv.conf.**
On a box with clean DNS, delete the block (use the default
`dnsPolicy: ClusterFirst`) — do NOT carry origin-specific pins onto clean infra,
and do NOT strip them blindly on a polluted node.

**The `hostAliases` are NOT replicated.** The origin pins Logto/Lawbench
because its fail-closed auth boot path must reach Logto JWKS. The public pod has
NO Logto dependency, so those pins are intentionally absent here. If the China
box needs a host pin for its OWN MinIO/Postgres endpoints (e.g. a bare-IP China
MinIO with no DNS), add a `hostAliases` entry for *that* endpoint; otherwise
leave it off. See `prod-deploy-dns-pollution-fix` memory for the root-cause
analysis.

## 5. Key issuance & revocation flow

Keys are **issued on the origin only** — `create_public_app()` deliberately does
NOT mount the `auth` router, so `/auth/*` (OIDC login) and `/api/keys`
(issue/list/revoke) are `404` on the public pod (asserted by
`tests/test_public_app.py`). The operational flow:

1. **Issue (origin):** an operator browser-logs into the origin
   (`lawbench.finddatatech.cloud`) via the Logto OIDC flow, then
   `POST /api/keys { label, scopes }`. The `api_keys` row is written to the
   origin Postgres with a salted `pbkdf2_sha256` hash; the **plaintext key
   (`lbk_…`) is shown exactly once** in the response and never persisted or
   logged.
2. **Replicate (origin → China):** the `api_keys` row — including the
   `revoked_at` soft-delete column — travels to the China replica via the
   Postgres logical replication established in §2 (it is in the publication's
   `FOR TABLE` list). Seconds in steady state; minutes under GFW pressure.
3. **Hand off (out-of-band):** the operator hands the plaintext key to the
   China caller over a side channel (email, vault, etc.). The caller presents
   it as `X-API-Key: lbk_…` to the public pod, which verifies it by looking up
   the 16-char prefix in the replicated `api_keys` table and checking the
   slow-hash + `revoked_at IS NULL`.
4. **Revoke (origin):** `POST /api/keys/{id}/revoke` sets `revoked_at` on the
   origin row; the update replicates to the China replica, so the key stops
   authenticating on the public pod within the replication lag window. No
   out-of-band revocation call to the China box is needed.

The public pod never stores, logs, or displays plaintext keys — it only
verifies the slow-hash against the replicated row. Key management (issuance +
revocation) is a **single origin-side control plane**; the China box is a
read-only verifier.

## 6. Rate limiting

The public pod runs the in-process token-bucket limiter (`src/web/rate_limit.py`)
gated by `RATE_LIMIT_ENABLED=1` (dormant on the origin). Tuning:
`RATE_LIMIT_RPS` (sustained refill, default 10), `RATE_LIMIT_BURST` (bucket
capacity, default 20). `/healthz` is exempt so probes never 429 a healthy pod.
A gateway-level Caddy `rate_limit` is the preferred production posture; the
in-process limiter is the no-gateway fallback.

## 7. Standing-constraint checklist

These invariants must hold on the public pod exactly as they hold on the origin.
Verified at build/test time in `tests/test_public_app.py` +
`tests/test_apikey_readonly.py` + `tests/test_rate_limit.py`; re-check after any
change to the public factory or auth path.

- [x] **Auth is fail-closed.** `check_public_auth_config()` runs at startup
      (`create_public_app` `@app.on_event("startup")`) and raises `ConfigError`
      if `AUTH_SESSION_SECRET` is unset **or** `database_url` is empty — the pod
      refuses to bind rather than run as an open server. Mirrors the origin's
      `check_auth_config()` (which additionally requires `LOGTO_*`); the public
      pod's smaller required set reflects its no-Logto posture, but the
      fail-closed guarantee is identical.
- [x] **API keys are salted slow-hash; plaintext shown once, origin only.**
      `lbk_…` keys are `pbkdf2_sha256`-hashed with a per-row salt in the
      `api_keys` table; the plaintext is returned by `POST /api/keys` on the
      **origin** exactly once and never persisted/logged. The public pod only
      *verifies* (prefix lookup + slow-hash compare + `revoked_at IS NULL`) — it
      has no key-issuance route (`/api/keys` → 404) and never sees plaintext
      beyond the incoming `X-API-Key` header, which it does not store.
- [x] **No password storage / no `users` table.** Identity is fully delegated
      to Logto on the origin (OIDC); the public pod has no Logto dependency and
      no identity store of any kind. No `password`/`password_hash` column, no
      `users` table, anywhere in the public pod's code path.
- [x] **DNS block replicated (not stripped) on a polluted-node China box.**
      `deploy/public/deployment.yaml` carries the `dnsPolicy: None` +
      kube-dns-only `dnsConfig` block **verbatim** from the origin, with a
      load-bearing comment: keep it ONLY if the China box is a k3s node inheriting
      the `mesh.finddata.cn` pollution; on clean DNS, delete the block (default
      `ClusterFirst`) — do NOT strip blindly on a polluted node (the origin pod
      CrashLoopBackOff'd without it). The `hostAliases` (Logto/Lawbench pins)
      are intentionally NOT replicated — the public pod has no Logto dependency;
      add a `hostAliases` entry only for the China box's OWN bare-IP endpoints.
- [x] **`/healthz` exempt from auth AND rate limiting.** `get_current_user`
      short-circuits `/healthz` (exact) + `/auth/*` (prefix); the rate-limit
      middleware short-circuits `_EXEMPT_PATH = "/healthz"`. So liveness/readiness
      probes never get 401/429 on a healthy pod — k8s will not restart a healthy
      pod for its own throttle. Verified by `test_healthz_exempt_when_over_limit`
      and `test_healthz_open_without_creds`.
- [x] **Origin behavior is byte-for-byte unchanged.** Every public-pod
      addition is env-gated or additive: `MINIO_PUBLIC_*` falls back to
      `MINIO_*` when `MINIO_PUBLIC_HOST` is unset; `RATE_LIMIT_ENABLED`
      defaults to `"0"` (middleware not registered); `READONLY_REPLICA`
      defaults to `"0"` (best-effort `last_used_at` write preserved); the
      public factory is a separate module (`public_app.py`) — `app.py` and its
      11-router mount are untouched. The origin image runs `create_app()`
      when `PUBLIC_API` is unset/`0`.
