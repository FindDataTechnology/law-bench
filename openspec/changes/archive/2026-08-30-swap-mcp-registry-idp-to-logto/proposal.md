# Proposal: swap-mcp-registry-idp-to-logto

## Why

The AI Gateway & Registry at `mcp.token118.com` (agentic-community/mcp-gateway-registry,
deployed at `/opt/mcp-gateway-registry` on the america box, 23.144.68.246) carries its own
Keycloak realm plus a dedicated Keycloak Postgres just to authenticate a handful of users,
while the box already runs a shared Logto (`idp-logto`) that law-bench and NewAPI use as
their single login system. Consolidating on Logto removes two containers, one admin surface,
and one set of user credentials. The registry currently holds 1 built-in server, 0 agents,
0 skills, and ~zero users — there is no cheaper moment to swap identity providers.

## What Changes

- Add a `logto` authentication provider to the gateway's auth-server: a
  `providers/logto.py` class (JWKS + issuer + audience verification, fail-closed id_token
  chokepoint preserved), a `logto:` entry in `oauth2_providers.yml`, and a factory branch
  in `providers/factory.py`. Rebuild the `auth-server` image (self-built via
  `build_and_run.sh`).
- Switch `AUTH_PROVIDER=keycloak` → `AUTH_PROVIDER=logto` with new `LOGTO_*` env vars
  (external URL, internal URL, client id/secret, M2M client id/secret, claims mapping).
- Adopt the already-migrated Logto endpoint `auth.token118.com` (ENDPOINT env,
  Caddy site block, and DNS were completed ahead of this change during the broader
  tokenvault.vip → token118.com migration; verified live). `logto.tokenvault.vip`
  stays live in Caddy as the legacy host until law-bench and NewAPI are repointed
  (follow-up, out of scope).
- Register in Logto: a traditional-web application for the gateway login (redirect URI
  `https://mcp.token118.com/oauth2/callback/logto`) and a machine-to-machine application
  replacing the Keycloak M2M client; emit a `groups` claim via Logto custom JWT so the
  registry's group→scope mappings keep working.
- Join Docker networks: the `auth-server` compose service attaches the external
  `tokenvault-idp_default` network and calls Logto internally at
  `http://idp-logto:3001/oidc/*` (mirrors the internal/external URL split Keycloak uses).
- Retire the `keycloak` and `keycloak-db` compose services after cutover verification.
- Update the admin-automation runbook: M2M token minting moves from the Keycloak
  client-credentials script to the Logto M2M application (same client_credentials flow,
  new endpoint and credentials).

No registry data (servers/agents/skills catalog, Mongo) is touched; sessions and
auth-server-minted HS256 API tokens are IdP-agnostic and survive the swap. User identity
(`sub`) changes for the bootstrap admin user — acceptable while the registry is empty.

## Capabilities

### New Capabilities
- `mcp-gateway-auth`: authentication behavior of the AI Gateway & Registry at
  mcp.token118.com — interactive login via Logto OIDC (authorization code + PKCE,
  fail-closed id_token verification), group→scope authorization fed by the Logto
  groups source (roles), machine-to-machine access via a Logto M2M application
  (client_credentials validated against Logto JWKS), and the auth.token118.com endpoint
  posture (legacy logto.tokenvault.vip kept alive).

### Modified Capabilities
<!-- None — no existing law-bench spec covers this deployment; all existing specs are untouched. -->

## Impact

- **Systems**: america box (23.144.68.246) — `/opt/mcp-gateway-registry` compose stack
  (auth-server rebuilt; keycloak/keycloak-db retired), Caddy config (new
  `auth.token118.com` site), DNS (token118.com zone), Logto instance (endpoint config +
  two new applications + custom JWT claim).
- **Code**: upstream `auth_server/providers/{logto.py,factory.py}` +
  `oauth2_providers.yml`, tracked as a local patch on the box (upstream PR optional,
  follow-up). Deployment runbook notes live in this repo's `deploy/` area.
- **Automation**: the M2M minting script used for registry administration changes
  endpoint/credentials only.
- **Rollback**: `.env` + compose backup before cutover; revert = restore env, restart
  stack with Keycloak services re-enabled (Keycloak volumes are retained until the
  change is archived).
- **BREAKING**: interactive users must re-login (new IdP session); the Keycloak-issued
  M2M credentials stop working at cutover.
