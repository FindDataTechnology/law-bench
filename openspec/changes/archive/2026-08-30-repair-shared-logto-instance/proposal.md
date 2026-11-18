# Proposal: repair-shared-logto-instance

## Why

The shared Logto instance (`idp-logto`, serving `auth.token118.com` for law-bench, NewAPI,
and — since `swap-mcp-registry-idp-to-logto` — the AI Gateway & Registry) fails interactive
password sign-in systemically: verification returns 422 `invalid_credentials` even for
password hashes that verify correct using Logto's own argon2 library (confirmed for both a
freshly created user and a pre-existing user), with intermittent 500s and hung token grants
that only a container restart temporarily clears. The instance also shows drift markers: an
unpinned `svhd/logto:latest` image, no `_logto_alterations` bookkeeping table in the
database, and an invalid secret on the built-in Management API M2M app (`m-default`).
Any consumer that needs a human login — including finishing the gateway cutover
(tasks 5.1/5.2 of the swap change) — is blocked by this.

## What Changes

- Back up the Logto database (pg_dump) before any repair action.
- Pin the `idp-logto` image to an explicit version (digest-pinned from the currently
  running container, or a chosen stable release), replacing the drifting `latest` tag in
  `/opt/tokenvault-idp/docker-compose.yml`.
- Run Logto's official CLI database-alteration check/deploy and sign-in-experience seed
  (`cli db alteration deploy latest`, `cli db seed -- --swe` if indicated) so schema and
  bookkeeping state match the running version; reconcile the missing alterations table.
- Repair or formally retire the broken `m-default` Management API M2M secret so the
  supported management path works again.
- Verify the full interactive path end-to-end: password sign-in for the `admin` user on
  the gateway app (finish swap tasks 5.1/5.2), law-bench login redirect, NewAPI OIDC
  entry, and admin console reachability.
- Document the repaired posture (pinned version, backup location, verification steps) in
  the deploy notes.

No data migration of users is planned; existing users (including `gwadmin00001` created
during the gateway cutover) remain.

## Capabilities

### New Capabilities
- `shared-logto-idp`: observable behavior of the shared Logto identity provider at
  auth.token118.com — password sign-in succeeds for any valid credential on any tenant
  app, OIDC discovery/token grants are stable across restarts, the database schema
  matches the running release via tracked alterations, the image version is pinned, and
  the management API path is functional.

### Modified Capabilities

## Impact

- **Systems**: america box `/opt/tokenvault-idp` compose project (logto service), the
  `logto` Postgres database (schema alterations + backup), and briefly every consumer
  that redirects to Logto (law-bench, NewAPI, mcp.token118.com) during container
  recreation.
- **Dependencies**: none added; the running release is pinned rather than upgraded unless
  the alteration check proves the current schema predates the running version, in which
  case alterations deploy forward (no version downgrade).
- **Risk containment**: full DB backup + image digest recorded before changes; rollback =
  restore dump and restart on the pinned image.
- **Unblocks**: `swap-mcp-registry-idp-to-logto` tasks 5.1/5.2 (gateway interactive login).
- **Known non-issue**: external reachability flakiness of the legacy host
  `logto.tokenvault.vip` is network-level (server-side hairpin serving 200) and stays a
  noted follow-up for when law-bench/NewAPI are repointed.
