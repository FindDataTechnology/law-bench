## Why

The contract assembly system is stuck at a 7/10 evaluation ceiling for `sale` contracts — 10 consecutive runs all produce the same score, failing on `ownership_transfer`, `inspection_period`, and `ownership_retention`. The root cause is a structural disconnect: the tag system has no semantic link between clauses and rubric criteria, so the self-healing pipeline's `improve` node blindly excludes clauses without knowing which legal topic to fix. Meanwhile, single-judge evaluation (kimi-k3) is structurally unreliable — it confuses contracts with rubrics and misreads fields — capping the evaluation signal's trustworthiness. Three dead tag dimensions (`strength`, `risk`, `mandatory`) add noise without driving assembly. A redesigned tag system with a `legal_topic` dimension, multi-judge consensus, and topic-aware self-iteration will break through the ceiling.

## What Changes

- **BREAKING** Remove dead tag dimensions: `strength`, `risk`, `mandatory` (never drove assembly)
- **BREAKING** Fix stance vocabulary mismatch: pipeline generates `pro_seller`/`pro_buyer` but vocab defines `pro_a`/`pro_b` — normalize to `pro_a`/`pro_b`/`balanced`
- **NEW** Add `legal_topic` tag dimension: type-specific, derived from rubric criterion names, creates the clause→rubric semantic bridge
- **NEW** Multi-judge evaluation: 3 models (kimi-k3, glm-5, deepseek) vote per criterion via majority; store per-judge verdicts for analysis
- **NEW** Topic-aware self-iteration: `improve` node maps failing criteria → `legal_topic` → searches for or generates targeted clauses (replaces blind exclusion)
- **NEW** Auto-tagging pipeline: batch-label existing clauses with `legal_topic` via LLM sub-agents
- **NEW** Named vs unnamed contract differentiation: 19 Civil Code named contracts auto-derive topics from article ranges; 24 unnamed contracts use LLM inference from industry statutes
- Auto-approve/reject logic becomes topic-aware: rejects only when a topic has redundant coverage from better clauses

## Capabilities

### New Capabilities
- `legal-topic-tags`: The `legal_topic` tag dimension — schema, vocabulary derivation from rubrics, backfill for existing clauses, and assembly integration
- `multi-judge-evaluation`: Multi-model evaluation with majority voting, per-judge verdict storage, and confidence scoring
- `topic-aware-self-iteration`: Redesigned improve/learn nodes that map failures to legal topics and generate targeted clause fixes

### Modified Capabilities
- `auto-iteration-pipeline`: Pipeline graph gains topic-aware improve node, multi-judge evaluate node, and topic-coverage-based learn node
- `tag-combinatorics`: Tag vocabulary changes (remove 3 dims, add legal_topic) affect combination enumeration and validation

## Impact

- **Code**: `src/clauses/tags.py` (schema), `src/clauses/assemble.py` (topic filtering), `src/eval/scoring.py` (multi-judge), `src/eval/judge.py` (judge factory), pipeline graph files under `fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/pipeline/`
- **Database**: `clauses` table tags JSONB gains `legal_topic` key; `eval_runs` / new `judge_verdicts` table for per-judge storage; `tag_dims` table updated
- **APIs**: `contract_evaluate` MCP tool gains multi-judge option; `clause_update`/`clause_review` accept `legal_topic`; `tag_validate` recognizes new dimension
- **Dependencies**: 3 LLM judge endpoints must be available (currently via litellm relay at linjie.love)
- **Data**: ~5000+ existing clauses need `legal_topic` backfill; 43 rubric sets need criterion→topic mapping
