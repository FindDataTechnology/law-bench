# Skills catalog runbook (mcp.finddatatech.cloud)

How the AI Gateway & Registry skills catalog on the cheap box is curated and
operated. Sibling doc: [README.md](README.md) (gateway compose + law-bench MCP
registration — shares the same Logto M2M credential source). Change of record:
`openspec` change `restore-legal-skills-catalog`; the original curation is the
archived change `catalog-legal-skills-in-gateway` (america era,
`deploy/america-box/mcp-gateway-skills.md` — historical record only).

## How skills work in the gateway

Skills are **URL references**, not hosted copies. Registering a skill = one API
call naming the upstream `SKILL.md` raw URL. At registration the gateway fetches
and parses the agentskills.io frontmatter and hashes the content as a drift
baseline. (Unlike the america-era build, this deployment does **not** populate
`resource_manifest` — companion files under `references/`/`scripts/` are not
listed; `POST /api/skills/{path}/refresh-resources` exists if needed.)

Ongoing behavior: the health checker re-fetches the upstream URL; on content-hash
drift **or an unreachable upstream** the skill is **auto-disabled** (fail-safe).
Auto-disabled skills disappear from `GET /api/skills` listings but still exist —
`register` handles them transparently (409 → PUT by name → toggle back on; the
log line reads `updated+enabled`).

**Name policy:** gateway names are lowercase alphanumeric + single hyphens.
`metadata.name_zh` / `metadata.skill_dir` / `metadata.fm_name` keep the original
Chinese/original name. Renames and exclusions are recorded in the `CATALOG`
header comment in `scripts/infra/register_skills_gateway.py`.

## The curated catalog (121 skills)

| Source repo | Author | License posture | Visibility | Count |
|---|---|---|---|---|
| legalskill/legalskill (律锥) | LegalSkill 社区 | CC BY-SA 4.0 per skill | public | 2 |
| pa1nrui1/legal-skills | 潘睿 (执业律师) | repo MIT; 3 skills declare CC-BY-NC-SA | 56 public / 3 group | 59 |
| cat-xierluo/legal-skills | 杨卫薪 (执业律师) | per-file: MIT or CC-BY-NC | 7 public / 15 group | 22 |
| THUYRan/Legal-Skills-Chinese | 项目团队 (执业法律专业人员) | repo README: CC BY-NC-ND 4.0 (repo-wide) | group | 38 |

The 2026-09-18 re-resolution moved two cat-xierluo entries out of the original
24 (paddle-ocr excluded — merged upstream into legal-ocr; weekly-legal-briefing
excluded — deleted upstream) and renamed one (industry-research-report →
legal-industry-report). Current authoritative split: **121 = 65 public + 56
group (`registry-admins`)**; the rename/exclusion log lives in the `CATALOG`
header comment in `scripts/infra/register_skills_gateway.py` (see also
`pa1nrui1-contract-review` renamed away from `contract-review`, which the
gateway already held for an unrelated paste.rs-based entry).

- **public** (65): legal-practice skills under permissive licenses.
- **group** (56): CC-BY-NC / CC-BY-NC-SA / CC-BY-NC-ND. Not publicly promoted —
  NC licenses forbid commercial redistribution; ND additionally forbids modified
  distribution, so NC-ND skills are served **verbatim** (the gateway's
  URL-reference model satisfies this; do not publish derived variants).
- The gateway also holds **22 unrelated skills** (finance/data-analysis,
  registered 2026-09-11 by gateway user `aloadtree`), which this catalog does
  not manage. Note `contract-review` there points at an ephemeral
  `paste.rs` paste and has no license metadata — it is unrelated to our
  `pa1nrui1-contract-review`.

## Operating the catalog (on cheap1)

Script: `/root/register_skills_gateway.py` (copy of
`scripts/infra/register_skills_gateway.py`; strip CRLF after copying from
Windows: `sed -i 's/\r$//'`). Reaching cheap1: SSH to cheap4
(`root@103.236.97.114:60188`) then `ssh root@100.64.0.11` (tailscale, key auth;
cheap1 has no public SSH).

Credentials come from the gateway compose env
(`/opt/mcp-gateway-registry/.env`): export `LOGTO_M2M_CLIENT_ID` as
`LOGTO_M2M_APP_ID` plus `LOGTO_M2M_CLIENT_SECRET` (same M2M app as the MCP
server registration, `mcpgatewaym2m` → `registry-admins`; the Mongo
`idp_m2m_clients` mapping prerequisite is documented in the README).

