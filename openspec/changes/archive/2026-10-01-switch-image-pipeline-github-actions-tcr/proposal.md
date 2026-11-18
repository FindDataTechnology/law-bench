## Why

The current image pipeline (Gitee webhook → Jenkins on the cluster's weakest
node → in-cluster Harbor over plain HTTP) is fragile: builds die with the
flaky Jenkins node, Harbor pull auth has broken before, and the 2.3 GB image
transits a cluster-hosted registry on an already disk-tight node. Building on
GitHub's hosted runners and publishing to Tencent TCR personal edition moves
the build off the cluster entirely and gives the cluster a fast (verified
~0.24 s RTT) China-side registry to pull from. The GitHub repo also needs to
move from the `law-ai-official` org to `FindDataTechnology` so the project
lives under the same org as the rest of the company's assets.

## What Changes

- **GitHub Actions becomes the image builder.** `.github/workflows/build-and-push.yml`
  is rewritten to push to Tencent TCR personal edition
  (`ccr.ccs.tencentyun.com/law-bench/law-template`) instead of the in-cluster
  Harbor. The Harbor insecure-registry workarounds go away (TCR is HTTPS); the
  China-mirror build args go away too (hosted runners reach ghcr.io / pypi.org
  directly, so the Dockerfile defaults apply). Tag scheme stays `sha-<short>`
  plus `latest` on main.
- **Cluster pulls from TCR.** `deploy/deployment.yaml` and
  `deploy/assistant-mcp-deployment.yaml` switch their image references from
  `100.64.0.8:30880/law-bench/law-template:sha-*` to
  `ccr.ccs.tencentyun.com/law-bench/law-template:sha-*`, with an
  `imagePullSecrets` entry for a new k8s `docker-registry` secret
  (`tcr-pull`, ns `law-bench`) holding the TCR credentials.
- **Deploy trigger is unchanged: ArgoCD keeps watching Gitee.** Cluster nodes
  cannot reach github.com (verified 2026-09-30 from cheap-6 and cheap-7), so
  Gitee remains the manifest source ArgoCD syncs; a deploy is still "bump the
  image tag in `deploy/*.yaml`, push to Gitee".
- **Dual-track transition (user decision).** Jenkins, the Gitee webhook, and
  the Jenkinsfile all stay operational during the transition. Harbor keeps
  its existing images read-only as the rollback path: flipping the manifest
  image references back to the Harbor path rolls back to a Jenkins-built tag.
- **GitHub repo transfers to the `FindDataTechnology` org** (executed with
  `gh api` by an account that is admin of both the repo and the org). Local
  `github` remote is re-pointed, and pushing to GitHub from the dev machine
  is routed through the local proxy (127.0.0.1:7890) via a repo-scoped
  `http.proxy` git config.
- **Actions secrets**: repo-level `TCR_USER` / `TCR_PASS` (org-level secrets
  are not usable with the current token). Secrets survive the repo transfer.
- **Runbook updated** (`deploy/cheap-box/README.md`): image delivery section
  rewritten for the new flow, with the rollback-by-flip procedure.

Out of scope: `copilot-runtime` image (stays manual), `mcp-deployment.yaml`
(stale vs live, excluded from ArgoCD), the `review-agent`/`public` manifests
(stale `harbor.local` refs, not live), and any change to the fd-* services.

## Capabilities

### New Capabilities
- `image-delivery`: how the law-bench image is built, published, and pulled —
  GitHub Actions build → TCR publish → cluster pull with secret → ArgoCD
  rollout via Gitee, including the dual-track rollback contract.

### Modified Capabilities

(none — no product spec changes)

## Impact

- `.github/workflows/build-and-push.yml` (rewrite), `deploy/deployment.yaml`,
  `deploy/assistant-mcp-deployment.yaml` (image refs + pull secret),
  `deploy/cheap-box/README.md` (runbook).
- Cluster (one-time, during apply): create secret `tcr-pull` in ns
  `law-bench`; verify a node can `ctr`/kubelet-pull from
  `ccr.ccs.tencentyun.com` before the first roll.
- GitHub: repo transfer `law-ai-official/law-bench` → `FindDataTechnology/law-bench`;
  repo secrets `TCR_USER`/`TCR_PASS`.
- No application code changes; the image content is byte-identical to what
  the Jenkins path produces from the same commit.

## Resolution (2026-10-01)

Delivered, via the fleet-standard hk+relay channel rather than the direct
ccr push originally proposed (that path measured ~0.14MB/s and never
completed a push). See design.md "Resolution" and the rewritten delta spec
for the as-built flow; smoke 13/13 PASS and all 18 tasks closed.
