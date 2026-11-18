# Design: retoken-dashboard-no-gloss

## Context

DESIGN.md commits: flat, 1px Rule Gray hairlines, tint-pair states, Bench Blue as the only working accent, no gradients/glow, full ruling reserved for the verdict matrix. The dashboard's private style block ignores all of it (Tailwind-ish literals, a gradient, 2px heading rules, fully ruled data tables).

## Decisions

1. **Token substitution table** (old → new): `#f8f9fa`/`--card-bg` fallback → `var(--panel)`; `#e0e0e0` → `var(--border)`; `#666`/`#999` → `var(--muted)`; `#2563eb`/`--primary` fallback → `var(--accent)`; `#f1f5f9` → `#f5f7fa` (the established matrix-header tone); `#000` → `var(--text)`. All `var(--x, fallback)` forms lose their fallbacks — the app defines every custom property at `:root`, and dead fallback literals are what the detector flags.
2. **Status tints remap by meaning, not by nearest hue.** Yellow (`#fef9c3`) has no committed token and must not gain one; the verdict tint family already encodes graded outcomes: all-pass → pass tint (#ecfdf5), ≥80 → no fill (the ✓ and bar carry the signal), ≥50 → rate tint (#eff6ff, "partial"), <50 → fail tint (#fef2f2, "weak"). The old `.high-pass` fill (#f0fdf4) was near-invisible anyway — dropping it loses nothing.
3. **The pass-bar: flat Bench Blue, no motion.** Gradient → `var(--accent)` fill (blue is the system's data accent, same as rate cells); track → `#f5f7fa` with a Rule Gray hairline; `transition: width` deleted rather than converted to transform — a static bar is honest, and the system ships no scattered transitions today. The centered percentage text stays, now `var(--text)`.
4. **Data tables return to system grammar**: row rules only (drop the full-border override), header tone #f5f7fa, weights via the global th styles. The dashboard's tables are ordinary data tables, not verdict matrices.
5. **Rem rhythm**: px values convert to the app's scale (16px→1rem, 20px→1.25rem, 8px→0.5rem, 12px→0.75rem, 32px→2rem); the 2px heading underline becomes the system's 1px hairline.

## Risks / Trade-offs

- [Losing the yellow "mid" tint changes the visual grading] → Mitigation: the four levels remain distinguishable (green fill / none / blue tint / red tint) and now match the verdict grammar the operator already reads in the compare matrix.

## Migration Plan

Client-only, rollback = revert.
