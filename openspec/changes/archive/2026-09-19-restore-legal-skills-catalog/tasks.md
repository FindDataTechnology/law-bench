# Tasks: restore-legal-skills-catalog

## 1. Script hardening (design D3, D4)

- [x] 1.1 Add the static collision guard: duplicate `name` values inside `CATALOG`
       abort the script before any network call (`sys.exit` with the offending names)
- [x] 1.2 Add the runtime collision guard in `cmd_register`: before the PUT-update
       branch, resolve the existing entry's source URL (listing field if present,
       else `GET /api/skills/{path}` detail); if it maps to a different upstream than
       the catalog entry, report `COLLISION`, skip the entry leaving the existing one
       untouched, and make the run exit non-zero
- [x] 1.3 Extend `remove` with `--repo` / `--visibility` filters reusing `_select`
       (positional `<name>` behavior unchanged; document that a filter run lists
       targets before deleting)
- [x] 1.4 Sanity-check locally: `python -m py_compile`, `register --dry-run` over the
       full catalog, and a hand-crafted duplicate-name case proving 1.1 fires

## 2. Smoke test against the live cheap gateway (design D6 stage 1)

- [x] 2.1 On cheap1, source M2M creds from `/opt/mcp-gateway-registry/.env`
       (`LOGTO_M2M_APP_ID` / `LOGTO_M2M_CLIENT_SECRET` export mapping), copy the
       script over, strip CRLF, and confirm the API shape: minted token →
       `GET /api/skills` (expect 200, empty or current list), note whether the
       listing exposes the source URL field (feeds 1.2's fast path) and that
       per-skill `visibility`/`allowed_groups` are honored
- [x] 2.2 Throwaway lifecycle test with one real upstream `SKILL.md` URL under a
       scratch name: register → show → remove → show, confirming each observable
       outcome (and the collision guard against the scratch entry) before touching
       the real catalog

## 3. Restore the original 85 (design D1, D6 stage 2)

- [x] 3.1 Run `register` for the public set (律锥 + pa1nrui1; 66 skills) via
       `setsid nohup`, monitor `GET /api/skills?limit=1` `total_count`; investigate
       any FAIL rows before proceeding
- [x] 3.2 Run `register` for the restricted set (cat-xierluo; 19 group skills) and
       confirm each lands with `visibility=group`, `allowed_groups=[registry-admins]`
- [x] 3.3 Re-run the full `register` once and confirm no duplicates (in-place update
       verified) and the collision guard does not fire on legit re-registration

## 4. THUYRan extension (design D2, D6 stage 3)

- [x] 4.1 Walk `THUYRan/Legal-Skills-Chinese`: resolve every `SKILL.md` raw URL,
       verify HTTP 200 + agentskills.io frontmatter + the CC BY-NC-ND 4.0
       declaration per skill; apply the legal-only curation rule; record the exact
       count and any exclusions (license-ambiguous → excluded and noted, not guessed)
- [x] 4.2 Spot-check companion resources (references/ scripts/ templates/) are
       discoverable in each skill's upstream directory
- [x] 4.3 Pin the entries into `CATALOG`: `visibility=group`,
       `allowed_groups=["registry-admins"]`, tags `legal`/`chinese-law`/`thuyran`,
       `metadata.source_repo=THUYRan/Legal-Skills-Chinese`; resolve name clashes with
       the existing 85 by `thuyran-` prefix (original slug/dir kept in metadata);
       re-run the 1.1/1.4 checks
- [x] 4.4 Run `register --repo THUYRan/Legal-Skills-Chinese` and verify: expected
       count added, all group-restricted, total = 66 public + 57 group = 123

## 5. End-to-end verification (design D6, spec scenarios)

- [x] 5.1 From outside the box, list skills via `https://mcp.finddatatech.cloud`
       `/api/skills` with the admin M2M token: confirm 123 entries with the expected
       visibility split and metadata (license, author, source repo, tags)
- [x] 5.2 Fetch one public skill's content through the gateway and confirm it matches
       the upstream `SKILL.md` byte-for-byte (verbatim also asserted on one THUYRan
       skill — NC-ND serve-verbatim requirement)
- [x] 5.3 Confirm restricted skills carry `visibility=group` and are absent from any
       non-authenticated listing surface; note in the runbook that group enforcement
       itself is gateway-side (admin-channel-only verification posture)
- [x] 5.4 Confirm drift posture fields are reported per skill and the re-sync command
       (re-run register) is understood; document, don't deliberately trigger

## 6. Runbook and docs (design D5)

- [x] 6.1 Write `deploy/cheap-box/mcp-gateway-skills.md`: URL-reference model +
       drift detection summary, credential sourcing on cheap1, register/show/remove
       commands (incl. the new `remove` filters), long-batch handling, license policy
       (CC-BY-NC and CC BY-NC-ND: group-restricted, verbatim, authorization-gated
       public promotion with a placeholder authorization-record section), expected
       counts (66/57/123), verification steps
- [x] 6.2 Add the one-line pointer in the cheap-box README gateway section; leave
       `deploy/america-box/**` untouched
- [x] 6.3 `openspec validate restore-legal-skills-catalog --strict` passes; after
       archive + sync, hand-fix the main `mcp-gateway-skills-catalog` spec Purpose
       (still names the retired mcp.token118.com host)
