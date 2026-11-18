-- ─────────────────────────────────────────────────────────────────────────────
-- agent_runs table — per-run metrics for the contract-review-agent.
--
-- One row per completed agent run. Stores per-node timing, per-model call
-- breakdown (tokens/cost/latency), the reviewer suggestions and which were
-- applied, slot coverage, and links to the existing eval_runs row produced
-- by the rubric + deepeval evaluation.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agent_runs (
    id              BIGSERIAL PRIMARY KEY,
    thread_id       TEXT        NOT NULL,              -- LangGraph thread_id
    contract_type   TEXT        NOT NULL,
    tags            JSONB       NOT NULL DEFAULT '{}', -- scenario/stance used for gen
    task_desc       TEXT,

    -- per-node elapsed seconds, e.g. {"generate_v1": 2.3, "review_panel": 8.1}
    node_timings    JSONB       NOT NULL DEFAULT '{}',
    -- [{model, tokens, cost, latency_seconds, node}] per LLM call
    model_calls     JSONB       NOT NULL DEFAULT '[]',
    -- all synthesized reviewer suggestions (pre-triage)
    review_suggestions       JSONB NOT NULL DEFAULT '[]',
    -- suggestions the human accepted at CP1 (post-triage)
    suggestions_applied      JSONB NOT NULL DEFAULT '[]',

    -- slot coverage
    total_slots         INTEGER NOT NULL DEFAULT 0,
    human_filled_slots  INTEGER NOT NULL DEFAULT 0,

    -- evaluation linkage + deepeval side (rubric side lives in eval_runs)
    eval_run_id     BIGINT REFERENCES eval_runs(id) ON DELETE SET NULL,
    deepeval_scores JSONB NOT NULL DEFAULT '{}',

    -- aggregate
    total_duration  REAL,                               -- wall-clock seconds
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Recent-runs listing query path
CREATE INDEX IF NOT EXISTS idx_agent_runs_created_at ON agent_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_contract_type ON agent_runs (contract_type);
CREATE INDEX IF NOT EXISTS idx_agent_runs_thread_id ON agent_runs (thread_id);
