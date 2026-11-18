# Design: catalog-legal-skills-in-gateway

## Context

The gateway's skills feature is URL-reference based (verified against upstream
`docs/agent-skills-operational-guide.md`, `registry/services/skill_service.py`, and the
live `openapi.json`): registering a skill is `POST /api/skills` with a name and an
upstream `SKILL.md` raw URL; the gateway parses frontmatter, discovers companion
resources, hashes content for drift detection, and proxies content on demand via
`/api/skills/{name}/content`. The Logto M2M channel from the law-bench MCP registration
(`mcpgatewaym2m` → `registry-admins`, documented in
`deploy/america-box/mcp-gateway-registration.md`) already confers skills management
scope — no auth work is needed. The three source repos are agentskills.io-format
compatible (contract-copilot spot-checked: full frontmatter with license/author fields,
plus references/scripts/templates resources). The iFLYTEK SkillHub instance on the same
box is an alternative self-hosted registry but is empty, domain-less, and out of scope.

The gateway runs a pinned upstream commit with local patches — endpoint shapes MUST be
confirmed against the on-box `api/openapi.json` (and a live `GET /api/skills` with an
M2M token) before the script is written, not assumed from upstream `main` docs.

## Goals / Non-Goals

**Goals:**

- One repeatable script (`scripts/infra/register_skills_gateway.py`) that registers,
  shows, and removes the curated skills idempotently.
- License-driven visibility enforced at registration time (public vs group-restricted).
- A runbook making catalog operations routine (register / re-sync after drift / remove
  / visibility upgrade after authorization).

**Non-Goals:**

- Any change to gateway auth, compose stack, images, or the law-bench MCP registration.
- Hosting/mirroring skill content in the gateway beyond what its URL-reference model
  already caches.
- Touching the iFLYTEK SkillHub deployment (separate security follow-up: it is exposed
  on public NodePorts 30930/30931 with no domain or auth hardening).
