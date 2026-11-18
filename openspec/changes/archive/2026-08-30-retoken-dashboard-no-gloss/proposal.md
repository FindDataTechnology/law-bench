# Proposal: retoken-dashboard-no-gloss

## Why

Every detector finding on this codebase (13 of 13, three consecutive scans) lives in `dashboard.html`'s private `<style>` block: 12 literal colors outside DESIGN.md and a `transition: width` layout animation — including a red/amber/green `linear-gradient` that directly violates the confirmed No-Gloss anti-reference. Left alone, the newest page becomes the template future pages copy. The user pre-approved the direction: re-express the same visual intent entirely in committed tokens, no gloss.

## What Changes

- All dashboard styles re-expressed in committed tokens/established literals: stat cards → Panel White + Rule Gray; stat values → Bench Blue accent; muted text → Muted Slate; header rows → the matrix-header tone; borders → Rule Gray hairlines (2px heading rule becomes the system's 1px).
- Status row tints remapped to the verdict tint family by meaning: all-pass → pass tint (#ecfdf5), high → no fill, mid → rate tint (#eff6ff), low → fail tint (#fef2f2). No hues outside the committed palette.
- The pass-bar gradient becomes a flat Bench Blue fill on a Nested-Paper-tone track; the `transition: width` animation is removed (static, honest — no layout-thrash motion).
- Ordinary data tables drop full ruling (row rules only), matching the system's "full ruling is reserved for the verdict matrix" rule; px paddings/gaps move to the app's rem rhythm.
- No markup changes beyond removing nothing — classes stay, so template logic (pass-row/high-pass/mid-pass/low-pass) is untouched.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

(none — pure visual re-expression, no spec-level behavior change; `skip_specs: true`)

## Impact

- `src/web/templates/dashboard.html` — the `<style>` block only.
- Expected: detector findings on `src/web/templates` drop 13 → 0.
