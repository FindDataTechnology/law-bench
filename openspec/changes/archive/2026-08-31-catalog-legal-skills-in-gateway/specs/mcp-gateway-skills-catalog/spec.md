## Purpose

Define the skills catalog posture of the AI Gateway & Registry at mcp.token118.com:
which vetted legal skills from the three curated GitHub repos are registered, under
what license-driven visibility, how registration and removal are automated, and how
operators run the catalog day to day.

## ADDED Requirements

### Requirement: Legal Skills Catalog Registration

The gateway skills catalog SHALL contain the curated legal-practice skills from
`legalskill/legalskill` (律锥), `pa1nrui1/legal-skills`, and `cat-xierluo/legal-skills`,
each registered as a URL reference to the upstream `SKILL.md` raw file with metadata
(license, author, source repo, topic tags). Only legal-practice skills SHALL be
registered; non-legal skills in those repos (e.g. 律锥's 高考志愿 advisor and
repo-publish manager) SHALL be excluded. A skill whose upstream `SKILL.md` is
unreachable or lacks agentskills.io frontmatter (name/description) SHALL NOT be
registered.

#### Scenario: Permissive-license skill registered

- **WHEN** the registration automation runs against a reachable `SKILL.md` raw URL of
  a legal-practice skill from 律锥 or pa1nrui1
- **THEN** the gateway lists the skill with its name, description, license, author,
  source repo, and tags, and the skill's companion resources (references/scripts)
  discovered from the upstream directory are shown in the skill entry

#### Scenario: Unreachable or malformed upstream rejected

- **WHEN** a candidate skill's `SKILL.md` raw URL returns an error or its frontmatter
  is missing required fields
- **THEN** the automation reports the failure, registers nothing for that skill, and
  exits non-zero so the omission is visible

### Requirement: License-Driven Visibility

Skill visibility SHALL follow the upstream license: skills under permissive licenses
(Apache-2.0 + CC-BY-SA-4.0, MIT) SHALL be registered public; skills whose files declare
CC-BY-NC (the cat-xierluo repo) SHALL be registered group-restricted to
`registry-admins` and SHALL NOT be publicly promoted until the author's written
authorization is recorded in the runbook.

#### Scenario: CC-BY-NC skill hidden from non-admin principals

- **WHEN** a principal without `registry-admins` group membership lists the skills
  catalog or requests the content of a cat-xierluo skill
- **THEN** the skill does not appear in their catalog listing and content access is
  denied, while an admin principal sees and can fetch it

#### Scenario: Authorization upgrade path

- **WHEN** the cat-xierluo author's written authorization is obtained and recorded in
  the runbook
- **THEN** the affected skills' visibility is switched to public via the modification
  API and they become visible to all gateway consumers

### Requirement: Registration Automation and Lifecycle

A repository automation script SHALL manage the catalog skills using the gateway M2M
channel (Logto client_credentials → registry-admins scopes), with actions to register
all curated skills (with metadata), show the current catalog state, and remove skills
by name. Re-running registration against an already-registered skill SHALL update its
metadata in place rather than duplicate it.

#### Scenario: Register, show, remove lifecycle

- **WHEN** the automation's register action runs, then `show` is invoked, then
  `remove <name>` is invoked for one skill
- **THEN** register reports each skill's outcome, show lists the registered skills
  with their visibility and metadata as registered, and remove deletes exactly the
  named skill leaving the others intact

#### Scenario: Re-registration updates in place

- **WHEN** registration is run twice for the same skill name
- **THEN** the gateway holds one skill entry for that name whose metadata reflects the
  latest registration, not two entries

### Requirement: Skills Catalog Operations Runbook

A runbook in `deploy/america-box/` SHALL document the skills catalog: the registration
mechanics (URL-reference model, drift detection), the exact register/show/remove
commands, the license-driven visibility policy including the CC-BY-NC authorization
path, and verification steps through the public gateway URL. The existing MCP
registration runbook SHALL cross-link to it.

#### Scenario: Operator can verify the catalog end to end

- **WHEN** an operator follows the runbook's verification steps from a machine outside
  the box
- **THEN** they can authenticate, list the registered skills with expected visibility,
  fetch a public skill's content through the gateway, and confirm a restricted skill is
  not accessible without admin group membership

#### Scenario: Upstream drift response documented

- **WHEN** an upstream repo changes a registered skill's files
- **THEN** the runbook states the expected gateway behavior (content-hash drift
  detection auto-disables the skill) and the re-sync command to restore it
