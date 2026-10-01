"""Contract-context JSON API: the agent-facing surface under ``/api/contracts``.

Every endpoint is a thin route over an existing service function (``src.contracts``,
``src.clauses``, ``src.eval``) - no business logic. DB-backed reads take
``db: DbConn = Depends(get_db)`` reusing the existing connection-borrowing seam so
tests can point the layer at a throwaway DB. All endpoints are documented in the
``/api/docs`` OpenAPI schema (the generated-file download route is the only
exception - it is an implementation detail of the ``generate`` download URLs).

Endpoints:

- ``GET  /api/contracts``                          list contract classes
- ``GET  /api/contracts/{type}``                    comprehensive context bundle
- ``GET  /api/contracts/{type}/slots``              slot manifest + ontology coverage
- ``GET  /api/contracts/{type}/laws``               law refs + full survey markdown
- ``GET  /api/contracts/{type}/tags``               tag vocabulary for the type
- ``GET  /api/contracts/{type}/clauses``            clause catalog (filter + paginate)
- ``POST /api/contracts/{type}/generate``           assemble + render (docx default)
- ``GET  /api/contracts/{type}/files/{filename}``   serve a generated docx/pdf (internal)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from src.clauses import generate_contract_assembled, list_clauses
from src.clauses.coherence import CoherenceError
from src.clauses.extract import SECTION_ORDER
from src.clauses.tags import tag_vocab_for_type
from src.contracts import (
    extract_laws_for_type,
    get_slot_instructions,
    get_template,
    list_contract_types,
)
from src.contracts.artifacts import (
    generate_all_stored,
    generate_stored,
    get_artifact,
    list_artifacts,
    download as download_artifact,
)
from src.contracts.slot_ontology import instruction_for_slot
from src.eval.errors import NotFoundError
from src.eval.law_info import get_law_info
from src.eval.manage import list_prompts, list_rubrics_with_counts

from ..auth.deps import require_scope
from ..deps import DbConn, get_db

# src/web/routes/contract_context.py -> routes -> web -> src -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_DIR = _REPO_ROOT / "output" / "contracts"

# The router is split into a read-only surface and a write surface so the public
# pod (``create_public_app``) can mount only ``read_only_router`` and exclude the
# generation/write routes (design D2: behavior-preserving split — the origin
# includes both). Both routers share the ``/api/contracts`` prefix and the
# ``contract-context`` tag so the origin's OpenAPI shape is unchanged.
read_only_router = APIRouter(prefix="/api/contracts", tags=["contract-context"])
write_router = APIRouter(
    prefix="/api/contracts",
    tags=["contract-context"],
    dependencies=[Depends(require_scope("content:write"))],
)

# Backward-compat alias ``router`` is assembled at the END of this module:
# ``include_router`` copies the sub-routers' routes at call time, so the parent
# must be built AFTER every ``@read_only_router``/``@write_router`` decorator
# below has registered its route. See ``router`` at the file bottom.


class GenerateRequest(BaseModel):
    """Shared request body for ``generate`` and ``generate-stored``."""
    scenario: str | None = None
    stance: str | None = None
    custom_clause_ids: list[int] | None = None
    format: Literal["docx", "pdf", "both", "markdown"] = "docx"
    # Re-upload the requested formats for an existing artifact (overwrite the
    # MinIO object) even when the body hash matches — refresh visuals after a
    # renderer change that does not alter body_text. No-op on new artifacts.
    force: bool = False


# --- response shaping ------------------------------------------------------ #


def _require_type(contract_type: str) -> dict:
    """Validate ``contract_type``; raises :class:`NotFoundError` (-> 404) if unknown.

    Returns the template so callers that already need it (slots, bundle) reuse it
    instead of re-fetching.
    """
    return get_template(contract_type)


def _slot_manifest_with_ontology(
    contract_type: str, template_slots: list[str]
) -> list[dict]:
    """Slot instructions for every template slot, with a ``source`` per entry.

    ``registry``   - from the type's hand-written manifest (``get_slot_instructions``)
    ``ontology``   - resolved from ``slot_ontology.instruction_for_slot`` for a
                     variant slot (e.g. ``seller_address`` -> the ``address`` concept)
    ``uncovered``   - template slot with no instruction anywhere (data debt)

    The ``name`` is always the literal ``{{slot}}`` token in the template body so an
    agent can map instruction -> placeholder directly.
    """
    manifest = {si["name"]: si for si in get_slot_instructions(contract_type)}
    out: list[dict] = []
    for slot in template_slots:
        if slot in manifest:
            entry = dict(manifest[slot])
            entry["source"] = "registry"
        else:
            instr = instruction_for_slot(slot, contract_type)
            if instr is not None:
                entry = {
                    "name": slot,
                    "label": instr.get("label", ""),
                    "description": instr.get("description", ""),
                    "example": instr.get("example", ""),
                    "required": instr.get("required", False),
                    "source": "ontology",
                }
            else:
                entry = {
                    "name": slot,
                    "label": "",
                    "description": "",
                    "example": "",
                    "required": False,
                    "source": "uncovered",
                }
        out.append(entry)
    return out


def _latest_rubric_for_type(contract_type: str, db: DbConn) -> dict | None:
    """Latest-version rubric for the type as ``{name}``, or ``None``.

    Highest ``v<N>`` among ``contract_<type>_v<N>`` names; else the alphabetically-
    last ``contract_<type>_*`` name; else ``None``. Mirrors the MCP pipeline's
    ``default_rubric`` but returns ``None`` instead of raising.
    """
    rubrics = list_rubrics_with_counts(db_path=db)
    names = [r["name"] for r in rubrics]
    pat = _version_pattern(contract_type)
    versioned = [(int(m.group(1)), n) for n in names if (m := pat.match(n))]
    if versioned:
        return {"name": max(versioned)[1]}
    prefixed = sorted(n for n in names if n.startswith(f"contract_{contract_type}_"))
    if prefixed:
        return {"name": prefixed[-1]}
    return None


def _version_pattern(contract_type: str):
    import re

    return re.compile(rf"^contract_{re.escape(contract_type)}_v(\d+)$")


def _clause_count_summary(contract_type: str, db: DbConn) -> dict:
    """``{base: N, tagged: N, custom: N}`` (+ any other sources) for the type."""
    clauses = list_clauses(contract_type=contract_type, db=db)
    counts: dict[str, int] = {"base": 0, "tagged": 0, "custom": 0}
    for c in clauses:
        src = c.get("category") or "base"
        counts[src] = counts.get(src, 0) + 1
    return counts


def _clause_summary(c: dict) -> dict:
    """Project a clause row to the agent-facing shape."""
    return {
        "id": c["id"],
        "section": c["section"],
        "source": c.get("category"),
        "manual": c.get("manual", False),
        "tags": c.get("tags") or {},
        "body": c["body"],
        "slot_instructions": c.get("slot_instructions") or [],
        "law_refs": c.get("law_refs") or [],
    }


def _file_url(path_str: str | None, contract_type: str) -> str | None:
    """Download URL for a generated file, or ``None`` when no file was written."""
    if not path_str:
        return None
    name = Path(path_str).name
    return f"/api/contracts/{contract_type}/files/{quote(name)}"


# --- endpoints ------------------------------------------------------------- #


@read_only_router.get("", summary="List contract classes")
def list_types() -> list[dict]:
    """Supported contract classes as ``[{key, zh}]`` in registry file order."""
    return list_contract_types()


# --- stored artifacts ----------------------------------------------------- #
# Declared before the dynamic ``/{contract_type}`` route so the static
# ``/artifacts`` path is not captured by the ``{contract_type}`` parameter.


@read_only_router.get("/artifacts", summary="List stored contract artifacts")
def list_artifacts_route(
    contract_type: str | None = None, db: DbConn = Depends(get_db)
) -> list[dict]:
    """Stored artifact metadata rows (no ``body_text``), newest first, optionally
    filtered by ``?contract_type=``.
    """
    return list_artifacts(contract_type=contract_type, db=db)


@read_only_router.get("/artifacts/{artifact_id}", summary="Stored artifact metadata")
def get_artifact_route(artifact_id: int, db: DbConn = Depends(get_db)) -> dict:
    """Full artifact row including ``body_text``. 404 if the id is unknown."""
    row = get_artifact(artifact_id, db=db)
    if row is None:
        raise HTTPException(status_code=404, detail=f"artifact not found: {artifact_id}")
    return row


@read_only_router.get("/artifacts/{artifact_id}/download", summary="Download a stored artifact")
def download_artifact_route(
    artifact_id: int, format: str = "docx", variant: str = "final", db: DbConn = Depends(get_db)
) -> StreamingResponse:
    """Stream a stored docx/pdf from MinIO. ``variant`` selects the final (default)
    or slotted (fillable template) render. 404 if the artifact or the requested
    format/variant is missing.
    """
    if format not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be docx or pdf")
    if variant not in ("final", "slotted"):
        raise HTTPException(status_code=400, detail="variant must be final or slotted")
    try:
        response, content_type, filename = download_artifact(artifact_id, format, variant=variant, db=db)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    def _stream():
        try:
            for chunk in response.stream(amt=8192):
                yield chunk
        finally:
            try:
                response.close()
                response.release_conn()
            except Exception:
                pass

    return StreamingResponse(
        _stream(),
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@write_router.post("/{contract_type}/generate-stored", summary="Generate, upload to MinIO, store")
def generate_stored_route(
    contract_type: str, body: GenerateRequest, db: DbConn = Depends(get_db)
) -> dict:
    """Generate a contract (docx/pdf), upload to MinIO, record ``contract_artifacts``
    row(s). Content-addressed by ``md5(body_text)``: identical inputs reuse the same
    artifact (``reused: true``); missing formats are filled.

    - **By tag** (``scenario`` and/or ``stance`` and/or ``custom_clause_ids`` given):
      generates a single variant, returns
      ``{artifact_id, docx_url, pdf_url, body_text, slots, reused}``.
      Coherence-gate failure -> 422; unknown type -> 404.
    - **By contract type** (no tags): generates **every** scenario x stance x base
      combination for the type and stores them all, returning a summary
      ``{contract_type, format, artifacts: [...], count, new, reused, failed,
      failures}``. Per-combo coherence failures are reported in ``failures``
      (not 422); unknown type -> 404.
    """
    if body.scenario or body.stance or body.custom_clause_ids:
        try:
            return generate_stored(
                contract_type,
                scenario=body.scenario,
                stance=body.stance,
                custom_clause_ids=body.custom_clause_ids,
                format=body.format,
                db=db,
                force=body.force,
            )
        except CoherenceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    return generate_all_stored(contract_type, format=body.format, db=db, force=body.force)


@read_only_router.get("/{contract_type}", summary="Comprehensive context bundle")
def get_bundle(contract_type: str, db: DbConn = Depends(get_db)) -> dict:
    """Everything an agent needs to draft a contract of this type in one call:
    template body + slots, slot instructions (with ontology coverage), structured
    法律法规 refs, the tag vocabulary, the canonical section order, a clause
    availability summary, and pointers to the per-type rubric + prompts.
    """
    template = _require_type(contract_type)
    manifest = _slot_manifest_with_ontology(contract_type, template["slots"])
    try:
        law_refs = extract_laws_for_type(contract_type)
    except NotFoundError:
        law_refs = []
    return {
        "type": template["type"],
        "zh_name": template["zh_name"],
        "template": {"body": template["body"], "slots": template["slots"]},
        "slot_instructions": manifest,
        "laws": {"refs": law_refs},
        "tags": tag_vocab_for_type(contract_type),
        "sections": list(SECTION_ORDER),
        "clauses": _clause_count_summary(contract_type, db),
        "rubric": _latest_rubric_for_type(contract_type, db),
        "prompts": [
            {"name": p["name"], "purpose": p.get("purpose")}
            for p in list_prompts(db_path=db)
            if p.get("contract_type") == contract_type
        ],
    }


@read_only_router.get("/{contract_type}/slots", summary="Slot instructions (with ontology)")
def get_slots(contract_type: str) -> list[dict]:
    """The slot-instruction manifest for the type, covering every ``{{slot}}`` in the
    template. Variant slots (e.g. ``seller_address``) are resolved via the slot
    ontology; each entry carries ``source``: ``registry`` / ``ontology`` / ``uncovered``.
    """
    template = _require_type(contract_type)
    return _slot_manifest_with_ontology(contract_type, template["slots"])


@read_only_router.get("/{contract_type}/laws", summary="Per-type laws (refs + survey markdown)")
def get_laws(contract_type: str, db: DbConn = Depends(get_db)) -> dict:
    """Structured 法律法规 refs plus the full Doubao+DeepSeek survey markdown."""
    _require_type(contract_type)
    try:
        refs = extract_laws_for_type(contract_type)
    except NotFoundError:
        refs = []
    try:
        survey = get_law_info(contract_type, db=db)
        survey_md = {"doubao": survey.get("doubao"), "deepseek": survey.get("deepseek")}
    except NotFoundError:
        survey_md = {"doubao": None, "deepseek": None}
    return {"refs": refs, "survey_md": survey_md}


@read_only_router.get("/{contract_type}/tags", summary="Tag vocabulary for the type")
def get_tags(contract_type: str) -> dict:
    """Merged tag vocabulary ``{dim: [values]}`` (universal + type-specific)."""
    _require_type(contract_type)
    return tag_vocab_for_type(contract_type)


@read_only_router.get("/{contract_type}/clauses", summary="Clause catalog (filter + paginate)")
def get_clauses(
    contract_type: str,
    scenario: str | None = None,
    stance: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: DbConn = Depends(get_db),
) -> dict:
    """Clause catalog for the type, filterable by ``scenario`` / ``stance`` / ``source``
    and paginated via ``limit`` (default 50, max 200) / ``offset`` (default 0).
    Returns ``{clauses: [...], total, limit, offset}``.
    """
    _require_type(contract_type)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    tags: dict | None = None
    if scenario or stance:
        tags = {}
        if scenario:
            tags["scenario"] = scenario
        if stance:
            tags["stance"] = stance
    all_clauses = list_clauses(
        contract_type=contract_type, category=source, tags=tags, db=db
    )
    total = len(all_clauses)
    page = all_clauses[offset : offset + limit]
    return {
        "clauses": [_clause_summary(c) for c in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@write_router.post("/{contract_type}/generate", summary="Assemble + render a contract")
def generate_contract(
    contract_type: str, body: GenerateRequest, db: DbConn = Depends(get_db)
) -> dict:
    """Assemble a contract via the existing tag-driven assembly (per-section override
    ``custom > tagged > base`` + coherence gate) and render it. ``format`` defaults to
    ``docx``; ``markdown`` returns text only (no file). The response always carries
    ``body_text``. A coherence-gate failure returns 422; an unknown type returns 404.
    """
    try:
        result = generate_contract_assembled(
            contract_type,
            scenario=body.scenario,
            stance=body.stance,
            custom_clause_ids=body.custom_clause_ids,
            format=body.format,
            db=db,
        )
    except CoherenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # NotFoundError (unknown type) propagates to the app-level handler -> 404.
    return {
        "body_text": result.get("body_text"),
        "slots": result.get("slots"),
        "instructions": result.get("instructions"),
        "law_refs": result.get("law_refs"),
        "diagnostics": result.get("diagnostics"),
        "docx_url": _file_url(result.get("docx_path"), contract_type),
        "pdf_url": _file_url(result.get("pdf_path"), contract_type),
    }


@read_only_router.get("/{contract_type}/files/{filename}", include_in_schema=False)
def download_file(contract_type: str, filename: str):
    """Serve a generated docx/pdf from ``output/contracts/`` (download URL target).

    Path-traversal safe: rejects ``..``/``/``/``\\`` and verifies the resolved path
    stays within the output directory.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=404)
    out_dir = _OUTPUT_DIR.resolve()
    target = (out_dir / filename).resolve()
    try:
        target.relative_to(out_dir)
    except ValueError:
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404)
    media = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if filename.endswith(".docx")
        else "application/pdf"
    )
    return FileResponse(str(target), media_type=media, filename=filename)


# --------------------------------------------------------------------------- #
# Backward-compat alias: assemble the parent ``router`` HERE, at module bottom,
# AFTER every ``@read_only_router`` / ``@write_router`` decorator above has
# registered its route. ``APIRouter.include_router`` copies the sub-router's
# route list at call time — building the parent before the decorators run would
# copy an empty list and the origin app (which does
# ``app.include_router(contract_context.router)``) would 404 on every path.
# The public pod instead mounts ``read_only_router`` directly.
# --------------------------------------------------------------------------- #
router = APIRouter(tags=["contract-context"])
router.include_router(read_only_router)
router.include_router(write_router)
