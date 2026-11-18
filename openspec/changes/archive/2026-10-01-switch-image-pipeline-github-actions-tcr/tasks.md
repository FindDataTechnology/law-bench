## 1. Repo sync + transfer to FindDataTechnology org

- [x] 1.1 Fast-forward local main to `origin/main` (absorb Gitee-only commit `41bb8f7`)
- [x] 1.2 Push main to the `github` remote so the mirror is current before transfer
- [x] 1.3 Transfer the repo: `gh api -X POST repos/law-ai-official/law-bench/transfer -f new_owner=FindDataTechnology`, then verify `gh repo view FindDataTechnology/law-bench`
- [x] 1.4 Re-point local remote: `git remote set-url github https://github.com/FindDataTechnology/law-bench.git`; set `git config --global http.https://github.com.proxy http://127.0.0.1:7890`; verify a `git fetch github` succeeds

## 2. GitHub Actions → TCR workflow

- [x] 2.1 Set repo secrets `TCR_USER` (`100035884308`) and `TCR_PASS` on `FindDataTechnology/law-bench` (`gh secret set`)
- [x] 2.2 Rewrite `.github/workflows/build-and-push.yml`: constant image `ccr.ccs.tencentyun.com/law-bench/law-template`, drop insecure-registry steps and CN-mirror build args, keep metadata tag scheme + GHA cache, add `concurrency` group, update header comment (secrets doc)
- [x] 2.3 Commit + push to GitHub, watch runs green — superseded channel: repo now builds via image.yml (tcr-image-pipeline); run 36751041562 built law-template + law-render green in 97 s
- [x] 2.4 Verified via skopeo from cheap-3 with relay creds: `law-template:sha-ba0a6c9` + `law-render:sha-ba0a6c9` present on ccr after relay backfill (first real images ever in the law-bench ccr repos)

## 3. Cluster pull path

- [x] 3.1 Create the pull secret from a cluster box with working kubectl (cheap-6, or cheap-4 with `KUBECONFIG=/root/.kube/config-cheap13`): `kubectl -n law-bench create secret docker-registry tcr-pull --docker-server=ccr.ccs.tencentyun.com --docker-username=100035884308 --docker-password=<TCR_PASS>`
- [x] 3.2 Superseded by stronger production evidence: render-service pod cold-pulled `law-render:sha-ba0a6c9` on cheap-8 (a node that never held it) via node-level registries.yaml auth — no probe pod needed

## 4. Manifest flip + roll (content-identical first roll)

- [x] 4.1 deployment.yaml references ccr (now `sha-ba0a6c9` after extract-render-service rolls); `tcr-pull` imagePullSecrets retained (harmless with node-level auth); nodeSelector kept
- [x] 4.2 assistant-mcp-deployment.yaml on ccr `sha-ba0a6c9`, tcr-pull retained
- [x] 4.3 Rolled through ArgoCD without forced refresh: initial fat rolls 2026-09-30, then extract-render-service B/C/D 2026-10-01; all pods Running/Ready
- [x] 4.4 smoke_prod.sh PASS 13/13 (2026-10-01) + assistant-MCP anonymous 401 verified
- [x] 4.5 Every commit dual-pushed to Gitee + GitHub throughout

## 5. Docs

- [x] 5.1 `deploy/cheap-box/README.md`: rewrite the "Image delivery" material — new flow diagram (push GitHub → Actions → TCR; bump tag → push Gitee → ArgoCD), the pull secret, the rollback-by-flip procedure, TCR tag-cleanup note, and the Jenkins/Harbor dual-track status
- [x] 5.2 `AGENTS.md` ops section: note the new image flow + "push both remotes" habit and that cluster↔github is unreachable (ArgoCD must stay on Gitee)
- [x] 5.3 validate passes (2026-10-01, after reality-reconciliation edits)

## Status (2026-09-30, paused by user)

- **Done:** 1.1–1.4 (repo transferred to `FindDataTechnology/law-bench`, remotes
  + git proxy set), 2.1 (secrets `TCR_USER`/`TCR_PASS`), 2.2 (workflow
  rewritten), 3.1 (`tcr-pull` secret in ns `law-bench`), 5.1–5.2 (docs).
- **Blocked at 2.3:** three build runs (2h12m / 1h17m / 14m, all cancelled)
  stalled identically — early tiny cache blobs appear, then zero layer
  progress. Login to TCR succeeds fast; the blob-upload leg from a US-hosted
  runner to TCR personal edition is the prime suspect (crawl-throttled).
  Progress signal used: `gh cache list` blob growth.
- **Transfer gotcha:** workflows arrive `disabled_manually` after a repo
  transfer — `gh workflow enable` was needed (remember on any future move).
- **Local-uncommitted:** `deploy/deployment.yaml` +
  `deploy/assistant-mcp-deployment.yaml` carry the TCR image refs +
  `imagePullSecrets` with placeholder tag `sha-98bbbb8` (never landed);
  re-point the tag to the sha that actually lands before pushing to Gitee.
- **Diagnostic kept:** `.github/workflows/tcr-speed-test.yml` (committed,
  dispatchable) measures a ~50 MiB push to TCR vs GHCR. Dispatch it after the
  image slimming to verify throughput BEFORE burning a full build.
- **Resume path:** slim image (separate session; direction: move LibreOffice
  + CJK fonts to a shared render-service pod — seam is the `PdfConverter`
  protocol in `src/generator/converter.py`, live callers
  `src/clauses/assemble.py` + `src/contracts/artifacts.py`) → dispatch
  `tcr-speed-test` → if throughput OK, resume 2.3 (dispatch build-and-push,
  verify tag, probe pod), then 4.x (tag flip + push Gitee + ArgoCD + smoke).
  Cluster, Gitee, and ArgoCD are untouched — live prod still runs Harbor
  images (dual-track intact).
