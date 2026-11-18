## 1. Pre-flight verification

- [x] 1.1 Verify `judge_c_gold.grounded.jsonl` (1074 rows) is 0% leak: no row has `clause_text.body` equal to or derived from `reasoning.justification` (verified on the `seed:bootstrap:*` subset of the merged superset — the standalone 1074-row file was already promoted by the earlier run; 1074 rows / 0 leaks)
- [x] 1.2 Verify `judge_c_gold.ai_reviewer.jsonl` (1187 rows) is 0% leak (same check) (1187 rows / 0 leaks)
- [x] 1.3 Confirm the two sources are disjoint: union count (2261) equals sum of source counts (1074 + 1187), 0 overlap by `provenance.id` (overlap=0, union=2261)

## 2. Merge into canonical gold superset

- [x] 2.1 Concatenate `judge_c_gold.grounded.jsonl` + `judge_c_gold.ai_reviewer.jsonl`, dedup by `provenance.id`, write `data/finetune/judge-c/judge_c_gold.merged.jsonl` (expect 2261 rows) (re-run produced a byte-identical file)
- [x] 2.2 Verify the merged superset is 0% leak (same check as 1.1) (0 leaks)
- [x] 2.3 Verify merged verdict breakdown: pass=1208, fail=1053 (confirmed)

## 3. Materialize canonical gold + bronze

- [x] 3.1 Run `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/export_dataset.py judge-c --gold data/finetune/judge-c/judge_c_gold.merged.jsonl` to rebuild `judge_c_gold.jsonl` (2261 rows, replaces the 32%-leaked 1969-row file) and `judge_c_bronze.jsonl` (9134 rows, tier=bronze, verdict=fail)
- [x] 3.2 Confirm `judge_c_gold.jsonl` row count is 2261 and 0% leak (2261 unique ids, 0 leaks, parse-equal to merged)
- [x] 3.3 Confirm `judge_c_bronze.jsonl` row count is 9134 and all rows are `tier: bronze`, `verdict: fail` (9134/9134/9134)

## 4. Promote to grounded + open flywheel gate

- [x] 4.1 Copy `judge_c_gold.merged.jsonl` -> `judge_c_gold.grounded.jsonl` so the gate keys off the clean superset
- [x] 4.2 Run `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/export_dataset.py gate`
- [x] 4.3 Confirm the gate reports the 2261-row grounded gold and returns OPEN (✅ 飞轮闸门通过: Judge-C gold 有 2261 条四元组 (judge_c_gold.grounded.jsonl), exit 0)

## 5. Acceptance suite

- [x] 5.1 Run `uv run --no-project --with litellm --with python-dotenv python -X utf8 scripts/finetune/verify_expand.py` (the 13-check suite) (ALL CHECKS PASSED, exit 0)
- [x] 5.2 Confirm all 13 checks pass, including: new-table provenance (§2.1), bronze-excluded-from-gold (§2.2), four-tier routing (§2.3), gold-only reward-positive (§3.4), silver scaffolds (§6.1), builder did not re-create gold (§4.4), and gate open/close behavior (§5.3 - stashes both gold files in `.verify-bak`, restores in `finally`) (12 printed PASS checks, all green; both gold files restored at 2261 rows)
- [x] 5.3 Confirm no scratch artifacts left behind in `.verify-bak` after the suite's `finally` restoration (no leftovers)

## 6. Scratch probe script cleanup

- [x] 6.1 Delete `scripts/finetune/_probe_endpoints.py`
- [x] 6.2 Delete `scripts/finetune/_probe_clusters.py`
- [x] 6.3 Delete `scripts/finetune/_probe_models.py`
- [x] 6.4 Delete `scripts/finetune/_probe_judge_capability.py`
- [x] 6.5 Confirm `git status` shows the 4 probe scripts as deleted (untracked `_sample_seeds.py` is unrelated, leave it) (deviation: the 4 probes were untracked, so they show no `D` lines — they are gone from disk and absent from `git status scripts/finetune/`; `_sample_seeds.py` does not exist in this tree)

## 7. Resume ai_reviewer generation (blocked on gateway recovery)

- [x] 7.1 Confirm the upstream gateway completion endpoint is healthy (probe `OPENAI_API_BASE/v1/chat/completions` with the configured `EVAL_MODEL`); do not proceed until it returns 200 (old relay 154.94.237.22:3000 stayed dead; `.env` switched to `http://124.223.42.3:31800/v1` — probe with EVAL_MODEL's kimi-k3 returned 200)
- [x] 7.2 Run `generate_ai_reviewer_gold.py` resume (deviation from plan: `openai/cursor-grok-4.6-medium` does not exist on the new gateway; ran `--model openai/deepseek-v4-pro --workers 8` — kimi-k3 and glm-5.3 both burn the script's hardcoded 800-token budget on hidden reasoning and return unparseable output, deepseek-v4-pro completes. Needed 6 resume sweeps (invalid pairs are retryable; ~50% recovered per pass) plus a final 5-pair lift at max_tokens=4000 that reused the generator's own prompt/assembly/validation)
- [x] 7.3 Confirm the run writes the remaining 310 quadruples into `judge_c_gold.ai_reviewer.jsonl` (expect total 1497 rows) (1497 rows, unique ids, 0 leak, pass=616/fail=881; the 7 gap types closed: sale 208, technology 54, tourism_service 36, transport 15, utilities_supply 42, warehousing 24, work 16)
- [x] 7.4 Re-run steps 2.1–2.3, 3.1–3.3, 4.1–4.3, 5.1–5.2 to re-merge, re-materialize, re-promote, re-open gate, and re-verify against the now-complete 1497-row `ai_reviewer` source (merged 2571 = 1074 + 1497, 0 leak, pass=1321/fail=1250; gold 2571 / bronze 9134; gate OPEN on 2571-row grounded; verify_expand ALL CHECKS PASSED, no `.verify-bak` leftovers)

## 8. Final validation

- [x] 8.1 Confirm canonical `judge_c_gold.jsonl` is the single source of truth consumed by the SFT loader, at 2261 rows (pre-resume) or the post-resume merged count, 0% leak (post-resume: 2571 rows, `judge_c_gold.jsonl` == `grounded.jsonl` == `merged.jsonl` parse-equal, 0 leaks)
- [x] 8.2 Confirm the flywheel gate is OPEN on the clean grounded superset (✅ 2571 条四元组, judge_c_gold.grounded.jsonl)
- [x] 8.3 Confirm Drafter-A reward modeling is unblocked by the open gate (per the flywheel order constraint) (`load_drafter_reward_positive()` runs with the gate open; reward set gold-only, 0 records so far)
