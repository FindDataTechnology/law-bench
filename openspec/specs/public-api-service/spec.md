# public-api-service Specification

## Purpose

A standalone, China-deployed, read-only FastAPI service that mounts a *subset* of the law-bench web app's existing routers behind API-key-only authentication plus gateway rate limiting, reading from a Postgres read-replica and a synced MinIO corpus. It has no Logto dependency and no write/admin/generation routes. It exists so callers in China can reach the read surface without per-request cross-border DB hops, and so a compromised key or a GFW-induced outage on the China box cannot reach the generation/admin paths on the origin.

## Requirements

### Requirement: Standalone public app factory

The system SHALL provide a `create_public_app()` factory (e.g. `src/web/public_app.py`) that constructs a FastAPI instance mounting *only* the read-heavy router subset: `contract_context`, `contracts`, `samples`, `search`, `law_info`, and the read paths of `clauses`. The factory SHALL NOT mount the `api` (CRUD), `generation` (modes D/E/F/G), `dashboard`, `pages` (HTML chrome), or `auth` (OIDC + `/api/keys`) routers. The factory SHALL apply the same constructor-level `dependencies=[Depends(get_current_user)]` as the origin app so every mounted route inherits auth. The factory SHALL disable the auto-generated docs surface by passing `docs_url=None`, `redoc_url=None`, and `openapi_url=None` to the `FastAPI(...)` constructor. A `/healthz` route identical to the origin's SHALL be included.

#### Scenario: Only the read-heavy router subset is mounted

- **WHEN** `create_public_app()` is called and the resulting app's routes are enumerated
- **THEN** the mounted paths include `/api/contracts`, `/api/contracts/{contract_type}` and its sub-paths, `/samples`, `/api/search`, `/law-info`, and `/clauses`, and do NOT include `/api/rubrics`, `/api/prompts`, `/api/compare`, `/api/evaluate`, `/api/contracts/{type}/generate-batch`, `/api/contracts/{type}/pipeline`, `/api/contracts/{type}/auto-reject`, `/api/contracts/{type}/regenerate-template`, `/api/generation-jobs`, `/dashboard`, `/`, or `/auth/*`

#### Scenario: Constructor-level auth still applies

- **WHEN** a request arrives at any mounted public route with no `X-API-Key` (and no cookie/Bearer)
- **THEN** the system responds `401` without executing the route handler

#### Scenario: Docs surface is disabled

- **WHEN** `GET /openapi.json`, `GET /api/docs`, or `GET /redoc` is requested against the public app
- **THEN** each responds `404` (the docs routes are not registered)

#### Scenario: Healthz remains reachable unauthenticated

- **WHEN** `GET /healthz` is requested with no credentials
- **THEN** the system responds `200` with `{"status": "ok"}`

### Requirement: Key-only auth posture on the public pod

The public app SHALL resolve caller identity via the `X-API-Key` channel. The session-cookie and Logto-JWKS Bearer resolution paths SHALL remain registered (so the shared `get_current_user` dependency is reused unchanged) but SHALL be effectively dormant on the public pod because no browser login is mounted and the pod is not configured to reach Logto's JWKS across the border. A valid `X-API-Key` SHALL authenticate the request; an absent key (with no other credential) SHALL yield `401`, **with exactly one exemption: the overview route(s) mounted by `bench-public-overview` (精确路径 `/api/public/overview`) MAY be registered in the app's exempt-path mechanism and reached anonymously; the exemption SHALL NOT cover sibling paths, prefixes, or wildcards, and absent/broken exemption registration SHALL fail closed to 401**. Key *issuance* (`POST /api/keys`) SHALL NOT be available on the public pod — keys are issued on the origin and handed to China callers out-of-band; the public pod only *verifies* them.

#### Scenario: Valid API key authenticates a public request

- **WHEN** a request to `GET /api/contracts/sale` carries `X-API-Key: lbk_<valid>` and no cookie/Bearer
- **THEN** the system resolves the identity from the API key and the request proceeds without `401`

#### Scenario: Missing key is rejected

- **WHEN** a request to `GET /api/contracts/sale` carries no `X-API-Key` and no cookie/Bearer
- **THEN** the system responds `401` with a JSON body `{"error": "authentication required"}`

#### Scenario: Key issuance is not reachable from the public pod

- **WHEN** `POST /api/keys` is requested against the public app (even with a valid existing key)
- **THEN** the system responds `404` (the `auth` router carrying `/api/keys` is not mounted)

#### Scenario: Overview exemption is the only anonymous path

- **WHEN** a request without any credential hits `GET /api/public/overview` versus any sibling path (e.g. `/api/public/overview/x`, `/api/contracts`)
- **THEN** the overview route returns `200` (anonymous, rate-limited per `bench-public-overview`) while every sibling path responds `401`

### Requirement: Gateway rate limiting layered on key auth

The system SHALL enforce per-key rate limiting on the public endpoint in addition to API-key authentication, because a key authenticates but does not throttle. The limit MAY be enforced at the gateway (e.g. Caddy `rate_limit`) or via an in-process middleware; in either case the limit SHALL be keyed on the resolved caller identity (the API-key prefix or user id), not on the source IP alone, so one abusive caller does not starve others sharing a NAT. When the limit is exceeded the system SHALL respond `429 Too Many Requests` with a `Retry-After` header. Authenticated but rate-limited requests SHALL NOT execute the route handler.

#### Scenario: Burst over the limit is throttled

- **WHEN** a caller with a valid `X-API-Key` issues requests in excess of the configured per-key burst within the configured window
- **THEN** the excess requests respond `429` with a `Retry-After` header and the route handler is not invoked for those requests

