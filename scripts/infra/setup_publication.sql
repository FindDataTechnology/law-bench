-- scripts/infra/setup_publication.sql
-- =============================================================================
-- Origin-side setup for the public pod's Postgres read-replica (OpenSpec task 4.1).
-- Run ON THE ORIGIN Postgres (the law-bench primary, 10.43.138.128 / k3s svc).
--
-- Two things happen here, both idempotent (re-runnable):
--   1. A logical-replication role `law_bench_repl` (REPLICATION LOGIN) is created
--      (or left as-is if it already exists). Its password is NOT set inline here —
--      set it via an environment-substituted PGPASSWORD at apply time so the secret
--      never lives in the repo. See docs/public-api-deploy.md for the `psql -v`
--      invocation.
--   2. A publication `law_bench_public` is (re)created FOR TABLE <read-path set>.
--      `DROP PUBLICATION IF EXISTS` then `CREATE` so the table list is always the
--      current truth (adding a table later = edit this file + re-run).
--
-- Replicated tables (the read-path set the public pod queries):
--   api_keys          — X-API-Key verify on the China pod (the load-bearing one).
--   contract_artifacts — GET /api/contracts/artifacts/{id}/download, /samples.
--   clauses           — /clauses, /api/contracts/{type}/clauses, assembly reads.
--   tag_dims          — tag vocab for the clause/assembly read paths.
--   law_info          — /law-info, /api/contracts/{type}/laws.
--   rubrics, criteria — /api/contracts/{type}/review read path (rubric + criteria).
--   prompts           — prompt read path (contract_context lists prompts).
--
-- NOTE on `contract_types`: the task list names it, but the contract-type catalog
-- is FILE-BACKED (src/contracts/data/contracts.json) — it is not a Postgres table,
-- so logical replication does not cover it. The catalog ships inside the image
-- (same image runs origin and public pod), so the public pod has the same catalog
-- as the origin that built it. New types added after a deploy require a re-deploy
-- of the public pod (the image is the sync mechanism for the catalog). This is
-- documented in docs/public-api-deploy.md.
--
-- Replica identity: every published table has a `id` PRIMARY KEY, so the default
-- replica identity (PK) suffices for UPDATE/DELETE replication — no
-- `REPLICA IDENTITY FULL` needed.
-- =============================================================================

-- 1. Replication role (idempotent). REPLICATION grants the logical-replication
--    privilege; LOGIN lets the China subscription connect as this role. The
--    password is injected at apply time (see deploy doc); the placeholder here
--    is intentionally a no-op ALTER so a bare `psql -f` does not set a weak one.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'law_bench_repl') THEN
        CREATE ROLE law_bench_repl REPLICATION LOGIN;
        RAISE NOTICE 'created role law_bench_repl (set its password out-of-band)';
    ELSE
        RAISE NOTICE 'role law_bench_repl already exists — left as-is';
    END IF;
END
$$;

-- 2. Publication (idempotent via drop-then-create so the FOR TABLE list is the
--    single source of truth). `publish` scope: only INSERT/UPDATE/DELETE — the
--    public pod never truncates, and excluding TRUNCATE avoids surprising the
--    replica with a mass-delete it did not expect.
DROP PUBLICATION IF EXISTS law_bench_public;

CREATE PUBLICATION law_bench_public
    FOR TABLE
        api_keys,
        contract_artifacts,
        clauses,
        tag_dims,
        law_info,
        rubrics,
        criteria,
        prompts
    WITH (publish = 'insert, update, delete');

-- 3. Grant CONNECT on the database + USAGE on the schemas the published tables
--    live in so the replication role can actually open the connection the
--    subscription needs. (Publication membership alone does not confer schema
--    access.) Idempotent: GRANT is a no-op if already held.
GRANT CONNECT ON DATABASE current_database() TO law_bench_repl;
-- The law-bench schema is the default `public` namespace. If the deploy uses a
-- non-default schema, add it here. `public` covers the current deploy.
GRANT USAGE ON SCHEMA public TO law_bench_repl;

-- 4. Verification query (run manually after apply to confirm membership):
--    SELECT * FROM pg_publication_tables WHERE pubname = 'law_bench_public';
--    -- should list the 8 tables above.
--    -- And check the role:
--    SELECT rolname, rolreplication, rolcanlogin FROM pg_roles
--    WHERE rolname = 'law_bench_repl';