- Contacting the cat-xierluo author (documented as the operator's manual step).

## Decisions

### D1 — URL-reference registration in the gateway, not vendoring, not SkillHub

Register upstream `SKILL.md` raw URLs directly in the gateway's native skills entity.

- *Alternative: mirror the skill files into a repo we control* — turns us into a
  redistributor (worse for CC-BY-NC), adds a sync pipeline, and loses the gateway's
  drift detection. Rejected.
- *Alternative: use the box's iFLYTEK SkillHub* — it is a hosted-package registry
  (upload/version/namespaces) designed for distribution via its own CLI; it would
  duplicate infrastructure for zero benefit here, is currently empty and unconfigured,
  and its ClawHub-CLI integration targets a different consumer flow. Rejected for this
  change; flagged as separate follow-up.

### D2 — Curated skill list pinned by walking the repos at implementation

The candidate set from exploration:

| Repo | Include (candidate) | Exclude | Visibility |
|---|---|---|---|
| legalskill/legalskill (`skill/`) | `legalskill-legal-consultation` (五阶段法律咨询), `tencent-ima-copilot-legal-consultation` | `gaokao-quick-advisor`, `claw-agent-workspace`, `repo-domain-publish-manager` (non-legal-practice) | public |
| pa1nrui1/legal-skills | task-routing, material-reading, regulation-check, human-review workflow skills (exact dir names pinned at implementation) | — | public |
| cat-xierluo/legal-skills | litigation analysis, patent analysis, `contract-copilot`, other legal-practice skills (exact dir names pinned at implementation) | — | group-restricted |

Task 1 pins the exact list: walk each repo's skills directory, resolve each
`SKILL.md` raw URL, verify HTTP 200 + frontmatter, and drop anything that fails. The
design does not invent paths it has not verified.

### D3 — Standalone stdlib-only script mirroring the MCP registration pattern

`scripts/infra/register_skills_gateway.py` copies the proven shape of
`scripts/infra/register_mcp_gateway.py`: stdlib-only (urllib, no deps), actions
`register` / `show` / `remove`, M2M token minted per run from Logto
(client_credentials, resource `https://mcp.token118.com/api`), credentials read from
on-box `/root/.mcp_logto_creds` (never committed). The curated catalog lives as a
Python constant in the script: `{name, repo, url, license, author, tags, visibility}`.
Endpoint field names are pinned in task 1 from the on-box `openapi.json`
(`POST /api/skills` for register; modify/toggle endpoint for visibility; remove
endpoint for delete — exact names verified then).

- *Alternative: shell/curl script* — breaks on Windows dev boxes and grows unmaintainable. Rejected.
- *Alternative: extend `register_mcp_gateway.py`* — different entity, different fields;
  single-purpose tools stay readable. Rejected.

### D4 — Visibility via the gateway's per-skill visibility/group controls

Public skills register with default (public) visibility; CC-BY-NC skills register
group-restricted with `allowed_groups=[registry-admins]` — the same group the MCP
server registration uses, so admin principals already in that group see everything.
The exact request fields are confirmed from the on-box openapi schema before coding;
if the deployed gateway's skills API lacks per-skill group restriction, fall back to
registering CC-BY-NC skills with the most restrictive visibility available and record
the limitation in the runbook (spec scenario then verified accordingly).

### D5 — CC-BY-NC handling: restricted now, documented authorization path

Registering restricted-for-internal-evaluation is a defensible fair use posture
(no public distribution); public promotion is deferred until the author grants written
authorization, recorded in the runbook before any visibility switch.

- *Alternative: exclude cat-xierluo entirely* — loses the highest-quality contract
  review skill from internal evaluation; the restricted posture already satisfies the
  license. Rejected.
- *Alternative: register publicly and attribute* — CC-BY-NC forbids commercial use and
  the gateway is commercial-facing infrastructure. Rejected.

### D6 — Runbook as a new file with cross-links

`deploy/america-box/mcp-gateway-skills.md` carries the skills-specific mechanics
(URL-reference model, drift behavior, register/show/remove/visibility commands,
license policy + authorization record, E2E verification from outside the box).
The existing `mcp-gateway-registration.md` gets a one-line cross-link. Keeping skills
separate avoids bloating the MCP-server runbook, which is already dense.

## Risks / Trade-offs

- [Deployed gateway commit may differ from upstream `main` skills API] → task 1
  verifies against on-box `openapi.json` + live `GET /api/skills` before any script is
  written; field names pinned from the deployed schema, not docs.
- [Upstream repos restructure and break registered URLs] → gateway drift detection
  auto-disables affected skills (fail-safe, not fail-open); runbook documents the
  re-sync command; catalog constant in the script is the single place to update URLs.
- [CC-BY-NC compliance] → restricted visibility + no public promotion until written
  authorization recorded; removal action provides an instant off switch.
- [律锥 CC-BY-SA share-alike interpretation] → we distribute via attribution +
  link-back to the upstream repo (the gateway content proxy preserves source URLs);
  no modification of the skills themselves. If the operator wants stricter safety,
  律锥 skills can also be dropped to restricted with a one-line change.
- [Windows CRLF corrupts the script when copied to the box] → same mitigation as the
  previous script: copy with CRLF-stripping (previous runbook documents the pattern).
- [Script leaks M2M credentials] → credentials only ever read from on-box
  `/root/.mcp_logto_creds` (0600); repo receives no secret material.

## Migration Plan

1. Verify the live gateway skills API (openapi.json + `GET /api/skills` with M2M token).
2. Walk the three repos, pin the exact skill list + raw URLs, verify format/reachability.
3. Write the script with the pinned catalog constant; register public skills first,
   then restricted ones.
4. E2E verify: catalog listing, public content fetch, restricted skill hidden from a
   non-admin principal.
5. Write the runbook + cross-link; record the CC-BY-NC authorization placeholder.
6. Rollback at any point: script `remove` action per skill (or remove all); no other
   system state exists.

## Open Questions

- Exact skill directory names for pa1nrui1 and cat-xierluo (pinned by task 1's repo
  walk; does not affect approach or spec).
- Whether the deployed skills API exposes per-skill group restriction (D4 fallback if
  not; verified in task 1).
