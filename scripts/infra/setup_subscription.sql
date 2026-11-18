-- setup_subscription.sql — run ONCE on the CHINA replica's Postgres.
--
-- Prerequisites (run on the ORIGIN first):
--   1. setup_publication.sql has been applied and the replication role exists.
--   2. The China box can reach the origin's Postgres port (the open question
--      in design.md D-Open-1). If it cannot, skip this file and use the
--      batch pg_dump fallback documented in design.md §4.3.
--
-- What it does:
--   - Creates the local tables (same DDL as the origin) so the subscriber has
--     somewhere to apply replicated rows. Uses IF NOT EXISTS so re-running is
--     safe. The origin's ensure_schema() would also create these on first
--     public-pod boot, but running them here makes the subscription setup
--     explicit and order-independent.
--   - Creates a SUBSCRIPTION that opens one persistent replication connection
--     to the origin and streams changes from the publication.
--
-- Tuning:
--   - Replace '<origin-host>' / '<repl-password>' below before running. The
--     host is the origin's Postgres endpoint reachable from the China box
--     (likely 23.144.68.246:15432 via kubectl port-forward, or the public IP
--     if the k3s service is exposed).
--   - The subscription is created ENABLED (starts streaming immediately). To
--     pause: ALTER SUBSCRIPTION law_bench_sub DISABLE; to resume: ENABLE.
--   - Monitoring: SELECT * FROM pg_stat_subscription; lag is visible via
--     pg_stat_subscription_stats (Postgres 14+).
--
-- Idempotent: re-running after a partial failure is safe — CREATE TABLE IF
-- NOT EXISTS is a no-op on existing tables; CREATE SUBSCRIPTION errors if the
-- name already exists, in which case drop-and-recreate:
--   ALTER SUBSCRIPTION law_bench_sub DISABLE;
--   DROP SUBSCRIPTION IF EXISTS law_bench_sub;
--   -- then re-run this file.

-- 1. Local tables (same DDL as origin's ensure_schema / harbor_seed).
--    Only the tables in the publication need to exist locally.

CREATE TABLE IF NOT EXISTS api_keys (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key_prefix   TEXT NOT NULL UNIQUE,
    key_hash     TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    label        TEXT NOT NULL,
    scopes       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS contract_artifacts (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type       TEXT NOT NULL,
    scenario            TEXT,
    stance              TEXT,
    custom_clause_ids   JSONB,
    body_hash           TEXT NOT NULL UNIQUE,
    body_text           TEXT NOT NULL,
    slots               JSONB NOT NULL DEFAULT '[]'::jsonb,
    docx_key            TEXT,
    pdf_key             TEXT,
    minio_bucket        TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clauses (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type    TEXT NOT NULL,
    category         TEXT NOT NULL,
    section          TEXT NOT NULL,
    body             TEXT NOT NULL,
    slot_instructions JSONB NOT NULL DEFAULT '[]'::jsonb,
    law_refs         JSONB NOT NULL DEFAULT '[]'::jsonb,
    level            TEXT,
    source_path      TEXT,
    source_doc_title TEXT,
    body_hash        TEXT NOT NULL,
    manual           BOOLEAN NOT NULL DEFAULT false,
    tags             JSONB NOT NULL DEFAULT '{}'::jsonb,
    tag_review       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tag_dims (
    name           TEXT NOT NULL,
    contract_type  TEXT,
    category       TEXT,
    values         JSONB NOT NULL DEFAULT '[]'::jsonb,
    free_form      BOOLEAN NOT NULL DEFAULT false,
    zh_label       TEXT,
    description    TEXT
);

CREATE TABLE IF NOT EXISTS law_info (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    contract_type TEXT NOT NULL,
    source        TEXT NOT NULL,
    zh_name       TEXT,
    content       TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE(contract_type, source)
);

CREATE TABLE IF NOT EXISTS rubrics (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    context     TEXT NOT NULL,
    source      TEXT NOT NULL,
    source_path TEXT,
    description TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    contract_type TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    content       TEXT NOT NULL,
    source        TEXT NOT NULL,
    prompt_type   TEXT,
    description   TEXT,
    created_at    TEXT NOT NULL
);

-- 2. The subscription itself.
--
--    IMPORTANT: replace the two placeholders below before running:
--      <origin-host>     = origin Postgres endpoint reachable from China
--                        (e.g. 23.144.68.246, or a DNS name that resolves
--                        from the China box)
--      <repl-password>   = the password set for the law_bench_repl role in
--                        setup_publication.sql on the origin
--
--    The port defaults to 5432; override with <origin-host>:<port> if the
--    origin is exposed on a non-standard port (e.g. 15432 via k3s NodePort).

DO $$
BEGIN
    -- Drop-and-recreate so the script is re-runnable after a partial failure.
    -- On a clean first run the DROP is a no-op (IF EXISTS).
    IF EXISTS (SELECT 1 FROM pg_subscription WHERE subname = 'law_bench_sub') THEN
        ALTER SUBSCRIPTION law_bench_sub DISABLE;
        DROP SUBSCRIPTION law_bench_sub;
    END IF;
END
$$;

CREATE SUBSCRIPTION law_bench_sub
    CONNECTION 'host=<origin-host> port=5432 dbname=law_bench user=law_bench_repl password=<repl-password>'
    PUBLICATION law_bench_public
    WITH (
        copy_data = true,          -- initial table sync on subscribe
        create_slot = true,        -- create the replication slot on the origin
        enabled = true             -- start streaming immediately
    );

-- 3. Verify. After running, confirm rows are flowing:
--    SELECT * FROM pg_stat_subscription;                -- should show one row, received_lsn advancing
--    SELECT count(*) FROM api_keys;                     -- should match origin
--    SELECT count(*) FROM contract_artifacts;           -- should match origin
--    SELECT count(*) FROM clauses;                      -- should match origin
