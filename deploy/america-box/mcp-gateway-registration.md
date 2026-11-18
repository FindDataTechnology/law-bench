# law-bench on the AI Gateway & Registry (mcp.token118.com)

Change: `expose-lawbench-mcp-via-gateway` (openspec). The law-bench MCP server
(`fd-coding-law-bench-mcp`, 52 tools) serves streamable HTTP from a dedicated pod
in the `law-bench` k8s namespace and is registered — non-public — in the AI
Gateway & Registry at `https://mcp.token118.com` (america box, `/opt/mcp-gateway-registry`).

Sibling runbook: [mcp-gateway-skills.md](mcp-gateway-skills.md) — the gateway's
*skills* catalog (URL-referenced SKILL.md entries) is operated separately, with the
same Logto M2M credential source (`/root/.mcp_logto_creds`).

```
MCP client ──► https://mcp.token118.com/law-bench/mcp          (gateway: Logto authn, group scopes)
                 │ nginx (auth_request /validate) → auth-server /mcp-proxy/law-bench/
                 ▼
              http://23.144.68.246:30840/mcp                   (NodePort 30840, X-API-Key guard)
                 │
                 └─ law-bench-mcp pod (ns law-bench, image sha-mcphttp1, MCP_HTTP_TRANSPORT=http)
```

Two credentials, different roles:

| Credential | Presented by | Checked by | Purpose |
|---|---|---|---|
| Logto identity (browser session, gateway API token, or M2M JWT) | MCP client → gateway | nginx `/validate` (+ Logto JWKS) | WHO you are at the gateway; scopes from groups via Mongo `mcp_scopes_default` |
| Shared backend token (`MCP_HTTP_TOKEN`, k8s secret `law-bench-mcp`) | MCP client → backend, as `X-API-Key` or `Authorization: Bearer` | law-bench MCP `_TokenGuard` (fail-closed) | backend authn; the gateway does NOT inject it — clients carry it |

The proxy hop strips the client's `Authorization` before reaching the backend,
so the two never collide. Direct (non-gateway) clients hit NodePort 30840 with
`X-API-Key` or a bearer header.

## Registration state (2026-08-30)

- Catalog entry: `/law-bench`, `deployment=remote`, `transport=streamable-http`
  (default `supported_transports`), `proxy_pass_url=http://23.144.68.246:30840/mcp`,
  `auth_scheme=api_key` (`auth_header_name=X-API-Key`), visibility
  **`group-restricted`** with `allowed_groups=registry-admins` — absent from the
  anonymous ARD catalog, usable by gateway users carrying the `registry-admins` group.
- Backend serves 52 tools (fastmcp 3.4.7); health checks green (registry decrypts
  the stored credential for its own health prober — the only server-side use).

## Known issue: login button → localhost:8888 (hotfix 2026-08-31)

The login page fetches `auth_server_url` from `/api/auth/config`; if that fetch fails
(e.g. during an auth-server restart), the frontend falls back to
`http://localhost:8888`, and the "Continue with Logto" button then navigates the
user's browser to their own machine — the click appears to do nothing and never
reaches the control panel. Hotfix applied 2026-08-31 (root cause: dev default baked
into upstream `frontend/src/pages/Login.tsx`):

- **Bundle hotfix (lost on container recreation)**: both `'http://localhost:8888'`
  literals in `/app/frontend/build/static/js/index.BpTler7s.js` inside the registry
  container were replaced with `window.location.origin`:
  `sed -i 's|\`http://localhost:8888\`|window.location.origin|g' <bundle>` (a
  `.bak-localhostfix` copy sits next to it). Verify with
  `grep -c localhost:8888 <bundle>` → 0.
- **Source fix (persists)**: `/opt/mcp-gateway-registry/frontend/src/pages/Login.tsx`
  lines ~44 and ~79 now use `window.location.origin` — included in the next image
  build. Re-apply the bundle hotfix after any container recreation until then.

The whole login chain (gateway 302s → Logto authorize/sign-in → callback → session)
was verified healthy end to end on 2026-08-31 with a real browser round trip.


## Register / update / remove / verify

All registry management calls authenticate with the Logto M2M application
(`mcpgatewaym2m`; secrets in `/root/.mcp_logto_creds`, 0600):

```sh
# on the america box
set -a; source /root/.mcp_logto_creds; set +a
export MCP_HTTP_TOKEN=$(kubectl -n law-bench get secret law-bench-mcp \
    -o jsonpath='{.data.MCP_HTTP_TOKEN}' | base64 -d)

# register (idempotent-enough: on a conflict, remove first, re-register)
python3 /root/register_mcp_gateway.py register

# catalog + state (enabled flag matters: new registrations start disabled)
python3 /root/register_mcp_gateway.py show

# enable/disable (toggle needs an explicit new_state)
TOKEN=$(python3 - <<'EOF'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('rmg', '/root/register_mcp_gateway.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._mint_m2m_token(os.environ.get('LOGTO_M2M_APP_ID','mcpgatewaym2m'),
                        os.environ['LOGTO_M2M_CLIENT_SECRET']))
EOF
)
curl -s -X POST https://mcp.token118.com/api/servers/toggle \
  -H "Authorization: Bearer $TOKEN" -d "path=/law-bench" -d "new_state=true"

# remove (full rollback = this + delete the k8s deployment/service)
python3 /root/register_mcp_gateway.py remove --yes
```

The script source of truth is `scripts/infra/register_mcp_gateway.py` in the
law-bench repo; the copy at `/root/register_mcp_gateway.py` is uploaded from it.

## End-to-end verification

