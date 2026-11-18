# AI Gateway & Registry auth posture (Logto) — historical + current

Change: `swap-mcp-registry-idp-to-logto` + `repair-shared-logto-instance` (openspec).

**The america box (23.144.68.246) and the entire token118.com domain family are
retired (2026-09-09).** This file is kept as the historical record of the
america-era Logto wiring. The live stack is documented in
`deploy/cheap-box/README.md`; what follows is the current shared-IdP picture and
the america-era constants for reference.

## Current identity provider (shared, production)

- **Logto runs as docker containers on guangzhou-xinru** (134.175.46.69 /
  tailscale 100.64.0.3): `fd-logto`, `fd-postgres`, `fd-redis`. Container created
  2026-08-22; env `ENDPOINT=https://auth.finddatatech.cloud`,
  `ADMIN_ENDPOINT=https://auth-admin.finddatatech.cloud`, `TRUST_PROXY_HEADER=1`.
- **Public endpoint:** `https://auth.finddatatech.cloud` (issuer
  `https://auth.finddatatech.cloud/oidc`, ES384). Served by nginx + certbot on
  chengsi (124.220.7.175) proxying to `100.64.0.3:3001` (fd-logto); Admin Console
  SPA at `https://auth-admin.finddatatech.cloud` → `:3002`.
- **DB:** `fd-postgres`, database `logto`, user `fd`
  (`sudo docker exec fd-postgres psql -U fd -d logto`).
- **Admin console login:** user `finddata`.
- **API resource for M2M tokens:** `https://mcp.finddatatech.cloud/api` (Logto
  requires `resource` on client_credentials).
- **Admin authorization:** Logto role `registry-admins` (default tenant) → gateway
  maps `roles` claim (userinfo) to groups → Mongo `mcp_scopes_default.registry-admins`.

## America-era constants (dead, recorded for history)

| Item | Value |
|---|---|
| Public endpoint | `https://auth.token118.com` (dead) |
| Web app | `mcpgatewayweb` — redirect `https://mcp.token118.com/oauth2/callback/logto` |
| M2M app | `mcpgatewaym2m` |
| API resource | `https://mcp.token118.com/api` |
| Gateway admin user | `mcpadmin` / `mcpadmin@token118.com` |

## Machine-to-machine access (automation, current)

```sh
curl -u "<mcp-gateway-m2m-app-id>:<secret>" \
  -d 'grant_type=client_credentials&resource=https%3A%2F%2Fmcp.finddatatech.cloud%2Fapi' \
  https://auth.finddatatech.cloud/oidc/token
# → access_token (ES384 JWT, 1h) → Authorization: Bearer <token> on https://mcp.finddatatech.cloud/api/*
```

## Registry usage

The registry's first registered server is law-bench (change
`expose-lawbench-mcp-via-gateway`): see `mcp-gateway-registration.md` for the
deployment, registration, and M2M-scope details.
