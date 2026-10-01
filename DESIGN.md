---
name: 评估规则管理器 — Law-Bench
description: The evidence ledger for Chinese legal-contract evaluation — clause curation, LLM-judge scoring, and prompt compares in one calm, flat workbench.
colors:
  bench-blue: "#2563eb"
  bench-blue-deep: "#1d4ed8"
  verdict-green: "#047857"
  objection-red: "#dc2626"
  objection-red-deep: "#b91c1c"
  harbor-violet: "#7c3aed"
  citation-cyan: "#0891b2"
  citation-cyan-deep: "#155e75"
  ledger-gray: "#f6f7f9"
  panel-white: "#ffffff"
  rule-gray: "#e2e5ea"
  ledger-ink: "#1f2933"
  muted-slate: "#6b7280"
  nested-paper: "#fbfcfd"
  pass-tint: "#ecfdf5"
  fail-tint: "#fef2f2"
  rate-tint: "#eff6ff"
typography:
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "1.4rem"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "0.8rem"
    fontWeight: 700
    letterSpacing: "0.03em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "8px"
  pill: "999px"
spacing:
  xs: "0.3rem"
  sm: "0.6rem"
  md: "0.8rem"
  lg: "1.25rem"
components:
  button-primary:
    backgroundColor: "{colors.bench-blue}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "0.4rem 0.8rem"
  button-primary-hover:
    backgroundColor: "{colors.bench-blue-deep}"
  button-default:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ledger-ink}"
    rounded: "{rounded.md}"
    padding: "0.4rem 0.8rem"
  button-default-hover:
    backgroundColor: "#f0f2f5"
  button-danger:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.objection-red}"
    rounded: "{rounded.md}"
    padding: "0.4rem 0.8rem"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ledger-ink}"
    rounded: "{rounded.md}"
    padding: "0.4rem 0.8rem"
  badge-default:
    backgroundColor: "#eef1f5"
    textColor: "{colors.ledger-ink}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.45rem"
  badge-harbor:
    backgroundColor: "{colors.harbor-violet}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.45rem"
  badge-local:
    backgroundColor: "{colors.citation-cyan-deep}"
    textColor: "{colors.panel-white}"
    rounded: "{rounded.pill}"
    padding: "0.1rem 0.45rem"
  panel:
    backgroundColor: "{colors.panel-white}"
    rounded: "{rounded.md}"
    padding: "1.25rem"
  input:
    backgroundColor: "{colors.panel-white}"
    textColor: "{colors.ledger-ink}"
    rounded: "{rounded.md}"
    padding: "0.45rem 0.55rem"
---

# Design System: 评估规则管理器 — Law-Bench

## Overview

**Creative North Star: "The Evidence Ledger"**

This is a workbench, not a brochure. Every screen is a page in a ledger where evaluation evidence gets recorded: rubrics, prompts, clauses, verdict matrices, compare runs. The interface stays utilitarian and calm — dense but breathing — so a solo operator can move from curation to judgment to comparison without the chrome ever raising its voice. Structure is carried entirely by 1px rules and background tints on a light paper field; there are no shadows, no gradients, and no decoration.

The loudest element on any page is allowed to be data: the tinted pass/fail/rate cells of the verdict matrix, the green/red flash strips, the violet and cyan category badges. Controls are compact and predictable — quiet white panels on Ledger Gray, restrained buttons, plain system type with PingFang SC / Microsoft YaHei keeping Chinese text crisp.

Confirmed visual anti-reference: marketing-page gloss. No gradients, glassmorphism, glow effects, or hero imagery — ever.

**Key Characteristics:**
- Flat by conviction: zero shadows; 1px Rule Gray borders and tonal paper steps carry all structure
- One accent (Bench Blue) for links, the primary action, and rate data — everything else is neutral or semantic
- State speaks through tint + text color (pass/fail/rate cells, flash strips), never through heavier chrome
- Compact, information-first density inside white panels on a 980px single column
- System font stacks only; monospace for prompt/draft bodies; no webfonts, no icon sets

