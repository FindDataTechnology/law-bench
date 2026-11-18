## Why

Judge-C gold training data was stuck: the materialized `judge_c_gold.jsonl` (1969 rows) carried the pre-regrounding input-leak in 32% of its rows (the judge's own justification had been copied into `clause_text.body`), and the fresh `ai_reviewer` generation run stalled at 1187/1497 pairs when the upstream gateway's completion pools went down. Both source datasets are individually clean (0% leak), but no single canonical gold file reflected that — the flywheel gate was passing on a partially-leaked artifact, and 7 contract types (310 pairs) remained ungenerated. This change closes the Judge-C gold path: produce one clean, disjoint, validated gold superset; open the gate on it; verify the 13-check suite; resume generation for the remaining 310 pairs when the gateway recovers; and remove scratch probe scripts that must not ship.

## What Changes

- Build a merged clean gold superset from the two 0%-leak source files (`judge_c_gold.grounded.jsonl` 1074 rows + `judge_c_gold.ai_reviewer.jsonl` 1187 rows), deduplicated by `provenance.id`. The two sources are disjoint by construction (different id schemes: `seed:bootstrap:run:{eval_run_id}:crit:{criterion}` vs `gold:ai_reviewer:{ct}:{rule_id}:{pr_id}`), union = 2261 rows, 0% leak, pass=1208 / fail=1053.
- Re-materialize `data/finetune/judge-c/judge_c_gold.jsonl` from the merged 2261-row superset via `export_dataset.py judge-c --gold merged.jsonl`, replacing the 32%-leaked 1969-row file.
- Promote the merged superset to `judge_c_gold.grounded.jsonl` so `flywheel_gate()` (which prefers `grounded.jsonl`) passes on the clean superset, not the stale materialized file.
- Rebuild `judge_c_bronze.jsonl` (9134 rows, tier=bronze, verdict=fail) alongside the gold materialization so gold+bronze stay in sync.
- Open the flywheel gate (`export_dataset.py gate`) and confirm it reports the 2261-row grounded gold.
- Run `verify_expand.py` (the 13-check suite) against the materialized state to confirm: new-table provenance, bronze-excluded-from-gold, four-tier routing, gold-only reward-positive, silver scaffolds, builder did not re-create gold, and gate open/close behavior.
- Resume the `ai_reviewer` generation run for the remaining 310 pairs across 7 incomplete contract types (sale 123, technology 54, tourism_service 36, transport 15, utilities_supply 42, warehousing 24, work 16) via `generate_ai_reviewer_gold.py --workers 8`. The run is resume-safe (`_load_done_ids` skips the 1187 done pairs); re-materialize after it completes.
- Remove 4 scratch probe scripts (`_probe_endpoints.py`, `_probe_clusters.py`, `_probe_models.py`, `_probe_judge_capability.py`) from `scripts/finetune/` — they are diagnostic-only, never part of the pipeline, and must not be committed.

## Capabilities

### New Capabilities

(none — this change does not introduce a new capability)

### Modified Capabilities

- `finetune-data-flywheel`: the Judge-C gold dataset requirement is tightened to require that the canonical gold file is assembled from leak-free source datasets only, that the flywheel gate keys off the clean grounded superset, and that resume-safe generation of fresh `ai_reviewer` gold is the instrument for closing coverage gaps on incomplete contract types.

## Impact

- **Data artifacts** (`data/finetune/judge-c/`): `judge_c_gold.jsonl` (1969→2261 rows, 32%-leak→0%), `judge_c_gold.grounded.jsonl` (1074→2261 rows), `judge_c_gold.merged.jsonl` (new, 2261 rows), `judge_c_bronze.jsonl` (rebuilt, 9134 rows).
- **Scripts** (`scripts/finetune/`): `generate_ai_reviewer_gold.py` (unchanged, run to completion), `export_dataset.py` (unchanged, used to materialize + gate), `verify_expand.py` (unchanged, run as the acceptance suite). 4 scratch probe scripts deleted.
- **No code/API changes**: this change consumes existing tooling; it does not modify `validate_quadruple`, `flywheel_gate`, the four-tier routing, or the completion-only loss masking. The `ai_reviewer`-can-produce-pass verdict rule (already in `validate_quadruple`) is exercised, not changed.
- **External dependency**: completion of the remaining 310 pairs is blocked on upstream gateway recovery; the change is structurally complete (2261-row gold + open gate) regardless, and the 310 pairs are an additive resume, not a blocker for Judge-C SFT readiness.
