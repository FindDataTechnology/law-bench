"""Idempotent DDL for the workspace data layer (domain-neutral kernel).

Six tables back the template/domain/membership/invitation records and the
authoring surface (change events + work tasks). The DDL follows the kernel
convention: ``CREATE TABLE IF NOT EXISTS`` constants that
``src.eval.store.ensure_schema`` executes on first connect, right next to
``BENCH_SCHEMA``. There is no migration framework in this repository, so every
statement here must stay idempotent.

Vocabulary and comments in this module are deliberately generic: the kernel
does not know which verticals instantiate these records.

Notes on the shape:

- ``ontology_templates`` is append-only by version: an edit inserts a new row
  with a higher version, it never rewrites a historical row.
- ``domains`` anchors the exact template row (id) and version it was created
  from, so later versions do not retroactively change an existing domain.
- ``domain_members`` is append-only history: a role change retires the active
  row (``removed_at``) and inserts a fresh one. A partial unique index keeps at
  most one active row per (domain, user); plain history rows are unrestricted.
- ``domain_invitations`` stores only a digest of the credential, never the
  plaintext value.
- ``authoring_events`` is append-only: no UPDATE/DELETE paths exist by design
  (the change trail must stay replayable).
- ``ontology_publications`` is append-only: a publication freezes one immutable
  versioned snapshot of a domain's content (manifest + changelog JSONB). No
  UPDATE/DELETE code paths exist by design — historical snapshots must stay
  byte-identical forever; new content means a new version row.
- ``distribution_consumers`` registers machine pull credentials: only the
  credential digest is stored (never a plaintext token), and revocation is a
  soft flag (``revoked_at``) that the lookup layer treats as fail-closed.
- ``rag_corpora`` registers the retrieval corpus of a workspace: one row per
  domain (``domain_id`` UNIQUE) naming the search index it owns (``index_name``
  UNIQUE, so two workspaces can never point at one index), the source
  declarations (JSONB list of {bucket, prefix} objects; empty = no sources
  configured), and an optional embedding-model declaration (NULL = the global
  default). Re-registration replaces the row via upsert; ownership of a row
  never changes domain.
- The C5 console tables (change ``add-domain-first-workbench``) are additive and
  keep the same discipline: ``domain_members.last_opened_at`` is a per-user
  navigation hint (not content, not audit); ``domain_assets`` is a many-to-many
  directory over heterogeneous pre-existing asset tables (no FK, never touches
  the asset); ``domain_proposals`` is a submission snapshot + workflow state
  (never a second ontology store; confirmation goes through the kernel upsert);
  ``domain_proposal_events`` and ``distribution_pull_events`` are append-only
  trails with no UPDATE/DELETE path.
"""

from __future__ import annotations