#### Scenario: Limit is per-key, not per-IP

- **WHEN** two callers with distinct valid keys share the same source IP and both issue requests within the limit
- **THEN** neither is throttled by the other's traffic (the limit bucket is keyed on the caller identity, not the IP)

### Requirement: Read-replica data source

The public pod SHALL read contract/clause/rubric/artifact metadata from a Postgres read-replica that is local to the China box, not from the origin's Postgres across the border. The replica SHALL be fed by PostgreSQL logical replication (`CREATE PUBLICATION` on the origin / `CREATE SUBSCRIPTION` on the China replica) covering at least the tables the public routes read: `clauses`, `contract_artifacts`, `rubrics`, `criteria`, `prompts`, `tag_dims`, and `api_keys`. The `api_keys` table is replicated so the public pod can *verify* keys locally; key *issuance* (writes to `api_keys`) happens only on the origin and propagates via replication. The public pod SHALL treat its Postgres as read-only for application traffic — it SHALL NOT issue writes except the best-effort `last_used_at` touch (see the modified `web-auth` requirement), and that touch SHALL NOT be required for the request to succeed.

#### Scenario: Per-request reads hit the local replica

- **WHEN** `GET /api/contracts/sale/clauses` is served by the public pod
- **THEN** the backing query executes against the China-local Postgres replica, not the origin Postgres (no per-request cross-border connection)

#### Scenario: Newly issued key verifies on the replica

- **WHEN** a key is issued on the origin (`POST /api/keys`) and the replication lag has elapsed
- **THEN** a request carrying that key to the public pod authenticates successfully by verifying against the replicated `api_keys` row

### Requirement: MinIO corpus sync for download paths

The public pod's `samples` and `contracts` download paths (`GET /api/contracts/artifacts/{id}/download`) SHALL serve DOCX/PDF artifacts from a China-local MinIO (or a mirrored bucket), not from the origin MinIO at `23.144.68.246:30900` per-request. A sync job (cron or sidecar) SHALL copy new and changed artifacts from the origin bucket to the local bucket on a schedule. A download request for an artifact not yet synced SHALL respond `404` (never proxy back to the origin MinIO from the public pod).

#### Scenario: Download serves from local MinIO

- **WHEN** a request to `GET /api/contracts/artifacts/{id}/download?format=docx` arrives at the public pod for an artifact that has been synced
- **THEN** the bytes are streamed from the China-local MinIO, and no connection is made to the origin MinIO for that request

#### Scenario: Not-yet-synced artifact is 404, not proxied

- **WHEN** a download request arrives for an artifact whose object key is absent in the local MinIO (replication lag or sync gap)
- **THEN** the public pod responds `404` and does NOT attempt to fetch the object from the origin MinIO

### Requirement: Public pod deployment manifest with DNS hardening

The system SHALL ship a deployment manifest under `deploy/public/` for the China pod. When the China box is itself a k3s node whose host `resolv.conf` carries a wildcard search domain that resolves `.svc.cluster.local` names to a black-hole IP, the manifest SHALL replicate verbatim the DNS hardening from `deploy/deployment.yaml`: `dnsPolicy: None`, a `dnsConfig` block naming only the cluster kube-dns IP with the clean 3-domain search list and `ndots: 5`, and `hostAliases` pinning any external hostnames the pod must reach to their IPs. When the China box is a plain host with clean DNS, this block is omitted. The manifest SHALL load auth/DB/MinIO secrets from Kubernetes secrets (not inline env), SHALL expose a `/healthz` liveness/readiness probe, and SHALL NOT mount the initContainer that seeds `evaluation_rules.db` from the image (the public pod reads Postgres, not the SQLite file).

#### Scenario: Polluted-node DNS block is replicated

- **WHEN** the China box is a k3s node with the `mesh.finddata.cn` wildcard search domain
- **THEN** the public pod manifest includes `dnsPolicy: None`, a `dnsConfig.nameservers` entry pointing only at the cluster kube-dns, the 3-domain `searches` list, and `hostAliases` for any hostnames the pod reaches — and the pod starts without hanging on `psycopg.connect()`

#### Scenario: Clean-node manifest omits the DNS block

- **WHEN** the China box is a plain host with a clean `resolv.conf`
- **THEN** the manifest does not include the `dnsPolicy`/`dnsConfig`/`hostAliases` block (it is unnecessary and would reference the wrong kube-dns IP)

#### Scenario: SQLite seed initContainer is not mounted

- **WHEN** the public pod manifest is applied
- **THEN** there is no `seed-db` initContainer copying `evaluation_rules.db` into a PVC, because the public pod does not read SQLite

### Requirement: Fail-closed auth startup on the public pod

The public app SHALL refuse to serve if its auth configuration is unset. On startup it SHALL invoke `check_auth_config()` (or an equivalent readiness check) and SHALL NOT bind if the required auth environment (`AUTH_SESSION_SECRET` at minimum, so the shared cookie-signing path does not fail open) is missing. The pod's liveness/readiness probe SHALL report not-ready until the app is bound and auth-verified. This preserves the origin's fail-closed posture: the public pod never runs as an open server even if its env is misconfigured.

#### Scenario: Missing auth env prevents startup

- **WHEN** the public pod starts with `AUTH_SESSION_SECRET` unset
- **THEN** the process refuses to bind, the readiness probe fails, and no request is served

#### Scenario: Auth env present allows startup

- **WHEN** the public pod starts with the required auth environment set
- **THEN** the process binds, `/healthz` returns `200`, and protected routes enforce `401` without credentials
