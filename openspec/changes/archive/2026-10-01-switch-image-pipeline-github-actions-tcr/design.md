## Context

Today's pipeline: push to Gitee `origin` → webhook → Jenkins (pod on the
cluster's weakest node, China-mirror build args) → Harbor
(`100.64.0.8:30880/law-bench/law-template`, plain HTTP) → ArgoCD app
`law-bench` (watches Gitee, path `deploy`, automated+selfHeal) rolls pods.
The repo also has a GitHub mirror (`github` remote, `law-ai-official/law-bench`,
private, stale) and an existing GitHub workflow that pushes to Harbor with
insecure-registry workarounds.

Connectivity facts established 2026-09-30 (they drive every decision below):

| From → To | github.com | ccr.ccs.tencentyun.com |
|---|---|---|
| dev machine (direct git) | flaky/timeout; local proxy on 127.0.0.1:7890 works | assumed (not needed) |
| cheap-6 / cheap-7 (cluster) | **unreachable** (curl empty, both github.com and api.github.com) | **reachable** (GET /v2/ → 401 in ~0.24 s) |

State divergence: `origin/main` (Gitee) has `41bb8f7` (a Jenkinsfile tweak)
that local main lacks; `github/main` is far behind. The authenticated gh
account (`scs001`) is admin of both `law-ai-official/law-bench` and the
`FindDataTechnology` org, so it can execute the repo transfer. The TCR
personal namespace is `law-bench` (user-created); login user `100035884308`.

## Goals / Non-Goals

**Goals:**

- Image builds leave the cluster entirely (GitHub-hosted runners).
- Cluster pulls from a fast, HTTPS, China-side registry (TCR personal).
- Deploy trigger mechanics stay exactly what the operator knows today.
- A no-rebuild rollback path to the current Harbor images during a
  dual-track window.

**Non-Goals:**

- No change to ArgoCD application wiring beyond what a manifest flip needs.
- No `copilot-runtime` / fd-* / review-agent / public-manifest coverage.
- No deletion of Jenkins, the Jenkinsfile, or the Gitee webhook (dual-track).
- No new cluster infrastructure (no mirrors, no proxies inside the cluster).

## Decisions

### D1 — ArgoCD keeps watching Gitee; GitHub is code+CI only

Cluster nodes cannot reach github.com, so an ArgoCD application sourced from
GitHub would never sync. Gitee is reachable from the cluster and is already
the working source. A cluster-side egress proxy just to read GitHub was
rejected: one more fragile moving part for zero benefit.

Consequence: the deploy gesture remains "bump tag in `deploy/*.yaml`, push to
`origin` (Gitee)". Code pushes for CI go to the `github` remote; the operator
pushes both remotes as today (git proxy below makes the GitHub push reliable).

### D2 — Workflow: rewrite `build-and-push.yml` around TCR,HTTPS, defaults

