## MODIFIED Requirements

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
