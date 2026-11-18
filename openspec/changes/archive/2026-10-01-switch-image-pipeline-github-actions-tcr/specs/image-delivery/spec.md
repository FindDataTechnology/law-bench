## REMOVED Requirements

### Requirement: Build and publish the main image on push
**Reason**: The delivered tcr-image-pipeline channel (image.yml → hkccr →
relay → ccr) triggers on default-branch pushes and manual dispatch only;
the `v*` tag-push publish path was never implemented, and direct US-runner
→ccr publishing was abandoned (~0.14MB/s, no run ever completed).
**Migration**: Reference the immutable `sha-<short>` tag of any commit, or
the rolling `main` tag; to republish without a push, trigger the image
workflow via `workflow_dispatch`.

## ADDED Requirements

### Requirement: Build and publish the application images on push

The system SHALL build the law-bench application images (`Dockerfile` and
`Dockerfile.render` at repo root) via the repo's GitHub Actions image
workflow (`.github/workflows/image.yml`) whenever a commit is pushed to the
default branch, and on manual dispatch. The workflow SHALL push to the HK
registry hop `hkccr.ccs.tencentyun.com`, from which the cheap-3 tcr-relay
backfills `ccr.ccs.tencentyun.com` within its ≤5-minute sync cycle; direct
US-runner→ccr pushes are a dead path (~0.14MB/s) and MUST NOT be used. The
build MUST NOT depend on the GitHub-hosted runner having access to any
China-side mirror: the Dockerfile's default base image and package indexes
apply unchanged, and no single RUN layer exceeds ~300MB (transpacific blob
uploads wedge).

#### Scenario: Code push to main triggers a published image

- **WHEN** a commit is pushed to the default branch of the GitHub repository
- **THEN** the image workflow builds the images from that commit, pushes
  them to hkccr tagged `sha-<7-char-short-sha>` and `main`, and within one
  relay cycle (≤5 min) the same tags are servable from
  `ccr.ccs.tencentyun.com`

#### Scenario: Manual dispatch republishes

- **WHEN** the image workflow is triggered via `workflow_dispatch`
- **THEN** the same build-and-publish path runs without a push

## MODIFIED Requirements

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

The legacy Jenkins→Harbor channel SHALL remain available as the standing
fallback for image delivery (Jenkins jobs preserved). Rolling back SHALL
NOT require rebuilding anything: flip the manifest image references to a
Harbor tag that exists there (`100.64.0.8:30880/law-bench/...`) and push.

#### Scenario: Rollback by manifest flip

- **WHEN** a TCR-sourced roll misbehaves and the manifest references are
  flipped back to a Harbor tag that already exists
- **THEN** the next ArgoCD sync schedules pods from the Harbor image, with
  no rebuild involved
