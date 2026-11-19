# image-delivery Specification

## Purpose

Defines how the law-bench application images are built, published, and
delivered to the cheap cluster: GitHub Actions builds on push, publishes via
the HK registry hop with a relay backfill to Tencent TCR personal edition,
and the cluster pulls from TCR while ArgoCD continues to roll out from the
Gitee manifest source.

## Requirements

### Requirement: Build and publish the application images on push

The system SHALL build the law-bench application images (`Dockerfile` and
`Dockerfile.render` at repo root) via the repo's own GitHub Actions image
workflow (`.github/workflows/image.yml`) whenever a commit is pushed to the
default branch, and on manual dispatch. The workflow SHALL push to the HK
registry hop `hkccr.ccs.tencentyun.com`, from which the cheap-3 tcr-relay
backfills `ccr.ccs.tencentyun.com` within its ≤5-minute sync cycle; direct
US-runner→ccr pushes are a dead path (~0.14MB/s) and MUST NOT be used. The
build MUST NOT depend on the GitHub-hosted runner having access to any
China-side mirror: the Dockerfile's default base image and package indexes
apply unchanged, and no single RUN layer exceeds ~300MB (transpacific blob
uploads wedge).

When the source repo's account has exhausted its GitHub Actions quota, the
system SHALL instead build from a **source snapshot pushed to a private image
repository under another account**, and SHALL NOT switch to a public snapshot
repository to save quota (that publishes the source). The head repository SHALL
run the law-bench workflow, not a generic platform image workflow: a generic
gate probes another product's port/endpoint/required env and fails this image
unconditionally.

The image tag SHALL remain the snapshot repository's short commit sha, and the
snapshot root SHALL carry `BUILD-INFO.json` recording the true `baseCommit`.
Image labels are inherited from the base image and MUST NOT be used as the
provenance judgement.

#### Scenario: Code push to main triggers a published image

- **WHEN** a commit is pushed to the default branch of the image repository
- **THEN** the image workflow builds the image from that tree, pushes it to
  hkccr tagged `sha-<7-char-short-sha>`, and within one relay cycle (≤5 min)
  the same digest is servable from `ccr.ccs.tencentyun.com`

#### Scenario: Manual dispatch republishes

- **WHEN** the image workflow is triggered via `workflow_dispatch`
- **THEN** the same build-and-publish path runs without a push

#### Scenario: Quota exhausted, private snapshot channel

- **WHEN** the source account's private Actions quota is exhausted and another
  account's private quota is available
- **THEN** a snapshot of the source is pushed to that account's private image
  repository, the build runs there, the image reaches ccr via hkccr, and the tag
  is the snapshot commit's short sha

#### Scenario: Visibility must match

- **WHEN** the source repository is private
- **THEN** the snapshot target SHALL also be private, and pushing private source
  into a public snapshot repository SHALL be refused

#### Scenario: The build gate must not depend on a developer machine

- **WHEN** the test suite runs on a clean runner
- **THEN** cases requiring a sibling checkout or the `soffice` binary SHALL skip
  with a stated reason rather than fail, and cases MUST NOT depend on a
  developer's absolute home paths or on `pgpass`/trust authentication

### Requirement: Canonical registry path and tag scheme

The published images SHALL live at
`ccr.ccs.tencentyun.com/law-bench/<image>` (referenced by workloads; fed by
the relay from the hk hop). A `sha-<short>` tag SHALL identify exactly the
commit it was built from, and MUST NOT be re-pushed with different content;
`main` SHALL be the rolling tag.

#### Scenario: Manifest references resolve to TCR

- **WHEN** a deployment manifest references
  `ccr.ccs.tencentyun.com/law-bench/law-template:sha-<x>`
- **THEN** that tag exists in the registry (after the relay cycle for
  freshly pushed commits) and was built from commit `<x>`

### Requirement: Cluster pulls from TCR authenticated

Cluster nodes SHALL authenticate to `ccr.ccs.tencentyun.com` via node-level
`registries.yaml` configuration (landed 2026-09-30 fleet-wide), so any node
can pull any workload image without a pre-imported local containerd copy and
without a per-pod imagePullSecret. The web deployment and the
assistant-MCP deployment SHALL use TCR image references; legacy
`imagePullSecrets: tcr-pull` entries already in manifests are harmless and
MAY remain.

#### Scenario: First pull on a cold node

- **WHEN** a pod referencing a TCR image is scheduled on a node that has
  never held that image
- **THEN** kubelet pulls it successfully via the node-level registry
  authentication, without manifesting `ImagePullBackOff`

### Requirement: Deploy trigger stays the Gitee manifest bump

A production deploy SHALL remain: bump the image tag in the top-level
`deploy/*.yaml` manifests and push to the Gitee repository, which the ArgoCD
`law-bench` application watches. The GitHub repository hosts code and CI but
MUST NOT be an ArgoCD application source (cluster nodes cannot reach
github.com). Pushing code without a manifest tag bump SHALL NOT roll pods.
A freshly published ccr tag SHALL be allowed its relay cycle (≤5 min) before
manifests reference it, to avoid `ImagePullBackOff`.

#### Scenario: Roll by tag bump

- **WHEN** a commit that changes only the image tag in `deploy/deployment.yaml`
  is pushed to Gitee
- **THEN** ArgoCD syncs and the web pod runs the referenced TCR tag

#### Scenario: Code-only push does not roll

- **WHEN** a code commit is pushed without a manifest image-tag change
- **THEN** the running pods keep their current images

### Requirement: Dual-track rollback to Harbor remains available

Rolling back SHALL NOT require rebuilding anything. There are exactly two
supported rollback paths, both verified to exist:

1. **Flip the manifest to an image tag that already exists** (TCR
   `ccr.ccs.tencentyun.com/law-bench/...` or Harbor
   `100.64.0.8:30880/law-bench/...`) and push — the next ArgoCD sync schedules
   pods from that image.
2. **Rebuild from the private snapshot repository** (see the build requirement)
   when no suitable existing tag remains.

The system SHALL NOT rely on a standing Jenkins fallback. As of
2026-11-11 there is no Jenkins workload in any cluster (the `jenkins` namespace is empty, nothing
listens on `:31000`, and `jenkins.finddatatech.cloud` resolves to an edge site
with no Caddy route, which answers an empty `200`). A contract that promises a
channel nobody can use is worse than no contract, because during an outage it
replaces a real decision with a dead-end search.

#### Scenario: Rollback by manifest flip

- **WHEN** a TCR-sourced roll misbehaves and the manifest references are
  flipped back to a tag that already exists in TCR or Harbor
- **THEN** the next ArgoCD sync schedules pods from that image, with no rebuild
  involved

#### Scenario: No usable tag remains

- **WHEN** no existing tag is acceptable and a new image is required
- **THEN** the build goes through the private snapshot channel, not through a
  Jenkins job

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