WORKSPACE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ontology_templates (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL,
    version     INTEGER NOT NULL,
    schema      JSONB NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS domains (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key               TEXT NOT NULL UNIQUE,
    name              TEXT NOT NULL,
    template_id       BIGINT NOT NULL REFERENCES ontology_templates(id),
    template_version  INTEGER NOT NULL,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain_members (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    user_id     TEXT NOT NULL,
    role        TEXT NOT NULL,
    added_by    TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS domain_members_active_uk
    ON domain_members (domain_id, user_id) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS domain_members_domain_idx
    ON domain_members (domain_id);

CREATE TABLE IF NOT EXISTS domain_invitations (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id    BIGINT NOT NULL REFERENCES domains(id),
    role         TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    invited_by   TEXT NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_at  TIMESTAMPTZ,
    accepted_by  TEXT
);

CREATE TABLE IF NOT EXISTS authoring_events (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id  BIGINT NOT NULL REFERENCES domains(id),
    unit_kind  TEXT NOT NULL,
    unit_key   TEXT NOT NULL,
    op         TEXT NOT NULL CHECK (op IN ('create','update','delete')),
    before     JSONB,
    after      JSONB,
    operator   TEXT NOT NULL,
    via        TEXT NOT NULL DEFAULT 'authoring',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS authoring_events_unit_idx
    ON authoring_events (domain_id, unit_kind, unit_key);
CREATE INDEX IF NOT EXISTS authoring_events_created_idx
    ON authoring_events (domain_id, created_at);

CREATE TABLE IF NOT EXISTS authoring_tasks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    assignee    TEXT NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    target_kind TEXT,
    target_key  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','in_progress','done','cancelled')),
    transitions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS authoring_tasks_assignee_idx
    ON authoring_tasks (domain_id, assignee);
CREATE INDEX IF NOT EXISTS authoring_tasks_status_idx
    ON authoring_tasks (domain_id, status);

-- Append-only by design: no UPDATE/DELETE code paths exist for publications
-- (a published snapshot must stay byte-identical forever; new content is a
-- new version row, never a rewrite).
CREATE TABLE IF NOT EXISTS ontology_publications (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id    BIGINT NOT NULL REFERENCES domains(id),
    version      INTEGER NOT NULL,
    digest       TEXT NOT NULL,
    manifest     JSONB NOT NULL,
    changelog    JSONB NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain_id, version),
    UNIQUE (domain_id, digest)
);
CREATE INDEX IF NOT EXISTS ontology_publications_domain_idx
    ON ontology_publications (domain_id);

CREATE TABLE IF NOT EXISTS distribution_consumers (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    domains    TEXT[] NOT NULL DEFAULT '{}',
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS rag_corpora (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id       BIGINT NOT NULL UNIQUE REFERENCES domains(id),
    index_name      TEXT NOT NULL UNIQUE,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding_model TEXT,
    registered_by   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- C5 add-domain-first-workbench -------------------------------------------------
-- last_opened_at: the domain list orders by this user's own recency. It is a
-- per-user navigation hint, never content or an audit record; a removed
-- membership keeps its timestamp (the partial unique index already guarantees
-- at most one ACTIVE row per (domain, user)).
ALTER TABLE IF EXISTS domain_members
    ADD COLUMN IF NOT EXISTS last_opened_at TIMESTAMPTZ;

-- domain_assets: the domain's catalog of evaluation assets (rubrics, prompts,
-- compare sets, samples, clauses, law_info ...). Pure directory semantics:
-- many-to-many, and NO change to any asset table's shape or behaviour. A row
-- is a claim "this asset belongs in this domain's shelf", not ownership;
-- unassigning never touches the asset itself. asset_key is the asset's own
-- stable textual identifier (name / slug / id as text), never a FK, because
-- the asset tables are heterogeneous and predate domains.
CREATE TABLE IF NOT EXISTS domain_assets (
    domain_id   BIGINT NOT NULL REFERENCES domains(id),
    asset_kind  TEXT NOT NULL,
    asset_key   TEXT NOT NULL,
    added_by    TEXT NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (domain_id, asset_kind, asset_key)
);
CREATE INDEX IF NOT EXISTS domain_assets_asset_idx
    ON domain_assets (asset_kind, asset_key);

-- domain_proposals: the domain's proposal inbox (blueprint C5). A proposal is a
-- SUBMISSION SNAPSHOT plus its workflow state — it is never a second ontology
-- store and never participates in retrieval. Confirmation goes through the one
-- kernel write path (authoring upsert), so the KU table stays the only content
-- truth. The partial unique index is the idempotency rule: at most one PENDING
-- proposal per (domain, source, external_key); a rejected proposal stays on
-- record and a resubmission is only accepted with a different evidence_digest.
CREATE TABLE IF NOT EXISTS domain_proposals (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    domain_id       BIGINT NOT NULL REFERENCES domains(id),
    source          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    external_key    TEXT NOT NULL,
    body            TEXT NOT NULL,
    evidence        JSONB NOT NULL,
    evidence_digest TEXT NOT NULL,
    impact          TEXT NOT NULL DEFAULT '',
    state           TEXT NOT NULL DEFAULT 'pending'
                    CHECK (state IN ('pending', 'confirmed', 'rejected')),
    submitted_by    TEXT NOT NULL,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ,
    decision_note   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS domain_proposals_pending_uk
    ON domain_proposals (domain_id, source, external_key) WHERE state = 'pending';

-- sources：同一主张的**全部提交方**。去重身份过去是 (domain, source, external_key)，
-- 也就是"按提交方去重"——舰队岗与应用内团队同时上线时，同一主张会变成两行待确认，
-- 而人眼只有一双。现在按主张合并：同键同依据只有一行，source 记首个提交方，
-- sources 记全部提交方（见 src/bench/proposals.py::submit）。
ALTER TABLE domain_proposals
    ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb;
UPDATE domain_proposals
   SET sources = jsonb_build_array(source)
 WHERE sources = '[]'::jsonb;
CREATE INDEX IF NOT EXISTS domain_proposals_box_idx
    ON domain_proposals (domain_id, state, submitted_at DESC);

-- domain_proposal_events: append-only state trail (submit / confirm / reject).
-- No UPDATE or DELETE path may exist by design, same discipline as
-- authoring_events: the workflow history must stay replayable.
CREATE TABLE IF NOT EXISTS domain_proposal_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id BIGINT NOT NULL REFERENCES domain_proposals(id),
    from_state  TEXT,
    to_state    TEXT NOT NULL,
    actor       TEXT NOT NULL,
    note        TEXT,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS domain_proposal_events_proposal_idx
    ON domain_proposal_events (proposal_id, happened_at);

-- distribution_pull_events: append-only pull trail. The consumer row stays
-- untouched (no last_used_at column, no update contention); the ledger derives
-- "latest pull" per consumer from this table. Only successful pulls that
-- resolved a publication are recorded — a rejected credential or a 404 pull
-- leaves no event, so the trail never claims a pull that did not happen.
CREATE TABLE IF NOT EXISTS distribution_pull_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    consumer_id BIGINT NOT NULL REFERENCES distribution_consumers(id),
    domain_key  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    happened_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS distribution_pull_events_consumer_idx
    ON distribution_pull_events (consumer_id, happened_at DESC);

-- domain_agent_runs: 每轮智能体运行一行。这是"昨晚干了什么"的唯一答案，也是
-- `thin` 与 `failed` 必须分开的地方——前者升级给人，后者不得用重试掩盖。
--
-- 刻意不存推理过程：存的是**可复算的输入摘要 + 计数 + 产物引用**。运行结论文本
-- 没有审计价值，反而会诱使后来者把它当证据。`remaining` 单独成列，是因为
-- "批次不收敛"是实测过的失败模式，必须能被机械检测（见 src/bench/agent_runs.py）。
CREATE TABLE IF NOT EXISTS domain_agent_runs (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    role          TEXT NOT NULL,
    domain_key    TEXT NOT NULL,
    task_id       BIGINT REFERENCES authoring_tasks(id),
    run_key       TEXT,
    outcome       TEXT NOT NULL DEFAULT 'running'
                  CHECK (outcome IN ('running','ok','thin','failed','stopped')),
    input_digest  TEXT,
    counts        JSONB NOT NULL DEFAULT '{}'::jsonb,
    remaining     BIGINT,
    artifact_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    detail        TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS domain_agent_runs_domain_idx
    ON domain_agent_runs (domain_key, started_at DESC);
CREATE INDEX IF NOT EXISTS domain_agent_runs_outcome_idx
    ON domain_agent_runs (domain_key, outcome, started_at DESC);

-- 名字必须带域前缀：这个库是**多产品共用**的，`agent_runs` 这个泛名已被另一个
-- 产品线的同名表占用（字段是 thread/节点耗时/评分那一套，实测 23 行）。
-- `CREATE TABLE IF NOT EXISTS` 遇到
-- 同名旧表会静默跳过，随后给不存在的列建索引就会在**启动期**炸掉整个进程
-- （2026-11-09 实际发生，pod CrashLoopBackOff）。所以：不共用泛名，也不在启动期
-- 加断言——启动期抛异常本身就是那次事故的形态。

-- add-fleet-execution-loop §0.2 -----------------------------------------------
-- 三类指派人：人 / 内核岗位 / 已登记舰队。`assignee` 保留为人读展示名（既有读点
-- 与授权判断都在用它），类型与稳定引用另起两列——把「展示成什么」与「授权给谁」
-- 分开；混用一列时，同名不同身份的人会拿到别人的任务授权。
ALTER TABLE authoring_tasks
    ADD COLUMN IF NOT EXISTS assignee_kind TEXT NOT NULL DEFAULT 'human'
        CHECK (assignee_kind IN ('human','kernel-role','fleet'));
ALTER TABLE authoring_tasks
    ADD COLUMN IF NOT EXISTS assignee_ref TEXT;

-- 消费者分两种：只拉发布物的机器方，与既拉取又提交/回写的舰队。舰队的稳定标识
-- 存在 `fleet_ref`（如 `fleet_1794335712751_wfa3ww`），它是提案与运行回写里
-- `source` 的锚——来源从此能反查到一条登记，而不是一个曾经出现过的字符串。
-- 唯一性只约束「未吊销」：吊销后允许同一舰队重新登记，历史行保留可查。
ALTER TABLE distribution_consumers
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'machine'
        CHECK (kind IN ('machine','fleet'));
ALTER TABLE distribution_consumers
    ADD COLUMN IF NOT EXISTS fleet_ref TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS distribution_consumers_fleet_ref_uk
    ON distribution_consumers (fleet_ref)
 WHERE fleet_ref IS NOT NULL AND revoked_at IS NULL;

-- 提案的来源判定结论（`submitters.VERDICTS` 之一；NULL = 本列上线前入库的存量行）。
-- 单独成列而不是塞进 `impact`：迁移期要能按来源数「还有多少条没通过校验」，而
-- 从人读文本里做字符串匹配得到的计数不是判据。检索路径不读这一列，所以它不进
-- `_proposal_to_dict` 的投影——读面按需直查，既有消费方零感知。
ALTER TABLE domain_proposals
    ADD COLUMN IF NOT EXISTS submitter_verdict TEXT;
CREATE INDEX IF NOT EXISTS domain_proposals_submitter_verdict_idx
    ON domain_proposals (submitter_verdict, source)
 WHERE submitter_verdict IS NOT NULL;

-- 运行来源：内核岗位的确定性运行 / 外部舰队回写。没有这一列时，「谁在跑」只能
-- 看到内核那七个岗位，真正跑 LLM 的看不见——而 `/d/{key}/team` 正是查这张表。
-- `runner_ref` 是外部执行方的稳定标识（`fleet:<fleet>/<post>#<round>`），内核
-- 岗位留空：给它编一个反而会让「哪一轮」变成猜的。
ALTER TABLE domain_agent_runs
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'kernel'
        CHECK (origin IN ('kernel','fleet'));
ALTER TABLE domain_agent_runs
    ADD COLUMN IF NOT EXISTS runner_ref TEXT;
-- 幂等的**兜底**（不是替代）：回写去重靠存在性检查（`agent_runs.record_external_run`），
-- 但那一步有 TOCTOU 窗口——两个重试同时查不到行，于是同时插入，台账就会多一行
-- 「同一轮完成两次」。规格禁止的是「用唯一约束**代替**存在性检查」（`run_key` 允许
-- 为空、空值不参与唯一性，那种约束是假安全感），不禁止再加一道真能兜住的约束。
--
-- 部分索引只覆盖 `runner_ref IS NOT NULL`：只有外部回写受唯一性约束；内核岗位从不
-- 传 runner_ref，它们的 null 行一行都不受影响。兜底该有的形状就是约束那个必须唯一的域。
CREATE UNIQUE INDEX IF NOT EXISTS domain_agent_runs_runner_ref_key
    ON domain_agent_runs (runner_ref)
 WHERE runner_ref IS NOT NULL;

-- 产出结论互链（add-eval-verdict-ledger 4.1）：本轮产出的评测结论 id 列表。
-- 数组而非单值，因为一轮运行可以对多个知识单元各产出一条结论。
-- 默认空数组而非 NULL：NULL 要读面再分一次「没有结论」和「字段没填」，
-- 而这两种在这张表里是同一件事——本轮没产出结论。
-- 只存 id，不复制结论内容：两处各存一份必然漂移，台账的职责只是指路。
ALTER TABLE domain_agent_runs
    ADD COLUMN IF NOT EXISTS verdict_run_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
"""
