"""MCP tool behavior annotations (mcp-tool-annotations).

Every ``@mcp.tool`` registration passes ``annotations=annotations_for(<name>)``
so the protocol surface carries the four hints a client needs to decide its
auto-approval policy without reading source or guessing from Chinese prose:

- ``readOnlyHint``     - does not change any persistent state.
- ``destructiveHint``  - may cause an unrecoverable change (delete or an
  in-place overwrite with no history to restore from).
- ``idempotentHint``   - repeating the same call has no additional effect on
  the environment (protocol definition; only meaningful when not read-only).
- ``openWorldHint``    - the result depends on a non-enumerable, changing
  external entity set. Here that means the LLM gateway: drafting, judging,
  filling and retagging all route through a model. Database rows, the
  Elasticsearch corpus and the MinIO bucket are service-owned closed sets -
  "touches another service" is not "open world".

The table is the single source of truth: the runtime decorators, the
``tool-surface.json`` manifest and the selfcheck/test gates all read it.
``annotations_for`` raises on an unregistered name rather than defaulting -
a silent default would let a new tool ship with a wrong (or missing) hint.
"""

from __future__ import annotations

from typing import Any

#: Reads only: catalog / listing / query / metrics.
READ_ONLY: dict[str, Any] = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

#: Writes, but a repeated call converges on the same state (fixed output path,
#: content-addressed artifact reuse, set-to-value update).
WRITE_IDEMPOTENT: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}

#: Writes and appends a fresh row per call - repeating it adds state.
WRITE_APPEND: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": False,
}

#: Appends rows *and* calls the LLM (draft / judge / fill / retag).
WRITE_LLM_APPEND: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

#: Deletes a row or overwrites user-authored content in place with no history.
WRITE_DESTRUCTIVE: dict[str, Any] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": False,
}

