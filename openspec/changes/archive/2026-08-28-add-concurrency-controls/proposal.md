# Proposal: Concurrency Controls for Eval & Generation Runs

## Why

The runs the user waits on are slower than the infrastructure allows. `compare_run` generates drafts in fully sequential loops (`for prompt × for draft`, one drafter LLM call each) — a 3-prompt × 3-draft compare pays 9 sequential LLM round-trips before judging even starts. The judge layer already scores rubric criteria concurrently (`ThreadPoolExecutor`, hardcoded default `max_workers=8`) but that knob is invisible: no env var, no MCP param, no web field. On the website, `GenerationRequest.max_concurrent` exists but is silently ignored by the batch route — a dead field. The user runs MCP tools and the website daily and wants a 并发 knob to make runs finish faster.

One hard constraint shapes this change: the upstream relay (Volcengine Ark) saturates. A past incident turned rate-limit errors into unanimous judge FAILs and collapsed `property_service` to 0/10, which is why per-call 429/503 backoff exists. Concurrency must be *controllable*, not *unbounded* — every knob ships with a conservative default and a hard ceiling, and the existing backoff stays untouched.

## What Changes

- **Env-defaulted judge workers.** `src/eval/scoring.py::evaluate_contract` resolves its worker-pool default from `EVAL_MAX_WORKERS` (fallback 8), clamped to a hard ceiling. All existing call sites keep working unchanged.
- **Parallel compare draft generation.** `run_compare` gains a `concurrency` param (default 1 = today's sequential behavior) that generates the prompt × draft matrix through a bounded thread pool; persisted `eval_runs` rows keep the exact deterministic order of the sequential path.
- **MCP: `compare_run` gains `concurrency`.** Optional int param, clamped to the ceiling, effective value reported in the result.
- **Web compare: `concurrency` field.** `CompareCreate` (`POST /api/compare`) accepts it; the `/compare/new` build form gains a 并发 input. This is the synchronous browser path where wall-clock hurts most.
- **Web batch: honor `max_concurrent`.** The mode D `generate-batch` route actually parallelizes assembly across tag combinations with the request's `max_concurrent` (default 5), preserving per-combo error isolation and result order.

## Capabilities

### New Capabilities

- `evaluation-concurrency`: how worker-pool sizes are resolved (env default, clamping, ceiling) and the rate-limit backoff invariant that must hold under any concurrency; parallel draft generation in compare runs with deterministic persistence order.

### Modified Capabilities

- `prompt-compare`: `run_compare` gains the `concurrency` parameter and parallel draft generation; persistence order becomes an explicit guarantee.
- `prompt-compare-web`: the compare JSON API body and the build form gain the `concurrency` field.
- `law-bench-mcp`: the `compare_run` tool schema gains the optional `concurrency` parameter.
- `contract-generation-jobs`: Sync Batch Generation (mode D) honors `max_concurrent` instead of ignoring it.

## Impact

- **Code**: `src/eval/scoring.py` (env default + clamp), `src/eval/compare.py` (parallel draft loop), `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/tools/` (`compare_run` param), `src/web/models.py` + `src/web/routes/api.py` (compare body), `src/web/routes/generation.py` (batch parallelism), `src/web/templates/` + panel JS (并发 input), `src/web/i18n.py` (label).
- **APIs**: additive optional fields only — `POST /api/compare`, `POST /api/contracts/{type}/generate-batch`, MCP `compare_run`. No breaking changes; defaults preserve current behavior.
- **Dependencies**: none added (stdlib `concurrent.futures`).
- **Ops**: `.env.example` documents `EVAL_MAX_WORKERS`; relay-saturation ceiling documented so operators don't recreate the 0/10 incident.
- **Non-goals**: per-job judge-concurrency overrides for pipeline jobs E/F (the env knob covers them globally); intra-pipeline parallelism (generate→fill→evaluate stages are inherently sequential); changing the default compare draft concurrency above 1 (speed is opt-in).
