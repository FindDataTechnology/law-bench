"""Contract-generation mode routes: sync batch (D) + async jobs (E/F/G).

This router is the web surface for the generation capabilities that were
previously reachable only from an MCP client or the CLI. Every route is a thin
wrapper over an existing service function, the pipeline graph, or a subprocess -
no new business logic.

Routes:

- ``POST /api/contracts/{type}/generate-batch``       mode D, **sync**:
  assemble the contract across the requested (or enumerated) tag combinations
  and return ``{results, success_count, failure_count}`` + per-item file URLs.
- ``POST /api/contracts/{type}/pipeline``             mode E, **async**:
  insert a ``generation_jobs`` row, schedule ``run_self_heal_pipeline`` via
  ``BackgroundTasks``, return ``202 + {job_id, status:'pending'}``.
- ``POST /api/contracts/{type}/auto-reject``          mode F, async: same job
  pattern around ``run_auto_reject_pipeline``; ``result_ref`` adds
  ``learn_applied``.
- ``POST /api/contracts/{type}/regenerate-template``  mode G, async: run
  ``scripts/generate_contract_templates_llm.py --type {type} --force`` as a
  subprocess (the harbor-extraction pattern), capture stdout/stderr.
- ``GET  /api/generation-jobs``                       recent jobs (default 20).
- ``GET  /api/generation-jobs/{id}``                  single job; 404 if missing.

Async status machine mirrors ``api_eval_runs``:
``pending -> running -> completed | failed``. The poller is one shape regardless
of mode because ``result_ref`` is a JSON-text pointer to the mode's real output.
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.clauses import generate_contract_assembled
from src.clauses.coherence import CoherenceError
from src.clauses.tags import tag_vocab_for_type, validate_tags
from src.contracts import get_template
from src.eval.store import (
    get_generation_job,
    list_generation_jobs,
    store_generation_job,
    update_generation_job,
)
from src.settings import GENERATE_TEMPLATES_SCRIPT, REPO_ROOT

from ..auth.deps import require_scope
from ..deps import DbConn, get_db
from ..models import GenerationJobDetail, GenerationJobSubmit, GenerationRequest

router = APIRouter(prefix="/api", tags=["contract-generation"])


# --- shared helpers -------------------------------------------------------- #


def _require_type(contract_type: str) -> dict:
    """Validate ``contract_type``; raises :class:`NotFoundError` (-> 404) if unknown.

    Returns the template so callers can reuse it instead of re-fetching.
    """
    return get_template(contract_type)


def _file_url(path_str: str | None, contract_type: str) -> str | None:
    """Download URL for a generated file, or ``None`` when no file was written."""
    if not path_str:
        return None
    return f"/api/contracts/{contract_type}/files/{quote(Path(path_str).name)}"


def _check_mode(body: GenerationRequest, expected: str) -> None:
    """If the panel sent a ``mode`` field, it must match this route's canonical mode.

    The URL already determines the mode; ``mode`` is panel bookkeeping. We only
    reject a mismatch so a misrouted request fails fast (400) instead of doing
    the wrong work silently.
    """
    if body.mode and body.mode.upper() != expected:
        raise HTTPException(
            status_code=400,
            detail=f"mode {body.mode!r} does not match this route (expected {expected})",
        )


def _parse_result_ref(row: dict) -> Any:
    """Decode the ``result_ref`` JSON text into an object (or ``None``).

    The store layer persists ``result_ref`` as JSON text; ``GenerationJobDetail``
    declares it ``Optional[Any]`` so the panel gets a parsed object, not a string.
    A non-JSON value (legacy/manual row) is returned as the raw string.
    """
    raw = row.get("result_ref")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw


def _tags_from_body(body: GenerationRequest) -> dict | None:
    """Build the ``tags`` dict (scenario/stance) the pipeline + assembly expect."""
    tags: dict = {}
    if body.scenario:
        tags["scenario"] = body.scenario
    if body.stance:
        tags["stance"] = body.stance
    return tags or None


# --- mode D: sync batch generation ----------------------------------------- #


def _enumerate_combinations(contract_type: str) -> list[dict]:
    """Cartesian product of the type's tag dimensions (minus ``source``).

    Mirrors ``contract_generate_batch``'s enumeration path so the web route and
    the MCP tool produce the same combos.
    """
    vocab = tag_vocab_for_type(contract_type)
    dims = [k for k in vocab.keys() if k != "source"]
    values = [vocab[k] for k in dims]
    return [dict(zip(dims, combo)) for combo in product(*values)]


@router.post(
    "/contracts/{contract_type}/generate-batch",
    summary="Batch-assemble contracts across tag combinations (mode D, sync)",
    dependencies=[Depends(require_scope("content:write"))],
)
def generate_batch(
    contract_type: str, body: GenerationRequest, db: DbConn = Depends(get_db)
) -> dict:
    """Assemble the contract across the requested (or enumerated) tag combinations.

    Runs synchronously: assembly is local DB+template work (no LLM call), so even
    dozens of combos finish in seconds. ``max_concurrent`` (default 5, clamped
    to [1, 16]) bounds assembly parallelism; combos assemble through a bounded
    pool with per-combo connections, results stay in combination order. At 1
    the batch assembles sequentially on the borrowed request connection.
    Per-combo coherence-gate failures are reported in the item's ``error``
    (not a 422) so one bad combo doesn't sink the batch. Returns
    ``{contract_type, total_requested, success_count, failure_count, results}``
    where each result carries ``docx_url``/``pdf_url``.
    """
    _require_type(contract_type)
    _check_mode(body, "D")

    if body.enumerate_all:
        combos = _enumerate_combinations(contract_type)
    elif body.tag_combinations:
        combos = []
        for tc in body.tag_combinations:
            cleaned = validate_tags(tc, contract_type)
            if cleaned:
                combos.append(cleaned)
        if not combos:
            raise HTTPException(
                status_code=400, detail="no valid tag combinations provided"
            )
    else:
        raise HTTPException(
            status_code=400,
            detail="must provide tag_combinations or set enumerate_all=True",
        )

    fmt = body.format
    # Clamp the request's declared (previously ignored) concurrency field.
    max_concurrent = max(1, min(body.max_concurrent, 16))

    def _gen_one(tc: dict, conn) -> dict:
        try:
            result = generate_contract_assembled(
                contract_type,
                scenario=tc.get("scenario"),
                stance=tc.get("stance"),
                custom_clause_ids=body.custom_clause_ids,
                format=fmt,
                db=conn,
            )
        except CoherenceError as exc:
            return {"success": False, "tags": tc, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - per-combo isolation
            return {"success": False, "tags": tc, "error": str(exc)}
        return {
            "success": True,
            "tags": tc,
            "body_text": result.get("body_text"),
            "docx_url": _file_url(result.get("docx_path"), contract_type),
            "pdf_url": _file_url(result.get("pdf_path"), contract_type),
            "diagnostics": result.get("diagnostics"),
        }

    if max_concurrent == 1:
        # Fast path: assemble on the borrowed request-scoped connection.
        results = [_gen_one(tc, db) for tc in combos]
    else:
        # Parallel path: each combo opens its own connection - the borrowed
        # request connection (and the process-wide shared connection) must not
        # cross threads. pool.map preserves combination order; per-combo
        # failures stay isolated in that combo's result.
        from src.eval.db import open_fresh_conn

        def _gen_isolated(tc: dict) -> dict:
            conn = open_fresh_conn()
            try:
                return _gen_one(tc, conn)
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
            results = list(pool.map(_gen_isolated, combos))
    successes = sum(1 for r in results if r.get("success"))
    return {
        "contract_type": contract_type,
        "total_requested": len(combos),
        "success_count": successes,
        "failure_count": len(results) - successes,
        "results": results,
    }


# --- modes E/F/G: async job submit ---------------------------------------- #


def _run_self_heal(
    job_id: int, contract_type: str, body: GenerationRequest, db_path: DbConn
) -> None:
    """Background task: run the self-heal pipeline and update the job row.

    The pipeline import is local so a missing ``langgraph``/MCP dependency at web
    startup only fails this job (-> ``failed``) instead of crashing the app.
    """
    try:
        update_generation_job(job_id, status="running", db_path=db_path)
        from fd_coding_law_bench_mcp.pipeline.graph import run_self_heal_pipeline

        state = run_self_heal_pipeline(
            contract_type,
            tags=_tags_from_body(body),
            stance=body.stance,
            rubric=body.rubric,
            task_desc=body.task_desc,
            fill_mode="llm",
            temperature=body.temperature,
            max_iterations=body.max_iterations,
            custom_clause_ids=body.custom_clause_ids,
        )
        result_ref = {
            "pipeline_run_id": state.get("pipeline_run_id"),
            "score": state.get("score"),
            "all_pass": state.get("all_pass"),
            "n_passed": state.get("n_passed"),
            "n_criteria": state.get("n_criteria"),
            "iteration": state.get("iteration"),
            "eval_run_id": state.get("eval_run_id"),
        }
        update_generation_job(
            job_id, status="completed", result_ref=result_ref, db_path=db_path
        )
    except Exception as exc:  # noqa: BLE001 - never let the background task raise
        update_generation_job(
            job_id, status="failed", error_message=str(exc), db_path=db_path
        )


def _run_auto_reject(
    job_id: int, contract_type: str, body: GenerationRequest, db_path: DbConn
) -> None:
    """Background task: run the auto-reject pipeline (generate -> fill -> evaluate
    -> check -> improve -> store -> learn) and update the job row.

    The ``learn`` node aggregates clause-review recommendations and auto-rejects
    custom clauses that cross ``AUTO_REJECT_THRESHOLD``; ``learn_applied`` is
    surfaced in ``result_ref``.
    """
    try:
        update_generation_job(job_id, status="running", db_path=db_path)
        from fd_coding_law_bench_mcp.pipeline.auto_graph import run_auto_reject_pipeline

        state = run_auto_reject_pipeline(
            contract_type,
            tags=_tags_from_body(body),
            stance=body.stance,
            rubric=body.rubric,
            task_desc=body.task_desc,
            fill_mode="llm",
            temperature=body.temperature,
            max_iterations=body.max_iterations,
            custom_clause_ids=body.custom_clause_ids,
        )
        result_ref = {
            "pipeline_run_id": state.get("pipeline_run_id"),
            "score": state.get("score"),
            "all_pass": state.get("all_pass"),
            "iteration": state.get("iteration"),
            "learn_applied": state.get("learn_applied"),
        }
        update_generation_job(
            job_id, status="completed", result_ref=result_ref, db_path=db_path
        )
    except Exception as exc:  # noqa: BLE001
        update_generation_job(
            job_id, status="failed", error_message=str(exc), db_path=db_path
        )


def _run_regenerate(
    job_id: int, contract_type: str, db_path: DbConn
) -> None:
    """Background task: regenerate the type's 母版 body via the LLM script.

    Shells out to ``scripts/generate_contract_templates_llm.py --type {type}
    --force`` (the harbor-extraction pattern) so the global ``contracts.json``
    mutation + LLM caching stay encapsulated in the script. Captures stdout/stderr
    into ``result_ref``; a non-zero exit -> ``failed`` with stderr in
    ``error_message``.
    """
    try:
        update_generation_job(job_id, status="running", db_path=db_path)
        if not GENERATE_TEMPLATES_SCRIPT.is_file():
            update_generation_job(
                job_id,
                status="failed",
                error_message=f"script not found: {GENERATE_TEMPLATES_SCRIPT}",
                db_path=db_path,
            )
            return
        proc = subprocess.run(
            [
                sys.executable,
                str(GENERATE_TEMPLATES_SCRIPT),
                "--type",
                contract_type,
                "--force",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        result_ref = {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if proc.returncode != 0:
            update_generation_job(
                job_id,
                status="failed",
                error_message=(proc.stderr or "").strip() or f"exit {proc.returncode}",
                result_ref=result_ref,
                db_path=db_path,
            )
            return
        update_generation_job(
            job_id, status="completed", result_ref=result_ref, db_path=db_path
        )
    except Exception as exc:  # noqa: BLE001
        update_generation_job(
            job_id, status="failed", error_message=str(exc), db_path=db_path
        )


@router.post(
    "/contracts/{contract_type}/pipeline",
    status_code=202,
    response_model=GenerationJobSubmit,
    summary="Submit a self-heal pipeline job (mode E, async)",
    dependencies=[Depends(require_scope("content:write"))],
)
def submit_pipeline(
    contract_type: str,
    body: GenerationRequest,
    background_tasks: BackgroundTasks,
    db: DbConn = Depends(get_db),
) -> dict:
    """Validate the type, insert a ``pipeline`` job row, schedule the self-heal
    pipeline, and return ``202 + {job_id, status:'pending'}``. Poll via
    ``GET /api/generation-jobs/{job_id}``.
    """
    _require_type(contract_type)
    _check_mode(body, "E")
    job_id = store_generation_job("pipeline", contract_type, db_path=db)
    background_tasks.add_task(_run_self_heal, job_id, contract_type, body, db)
    return {"job_id": job_id, "status": "pending"}


@router.post(
    "/contracts/{contract_type}/auto-reject",
    status_code=202,
    response_model=GenerationJobSubmit,
    summary="Submit an auto-reject pipeline job (mode F, async)",
    dependencies=[Depends(require_scope("content:write"))],
)
def submit_auto_reject(
    contract_type: str,
    body: GenerationRequest,
    background_tasks: BackgroundTasks,
    db: DbConn = Depends(get_db),
) -> dict:
    """Insert an ``auto_reject`` job row, schedule the auto-reject pipeline
    (which also runs the ``learn`` node that auto-rejects repeatedly-thin custom
    clauses), return ``202 + {job_id, status:'pending'}``.
    """
    _require_type(contract_type)
    _check_mode(body, "F")
    job_id = store_generation_job("auto_reject", contract_type, db_path=db)
    background_tasks.add_task(_run_auto_reject, job_id, contract_type, body, db)
    return {"job_id": job_id, "status": "pending"}


@router.post(
    "/contracts/{contract_type}/regenerate-template",
    status_code=202,
    response_model=GenerationJobSubmit,
    summary="Submit a 母版 regeneration job (mode G, async)",
    dependencies=[Depends(require_scope("admin"))],
)
def submit_regenerate(
    contract_type: str,
    body: GenerationRequest,
    background_tasks: BackgroundTasks,
    db: DbConn = Depends(get_db),
) -> dict:
    """Insert a ``regenerate`` job row, schedule the LLM 母版-regeneration
    subprocess for this contract type, return ``202 + {job_id, status:'pending'}``.

    The subprocess rewrites the global ``src/contracts/data/contracts.json``;
    the panel shows a confirm dialog naming that file before triggering this.
    """
    _require_type(contract_type)
    _check_mode(body, "G")
    job_id = store_generation_job("regenerate", contract_type, db_path=db)
    background_tasks.add_task(_run_regenerate, job_id, contract_type, db)
    return {"job_id": job_id, "status": "pending"}


# --- job polling ---------------------------------------------------------- #


@router.get(
    "/generation-jobs",
    response_model=list[GenerationJobDetail],
    summary="List recent generation jobs",
)
def list_jobs(limit: int = 20, db: DbConn = Depends(get_db)) -> list[dict]:
    """Recent generation jobs (most recent first, default 20)."""
    rows = list_generation_jobs(limit=limit, db_path=db)
    for r in rows:
        r["result_ref"] = _parse_result_ref(r)
    return rows


@router.get(
    "/generation-jobs/{job_id}",
    response_model=GenerationJobDetail,
    summary="Poll a generation job",
)
def get_job(job_id: int, db: DbConn = Depends(get_db)) -> dict:
    """Full job row. ``status`` is ``pending``/``running``/``completed``/``failed``;
    ``result_ref`` is the parsed JSON pointer to the mode's output (or ``None``
    while pending/running). 404 if the id is unknown.
    """
    row = get_generation_job(job_id, db_path=db)
    if row is None:
        raise HTTPException(status_code=404, detail=f"job not found: {job_id}")
    row["result_ref"] = _parse_result_ref(row)
    return row
