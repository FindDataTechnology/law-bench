# Design: harden-compare-flow

## Context

See proposal.md for motivation (critique snapshot, 22/40, three P1s). Today the compare launch form is a flat panel (`compare_form.html`) whose submit path lives in `initCompareForm()` (`app.js:197`): min-2 checked client-side but surfaced only in a muted span after pressing submit; a synchronous `POST /api/compare` with no abort, timer, or progress; auto-redirect on success. The result matrix renders in the compare-detail path of `app.js` with click-only `td.cell` triggers. `data-contract-type` is already emitted on every prompt checkbox but never read. The design system (DESIGN.md) commits: flat surfaces, 1px borders, tint-pair states, tokens only (incl. `objection-red-deep #b91c1c`), no new colors, no shadows.

## Goals / Non-Goals

**Goals:**
- Stop invalid experiments before they cost a drafting+judging cycle, without changing the API contract or `src/eval/compare.py`.
- Make the wait legible and recoverable (elapsed, cancel, no accidental duplicates).
- Make the signature interaction (cell → reasoning) keyboard- and screen-reader-operable inside the committed token palette.

**Non-Goals:**
- Async job API / true server-side progress (the API stays synchronous; the API docstring's CLI recommendation for huge runs stands).
- Server-side contract_type validation (MCP/CLI callers keep free strings; guidance is a web-UI concern).
- Dashboard re-tokenization, matrix overflow wrapper, permalink cells (queued for later passes).

## Decisions

1. **`contract_type` becomes `<input list=…>` + `<datalist>`, not a `<select>`.**
   The API and DB treat contract_type as a free string; prompts can exist for types absent from any catalog. A datalist gives catalog suggestions (from the page context's distinct prompt contract types, labeled via `label_for('contract_type', …)`) while preserving free text — zero breakage for edge seeds. A select would either lie (implying a closed set) or need an "other…" escape hatch. The route handler passes one extra context value (`contract_types`); no new endpoint.

2. **Checklist filter via the existing `data-contract-type`, checked-state preserved.**
   The filter is a small select ("全部类型" + distinct types). Hiding is `hidden` attribute on `.check` rows; checkbox state is untouched by filtering, so WIP restore and the counter stay correct. Counter text lives in a dedicated `#compare-count` element next to the prompts label, updated on every change; submit button gets `disabled` + the existing `.disabled` style below 2. (Keyboard/AT users get the count as part of the label text, not only color.)

3. **Rubric guidance is ordering, not filtering.** Rubric options whose name embeds the chosen type (`contract_<type>_v…`) float to the top with a subtle `(推荐)` suffix; others remain selectable (cross-type rubric use is legitimate today and the spec doesn't forbid it). Chosen over hard filtering because rubric↔type mapping is naming convention, not enforced schema.

4. **Run instrumentation is client-only; cancel = `AbortController`.**
   Timer: `setInterval` 1s into the status line (`已运行 m:ss`), cleared on settle. Cancel: one button next to Run that calls `controller.abort()`; on abort the UI returns to editable, states "等待已取消，服务器可能仍在运行；配置已保留" — honest about server semantics per the spec's no-false-claim clause. Progress beyond elapsed time would require server events; that's the non-goal async API. WIP already persists on input, but the cancel/error path now says so explicitly.

5. **Duplicate-resubmit guard keyed on request-body hash in `sessionStorage`.**
   On error/abort, store `JSON.stringify(body)` hash under `compare:lastAttempt`. On next submit with an identical body, `confirm()`-style inline dialog (localized) before firing. Changed config skips the gate. Chosen over server idempotency keys: no API change, covers the realistic double-fire (retry after network error), and the failure mode of the guard (session cleared) is merely losing an extra confirmation.

6. **Matrix cells: `<button class="cell-btn">` inside the `<td>`, tint on the button.**
   Button inherits the cell's tint background and text color, keeps the padding so the visual grammar is unchanged; `:focus-visible` gets a 2px `bench-blue` outline (flat, no shadow, token-only). Panels (`#compare-reasoning`, `#compare-draft`) get Esc handling + focus restore to the opener (tracked in a variable at open time). `#compare-status` and `#compare-meta` get `role="status"` / `aria-live="polite"`.

7. **Contrast fix by token swap, not a new color.**
   Fail-cell text moves `objection-red → objection-red-deep` (#b91c1c on #fef2f2 ≈ 5.9:1, AA at 0.85rem/600). Matrix header th keeps Muted Slate but the header fill stays #f5f7fa (measured ≈4.5:1 borderline) → header text darkens to `ledger-ink` instead (bold uppercase small caps read fine in ink; Muted Slate stays for ordinary table headers on white). No new tokens; DESIGN.md's fail-cell line gets a one-word update at archive time.

8. **Checklist becomes `fieldset`/`legend`; placeholders join the i18n catalog.**
   `div.checklist > span label` pattern becomes `fieldset.checklist > legend` (visually identical via existing styles + small legend rule). The two hardcoded placeholders (task zh string, label en string) become `t.form.*_ph` keys — this brings the template into compliance with the *existing* localized-placeholder requirement rather than changing it.

## Risks / Trade-offs

- [Abort doesn't stop server work → orphaned compares still exist] → Mitigation: honest copy (decision 4); the duplicate guard prevents the expensive double-run; true fix is the async API (explicit non-goal, recorded).
- [Datalist UX is uneven across browsers (Safari dropdown behavior)] → Mitigation: suggestions are additive guidance, free text + rubric ordering carry the validation intent; the filter select is the primary navigation aid.
- [`sessionStorage` guard can false-positive after a legit retry of the same config] → Mitigation: it's a confirm, not a block; one click proceeds.
- [Button-in-cell changes markup that `render()` and any DOM-dependent tests assume] → Mitigation: tasks include updating `fd-coding-law-bench-mcp` tests if they assert on `td.cell` structure; detector + manual pass before done.

## Migration Plan

Single deploy; all changes are client/template/route-context level and backward compatible (no API, schema, or service changes). Rollback = revert the commit. localStorage WIP shape is unchanged; cache version not bumped (result rendering change is presentational).

## Open Questions

- None blocking. (Whether to later add true async progress is already decided as a non-goal for this change.)