```bash
set -a; . /opt/mcp-gateway-registry/.env; set +a
export LOGTO_M2M_APP_ID="$LOGTO_M2M_CLIENT_ID"

python3 /root/register_skills_gateway.py show                    # name / vis / license / status
python3 /root/register_skills_gateway.py show --name contract-review

python3 /root/register_skills_gateway.py register                # all 121 (idempotent)
python3 /root/register_skills_gateway.py register --repo THUYRan/Legal-Skills-Chinese
python3 /root/register_skills_gateway.py register --visibility group
python3 /root/register_skills_gateway.py register --name legal-ocr
python3 /root/register_skills_gateway.py register --dry-run      # offline, no token needed

python3 /root/register_skills_gateway.py remove <name>           # delete exactly one skill
python3 /root/register_skills_gateway.py remove --repo THUYRan/Legal-Skills-Chinese
python3 /root/register_skills_gateway.py remove --visibility group
```

`register` is idempotent (listing → PUT update / POST create), fails closed on
name collisions with a *different* upstream (`COLLISION` line, exit non-zero),
and re-enables auto-disabled entries (`updated+enabled`).

Long batches: the full catalog takes ~15 min (the gateway fetches each
`SKILL.md` live). Run `setsid nohup <cmd> > log 2>&1 &` and poll
`GET /api/skills?limit=1` `total_count` (python stdout buffers to the log until
exit). Interrupted runs are safe to re-run.

## Transient upstream failures (GitHub raw throttling)

cheap1 egresses from a mainland IP; `raw.githubusercontent.com` is
intermittently throttled after bursts — registration FAILs then look like
`{'detail': 'Invalid SKILL.md URL: '}` (empty detail; a real dead URL instead
shows `HTTP 404`). Remedy: re-run `register` for the failed names with spacing
(`sleep 25` between skills). Do not confuse with `HTTP 404`, which means the
upstream path moved/gone — re-resolve the repo tree, then update `CATALOG`
(rename or exclude, noting why in the header comment).

## License policy and authorization path

- public promotion of any NC/NC-SA/NC-ND skill requires the author's **written
  authorization recorded here** (placeholder — none granted yet).
- THUYRan note: a few of its SKILL.md files mention "MIT" in their body text,
  but the repo-level README declares CC BY-NC-ND 4.0 for everything; treat all
  38 as NC-ND until the author (胡伊然 / huyr17@outlook.com) clarifies per file.
- Upstream drift auto-disables skills; re-run `register` to re-baseline and
  re-enable. This is routine re-sync, not an incident.

## Verification (from outside the box)

```bash
TOKEN=$(curl -s https://auth.finddatatech.cloud/oidc/token \
  -u "$LOGTO_M2M_APP_ID:$LOGTO_M2M_CLIENT_SECRET" \
  -d 'grant_type=client_credentials&resource=https://mcp.finddatatech.cloud/api' | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" \
  'https://mcp.finddatatech.cloud/api/skills?limit=1' | jq '.total_count'   # expect 143 = 22 unrelated + 121 curated

curl -s -H "Authorization: Bearer $TOKEN" \
  'https://mcp.finddatatech.cloud/api/skills/legal-ocr' | jq '.content_integrity.drift_detected, .is_enabled'

# Verbatim check: /content returns JSON {"content", "url", "drift_detected"} —
# compare the .content field's bytes against the upstream SKILL.md
jq -r '.content' <(curl -s -H "Authorization: Bearer $TOKEN" \
  https://mcp.finddatatech.cloud/api/skills/deductive-reasoning/content) | sha256sum
curl -s https://raw.githubusercontent.com/THUYRan/Legal-Skills-Chinese/main/skills/deductive-reasoning/SKILL.md | sha256sum
# (note: jq -r appends a trailing newline; compare with `printf '%s'` semantics or
# strip it on both sides — verified matching 2026-09-18)
```

Restricted-visibility note: our only credential is the admin M2M channel, so
group enforcement itself is verified by inspecting `visibility=group` +
`allowed_groups=["registry-admins"]` on the entries and relies on the gateway's
group filtering (same posture as the america-era change).
