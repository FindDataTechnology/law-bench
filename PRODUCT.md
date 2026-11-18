# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

A solo operator (the project's developer) using the web workbench end-to-end: curating and reviewing clauses, managing prompts and rubrics, running evaluation pipelines and prompt compares, and generating contract artifacts. The same operator acts as human reviewer over eval verdicts under the `lawbench-annotator` Logto role (repo-verified 2026-09-26). No external or team audience is targeted today (confirmed 2026-08-29).

## Product Purpose

An internal workbench for drafting and benchmarking Chinese legal contracts with LLMs. It assembles contracts from a curated, statute-grounded clause corpus, judges drafts against rubrics with an LLM judge, self-heals low-scoring drafts, and compares drafting prompts head-to-head. Success means measurable, reproducible improvements in contract quality per rubric scores, and a steadily deepening clause corpus.

## Positioning

The closed evaluation loop: tag-driven clause assembly, LLM-judge rubric scoring, self-heal pipelines, and prompt A/B compare in one bench. Neighboring contract generators produce drafts; this product measures them (confirmed by the operator).

## Operating Context

- Workflows run through a login-gated FastAPI + Jinja2 web UI (dashboard, clause review/edit, prompts, rubrics, compare runs, contract generation, clause RAG search, law references, law catalog, human review, samples, plus an admin-gated CopilotKit floating assistant) and a `law-bench` MCP server for agent-driven operation (repo-verified 2026-09-26).
- Evaluation state lives in Postgres (clauses, prompts, rubrics, eval/compare/pipeline runs); artifacts in RustFS, the S3-compatible object store whose `minio_*` env names persist; the bench core stays deliberately vector-free — semantic law search runs through the `law-api` gateway (Qdrant behind it) while Elasticsearch-backed clause-chunk RAG remains in `src/search/` (repo-verified 2026-09-26).
- Contract artifacts render to Markdown, DOCX, and PDF; deterministic fills default to temperature 0 for reproducibility.
- The workbench and public API serve under `*.finddatatech.cloud` on the shared k3s cluster, gated by the shared Logto IdP (`auth.finddatatech.cloud`); deploys flow Gitee → Jenkins → Harbor → ArgoCD (runbook: `deploy/cheap-box/README.md`) (repo-verified 2026-09-26).

## Capabilities and Constraints

- Chinese legal domain (confirmed): the UI stays simplified Chinese; contract content, clause bodies, rubrics, and law references remain PRC-law Chinese.
- Contract types are catalog-driven (sale, lease, employment, …) with tag dimensions such as scenario and stance.
- A PRC statute law catalog (32,275 laws at the 2026-09 refresh) lives as a replica in prod Postgres with alias curation, article-level citation resolution, and corpus audit; a 66-name ingestion backlog tracks catalog-side expansion (`docs/law-catalog-runbook.md`, `docs/law-catalog-ingestion-backlog.md`) (repo-verified 2026-09-26).
- The drafter can call a `law_search` tool through the law-api client and embed article-level citations in generated contracts (repo-verified 2026-09-26).
- Web human review over eval verdicts: blind annotation, inter-annotator agreement QC, and gold export; the annotator stamp is always the session identity, never a form field (repo-verified 2026-09-26).
- Undecided: none raised this session.

## Evidence on Hand

- Real evaluation history in Postgres: eval runs, compare runs, and pipeline runs with per-criterion verdicts.
- A curated clause corpus seeded from real contract sources with statute citations; workflow and architecture docs under `docs/` (evaluation-system.md, tag-driven-assembly.md, pipeline-architecture.md, v4-final-results.md, law_citation_audit_report.md).
- A live human-review pilot batch running over V4 outputs (repo-verified 2026-09-26).
- Absences future work must not fabricate: no customer testimonials, no external user research, no marketing claims.

## Product Principles

1. Evidence over vibes: drafting changes ship only after rubric-judged evaluation measures them.
2. The corpus is the product: curated, reviewed, statute-grounded clauses with tags beat prompt heroics.
3. Operator speed first: the web UI exists to make one person fast at curating and evaluating.
4. Chinese legal fidelity: contract language stays simplified Chinese and PRC-law accurate.
5. Reproducibility: versioned rubrics, stored artifacts, deterministic fills.
