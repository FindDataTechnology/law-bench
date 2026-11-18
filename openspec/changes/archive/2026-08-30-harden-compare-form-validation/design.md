# Design: harden-compare-form-validation

## Context

See proposal.md for motivation (critique re-run 29/40, two P2s). The form after `harden-compare-flow`: `initCompareForm()` already validates min-2 with a live counter and clamps `n_drafts`; `orderRubrics()` floats type-matching rubrics to the top but nothing blocks a mismatch. Field labels follow the app-wide `form label` pattern (block-styled siblings, no `for`); only `f-type-filter` is paired. DESIGN.md commits the warning grammar: fail tint (#fef2f2) + deep objection text (#b91c1c), visible text never color alone.

## Goals / Non-Goals

**Goals:** block rubric/type mismatches before they cost a run; make every launch-form field programmatically named.

**Non-Goals:** async run identity and matrix overflow (the two P1s — separate changes); pattern-less rubric policing; server-side validation (MCP/CLI callers keep free strings).

## Decisions

1. **Enforce only the naming convention, not a schema.** The mismatch check fires only when the selected rubric name matches `^contract_([a-z0-9_]+?)_v\d+$` (case-insensitive) — the convention the catalog actually uses. The captured `<type>` must equal the entered `contract_type` (trimmed, case-insensitive). Rubrics outside the convention pass freely: harbor and custom rubrics legitimately exist outside it, and blocking on them would be a false positive. Alternative rejected: filtering the select to matching rubrics only — breaks the "cross-type rubric use is not forbidden" posture the previous change deliberately kept; blocking at submit teaches without trapping.

2. **The mismatch teaches the key.** When the operator typed a localized label (买卖合同) instead of the machine key (`sale`), the warning names both sides ("规则类型 lease（租赁合同）与合同类型 买卖合同 不一致"), which surfaces the correct key implicitly. The datalist already nudges toward keys; this closes the loop at submit. No separate key-normalization magic — explicit beats clever.

3. **Warning surface: a dedicated inline strip under the rubric select**, not the status span. `#compare-rubric-warning` is a small styled div (`display:none` until set) using the committed tokens — fail-tint background, deep objection text, 8px radius — matching the flash/readonly-note family. It carries `role="alert"` so it announces when it appears. Alternative rejected: reusing `#compare-status` (aria-live polite) — a blocking error deserves assertive semantics, and mixing progress and validation copy in one region is what the critique dinged before.

4. **Check placement: submit-time, after the min-2 guard, before the fetch.** Live-checking on every rubric/type keystroke would nag mid-edit; submit-time is when the operator means it. The check runs before `btn.disabled = true` so the form never enters the "running" state on a blocked submit.

5. **Label association via the existing pattern.** Each `<label>` gets `for="<input-id>"`; every input already carries an id (`f-task`, `f-contract_type`, `f-rubric_name`, `f-mode`, `f-n_drafts`, `f-concurrency`, `f-label`). Zero styling change — the CSS targets `form label` element-wide. The checklist fieldset keeps its legend as the accessible name.

## Risks / Trade-offs

- [Convention drift: future rubrics named differently get no protection] → Mitigation: the spec scenario records that type-free rubrics are never blocked; if the convention changes, the regex lives in one place (`initCompareForm`).
- [`role="alert"` + a strip that stays after fixing] → Mitigation: the warning clears on any rubric or contract_type change, and on successful submit there is nothing to clear (block precedes fetch).

## Migration Plan

Single client/template deploy; no API or schema changes; rollback = revert.

## Open Questions

- None.
