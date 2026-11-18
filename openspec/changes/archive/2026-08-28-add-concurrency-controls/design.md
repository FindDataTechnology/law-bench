# Design: Concurrency Controls for Eval & Generation Runs

## Context

See `proposal.md` — Why. The load-bearing constraints from the codebase:

- Judge criteria are already scored through a `ThreadPoolExecutor` in `src/eval/scoring.py::evaluate_contract` with a hardcoded `max_workers=8` default and per-call 429/503 retry (3 attempts, 8s/16s backoff). That retry exists because relay saturation once turned rate-limits into unanimous FAILs and collapsed `property_service` to 0/10 — concurrency must never bypass it.
- `src/eval/compare.py::run_compare` generates drafts in nested sequential loops (`for prompt × for draft`), one DRAFTER LLM call each, then judges and persists each draft before the next.
- The MCP `compare_run` tool wraps `run_compare`; the web `POST /api/compare` wraps it too (`CompareCreate` in `src/web/models.py`). Both are the user's daily surfaces.
- The web mode D `generate-batch` route iterates tag combinations sequentially; its request model already declares `max_concurrent: int = 5` but the route ignores it.
- All LLM traffic (drafter + judge) terminates at the same Volcengine Ark relay, so every knob shares one saturation budget.

## Goals / Non-Goals

**Goals:**
- One coherent story for "how parallel can this system get": judge workers via env, compare drafts via per-call param, batch assembly via request field — all clamped, all defaulting to today's behavior.
- Deterministic persisted output: a compare run at any concurrency stores byte-identical row order/content to a concurrency-1 run.
- Hermetic testability: every bound and ordering guarantee provable with monkeypatched LLM calls.

**Non-Goals:**
- Per-job judge-concurrency overrides for pipeline jobs E/F (`EVAL_MAX_WORKERS` covers them globally; threading a per-request override through the LangGraph state is plumbing without measured need).
- Overlapping the evaluate phase with the draft phase inside a compare (see D3).
- Intra-pipeline parallelism (`generate → fill → evaluate` is inherently sequential).
- Any queuing/scheduling infrastructure (no Celery/Redis); plain thread pools only.

## Decisions

### D1: Env resolution helper in `scoring.py`, read at call time
`evaluate_contract`'s `max_workers` default changes from literal `8` to `None`; when `None`, a small resolver reads `EVAL_MAX_WORKERS`, falls back to 8 on unset/invalid, clamps to [1, 16], and logs when clamping/falling back. Read env at call time (not import time) so tests and long-running processes pick up changes; explicit `max_workers` args keep precedence (the dual-judge path at `scoring.py:207` and existing tests rely on it).
*Alternative*: resolve in `src/settings.py` at import — rejected: hides per-test overrides behind module import order.

### D2: Ceiling arithmetic — 16 global, 8 per knob
`EVAL_MAX_WORKERS` clamps at 16; compare `concurrency` and judge within-compare workers clamp at 8. Rationale: worst case a compare at full tilt runs 8 drafts + 8 judges ≈ 16 in flight, matching the global ceiling, so no single surface can exceed what the relay tolerated at the incident-adjacent default. Defaults (8 judge / 1 draft / 5 batch) all preserve today's relay load exactly.
*Alternative*: single shared semaphore across surfaces — rejected: cross-process (web + MCP) anyway, adds coordination without enforceable scope.

### D3: Compare parallelism = parallel draft phase, sequential ordered persist
`run_compare` precomputes the `(prompt, draft_index)` matrix, generates drafts through a bounded `ThreadPoolExecutor` (litellm `completion` is thread-safe; drafter has no shared mutable state), collects texts into a matrix, then evaluates + persists in the existing loop order. No post-hoc sorting, no interleaved DB writes — the persistence code path is literally unchanged, only `draft_text` arrives precomputed.
*Alternative*: evaluate each draft as it completes (overlaps judge with drafter, ~30-40% faster wall-clock) — deferred: interleaved persistence risks row-order drift and needs a completion-ordered collector; revisit only if the two-phase gain proves insufficient.
*Failure*: one failed draft aborts the compare, same as today (exception propagates) — no partial-batch semantics invented.

### D4: Clamp-and-report, never reject
Out-of-range values (e.g. `concurrency: 99`) clamp silently to the ceiling and the effective value is included in the tool/API result. Operators tuning against a saturating relay need forgiveness, not 400s; the effective-value report keeps it observable.
*Alternative*: 422 on out-of-range — rejected: turns a tuning knob into a validation trap.

### D5: Mode D batch via ordered futures
`generate-batch` maps `_gen_one` over combos in a bounded pool and collects results positionally (`pool.map` semantics), preserving request order and the existing per-combo `try/except` isolation. `max_concurrent` clamps to [1, 16]; the declared-but-dead model field becomes load-bearing with its existing default of 5.

### D6: Web surfaces are additive passthroughs
`CompareCreate.concurrency: int = 1` (Pydantic `ge=1` guard; clamp to 8 in the handler), the `/compare/new` form gains a number input wired through the existing form-submit path, i18n label `并发` added to `src/web/i18n.py`. MCP `compare_run` gains `concurrency: int = 1`. Neither surface re-validates beyond clamping — the service layer owns the bound.

## Risks / Trade-offs

- [Elevated concurrency re-saturates the relay] → Defaults unchanged everywhere; hard clamps; the 429/503 backoff invariant is specced (`evaluation-concurrency`) and covered by tests that assert retry under a fake rate-limiting endpoint; effective values reported so operators see what actually ran.
- [Parallel drafts hit rate limits → compare fails where sequential succeeded] → Same exposure class as judge today; drafter calls go through litellm which retries 429s internally. Documented as operator responsibility to tune down under saturation.
- [Thread-safety regressions in shared state during parallel drafts] → Draft phase touches only litellm + immutable inputs; persistence stays on the calling thread. Hermetic tests assert the in-flight bound with a counting semaphore.
- [`max_concurrent` becoming load-bearing changes behavior for clients already sending it] → No client sends it today (panel doesn't render it; field was dead). Default 5 with clamp; ordered results make the change observable only as speed.

## Migration Plan

Roll forward: single deploy; env var optional (absent = defaults = current behavior). Rollback: redeploy previous image — no DB schema changes, no data migrations, additive request fields only.

## Open Questions

- Should the compare result payload surface per-phase timing (draft vs judge wall-clock) to help operators pick a concurrency? Nice-to-have; does not affect specs or structure — can be added during implementation if cheap.
