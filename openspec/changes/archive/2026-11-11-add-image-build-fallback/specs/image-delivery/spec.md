## MODIFIED Requirements

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
