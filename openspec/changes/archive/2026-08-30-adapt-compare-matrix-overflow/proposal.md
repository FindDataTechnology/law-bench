# Proposal: adapt-compare-matrix-overflow

## Why

The critique re-run (`.impeccable/critique/2026-08-29T19-50-38Z__src-web-templates-compare-form-html.md`) rated this P1: `white-space: nowrap` on matrix headers and cells with 4+ long bilingual prompt titles overflows the 980px panel — the signature surface's worst failure mode under real data, with no scroll strategy.

## What Changes

- The verdict matrix gets a horizontal-scroll container inside its panel: the table scrolls (`overflow-x: auto`) instead of breaking the layout, with a sensible table min-width.
- The header's muted prompt-name subline may wrap (the localized display title above it stays nowrap); verdict cells keep nowrap.
- No clipping, no new colors, no shadow.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `prompt-compare-web`: ADDED requirement for matrix overflow behavior (the matrix stays fully readable when columns exceed the container).

## Impact

- `src/web/templates/compare_detail.html` — wrap `#compare-matrix` in a scroll container.
- `src/web/static/style.css` — `.matrix-scroll` rules, table min-width, wrappable header subline.
