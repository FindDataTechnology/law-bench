## Context

The pre-regrounding `judge_c_gold.jsonl` (1969 rows, materialized before commit `7df5f14`) carried an input-leak: `bootstrap_gold_from_evals.py::_extract_clause_text` fell back to `reasoning[:200]` (the judge's own justification) when no quoted fragment was found, so ~32% of rows had `clause_text.body` derived from the target `reasoning.justification`. That leak was repaired at the source level by regrounding on `pipeline_runs.filled_text`, yielding two individually-clean source datasets:

- `judge_c_gold.grounded.jsonl` — 1074 rows, provenance id `seed:bootstrap:run:{eval_run_id}:crit:{criterion}`, `legal_base` sourced from rubric criteria.
- `judge_c_gold.ai_reviewer.jsonl` — 1187 rows, provenance id `gold:ai_reviewer:{ct}:{rule_id}:{pr_id}`, grounded from `pipeline_runs:{pr_id}.filled_text`.

The two sources are disjoint by construction (different id schemes, different provenance fields), union = 2261 rows, 0% leak, pass=1208 / fail=1053. But the canonical materialized file `judge_c_gold.jsonl` still reflected the stale 1969-row leaked artifact, the flywheel gate was passing on it, and 7 contract types (310 pairs) remained ungenerated because the `ai_reviewer` generation run stalled at 1187/1497 when the upstream gateway's completion pools went down. See `proposal.md - Why` for motivation.

Existing tooling is already sufficient: `export_dataset.py` (materialize + gate), `generate_ai_reviewer_gold.py` (resume-safe generation), `verify_expand.py` (13-check acceptance suite), and `validate_quadruple` (already accepts `human` / `ai_reviewer` / `machine_self_eval` reviewer tiers with `ai_reviewer`-can-produce-pass). No code change is required — this change consumes existing tooling.

## Goals / Non-Goals

**Goals:**

- Produce one canonical, leak-free Judge-C gold file assembled exclusively from the two 0%-leak source datasets, so the flywheel gate and SFT pipeline consume a single clean artifact.
- Make the flywheel gate key off the clean grounded superset (`judge_c_gold.grounded.jsonl`), not the stale materialized file.
- Define `ai_reviewer` resume-safe generation as the instrument for closing the 310-pair coverage gap, so an interrupted run can continue after gateway recovery without re-judging done pairs or corrupting the gold file.
- Codify the leak definition (`clause_text.body` derived from `reasoning.justification`) and the drop-not-down-weight rule as spec-level behavior, so a future regression is caught at the schema/gate level.
- Capture the `ai_reviewer`-can-produce-pass verdict rule explicitly in the spec (already enforced by `validate_quadruple`, now documented as observable behavior).

**Non-Goals:**

- No change to `validate_quadruple`, `flywheel_gate`, the four-tier routing, or completion-only loss masking. These are consumed, not modified.
- No new capability. This tightens an existing requirement of `finetune-data-flywheel`; it does not introduce a new spec.
- No change to the bronze tier rules. Bronze remains `verdict=fail`, never ground truth, generated from `eval_criteria_results` for failure analysis only.
- No new generator or data source. The `ai_reviewer` generator is unchanged; only its resume contract is documented.
- No Drafter-A changes. Drafter-A is downstream of the flywheel order and untouched by this change.

## Decisions

### Decision 1: Merge two disjoint 0%-leak sources into one canonical gold superset, rather than re-materializing from a single source.

**Rationale:** The two sources use disjoint provenance id schemes and were independently verified 0% leak. Merging preserves both coverage (grounded rows cover `eval_runs`-derived judgments with rubric `legal_base`; `ai_reviewer` rows cover fresh LLM judgments on real filled contracts) without introducing a new leak surface. Union dedup by `provenance.id` is a no-op because the id schemes never collide (`seed:bootstrap:*` vs `gold:ai_reviewer:*`).

**Alternatives considered:**

- *Re-run `bootstrap_gold_from_evals` from scratch after the `7df5f14` repair.* Rejected: 895 of the original 1969 rows were unrecoverable (their source `eval_runs` no longer map cleanly), and re-running would not produce the `ai_reviewer` pass-class rows that fresh LLM judgment provides.
- *Keep the two sources separate and have the gate read both.* Rejected: the canonical file is the SFT input; a two-file gate complicates the SFT loader and invites drift between the two sources and the materialized file. One merged superset is the single source of truth.

### Decision 2: Drop leaked rows, do not down-weight or repair them.

**Rationale:** A leaked row is anti-supervision — the model is trained to predict a justification it has already seen in the input, which is the inverse of the judge task. Down-weighting still exposes the model to the leak; only dropping removes it. The 895 unrecoverable rows from the pre-regrounding artifact are therefore dropped, not repaired.

**Alternatives considered:**

- *Strip the leaked portion from `clause_text.body`.* Rejected: the leaked body is the entire body in the worst rows (body == justification verbatim); stripping leaves an empty input, which fails schema validation anyway. The drop outcome is identical but the repair is more complex and error-prone.

### Decision 3: The gate prefers `judge_c_gold.grounded.jsonl` and warns when falling back to `judge_c_gold.jsonl`.

**Rationale:** `grounded.jsonl` is the post-regrounding clean artifact; `judge_c_gold.jsonl` is the materialized SFT input that may lag behind. Keying the gate on `grounded.jsonl` means the gate reflects the cleanest available state. The fallback-with-warning path (already in `flywheel_gate()`) preserves backward compatibility if `grounded.jsonl` is absent, but makes the staleness visible.

**Alternatives considered:**

- *Gate on `judge_c_gold.jsonl` only.* Rejected: this is the file that carried the leak. Keying the gate on it would re-expose the pipeline to a stale-leak pass.
- *Gate on a checksum of both files.* Rejected: over-engineering for a single-binary gate decision. The grounded superset is the authoritative input.

### Decision 4: `ai_reviewer` generation is resume-safe by provenance id, not by output line count.

**Rationale:** `_load_done_ids` reads `provenance.id` from the existing output and skips pairs whose id is already present. This is robust to reordering, partial last-line writes, and output file truncation. Line-count-based resume would break if the output were ever re-sorted or truncated mid-write. The id `gold:ai_reviewer:{ct}:{rule_id}:{pr_id}` is a stable function of the pair, so the same pair always produces the same id.

**Alternatives considered:**

- *Checkpoint file with a separate progress log.* Rejected: a separate checkpoint is a second source of truth that can drift from the output file. Reading the output itself is canonical.
- *`--no-resume` always.* Rejected: re-judging 1187 done pairs wastes gateway quota and risks divergent verdicts on re-judge (temperature=0 is not bit-identical across provider retries).

### Decision 5: Remove the 4 scratch probe scripts as part of this change, not in a separate cleanup.

**Rationale:** `_probe_endpoints.py`, `_probe_clusters.py`, `_probe_models.py`, `_probe_judge_capability.py` are diagnostic-only scripts created during gateway troubleshooting. They are not part of the pipeline, must not ship, and are coupled to the gateway-down incident that blocked the 310-pair completion. Removing them in the same change keeps the change self-contained: when applied elsewhere, the recipient does not inherit diagnostic scratch.

**Alternatives considered:**

- *Move to a `scripts/finetune/_scratch/` dir and gitignore.* Rejected: diagnostic scripts that are gitignored are still present on disk and can be accidentally run against production endpoints. Deletion is cleaner.

## Risks / Trade-offs

- **[Gateway-down blocks the 310-pair completion]** The remaining 310 pairs across 7 contract types (sale 123, technology 54, tourism_service 36, transport 15, utilities_supply 42, warehousing 24, work 16) cannot be generated until the upstream gateway recovers. → *Mitigation:* the change is structurally complete at 2261 rows + open gate; the 310 pairs are an additive resume, not a blocker for Judge-C SFT readiness. The resume-safe contract means the run picks up where it left off once the gateway returns. No manual reconciliation is needed.
- **[Leak regression is not machine-enforced at the gate]** The spec mandates 0% leak, but `flywheel_gate()` checks non-emptiness, not leak rate. A future regrounding bug could re-introduce a leak and the gate would still pass. → *Mitigation:* `verify_expand.py` is the acceptance suite and is run as part of this change; a dedicated leak assertion (`clause_text.body != reasoning.justification` for all rows) should be added to a future change if leak-rate enforcement at the gate is desired. For now, the 0%-leak guarantee is established at materialization time by sourcing only from the two verified-clean sources.
- **[Disjoint-union assumption depends on id schemes not colliding]** The 0-overlap claim holds because `seed:bootstrap:*` and `gold:ai_reviewer:*` are structurally distinct. If a future source introduces a third id scheme that collides, dedup-by-id could drop rows silently. → *Mitigation:* the merged file is produced by a one-shot merge script (not a long-running service), and the union count (2261) is verified against the sum of source counts (1074 + 1187) at materialization time.
- **[`ai_reviewer` verdicts are LLM-dependent]** Fresh `ai_reviewer` pass/fail verdicts depend on the judging model. If the model changes between resume runs, a pair judged `fail` in run 1 and `pass` in run 2 (after resume) would produce inconsistent verdicts. → *Mitigation:* resume skips done pairs by id, so a pair is judged exactly once per output file. Re-judgment only happens with `--no-resume`, which is an explicit operator action.

## Migration Plan

1. **Pre-flight (already complete in source environment):** Confirm `judge_c_gold.grounded.jsonl` (1074 rows) and `judge_c_gold.ai_reviewer.jsonl` (1187 rows) are each 0% leak. Confirm union = 2261, 0 overlap.
2. **Merge:** Concatenate the two sources, dedup by `provenance.id` (no-op given disjoint schemes), write `judge_c_gold.merged.jsonl` (2261 rows).
3. **Materialize:** `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/export_dataset.py judge-c --gold judge_c_gold.merged.jsonl` — this rebuilds `judge_c_gold.jsonl` (2261) and `judge_c_bronze.jsonl` (9134) from the clean merged source.
4. **Promote to grounded:** Copy `judge_c_gold.merged.jsonl` → `judge_c_gold.grounded.jsonl` so the gate keys off the clean superset.
5. **Open gate:** `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/export_dataset.py gate` — confirm it reports the 2261-row grounded gold and returns OPEN.
6. **Acceptance:** `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/verify_expand.py` — confirm all 13 checks pass, including the gate open/close behavior (§5.3 stashes both gold files in `.verify-bak` and restores them in `finally`).
7. **Cleanup:** Delete `_probe_endpoints.py`, `_probe_clusters.py`, `_probe_models.py`, `_probe_judge_capability.py` from `scripts/finetune/`.
8. **Resume (when gateway recovers):** `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/generate_ai_reviewer_gold.py --model openai/cursor-grok-4.6-medium --workers 8` — resume-safe, skips the 1187 done pairs, judges the 310 pending. Re-materialize (steps 3–5) after it completes.

**Rollback:** Restore the pre-change `judge_c_gold.jsonl` and `judge_c_gold.grounded.jsonl` from version control or the `.verify-bak` stash. The 4 deleted probe scripts are recoverable from git history. No database or external-system state is mutated by this change, so rollback is purely file-level.

## Open Questions

- Whether to add a dedicated leak-rate assertion to `flywheel_gate()` (currently non-emptiness only) is deferred to a future change. This change establishes the 0%-leak guarantee at materialization time by sourcing only from verified-clean sources; gate-level leak enforcement is not required for SFT readiness.
