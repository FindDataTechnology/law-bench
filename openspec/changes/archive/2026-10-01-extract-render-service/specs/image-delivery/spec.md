## ADDED Requirements

### Requirement: Render service image delivery

The render-service image (built from `Dockerfile.render` at repo root) SHALL
be built and published by the repo's image workflow on the same triggers as
the main image (push to the default branch, manual dispatch), as a second
matrix entry, using the same `sha-<short>` plus `main` tag scheme. The
workflow SHALL push to the HK registry relay hop
(`hkccr.ccs.tencentyun.com/law-bench/law-render`); the tcr-relay SHALL
backfill it to `ccr.ccs.tencentyun.com` within its sync cycle, and the
render-service workload SHALL reference the ccr path. Nodes SHALL pull
without a per-pod imagePullSecret (cluster-wide registries.yaml auth).

#### Scenario: Push publishes both application images

- **WHEN** a commit is pushed to the default branch
- **THEN** the HK registry contains both `law-bench/law-template:sha-<short>`
  and `law-bench/law-render:sha-<short>` built from that commit, and within
  one relay cycle (≤5 min) `ccr.ccs.tencentyun.com` serves the same tags

#### Scenario: Render pod cold-node pull

- **WHEN** the render-service pod referencing
  `ccr.ccs.tencentyun.com/law-bench/law-render:sha-<x>` is scheduled on a
  node that has never held that image
- **THEN** kubelet pulls it successfully via the node-level registry
  authentication, without manifesting `ImagePullBackOff`

