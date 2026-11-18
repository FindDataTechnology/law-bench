# Proposal: harden-compare-flow

## Why

The impeccable critique of the prompt-compare surface (`.impeccable/critique/2026-08-29T15-51-08Z__src-web-templates-compare-form-html.md`, 22/40) found three P1 issues: an unvalidated launch form that lets invalid experiments run a full drafting+judging cycle before failing, a synchronous minutes-long run instrumented by one muted sentence with no cancel (refresh orphans a server-side run; retry can duplicate it), and a verdict matrix whose defining interaction — cell → judge reasoning — is unreachable by keyboard or screen reader. The compare flow is the product's signature surface; these gaps cost real evidence and lock out assistive tech.

## What Changes

- **Typed contract type**: the free-text `contract_type` input becomes an input with a `datalist` of known contract types (derived from the prompts table's distinct values, labeled via the existing `data-label-i18n` catalog). The field stays a plain string end-to-end — no API change, no breaking of MCP/CLI callers.
- **Checklist filtering + live count**: the prompt checklist gains a contract-type filter (via the already-present-but-unused `data-contract-type` attributes) and a live "已选 k 个（至少 2）" counter; the submit button disables below 2 with an inline warning instead of a post-submit muted message.
- **Rubric guidance**: when a contract type is set, rubric options whose name matches that type (`contract_<type>_v<N>`) are sorted/recommended; mismatches are not blocked.
- **Run instrumentation**: the submit handler gains an elapsed timer, coarse progress text, a cancel button backed by `AbortController`, and a "配置已保留" reassurance line; on error the WIP is explicitly confirmed saved and resubmission asks before duplicating.
- **Drafts bound**: `n_drafts` gets a max (8) matching concurrency's bound; out-of-range values clamp client-side.
- **Matrix accessibility**: verdict cells become keyboard-focusable buttons inside the `<td>` (tint preserved), reasoning/draft panels close on Esc and restore focus, status/meta regions get `aria-live`, the checklist becomes a real `fieldset`/`legend`, and the fail-cell text contrast is fixed by moving fail-cell text to the existing darker token (objection-red-deep) — no new colors.
- **Copy consistency**: the `mode` option label localizes (`仅起草`) or the row hides while only one mode exists; the hardcoded zh task placeholder and en label placeholder move into the i18n catalog.

Non-goals (recorded for a later pass): dashboard re-tokenization (user-approved direction: re-token, no gloss), matrix horizontal-overflow wrapper (P2), permalink verdict cells, async job API.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `prompt-compare-web`: the Compare Web UI requirement gains form-validation, run-instrumentation, and accessibility scenarios; no API or service behavior changes.

## Impact

- `src/web/templates/compare_form.html` — typed contract_type field, filter control, counter, fieldset, placeholder i18n.
- `src/web/static/app.js` — `initCompareForm()` (validation, counter, filter, abort/timer/progress, duplicate-resubmit guard) and the compare-detail render path (button-in-cell, Esc/focus, aria-live).
- `src/web/static/style.css` — fail-cell text token swap, focus-visible treatment for matrix cell buttons (flat, border-accent — no shadows).
- `src/web/i18n.py` — new zh/en keys (counter, cancel, timer, progress, saved-config, filter, warnings); placeholder strings join the catalog.
- Route context (`src/web/routes/pages.py` or wherever `page_new_compare` builds context) — pass distinct contract types to the template.
- No changes to `src/eval/compare.py`, the JSON API contract, or the database schema.