```sh
# 1. backend direct (NodePort): unauthenticated must 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://23.144.68.246:30840/mcp \
  -H "Content-Type: application/json" -d '{}'          # → 401

# 2. gateway anonymous must 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://mcp.token118.com/law-bench/mcp \
  -H "Content-Type: application/json" -d '{}'          # → 401

# 3. anonymous ARD catalog must not list law-bench
curl -s "https://mcp.token118.com/.well-known/mcp-servers" | grep -c law-bench   # → 0

# 4. full MCP session through the gateway (52 tools) — uses the law-template
#    image's fastmcp client
#    (see scripts in this session's runbook or use any MCP client with
#     Authorization: Bearer <gateway identity> + X-API-Key: <MCP_HTTP_TOKEN>)
```

An interactive user connects the same way: browser login at `mcp.token118.com`
(must be in the `registry-admins` Logto role), fetch the connect config for
`/law-bench`, and point their MCP client at `https://mcp.token118.com/law-bench/mcp`
with the shared backend token as `X-API-Key`.

## Deployment shape (k8s, ns law-bench)

- `deploy/mcp-deployment.yaml` (repo): Deployment `law-bench-mcp` + NodePort
  Service `30840`. Same image as the origin web pod; the container command is
  overridden to `python -m fd_coding_law_bench_mcp` with `MCP_HTTP_TRANSPORT=http`
  (port 8080). `docker-entrypoint.sh` untouched.
  The MCP package reaches the interpreter one of two ways: baked into `/app/.venv`
  by the Dockerfile (`uv pip install /deps/lawbench-mcp`) when the image was built
  with that context, or — as on the cheap cluster, where `sha-2c502d7` was not —
  via a node-local `--target` install mounted in and prepended to `PYTHONPATH`
  (see `deploy/cheap-box/README.md`).
- Probes are `tcpSocket` (every HTTP path requires the token, so httpGet would
  always 401).
- Secrets: `law-bench-mcp` (`MCP_HTTP_TOKEN`), plus the origin's
  `law-bench-db` / `law-bench-minio` / `law-bench-judge` (MCP tools write to the
  origin primary — this is intentional, unlike the read-only China public pod).
- Rollback: `kubectl -n law-bench delete deploy law-bench-mcp svc law-bench-mcp`
  + remove the registry row (above). Origin/public pods are untouched by all of it.

## Image rebuild (Windows checkout → box)

```sh
# from the repo root (only the paths the Dockerfile COPYs, CRLF-safe: the
# Dockerfile strips \r from scripts/*.sh at build time)
tar --exclude="__pycache__" -czf /tmp/lawbench-mcp-buildctx.tar.gz \
  src main.py templates db scripts pyproject.toml uv.lock \
  fd-coding-law-bench-mcp/src fd-coding-law-bench-mcp/pyproject.toml Dockerfile
# scp to the box, extract, then:
docker build -t 23.144.68.246:30880/law-bench/law-template:sha-<tag> /root/lawbench-mcp-build
docker push  23.144.68.246:30880/law-bench/law-template:sha-<tag>
# bump `image:` in deploy/mcp-deployment.yaml and kubectl apply
```

## Proxy-chain timeout (long tool calls)

The whole proxy chain is one knob: `MCP_PROXY_TIMEOUT` in
`/opt/mcp-gateway-registry/.env` (auth-server inner hop) — nginx renders
`proxy_read_timeout = MCP_PROXY_TIMEOUT + 30s` per MCP location block.
Set to **600** (law-bench pipelines run minutes); nginx shows `630s` for
`/law-bench/`. Requires the variable in BOTH services' compose env lists
(added to `registry` in `docker-compose.prebuilt.yml`; auth-server already had
it). After changing: `docker compose -f docker-compose.prebuilt.yml up -d registry auth-server`.

## Logto M2M authorization (fixed during this change — keep on upgrades)

The gateway derives M2M scopes in two steps, and both were missing/broken:

1. `idp_m2m_clients` (Mongo `mcp_registry`): maps `client_id → groups` when the
   M2M token carries no group claim. Inserted
   `{client_id: "mcpgatewaym2m", groups: ["registry-admins"], enabled: true}`.
2. `auth_server/server.py` scope-mapping branch only recognized
   `["keycloak","entra","cognito","okta","auth0"]` — a Logto-validated token's
   groups were enriched but never mapped to scopes (403 "no scopes configured").
   Fixed by adding `"logto"` to the list at the `map_groups_to_scopes` branch
   (~line 3628) and rebuilding `mcp-auth-server:logto`
   (`docker build -f docker/Dockerfile.auth -t mcp-auth-server:logto .`).

If a registry image upgrade ever resets the auth-server, re-apply the `"logto"`
patch from the box checkout's `auth_server/server.py` (the patch lives in the
on-box branch, tracked as part of the `swap-mcp-registry-idp-to-logto` local
patch set) and rebuild.

## Token rotation

```sh
# 1. new backend token
kubectl -n law-bench create secret generic law-bench-mcp \
  --from-literal=MCP_HTTP_TOKEN="$(openssl rand -hex 32)" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n law-bench rollout restart deploy/law-bench-mcp
# 2. re-register so the registry stores the new credential
python3 /root/register_mcp_gateway.py remove --yes
python3 /root/register_mcp_gateway.py register
```

## Follow-ups (out of scope here)

- Public visibility with a curated read-only tool subset (registry virtual
  servers) — before any public exposure.
- Repoint law-bench/NewAPI Logto endpoints to `auth.token118.com` (existing
  follow-up from the Logto swap).
