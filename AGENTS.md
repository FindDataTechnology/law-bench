# law-bench agent instructions

## Spec-driven workflow (OpenSpec)

This project uses [OpenSpec](https://openspec.dev) (CLI v1.8.0) for change management. Specs live in `openspec/specs/`, active changes in `openspec/changes/`, archived changes in `openspec/archive/`.

When the user asks to build, fix, or change a feature, use the OpenSpec workflow instead of implementing directly:

- New change: `/opsx:propose` (or skill `openspec-propose`) — creates the change and generates proposal/spec/design/tasks artifacts. Planning only; stop after artifacts are done.
- Implement an approved change: `/opsx:apply` (`openspec-apply-change`).
- Update artifacts of an existing change: `/opsx:update` (`openspec-update-change`).
- Explore the spec landscape: `/opsx:explore` (`openspec-explore`).
- Sync specs after archiving: `/opsx:sync` (`openspec-sync-specs`).
- Archive a completed change: `/opsx:archive` (`openspec-archive-change`).

Run `openspec list` / `openspec validate --all` to inspect state before making changes.

## Ops context (avoid stale assumptions)

- The **token118.com domain family and the america box (23.144.68.246) are retired** (2026-09-09). Do not target them in new changes or docs.
- The shared Logto IdP is `https://auth.finddatatech.cloud`; public services live under `*.finddatatech.cloud` on the cheap k3s cluster (runbook: `deploy/cheap-box/README.md`).
- Object storage is **RustFS** (S3-compatible). The app config still uses the `minio_*`/`MINIO_*` env names — treat "MinIO" in older docs/specs as RustFS.
- References to token118/america under `openspec/changes/archive/`, `openspec/specs/` history, and `deploy/america-box/` are immutable historical records — do not "fix" them.
- **Image pipeline (tcr-image-pipeline standard channel, since 2026-10-01):** `git push github main` triggers `.github/workflows/image.yml` (matrix: `law-template` + `law-render`), which pushes to the HK hop `hkccr.ccs.tencentyun.com/law-bench/<image>`; the cheap-3 tcr-relay (5-min cron, repos.conf lists both repos) backfills `ccr.ccs.tencentyun.com` — allow ≤5 min before referencing a fresh ccr tag. Nodes pull from ccr via node-level `registries.yaml` auth (no per-pod imagePullSecret needed; existing `tcr-pull` refs are harmless). Direct US→ccr pushes are a dead path (~0.14MB/s) — never push ccr from GitHub runners. Secrets: `TCR_USERNAME`/`TCR_PASSWORD` (repo-level). Tags: `sha-<short>` (immutable) + rolling `main`. Dockerfile rules: upstream-default sources (CN mirrors as empty-default ARGs), no single RUN layer >~300MB (transpacific blob uploads wedge). **Cluster nodes cannot reach github.com** — ArgoCD must keep watching the **Gitee** repo; a deploy = bump the image tag in `deploy/*.yaml` and push to Gitee (push code commits to both remotes). Jenkins→Harbor stays as the dual-track fallback.
