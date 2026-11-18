# Tasks: add-concurrency-controls

Reference: specs in `specs/` (5 deltas), design decisions D1–D6 in `design.md`.

## 1. Judge worker-pool env default (`evaluation-concurrency` R1–R2)

- [x] 1.1 In `src/eval/scoring.py`, change `evaluate_contract`'s `max_workers` default from `8` to `None`; add a resolver that reads `EVAL_MAX_WORKERS` at call time, falls back to 8 on unset/non-positive/non-integer, clamps to [1, 16], and logs fallback/clamp with the effective value. Explicit `max_workers` args keep precedence (dual-judge path at line ~207).
- [x] 1.2 Tests (`tests/test_scoring_concurrency.py` or extend the existing scoring tests, hermetic via monkeypatched judge): unset env → pool of 8; `EVAL_MAX_WORKERS=12` → 12; `=64` → clamped 16; `=abc` → fallback 8; explicit `max_workers` arg beats env.
- [x] 1.3 Backoff-invariant test: a fake judge metric whose `measure` raises `RateLimit/429` twice then succeeds must still produce a pass under an elevated worker pool — retry (8s/16s sleeps monkeypatched) must fire regardless of pool size; a call erroring after retries marks only its own criterion.

## 2. Compare parallel draft generation (`prompt-compare` delta, design D2–D3)

- [x] 2.1 In `src/eval/compare.py::run_compare`, add `concurrency: int = 1` param, clamp to [1, 8]; restructure the draft loop into two phases — generate the `(prompt × draft_index)` matrix through a bounded `ThreadPoolExecutor` into a precomputed `drafts` structure, then run the existing evaluate+persist loop unchanged over that structure (prompt-major, draft-minor order preserved).
- [x] 2.2 Tests (hermetic, monkeypatch `draft_fn` and `evaluate_contract`): default call is behavior-identical to pre-change (same rows, same order); with `concurrency=4` and a counting-semaphore fake drafter, observed in-flight drafts never exceed 4; persisted row order with `concurrency=4` equals the order from a `concurrency=1` run of the same inputs; `concurrency=20` runs at 8.
- [x] 2.3 Propagate the clamp visibly: `run_compare` includes `effective_concurrency` in its return payload (used by MCP + web results).

## 3. MCP `compare_run` param (`law-bench-mcp` delta, design D6)

- [x] 3.1 In `fd-coding-law-bench-mcp`'s compare tool, add `concurrency: int = 1` to the `compare_run` schema; pass through to `run_compare`; include `effective_concurrency` in the tool result.
- [x] 3.2 Hermetic MCP test (monkeypatch `src.eval.compare.run_compare`): param passes through; oversized value still succeeds via service clamp; result carries `effective_concurrency`; registration assertion still passes.

## 4. Web compare surface (`prompt-compare-web` delta, design D6)

- [x] 4.1 `src/web/models.py::CompareCreate` gains `concurrency: int = 1` (Pydantic `ge=1`); the `POST /api/compare` handler clamps to 8 and passes through to `run_compare`.
- [x] 4.2 API tests: request without `concurrency` behaves as before; `concurrency: 4` reaches `run_compare` as 4; `concurrency: 99` reaches it as 8; results identical content/order.
- [x] 4.3 `/compare/new` build form gains a number input (default 1, min 1, max 8) with localized label — add `并发` to `src/web/i18n.py` (zh) and the fallback key for other locales; wire the field into the form-submit body.
- [x] 4.4 Web tests: form renders the input with the localized label in zh; submitting includes `concurrency` in the create body.

## 5. Mode D batch honors `max_concurrent` (`contract-generation-jobs` delta, design D5)

- [x] 5.1 In `src/web/routes/generation.py::generate_batch`, clamp `body.max_concurrent` to [1, 16] and assemble combos through a bounded `ThreadPoolExecutor` using positional collection so results stay in request/enumeration order; keep the existing per-combo `try/except` isolation.
- [x] 5.2 Tests: 6 combos with `max_concurrent: 3` → in-flight ≤ 3 (counting-semaphore fake assembler) and `results` order matches the submitted combinations; one failing combo yields `success_count`/`failure_count` split with the error on that item only; `max_concurrent: 64` clamps to 16.

## 6. Docs & verification

- [x] 6.1 Document `EVAL_MAX_WORKERS` in `.env.example`: default 8, clamp [1, 16], and a comment noting the relay-saturation incident rationale (429s must never become FAILs; backoff is load-bearing).
- [x] 6.2 Run the full test suite; all green including the new files. (Note: local Windows env currently cannot build `litellm` — if still broken, run the suite in the working environment used for recent changes and record where it ran.)
