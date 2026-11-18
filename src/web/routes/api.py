"""JSON API for evaluation rubrics and criteria.

All write paths delegate to `src/eval/manage.py`, which raises `ManageError`
subclasses; those are mapped to HTTP statuses by exception handlers registered
in `src/web/app.py`. Routes here therefore stay thin: call the service, return
its dict. Each handler takes a ``db`` dependency (see ``src/web/deps.py``) so
tests can point the layer at a throwaway DB instead of the dev one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile
from fastapi.responses import JSONResponse

from src.eval import manage as M
from src.eval.compare import build_matrix, load_prompts, run_compare
from src.eval.scoring import evaluate_contract
from src.eval.store import (
    get_api_eval_run,
    get_compare,
    get_run_draft,
    list_api_eval_runs,
    list_compares,
    store_api_eval_run,
    update_api_eval_run,
)
from src.settings import DEFAULT_DB, EXTRACT_SCRIPT, REPO_ROOT

from ..auth.deps import require_scope
from ..deps import DbConn, get_db
from ..models import (
    CompareCreate,
    CriterionCreate,
    CriterionUpdate,
    EvaluateRunDetail,
    EvaluateRunSummary,
    EvaluateSubmitResponse,
    PromptCreate,
    PromptUpdate,
    ReorderRequest,
    RubricCreate,
    RubricUpdate,
)

router = APIRouter(prefix="/api", tags=["evaluation-rules"])


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


# --- read ------------------------------------------------------------------ #


@router.get("/rubrics")
def list_rubrics(db: DbConn = Depends(get_db)) -> list[dict]:
    """All rubrics with source/context/criterion count."""
    return M.list_rubrics_with_counts(db_path=db)


@router.get("/rubrics/{name}")
def get_rubric(name: str, db: DbConn = Depends(get_db)) -> dict:
    """A rubric's metadata and its ordered criteria."""
    return M.get_rubric_detail(name, db_path=db)


# --- rubric writes --------------------------------------------------------- #


@router.post(
    "/rubrics",
    status_code=201,
    dependencies=[Depends(require_scope("content:write"))],
)
def create_rubric(body: RubricCreate, db: DbConn = Depends(get_db)) -> dict:
    return M.create_rubric(
        body.name,
        body.context,
        body.description,
        [c.model_dump() for c in body.criteria],
        db_path=db,
    )


@router.patch(
    "/rubrics/{name}", dependencies=[Depends(require_scope("content:write"))]
)
def update_rubric(name: str, body: RubricUpdate, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)  # raises NotFoundError if missing
    return M.update_rubric(
        detail["id"], body.name, body.context, body.description, db_path=db
    )