- Image name is a **constant** in the workflow:
  `ccr.ccs.tencentyun.com/law-bench/law-template` — not secret-derived (the
  Harbor version needed a secret for the registry host because it was
  environment-specific; TCR's host is a fixed public endpoint).
- Secrets: repo-level `TCR_USER` / `TCR_PASS` (org-level secrets are not
  manageable with the current token; repo secrets survive the org transfer).
- Delete the insecure-registry daemon surgery and the buildx `http = true`
  config — TCR is HTTPS. This removes the `sudo systemctl restart docker`
  step entirely.
- Do **not** pass the Jenkins China-mirror build args (`BASE_IMAGE_MIRROR`,
  `UV_INDEX_URL`, `DEBIAN_MIRROR`, …): GitHub runners are outside China and
  the Dockerfile defaults (ghcr.io base, pypi.org, deb.debian.org) apply.
- Keep `docker/metadata-action` tagging (`type=sha,format=short`, `latest` on
  main, `type=ref,event=tag`) — the tag scheme is the contract the manifests
  and the provenance-check habit rely on.
- Keep `cache-from/to: type=gha` and add a `concurrency` group
  (Jenkins had `disableConcurrentBuilds`; pushes of code+roll commit in quick
  succession would otherwise queue two full builds).

### D3 — Cluster pull: k8s `docker-registry` secret, not k3s registries.yaml

A namespaced secret `tcr-pull` (server `ccr.ccs.tencentyun.com`) referenced
via `imagePullSecrets` in the two live manifests beats editing
`/etc/rancher/k3s/registries.yaml` per node: it is one kubectl command, it
scopes credentials to the `law-bench` namespace, and it needs no k3s restart
(the memories record registries.yaml changes requiring restarts and past 401
era). `imagePullSecrets` is also what the (stale but ArgoCD-tracked) sibling
manifests already model.

`nodeSelector` pins stay: the web pod's PVC lives on cheap-7 and live state
should not move in the same change as the registry switch. TCR pulls make
node-agnostic scheduling *possible* later; unpinning is deferred (Open
Question).

### D4 — Repo transfer via gh, sync-first

Order matters: (1) fast-forward local main to `origin/main` (absorbs
`41bb8f7`), (2) push main to the `github` remote so the future org repo is
current, (3) `gh api -X POST repos/law-ai-official/law-bench/transfer -f
new_owner=FindDataTechnology` — the account is admin of both sides, so the
transfer completes immediately; secrets, Actions history, and webhooks move
with the repo, (4) re-point the local `github` remote to
`https://github.com/FindDataTechnology/law-bench.git` (old URLs redirect, but
explicit beats implicit), (5) `git config --global
http.https://github.com.proxy http://127.0.0.1:7890` so pushes reliably ride
the local proxy.

The Gitee `origin` remote is untouched — it stays the ArgoCD source and the
deploy push target.

### D5 — Cutover order: verify the pull before flipping the manifests

1. Workflow verified end-to-end (a `sha-*` tag visible in TCR console/API)
   before any cluster change.
2. `tcr-pull` secret created; a throwaway pod (`kubectl run
   tcr-pull-test --image=ccr.ccs.tencentyun.com/law-bench/law-template:<tag>`)
   proves kubelet can pull on a live node; delete it.
3. Only then flip `deploy/deployment.yaml` and
   `deploy/assistant-mcp-deployment.yaml` to the TCR path of the **already
   deployed** `sha-db5ed10` (content-identical roll: proves the pull path
   without introducing a new build), push to Gitee, watch ArgoCD sync, smoke
   test. Subsequent rolls use freshly built tags.
   *(Apply-time amendment: the rewritten workflow only builds pushed HEADs, so
   `sha-db5ed10` cannot be produced through TCR. The first roll instead uses
   the freshly built `sha-<head>` whose diff vs db5ed10 is Jenkinsfile/CI/docs
   only — functionally the same content-identical guarantee.)*

Rollback = flip the references back to `100.64.0.8:30880/law-bench/law-template:sha-<x>`
with a Harbor-existing tag and push. No rebuild, no cluster change.

## Risks / Trade-offs

- [GH-hosted runner → TCR push crosses the Pacific; ~2.3 GB first push may
  take 10–30 min] → acceptable (Jenkins took 12–36 min); GHA layer cache
  shrinks later pushes; `latest`-only pushes stay cheap.
- [Org private repos may not include Actions minutes on the current GitHub
  plan ("组织仓库不支持私有仓库")] → first workflow run is the test; if
  billing blocks it, enable a spending limit or Actions billing on the org —
  operator decision, no code change involved.
- [TCR personal edition storage quota as `sha-*` tags accumulate] → runbook
  gets a cleanup note (keep `latest` + recent tags); console cleanup is
  manual.
- [TCR personal edition is a fixed-password credential, not a robot token]
 → password lives in GH repo secret + k8s secret only; rotation means
  updating two places (documented in runbook).
- [Two remotes to keep in sync by hand] → same as today; the runbook states
  push order (Gitee for rolls, GitHub for CI builds). A Gitee↔GitHub
  auto-mirror was considered and rejected (another sync service to operate;
  the cluster can't read GitHub anyway, so Gitee must stay manual-primary).
- [Dual-track window: Jenkins still fires on Gitee pushes] → that is the
  wanted fallback; its Harbor pushes are idempotent for manifests that no
  longer reference Harbor. Harmless; retire later by deleting the webhook.

## Migration Plan

1. **Repo sync + transfer** (D4): absorb `41bb8f7`, push GitHub, transfer to
   org, fix remote + git proxy.
2. **Secrets + workflow**: set `TCR_USER`/`TCR_PASS`, rewrite
   `build-and-push.yml`, push, `workflow_dispatch`, confirm the tag in TCR.
3. **Cluster prep**: create `tcr-pull`, pull-probe pod, delete probe.
4. **Manifest flip** to TCR refs of the currently deployed `sha-db5ed10`,
   push to Gitee, ArgoCD sync, `scripts/smoke_prod.sh`.
5. **Docs**: runbook image-delivery section + rollback-by-flip; AGENTS.md
   ops note about the new flow and the push-both-remotes habit.
6. **Steady state**: normal rolls become "push code to GitHub (build) → bump
   tag → push to Gitee (roll)". Jenkins/Harbor remain until the operator
   declares the window over (out of this change).

## Open Questions

- Unpin the `nodeSelector` on web/assistant-MCP once TCR pulls are proven on
  every node (post-change, needs PVC placement thought for the web pod).
- Cadence/tooling for TCR tag cleanup (manual console cleanup is fine to
  start).

## Resolution (2026-10-01)

The direct US-runner→ccr push designed here never completed: measured
~0.14MB/s, three runs cancelled after up to 2h12m, and (verified via a
temporary tag-list workflow) the registry never actually held the running
tags — pods ran off node-local pre-imported images. The fleet moved to the
standard tcr-image-pipeline channel instead: `image.yml` pushes to
hkccr.ccs.tencentyun.com (11.6MB/s leg), a cheap-3 skopeo relay backfills
ccr within a 5-minute cron cycle, and nodes authenticate via node-level
registries.yaml (no per-pod imagePullSecret). law-bench was onboarded
during extract-render-service: both images built green in 97 s, relay
backfill verified, and a production cold-node pull confirmed the auth
model. The delta spec was rewritten to the delivered behavior; this design
stands as the historical record of the direct-push attempt and why it died.
