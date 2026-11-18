# Design: repair-shared-logto-instance

## Context

Diagnosis performed during the gateway cutover (session notes, all verified live):

- Password verification fails for ALL users with 422 `invalid_credentials`, even when the
  stored hash is proven correct by running `hash-wasm`'s `argon2Verify` with the exact
  stored value inside the Logto container (the same library and code path the server
  uses — `build/workers/tasks/argon2i.js` generates, `main-*.js` `isPasswordValid`
  verifies).
- Failed attempts write NO audit (`logs` table) or sentinel rows, and the verification
  endpoint alternates between 422 and uncaught-exception 500s — the request never
  completes the normal pipeline.
- Token grants intermittently hang (0-byte responses until timeout) even for clients
  that worked minutes earlier; a container restart temporarily clears everything.
- Drift markers: `svhd/logto:latest` (unpinned), no `_logto_alterations` table in the
  `logto` database while the image ships alteration scripts, `m-default` management M2M
  secret rejected (`invalid_client`).
- Tenant plumbing is sound: `default` + `admin` tenants, RLS via
  `tenants.db_user = CURRENT_USER`, role memberships correct, both user rows visible
  under the tenant role. The DB user/role is NOT the problem.
- Consumers: law-bench (login redirect healthy), NewAPI (OIDC enabled), gateway
  (fully wired; blocked only on interactive sign-in), admin console (reachable).

The failure pattern — requests short-circuiting before audit/sentinel writes, combined
with schema-bookkeeping absence and a floating image tag — points to schema/behavior
drift between the running code and the database state, rather than any consumer-side
configuration.

## Goals / Non-Goals

**Goals**: make password sign-in work reliably for all tenants' apps; make the instance
reproducible (pinned image, tracked alterations); restore a working management API path;
provide rollback safety via a DB backup.

**Non-Goals**: no version upgrade beyond what alteration-deploy requires; no user data
migration; no changes to consumers (law-bench/NewAPI/gateway configs); no work on the
legacy `logto.tokenvault.vip` host's external reachability (network-level; it serves 200
via hairpin and is slated for retirement); no changes to the gateway auth-server.

## Decisions

### D1 — Backup and pin before touching anything

`pg_dump` the `logto` database and record the running image digest
(`docker inspect --format '{{.Image}}' idp-logto`) before any repair action. Pin the
compose file to that digest (`image: svhd/logto@sha256:…`). Rationale: the repair
(DDL alterations) is destructive-ish and the box's other consumers share this DB;
rollback must be one command.

*Alternative: upgrade to a newer release first* — rejected as the first step; alter the
data to match the code we already run, so behavior changes are attributable to one thing.

### D2 — Repair via the official CLI, not more SQL surgery

Run the pinned image's own CLI: `npm run cli db alteration deploy latest` (and
`cli db seed -- --swe` only if the CLI reports sign-in-experience rows missing). This is
Logto's supported migration path and creates the missing alterations bookkeeping. All
diagnosis-by-SQL this session was read-only or additive (rows we created stay); the
repair itself must go through the tool that owns the schema.

*Alternative: hand-patch tables* — rejected; that's how the drift likely arose.

### D3 — Verification ladder, cheapest first

After each repair step, verify in order: (1) CLI alteration status clean, (2) M2M grant
immediately after a container restart, (3) experience-API password verification for
`admin` (server-side, via a fresh interaction flow), (4) browser sign-in on the gateway,
(5) law-bench + NewAPI + admin-console spot checks. Stop at the first failing rung and
re-diagnose — do not stack changes.

### D4 — Management API: rotate `m-default`, keep the gateway independent

Rotate the `m-default` application secret through the DB (`application_secrets` insert +
`applications.secret` update) or retire-and-document it; the gateway's own M2M app
(`mcpgatewaym2m`) does not depend on it. Rotate rather than delete so Logto's internal
expectations about its seeded management client stay intact.

### D5 — If alterations do not fix it: bounded escalation

If D2 completes clean and password verification still fails, the next suspect is the
running code itself (bad `latest` pull). Escalate by re-deploying the image from a
specific earlier digest (from the box's docker image list history if present) or a
chosen stable upstream tag, repeating D3. Two escalation attempts maximum, then stop and
re-plan with the user — this is a shared production IdP.

## Risks / Trade-offs

- [Alteration deploy rewrites schema on a live shared DB] → full pg_dump backup first;
  alterations run inside the official CLI which is transactional per step; rollback =
  restore dump + restart.
- [Restart downtime hits all consumers] → single restart per step (~10 s), done in one
  maintenance moment; consumers only need Logto at login time.
- [`cli db seed` could overwrite sign-in-experience branding] → run `--swe` only if the
  CLI indicates rows are missing; back up `sign_in_experiences` rows first.
- [Pinned digest drifts from `latest` pull policy] → compose pinned + `pull_policy:
  never` note in deploy docs.
- [Root cause could be outside schema drift (e.g. image bug)] → bounded by D5; the
  backup/pin discipline keeps every experiment reversible.

## Migration Plan

1. Backup: pg_dump `logto` DB → `/root/logto-backup-<date>.sql`; record image digest.
2. Pin: compose `image:` → digest; `docker compose up -d logto` to adopt the pin.
3. Alterations: run `npm run cli db alteration deploy latest` in the container; verify
   the alterations table now exists and matches.
4. Rotate `m-default` secret (D4).
5. Restart; run the D3 verification ladder to green.
6. Update `/opt/tokenvault-idp/README.md` + this repo's deploy notes (pinned version,
   backup path, verification steps); finish swap tasks 5.1/5.2.

Rollback at any step: `docker compose down logto`, restore the dump
(`psql -U idp -d logto < backup.sql`), restore the previous compose image line, restart.