@router.delete(
    "/rubrics/{name}", dependencies=[Depends(require_scope("admin"))]
)
def delete_rubric(name: str, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    M.delete_rubric(detail["id"], db_path=db)
    return {"deleted": name}


# --- criterion writes ------------------------------------------------------ #


@router.post(
    "/rubrics/{name}/criteria",
    status_code=201,
    dependencies=[Depends(require_scope("content:write"))],
)
def add_criterion(name: str, body: CriterionCreate, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    return M.add_criterion(
        detail["id"], body.name, body.description, body.guidance, db_path=db
    )


# Defined before the {cid} routes so "/criteria/reorder" is not matched as an int cid.
@router.post(
    "/rubrics/{name}/criteria/reorder",
    dependencies=[Depends(require_scope("content:write"))],
)
def reorder_criteria(name: str, body: ReorderRequest, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_rubric_detail(name, db_path=db)
    ordered = M.reorder_criteria(detail["id"], body.ordered_criterion_ids, db_path=db)
    return {"ordered_criterion_ids": ordered}


@router.patch(
    "/rubrics/{name}/criteria/{cid}",
    dependencies=[Depends(require_scope("content:write"))],
)
def update_criterion(
    name: str, cid: int, body: CriterionUpdate, db: DbConn = Depends(get_db)
) -> dict:
    return M.update_criterion(cid, body.name, body.description, body.guidance, db_path=db)


@router.delete(
    "/rubrics/{name}/criteria/{cid}",
    dependencies=[Depends(require_scope("admin"))],
)
def delete_criterion(name: str, cid: int, db: DbConn = Depends(get_db)) -> dict:
    M.delete_criterion(cid, db_path=db)
    return {"deleted": cid}


# --- prompts --------------------------------------------------------------- #


@router.get("/prompts")
def list_prompts(db: DbConn = Depends(get_db)) -> list[dict]:
    """All generation prompts (without content bodies)."""
    return M.list_prompts(db_path=db)


@router.get("/prompts/{name}")
def get_prompt(name: str, db: DbConn = Depends(get_db)) -> dict:
    """A prompt's full record including its content."""
    return M.get_prompt(name, db_path=db)


@router.post(
    "/prompts",
    status_code=201,
    dependencies=[Depends(require_scope("content:write"))],
)
def create_prompt(body: PromptCreate, db: DbConn = Depends(get_db)) -> dict:
    return M.create_prompt(
        body.name,
        body.contract_type,
        body.purpose,
        body.content,
        body.description,
        body.prompt_type,
        db_path=db,
    )


@router.patch(
    "/prompts/{name}", dependencies=[Depends(require_scope("content:write"))]
)
def update_prompt(name: str, body: PromptUpdate, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_prompt(name, db_path=db)  # raises NotFoundError if missing
    return M.update_prompt(
        detail["id"],
        body.name,
        body.contract_type,
        body.purpose,
        body.content,
        body.description,
        body.prompt_type,
        db_path=db,
    )


@router.delete(
    "/prompts/{name}", dependencies=[Depends(require_scope("admin"))]
)
def delete_prompt(name: str, db: DbConn = Depends(get_db)) -> dict:
    detail = M.get_prompt(name, db_path=db)
    M.delete_prompt(detail["id"], db_path=db)
    return {"deleted": name}


# --- compare --------------------------------------------------------------- #


@router.get("/compare")
def list_compares_route(db: DbConn = Depends(get_db)) -> list[dict]:
    """Recent compare runs (compare-level fields only)."""
    return list_compares(db_path=db)


@router.get("/compare/{compare_id}")
def get_compare_route(compare_id: int, db: DbConn = Depends(get_db)) -> dict:
    """Full grouped compare result with a derived criteria × prompts matrix.

    ``draft_text`` is excluded (lazy-fetched via ``/run/{run_id}/draft``).
    """
    try:
        compare = get_compare(compare_id, db_path=db)
    except KeyError:
        return _err(404, f"Compare not found: {compare_id}")
    return {**compare, "matrix": build_matrix(compare)}


@router.post(
    "/compare",
    status_code=201,
    dependencies=[Depends(require_scope("content:write"))],
)
def create_compare(body: CompareCreate, db: DbConn = Depends(get_db)) -> dict:
    """Create and run a compare synchronously.

    Runs the drafter-only generation + the real judge for each prompt/draft.
    Large compares (many prompts × high ``n_drafts``) can take minutes; for
    those prefer the CLI (``python -m src.eval.compare``). Async-with-progress
    is a tracked follow-up. ``concurrency`` bounds parallel draft generation
    (clamped to [1, 8]; default 1 = sequential).
    """
    prompts = load_prompts(body.prompts, db_path=db)  # raises NotFoundError -> 404
    compare = run_compare(
        body.contract_type,
        body.rubric_name,
        body.task_desc,
        prompts,
        mode=body.mode,
        n_drafts=body.n_drafts,
        concurrency=max(1, min(body.concurrency, 8)),
        label=body.label,
        db_path=db,
    )
    return {**compare, "matrix": build_matrix(compare)}


@router.get("/compare/{compare_id}/run/{run_id}/draft")
def get_run_draft_route(compare_id: int, run_id: int, db: DbConn = Depends(get_db)) -> dict:
    """Lazy-fetch a single run's ``draft_text`` (kept out of the default payload)."""
    try:
        return get_run_draft(compare_id, run_id, db_path=db)
    except KeyError:
        return _err(404, f"Run {run_id} not found in compare {compare_id}")


# --- harbor re-extraction -------------------------------------------------- #


def run_harbor_extraction(db_path: Path = DEFAULT_DB) -> tuple[int, str, str]:
    """Run the harbor extraction script; return (returncode, stdout, stderr).

    Shared by the JSON endpoint and the HTML "Re-extract harbor" control so the
    two cannot diverge.
    """
    proc = subprocess.run(
        [sys.executable, str(EXTRACT_SCRIPT), "--db", str(db_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


@router.post(
    "/harbor/extract", dependencies=[Depends(require_scope("admin"))]
)
def harbor_extract(db: DbConn = Depends(get_db)) -> JSONResponse:
    """Re-run the harbor extraction script; return its summary + refreshed rubrics.

    Surface a non-zero exit as an error (e.g. harbor not installed).
    """
    if not EXTRACT_SCRIPT.is_file():
        return _err(500, f"extraction script not found: {EXTRACT_SCRIPT}")
    code, out, err = run_harbor_extraction()
    if code != 0:
        return _err(500, f"harbor extraction failed (exit {code}): {(err or '').strip()}")
    return JSONResponse(
        {"returncode": code, "stdout": out, "rubrics": M.list_rubrics_with_counts(db_path=db)}
    )


# --- evaluate -------------------------------------------------------------- #


def _run_evaluation_background(run_id: int, rubric_name: str, contract_text: str, db_path: DbConn) -> None:
    """Background task: evaluate contract and update api_eval_runs."""
    try:
        update_api_eval_run(run_id, status="running", db_path=db_path)
        result = evaluate_contract(contract_text, rubric_name, db_path=db_path)
        update_api_eval_run(
            run_id,
            status="completed",
            score=result["score"],
            all_pass=result["all_pass"],
            n_passed=result["n_passed"],
            n_criteria=result["n_criteria"],
            results=result,
            judge_model=result.get("judge_model"),
            db_path=db_path,
        )
    except Exception as e:
        update_api_eval_run(
            run_id,
            status="failed",
            error_message=str(e),
            db_path=db_path,
        )


@router.post(
    "/evaluate",
    status_code=202,
    response_model=EvaluateSubmitResponse,
    dependencies=[Depends(require_scope("content:write"))],
)
async def submit_evaluation(
    background_tasks: BackgroundTasks,
    rubric: str = Form(...),
    contract_text: str = Form(None),
    contract_file: UploadFile = None,
    db: DbConn = Depends(get_db),
) -> dict:
    """Submit a contract for async evaluation against a rubric.

    Accepts either inline contract_text or a contract_file upload (one required).
    Returns 202 Accepted with run_id for polling.
    """
    # Validate rubric exists (raises NotFoundError -> 404 if missing)
    M.get_rubric_detail(rubric, db_path=db)

    # Read contract text from file or form field
    if contract_file:
        content = await contract_file.read()
        text = content.decode("utf-8")
    elif contract_text:
        text = contract_text
    else:
        return _err(400, "Either contract_text or contract_file is required")

    # Insert pending row
    run_id = store_api_eval_run(rubric, text, db_path=db)

    # Start background evaluation
    background_tasks.add_task(_run_evaluation_background, run_id, rubric, text, db)

    return {"run_id": run_id, "status": "pending"}


@router.get("/evaluate", response_model=list[EvaluateRunSummary])
def list_evaluations(limit: int = 20, db: DbConn = Depends(get_db)) -> list[dict]:
    """Recent API evaluation runs (most recent first)."""
    return list_api_eval_runs(limit=limit, db_path=db)


@router.get("/evaluate/{run_id}", response_model=EvaluateRunDetail)
def get_evaluation(run_id: int, db: DbConn = Depends(get_db)) -> dict:
    """Full detail of an API evaluation run."""
    try:
        return get_api_eval_run(run_id, db_path=db)
    except KeyError:
        return _err(404, f"API eval run not found: {run_id}")