## Colors

A cool, paper-quiet neutral field with one decisive blue accent, two category violets/cyans, and semantic green/red reserved for verdicts.

### Primary
- **Bench Blue** (#2563eb): The working accent — links, primary buttons, and rate-cell data in the verdict matrix. Its rarity is the point.
- **Bench Blue, Deep** (#1d4ed8): Primary-button hover state only.

### Secondary
- **Harbor Violet** (#7c3aed): Category marker for harbor-sourced rubrics — badges and the violet readonly-note strip.
- **Citation Cyan** (#0891b2): Category marker for local-sourced rubrics; **Citation Cyan, Deep** (#155e75) is its badge step — darkened so white 0.72rem badge text clears AA.

### Tertiary
- **Verdict Green** (#047857): Pass states — ok flash text, pass-cell text.
- **Objection Red** (#dc2626): Destructive actions and fail states; **Objection Red, Deep** (#b91c1c) is its button-hover step.
- **Verdict tints** — pass (#ecfdf5), fail (#fef2f2), rate (#eff6ff): background fields for matrix cells and flash strips; they pair with their semantic text color, never stand alone.

### Neutral
- **Ledger Gray** (#f6f7f9): Page background — the paper the ledger is written on.
- **Panel White** (#ffffff): Every panel, button default, and input surface.
- **Rule Gray** (#e2e5ea): All 1px borders, dividers, and table rules.
- **Nested Paper** (#fbfcfd): Slightly shaded surface for content nested inside a panel (criterion rows, checklists, mode fieldsets, matrix header).
- **Ledger Ink** (#1f2933): Primary text.
- **Muted Slate** (#6b7280): Secondary text, labels, hints, table headers.

### Named Rules
**The No-Gloss Rule.** No gradients, glassmorphism, glow effects, or hero imagery, anywhere. The ledger is matte paper.
**The Tint Verdict Rule.** Evaluation outcomes are expressed as a background tint paired with a semantic text color — never as icons, badges with new hues, or heavier borders.

## Typography

**Display Font:** none — the system stack is the display voice.
**Body Font:** `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif`
**Label/Mono Font:** `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` for prompt/draft bodies and inline code.

**Character:** Native and quiet — every OS renders its own face, with PingFang SC / Microsoft YaHei keeping Chinese first-class. Hierarchy comes from size and muted color, never from a second typeface.

### Hierarchy
- **Title** (700, 1.4rem, 1.3): Page title (`h1`); the brand in the topbar runs 1.05rem/700.
- **Section** (700, browser default ~1.5rem/1.17em, 1.3): `h2`/`h3` inside panels — kept small on purpose.
- **Body** (400, 1rem, 1.5): Everything; rendered markdown bodies run 1.6 for long reading.
- **Label** (700, 0.8rem, 0.03em tracking, uppercase in table headers, Muted Slate): Field labels, table headers, legends; hints drop to 0.78rem/400.
- **Mono** (400, 0.9rem, 1.5): Prompt and draft bodies, pre-wrapped with `overflow-wrap: anywhere`; inline code at 4px-radius chip.

### Named Rules
**The System-Stack Rule.** No webfonts, ever. Latin and Chinese share the system stack; monospace is the only second voice, reserved for raw model text.

## Layout

One column, one rhythm. A full-width white topbar (1px bottom rule) carries the brand, eleven scope-gated nav links, a divided zh/en language switch, and a divided signed-in identity slot (a lone login link when anonymous); it wraps rather than collapses — below 1024px the brand takes the first row alone with the nav flowing beneath as tidy wrapped rows (0.45rem row gap), and below 560px the language switch and identity drop to their own full-width row with the divider rule removed. Below it, a single centered container (max 980px, 1.25rem gutters, 1.5rem top margin; gutters and panel padding step to 0.9rem below 720px) stacks white panels with 1.25rem gaps. Inside panels, density is compact: controls pad 0.4–0.55rem, rows gap 0.3–0.8rem, definition lists run a 9rem label column (6rem below 720px). Two-column moments exist only inside panels — side-by-side law-info detail (1fr 1fr, collapses at 900px), generation inputs (1fr 1fr, collapses at 720px), filter forms that wrap per-group (flex → column at 720px); toolbars stack at 560px. Wide tables never break the page: the verdict matrix keeps its 40rem min-width inside `.matrix-scroll`, and below 720px every other panel table becomes its own horizontal scroll container (`display: block; overflow-x: auto`) with row rules and header styling untouched. Touch is served by `pointer: coarse` — buttons, nav links, inputs, and checkboxes get 2.4rem (1.25rem for checks) minimum hit areas with the same flat styling; no hamburger, no hidden navigation, the link bar just wraps. Everything else is a bordered table or a stacked form; long content wraps within the panel, never overflows it.

## Elevation & Depth

There are no shadows in this system — flat is the doctrine. Depth is conveyed by exactly two devices: 1px Rule Gray borders that separate surfaces, and tonal paper steps (Panel White → Nested Paper #fbfcfd → matrix-header #f5f7fa) that nest content one level inside a panel. Hover does not lift; it either darkens the fill (buttons: #f0f2f5) or deepens the accent. Floating layers, if ever needed, would follow the same grammar: a border plus a tinted field, not a blur beneath.

### Shadow Vocabulary
None. State it plainly: this system ships zero box-shadows and keeps it that way.

### Named Rules
**The Flat-Ledger Rule.** Surfaces are flat at rest, on hover, and in every menu, modal, and toast that will ever be added. Structure comes from rules and tints, never from drop shadows.

## Shapes

One radius for everything interactive — 8px (`--radius`) on panels, buttons, inputs, fieldsets, flash strips, nested rows. A micro-radius (4px) softens inline code chips; badges are the only full pills (999px). All edges are hairline: 1px solid Rule Gray everywhere, with no thicker borders, no double rules, and no clipped or diagonal silhouettes. The form language is rectangular paper with softly dulled corners — nothing more.

## Components

Restrained, compact, quietly confident: controls stay understated so tinted verdicts stay the loudest thing on the page.

### Buttons
- **Shape:** dulled rectangle (8px radius)
- **Primary:** Bench Blue fill, white text, 0.4rem 0.8rem padding; hover deepens to Bench Blue Deep
- **Default:** Panel White fill, Rule Gray border, Ledger Ink text; hover fill #f0f2f5
- **Danger:** white ghost with Objection Red text; hover fills fail-tint #fef2f2
- **Ghost:** transparent fill, otherwise default; small variant drops to 0.82rem/0.2rem 0.5rem
- **Disabled:** opacity 0.5, pointer-events none — no color shifts
- **Focus:** browser default ring; no custom treatment today

### Chips
- **Badges:** full pill (999px), 0.72rem/600; three voices — default (Ledger Ink on #eef1f5, the neutral chip for prompt types and law sources), Harbor Violet with white text (harbor-sourced), Citation Cyan Deep #155e75 with white text (local-sourced, darkened for AA); no selected/unselected states — they are static category marks. A badge never ships without a background.

### Cards / Containers
- **Panel:** Panel White, 1px Rule Gray border, 8px radius, 1.25rem padding, stacked 1.25rem apart
- **Nested rows** (criterion rows, checklists, mode fieldsets): Nested Paper fill, 1px border, 8px radius, 0.6–0.75rem padding — one level of nesting only, never two

### Inputs / Fields
- **Style:** white fill, 1px Rule Gray border, 8px radius, 0.45rem 0.55rem padding; labels 0.8rem Muted Slate above, hints 0.78rem below
- **Focus:** browser default; **Error:** via fail-tint flash strip, not field chrome
- **Textareas:** min-height 4.5rem, vertical resize

### Navigation
- White topbar, 1px bottom rule, 0.75rem 1.25rem padding; brand 1.05rem/700; eleven plain links at 0.85rem gaps, rendered only for identities holding `content:read`; the current page is marked by `aria-current="page"` — ink text, 700, and a flat 2px Bench Blue underline; zh/en switch divided by a left rule, current language 700, other at 60% opacity; a signed-in identity slot divided by the same left rule (0.9rem; muted label, ink name, logout link — or a single login link when anonymous, doubling as the login affordance); the bar wraps on narrow widths

### Verdict Matrix (signature)
The compare matrix is the system's signature: a fully ruled table (1px borders on every cell, not just row rules), Nested Paper header row (ink text, uppercase 0.8rem labels), and center-aligned 600-weight verdict cells that speak only in tint pairs — pass (Verdict Green on #ecfdf5), fail (Objection Red Deep #b91c1c on fail-tint, for AA contrast), rate (Bench Blue on #eff6ff). Each verdict trigger is a real button inside the tinted cell so the interaction is keyboard-operable, with a flat 2px Bench Blue focus ring. A muted caption (0.78rem, top-left) may head the table, and wide matrices keep a 40rem min-width and scroll horizontally inside their panel rather than squeezing columns. Data tables elsewhere stay quieter: row rules only, no vertical borders, no fills.

### Flash Strips
Feedback is a full-width strip under the topbar, each voice a tint pair with a same-family 1px border: info (Ledger Ink on #eef6ff, Rule Gray border), error (Objection Red on fail-tint, #fecaca border), ok (Verdict Green on pass-tint, #a7f3d0 border) — the Tint Verdict Rule applied to messaging. The readonly-note is the violet sibling (Harbor Violet on #f5f3ff, #ddd6fe border, 0.85rem). The rubric-warning is the error pair scaled down to an inline form strip (fail-tint, #fecaca border, Objection Red Deep text, 0.85rem) for rubric/type mismatches.

### Rendered Markdown
Contract bodies and law text render inside panels at 1.6 line-height with anywhere-breaking: `h1` 1.2rem and `h2`/`h3` 1.05rem (700), inline code chips at a 3px radius on #f3f4f6, and blockquotes as a 3px Rule Gray left bar on #fafbfc with #555 text.

### Assistant Island (vendored)
The admin CopilotKit chat island is vendored third-party chrome with its own shadows, radii, and dark theme — the sanctioned exception to the No-Gloss and Flat-Ledger rules. It is themed toward the ledger where its schema allows (error pair = fail tint / #fecaca / Objection Red) and is never a style reference for first-party work.

## Do's and Don'ts

### Do:
- **Do** keep every interactive surface at the 8px radius and 1px Rule Gray borders; nesting gets exactly one tonal step (Nested Paper)
- **Do** express every state — pass, fail, rate, info, error, ok — as a tint paired with its semantic text color
- **Do** keep primary actions in Bench Blue and let links share it; it is the only working accent
- **Do** render prompt/draft bodies in the mono stack with pre-wrap and anywhere-breaking so long model output stays inside its panel
- **Do** keep Chinese-first type (PingFang SC / Microsoft YaHei in the stack) and bilingual zh/en parity on every screen

### Don't:
- **Don't** introduce shadows, gradients, glassmorphism, glow, or hero imagery — confirmed anti-reference
- **Don't** load webfonts, icon sets, or illustration; the system stacks are the whole type system
- **Don't** color code with new hues; category marks are only Harbor Violet and Citation Cyan, verdicts only green/red/blue tints
- **Don't** add vertical borders or fills to ordinary data tables — full ruling is reserved for the verdict matrix
- **Don't** widen the 980px column or break the single-panel rhythm without a collapse step (720px / 900px are the established breakpoints)
