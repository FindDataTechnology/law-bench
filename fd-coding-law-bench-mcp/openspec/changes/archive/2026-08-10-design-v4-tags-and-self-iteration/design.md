## Context

The contract assembly system uses a tag-driven override model (v3): `custom(stance) > tagged(scenario) > base(母版)`. Three tag dimensions drive assembly (`source`, `stance`, `scenario`), while three others (`strength`, `risk`, `mandatory`) are dead — never consumed by any code path. The evaluation pipeline (self-heal + auto-reject) is stuck at 7/10 on sale because:

1. **No clause→rubric mapping**: the improve node blindly excludes "thin" custom clauses without knowing which rubric criterion they should satisfy
2. **Single-judge noise**: kimi-k3 as sole judge produces inconsistent verdicts; memory records it as "structurally unreliable"
3. **Stance vocab mismatch**: pipeline generates `pro_seller/pro_buyer` but vocab defines `pro_a/pro_b`
4. **Auto-reject misfires**: clause 7257 (所有权保留, balanced) was auto-rejected despite being legally correct

43 contract types split into 19 named (民法典典型合同, articles 595-978) and 24 unnamed (行业法规管辖). Named contracts have deterministic legal structure from Civil Code articles; unnamed contracts depend on scattered statutes.

## Goals / Non-Goals

**Goals:**
- Break the 7/10 evaluation ceiling by establishing a semantic bridge between clauses and rubric criteria
- Replace single-judge evaluation with 3-model majority voting for reliable verdicts
- Clean up dead tag dimensions to reduce combinatorial noise
- Differentiate self-iteration strategy for named vs unnamed contracts
- Achieve 10/10 on sale as proof-of-concept, then batch-apply to all 43 types

**Non-Goals:**
- Rewriting the rubric criteria themselves (v3 rubrics are adequate)
- Changing the assembly precedence model (custom>tagged>base stays)
- Human-in-the-loop clause review (user has no legal background to review)
- Building a general-purpose legal knowledge graph (legal_topic is scoped to rubric mapping)

## Decisions

### D1: legal_topic = rubric criterion name (coarse-grained, one per clause)

Each clause gets at most one `legal_topic` tag whose value is derived from the rubric criterion it primarily addresses. E.g., a clause about "所有权自交付时转移" gets `legal_topic: ownership_transfer`.

**Why not multi-topic**: A clause that tries to cover multiple criteria is usually a sign it should be split. One-topic-per-clause keeps the mapping clean and the improve node's targeting simple.

**Why not a separate ontology table**: Rubric criterion names are already unique per contract type and well-defined. Adding a separate ontology layer would be over-engineering — the rubric IS the ontology.

**Alternative considered**: Semantic embedding similarity between clause body and criterion guidance. Rejected — too slow for batch tagging, and the criterion names are descriptive enough for LLM-based classification.

### D2: 3-model majority voting (kimi-k3 + glm-5 + deepseek)

Each evaluation runs 3 judges in parallel (one per model). Per criterion, majority wins (2/3 or 3/3). The verdict includes a confidence score: 1.0 for unanimous, 0.67 for majority.

**Why 3 not 5**: 3 is the minimum for majority voting. 5 adds cost without meaningful accuracy gain when the 3 models are architecturally different (Moonshot, Zhipu, DeepSeek).

**Why different models not different temperatures**: Temperature variation on the same model produces correlated errors (same training data, same biases). Different models have uncorrelated failure modes.

**Fallback**: If a model is unavailable (API down, rate limit), degrade to 2-judge + unanimous-required. If only 1 judge available, flag results as `low_confidence` and skip auto-reject.

**Alternative considered**: Using the same model with different prompts/system-messages. Rejected — same model, same biases.

### D3: Named vs unnamed contract differentiation

| Aspect | Named (19) | Unnamed (24) |
|--------|-----------|--------------|
| legal_topic source | Civil Code articles → auto-derive | Rubric criteria → LLM derive |
| Self-iteration aggressiveness | Aggressive (条文确定, can auto-generate clauses) | Conservative (法规多变, verify accuracy) |
| max_iterations | 3 | 5 |
| Auto-reject threshold | 3 (default) | 5 (higher bar) |

**Why**: Named contracts have well-defined legal structure from 民法典 chapters 9-27. The articles directly specify rights/obligations, so we can confidently auto-generate clauses that cite specific articles. Unnamed contracts depend on scattered statutes (劳动合同法, 保险法, etc.) that change more frequently and have more interpretive flexibility.

### D4: legal_topic backfill via sub-agent batch tagging

Use Claude sub-agents to batch-tag existing clauses. Each sub-agent handles one contract type: reads all clauses + rubric criteria, assigns `legal_topic` to each clause via LLM classification. Results written to `tags.legal_topic` via `clause_update`.

**Why sub-agents not a script**: The classification requires reading clause body text and matching it to rubric criterion guidance — this is an LLM task, not a regex task. Sub-agents parallelize across contract types.

**Why not manual review**: User has no legal background. LLM classification with spot-check on sale (the type we know best) is the pragmatic path.

### D5: Stance vocab fix — alias mapping, not rename

Add aliases `pro_seller → pro_a`, `pro_buyer → pro_b` in the tag validation layer rather than renaming existing values. This avoids breaking existing clauses that use either form.

**Why not just rename**: There are clauses in the DB with both forms. A migration would touch hundreds of rows for no functional gain. An alias map is one lookup table.

### D6: Delete dead dimensions (strength, risk, mandatory)

Remove from the starter vocab and tag validation. Existing clauses with these tags keep them (no data migration), but they no longer appear in `tag_vocab_list` or `tag_combinations_list` output.

**Why not keep as informational**: Dead dimensions add noise to `tag_combinations_list` (combinatorial explosion) and confuse the LLM-based improve node.

## Risks / Trade-offs

**[Risk] LLM legal_topic classification accuracy** → Mitigation: spot-check sale type (1288 clauses) manually by comparing topic distribution against rubric criteria coverage. If any criterion has 0 clauses, the classification is broken.

**[Risk] Multi-judge 3x cost** → Mitigation: judges run in parallel (ThreadPoolExecutor, same as current single-judge). Wall-clock time ≈ single judge. Token cost triples but evaluation is not the bottleneck (generation + fill is).

**[Risk] legal_topic is lossy (one topic per clause)** → Mitigation: if a clause genuinely covers multiple criteria, split it into multiple clauses during the self-iteration generate step. The improve node already creates new clauses.

**[Risk] Judge model availability** → Mitigation: graceful degradation (3→2→1). Pipeline stores per-judge verdicts so we can analyze disagreement patterns later.

**[Trade-off] Aggressive auto-generation for named contracts** may produce clauses with incorrect article citations → Mitigation: coherence gate validates slot consistency; legal_topic coverage check ensures each criterion has at least one clause; multi-judge eval catches bad citations.
