# Proposal: catalog-legal-skills-in-gateway

## Why

The AI Gateway & Registry at `mcp.token118.com` (america box, `/opt/mcp-gateway-registry`)
has a skills catalog entity that is entirely unused (0 skills), while three curated
Chinese legal-skill GitHub repos have been identified for aggregation:
`legalskill/legalskill` (律锥, Apache-2.0 + CC-BY-SA-4.0), `pa1nrui1/legal-skills`
(MIT), and `cat-xierluo/legal-skills` (MIT + CC-BY-NC). The gateway's skills feature is
URL-reference based — registering a skill is one API call against the upstream
`SKILL.md` raw URL, with automatic companion-resource discovery, content-hash drift
detection, and per-skill visibility control. The Logto M2M channel built for the
law-bench MCP registration (`mcpgatewaym2m` → `registry-admins`) already carries full
skills management scope, so this aggregation is nearly free and needs no new auth work.

## What Changes

- Add a registration automation script `scripts/infra/register_skills_gateway.py`
  (mirrors the existing `register_mcp_gateway.py` pattern: Logto M2M client_credentials
  token + stdlib-only REST calls) that publishes skills via `POST /api/skills` with
  name, upstream `SKILL.md` raw URL, and metadata (license, author, source repo, tags),
  and supports remove/show actions for lifecycle management.
- Curate and register the legal-practice skills from the three repos. Non-legal skills
  (e.g. 律锥's 高考志愿 advisor, repo-publish manager) are excluded. Each skill is
  verified format-compliant (agentskills.io frontmatter) before registration.
- Apply a license-based visibility policy at registration:
  - **public**: 律锥 (Apache-2.0 + CC-BY-SA-4.0) and pa1nrui1 (MIT) skills — permissive
    licenses allow catalog distribution.
  - **group-restricted** (`registry-admins` only): cat-xierluo skills — the skill files
    declare CC-BY-NC (non-commercial); serving them from the commercial-facing gateway
    publicly would exceed the license. They stay internal for evaluation until the
    author grants written authorization (upgrade path documented in the runbook).
- Verify end-to-end: skills listable and content fetchable through the gateway API
  (`/api/skills/{name}/content`), drift-detection auto-disable confirmed by behavior
  (documented, not deliberately triggered), restricted skills invisible to
  non-admin principals.
- Add a runbook `deploy/america-box/mcp-gateway-skills.md` (registration/removal/
  re-sync commands, license policy, CC-BY-NC authorization path, upgrade notes) and
  cross-link it from the existing MCP registration runbook.

Out of scope: the iFLYTEK SkillHub deployment on the same box (stays untouched; it is
an unrelated self-hosted skill registry, currently empty and domain-less — its public
NodePort exposure is flagged as a separate security follow-up), any modification of the
upstream repos, and any public promotion of the catalog beyond gateway visibility.

## Capabilities

### New Capabilities
- `mcp-gateway-skills-catalog`: the skills catalog posture of the AI Gateway &
  Registry at mcp.token118.com — URL-reference registration of vetted legal skills
  from the three GitHub repos, license-driven visibility (public vs group-restricted),
  skill metadata (license/author/tags), upstream drift detection, content distribution
  through the gateway, and the registration automation + runbook.

### Modified Capabilities
<!-- None — lawbench-mcp-gateway covers MCP server registration only; skills are a
     distinct gateway entity with distinct behavior. No existing spec's requirements
     change. -->

## Impact

- **Systems**: america box gateway registry — new rows in the Mongo skills collection;
  no new containers, no image builds, no compose changes, no auth changes.
- **Code**: `scripts/infra/register_skills_gateway.py` (new), `deploy/america-box/mcp-gateway-skills.md`
  (new runbook), cross-link edit in `deploy/america-box/mcp-gateway-registration.md`.
- **Upstream dependency**: skills stay hosted in the three GitHub repos; gateway
  auto-disables a skill when upstream content drifts — re-registration/re-sync becomes
  a routine runbook operation.
- **License risk (mitigated)**: CC-BY-NC skills are registered group-restricted only;
  the runbook documents that public promotion requires the author's written
  authorization.
- **Rollback**: `POST /api/skills/remove` per skill (script action `remove`); no other
  system state is created.