#: Tool name -> the four hints. Every registered tool is listed explicitly
#: (even when the value equals a shared preset) so a new tool that forgets to
#: register fails the gate instead of inheriting a plausible default.
TOOL_ANNOTATIONS: dict[str, dict[str, Any]] = {
    # --- agent metrics (DB reads + append-only instrumentation) ---
    "agent_run_get": dict(READ_ONLY),
    "agent_run_list": dict(READ_ONLY),
    "agent_run_store": dict(WRITE_APPEND),  # INSERT per call, no LLM
    # --- contract generation ---
    # Writes DOCX/PDF under out_dir. Derived, regenerable artifacts are not
    # destructive; the fixed output path makes a repeat converge.
    "contract_generate": dict(WRITE_IDEMPOTENT),
    # Forces format="markdown" (content is returned, not persisted), but it
    # still drives generate_contract_assembled, which mkdirs the output
    # directory before branching on format. A directory creation is an
    # environment change, so this is not read-only; the repeat converges.
    "contract_generate_batch": dict(WRITE_IDEMPOTENT),
    # Content-first path: markdown mode is pure, but format=docx/pdf writes
    # files, so the tool as a whole is not read-only.
    "contract_content": dict(WRITE_IDEMPOTENT),
    # Content-addressed by md5(body_text): identical inputs reuse the same
    # artifact row and object keys (reused=true), so a repeat adds no state.
    # MinIO is a service-owned bucket, not an open world.
    "contract_generate_stored": dict(WRITE_IDEMPOTENT),
    "contract_download": dict(READ_ONLY),
    # --- catalog / tags (pure DB reads) ---
    "contract_type_catalog": dict(READ_ONLY),
    "type_metadata": dict(READ_ONLY),
    "tag_vocab_list": dict(READ_ONLY),
    "tag_validate": dict(READ_ONLY),
    "tag_combinations_list": dict(READ_ONLY),
    # --- clauses ---
    "clause_list": dict(READ_ONLY),
    "clause_get": dict(READ_ONLY),
    # In-place body/section/tags replacement; no revision history to restore.
    "clause_update": dict(WRITE_DESTRUCTIVE),
    "clause_delete": dict(WRITE_DESTRUCTIVE),
    # Sets review status; re-approving restores assembly eligibility.
    "clause_review": dict(WRITE_IDEMPOTENT),
    # --- rubrics / criteria ---
    "rubric_list": dict(READ_ONLY),
    "rubric_get": dict(READ_ONLY),
    "rubric_create": dict(WRITE_APPEND),
    # In-place overwrite of the rubric row (harbor rubrics are rejected).
    "rubric_update": dict(WRITE_DESTRUCTIVE),
    "rubric_delete": dict(WRITE_DESTRUCTIVE),  # criteria cascade via FK
    "criterion_add": dict(WRITE_APPEND),
    "criterion_update": dict(WRITE_DESTRUCTIVE),
    "criterion_delete": dict(WRITE_DESTRUCTIVE),
    "criterion_reorder": dict(WRITE_IDEMPOTENT),  # same order -> same ordinals
    # --- prompts ---
    "prompt_list": dict(READ_ONLY),
    "prompt_get": dict(READ_ONLY),
    "prompt_create": dict(WRITE_APPEND),
    "prompt_update": dict(WRITE_DESTRUCTIVE),  # full-record overwrite
    "prompt_delete": dict(WRITE_DESTRUCTIVE),
    # --- evaluation (LLM judge) ---
    # Persists one eval_runs row per call unless no_store=True; the judge is
    # an LLM, so the result is not reproducible from the DB alone.
    "contract_evaluate": dict(WRITE_LLM_APPEND),
    "run_list": dict(READ_ONLY),
    "run_get": dict(READ_ONLY),
    # --- compare (LLM draft + judge per draft) ---
    "compare_run": dict(WRITE_LLM_APPEND),
    "compare_list": dict(READ_ONLY),
    "compare_get": dict(READ_ONLY),
    "compare_matrix": dict(READ_ONLY),
    "run_draft": dict(READ_ONLY),
    # --- long-running task handles (mcp-long-running-operations) ---
    "task_status": dict(READ_ONLY),
    "task_failed_items": dict(READ_ONLY),

    # --- pipelines (LLM fill/judge/improve; one pipeline_runs row per call) ---
    "self_heal_pipeline_run": dict(WRITE_LLM_APPEND),
    # Also auto-rejects high-confidence clauses; the review status is
    # reversible, so this is not destructive.
    "auto_reject_pipeline_run": dict(WRITE_LLM_APPEND),
    "pipeline_list": dict(READ_ONLY),
    "pipeline_get": dict(READ_ONLY),
    # Despite "read-only on clauses table", it persists a pipeline/eval run and
    # calls the LLM - the tool as a whole is a write.
    "tag_iteration_suggest": dict(WRITE_LLM_APPEND),
    # Rewrites clause tags, then rolls back on a score drop and returns the
    # original tags. The rollback makes it non-destructive; two self-heal runs
    # per call plus the LLM make it non-idempotent.
    "tag_iteration_apply": dict(WRITE_LLM_APPEND),
    # --- search / law / validation reads ---
    # Elasticsearch is a versioned, enumerable corpus owned by the service.
    "search_clauses": dict(READ_ONLY),
    "law_types": dict(READ_ONLY),
    "law_info": dict(READ_ONLY),
    "law_references": dict(READ_ONLY),
    "validation_check": dict(READ_ONLY),
    "validation_list": dict(READ_ONLY),
}


def annotations_for(name: str) -> dict[str, Any]:
    """Return a copy of ``name``'s hints; raise ``KeyError`` if unregistered."""
    try:
        return dict(TOOL_ANNOTATIONS[name])
    except KeyError:
        raise KeyError(
            f"tool {name!r} has no entry in annotations.TOOL_ANNOTATIONS"
        ) from None


def all_annotations() -> dict[str, dict[str, Any]]:
    """Every tool's hints, for generating ``tool-surface.json``."""
    return {name: dict(hints) for name, hints in TOOL_ANNOTATIONS.items()}
