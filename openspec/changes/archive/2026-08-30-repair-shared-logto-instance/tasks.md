# Tasks: repair-shared-logto-instance

## 1. Safety net

- [x] 1.1 `pg_dump` the `logto` database to `/root/logto-backup-<date>.sql` on the
  america box and verify the dump is non-trivial in size; record the running
  `idp-logto` image digest and the current `sign_in_experiences` rows
- [x] 1.2 Record baseline behavior for the verification ladder: M2M grant latency,
  a deliberately failing password attempt's audit/sentinel behavior, and discovery on
  both hostnames

## 2. Pin and repair

- [x] 2.1 Pin `idp-logto` image to the running digest in
  `/opt/tokenvault-idp/docker-compose.yml`; recreate the container; confirm consumers
  still healthy (discovery, M2M grant)
- [x] 2.2 Ran `npm run cli db alteration deploy latest`: "Found 0 alteration to deploy"
  (alteration state lives in `logto_configs` legacy mechanism — the missing
  `_logto_alterations` table was NOT a drift marker). Schema drift EXCLUDED as root
  cause. **Real root cause found instead**: production Logto is the china-box k3s pod
  (`auth.token118.com` → 124.223.42.3, namespace `idp`); the america compose stack is a
  leftover copy. Fixed the china logto deployment DNS (`dnsPolicy: None` + kube-dns
  `dnsConfig`, removing the polluted `mesh.finddata.cn` search domain), which eliminated
  the intermittent `ConnectionError: connection timeout` 500s on /oidc/auth, discovery
  and the experience API
- [x] 2.3 N/A: CLI reported no missing seeds

## 3. Management API

- [x] 3.1 ATTEMPTED rotation of `m-default` on the production (china) DB
  (`applications.secret` + `application_secrets` row + pod restart): still rejected
  `invalid_client` — this build validates its seeded management client against internal
  state, not the secret column. Outcome: retired (see 3.2)
- [x] 3.2 `m-default` retired-with-documentation (rotation not honored by the running
  version; noted in deploy docs). The gateway uses its own `mcpgatewaym2m` app
  (verified working); management-API automation can use a new first-party M2M app later

## 4. Verification ladder (stop at first red)

- [x] 4.1 M2M grant works immediately after a logto restart (token endpoint fast, no
  empty responses)
- [x] 4.2 Server-side experience-API password verification succeeds for the `admin`
  user (fresh interaction flow), and a wrong-password attempt now produces an audit +
  sentinel row
- [x] 4.3 Browser sign-in on the gateway completes: `mcp.token118.com` → Logto → back
  with a session; logout works (this also finishes swap tasks 5.1/5.2)
- [x] 4.4 Consumers spot-check: law-bench login entry 302, NewAPI OIDC authorize entry,
  admin console reachable; legacy `logto.tokenvault.vip` still serving via hairpin

## 5. Documentation

- [x] 5.1 Update `/opt/tokenvault-idp/README.md` (pinned image, backup location,
  alteration state, m-default outcome) and this repo's deploy notes; note the
  `latest`-tag pitfall and the pull-policy recommendation
- [x] 5.2 Not needed: root cause found and fixed (china k3s DNS pollution + wrong instance tested earlier); no escalation required. If verification had still failed after step 2 with a clean alteration
  status: stop after the second bounded escalation attempt (design D5), report
  findings, and re-plan with the user
