# Design: adapt-compare-matrix-overflow

## Context

The matrix lives in `#compare-result` (panel) in `compare_detail.html`; `table.matrix` styles put `white-space: nowrap` on `thead th` and `td.cell`. With 4+ columns of long bilingual titles the table exceeds the 980px container.

## Decisions

1. **Wrapper div (`overflow-x: auto`), not panel-level overflow.** Scoping the scroll to the table container keeps the headline/legend glued to the panel width while only the table scrolls. Alternative rejected: `overflow-x` on the panel — would also scroll the headline and legend, coupling unrelated content.
2. **Table `min-width: 40rem` (640px).** Keeps criterion column + 2–3 verdict columns legible on narrow viewports; wide matrices expand past it and scroll. Alternative rejected: per-column min-widths — more precise but more knobs for the same outcome at this data shape.
3. **Wrap only the muted subline.** `thead th` keeps nowrap so the display title stays single-line; `thead th .muted` (the raw prompt name) gets `white-space: normal` + `overflow-wrap: anywhere` so long names grow the row, not the table. Verdict cells (`✓ 通过`, `k/N`) stay nowrap — they are the data.
4. **No sticky first column / header.** Sticky positioning inside a scroll container plus the fully-ruled grid doubles CSS complexity for a solo-operator tool where scroll-back is cheap. Revisit if matrices routinely exceed ~8 columns.

## Risks / Trade-offs

- [Scroll container hides the rightmost columns on first paint] → Mitigation: a subtle scroll affordance is unnecessary at 2–4 visible columns; revisit if adoption shows users missing content.

## Migration Plan

Client-only, rollback = revert.
