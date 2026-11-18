# Tasks: catalog-legal-skills-in-gateway

## 1. Verify live API and pin the skill list

- [x] 1.1 On the america box, confirm the deployed gateway's skills API: grep
  `/api/skills` paths + request schemas from `/opt/mcp-gateway-registry/api/openapi.json`
  and `GET /api/skills` with a freshly minted M2M token (expect 200 + empty/current
  list); record exact register/modify/remove endpoint shapes and visibility fields
  (D4 fallback if per-skill group restriction is absent)
- [x] 1.2 Walk the three repos' skills directories (GitHub API or web), resolve each
  candidate `SKILL.md` raw URL, verify HTTP 200 + agentskills.io frontmatter
  (name/description present, license declared); pin the final catalog list with
  per-skill {name, repo, url, license, author, tags, visibility} and drop failures
- [x] 1.3 Spot-check that each pinned skill's companion resources (references/
  scripts/templates) are discoverable in its upstream directory so the gateway's
  auto-discovery has something to find

## 2. Registration automation script

- [x] 2.1 Create `scripts/infra/register_skills_gateway.py` mirroring
  `register_mcp_gateway.py` (stdlib-only; actions `register`/`show`/`remove`; M2M
  client_credentials from `/root/.mcp_logto_creds`; no secrets in the repo), with the
  curated catalog as a Python constant and register doing per-skill
  `POST /api/skills` with metadata + visibility (CC-BY-NC skills
  group-restricted to `registry-admins`)
- [x] 2.2 Implement `show` (list catalog skills with name/visibility/license) and
  `remove <name>` (delete exactly the named skill); make re-registration update in
  place (modify endpoint) rather than duplicate
- [x] 2.3 Smoke-test the script against the live gateway from the box: register →
  show → remove → show for one throwaway skill name using a real upstream SKILL.md
  URL, confirming each action's observable outcome before touching the real catalog

## 3. Register the curated skills

- [x] 3.1 Run `register` for the public set (律锥 legal-practice skills + pa1nrui1
  skills); confirm each appears with correct metadata and visibility
- [x] 3.2 Run `register` for the restricted set (cat-xierluo skills); confirm they are
  group-restricted to `registry-admins`
- [x] 3.3 Re-run the full `register` action once and confirm no duplicates were
  created (in-place update verified)

## 4. End-to-end verification

- [x] 4.1 From a machine outside the box: list skills through
  `https://mcp.token118.com/api/skills` with admin credentials; confirm the full
  curated set with expected visibility split
- [x] 4.2 Fetch a public skill's content via the gateway content endpoint and confirm
  it matches the upstream `SKILL.md` (with companion resources listed)
- [x] 4.3 Verify restricted skills are invisible/inaccessible to a non-admin principal
  (M2M token without registry-admins group, or an unauthenticated request), while
  admin access still works
- [x] 4.4 Confirm drift-detection posture: document (not deliberately trigger) that a
  content change upstream marks the skill drifted/disabled, and verify the gateway
  reports health/status fields for registered skills

## 5. Runbook and docs

- [x] 5.1 Write `deploy/america-box/mcp-gateway-skills.md`: URL-reference model
  summary, exact register/show/remove/visibility commands, license-driven visibility
  policy, CC-BY-NC authorization record section (placeholder until the author
  authorizes), drift re-sync procedure, E2E verification steps, CRLF-safe copy pattern
- [x] 5.2 Add a cross-link from `deploy/america-box/mcp-gateway-registration.md` to the
  skills runbook (and vice versa), noting the shared M2M credential source
- [x] 5.3 Flag the iFLYTEK SkillHub security follow-up (public NodePort exposure,
  empty instance) in the runbook's follow-ups section so it is not forgotten
