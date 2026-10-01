"""Compare generation prompts by drafting + evaluating each against a rubric.

A compare holds an area fixed (contract_type, rubric, task) and varies only the
prompt. For each prompt it generates one or more drafts (drafter-only mode: a
single direct DRAFTER-model LLM call per draft, the prompt's ``content`` as the
drafting instruction - the production crew is NOT invoked), evaluates each draft
against the named rubric with the existing ``evaluate_contract`` judge, and
persists the runs grouped under one ``compare_runs`` row.

Persistence lives in ``src/eval/store.py`` (``store_compare`` / ``get_compare``
/ ``list_compares`` / ``get_run_draft``); this module owns orchestration
(``run_compare``), the matrix aggregation (``build_matrix``), prompt resolution
(``load_prompts``), and the CLI.

CLI:
  python -m src.eval.compare --contract-type sale --rubric contract_sale_v1 \\
      --task "起草一份买卖合同，甲方…" --prompts draft_sale,draft_sale_v2 --n 1
  python -m src.eval.compare --list-compares
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from src.settings import DEFAULT_DB, TEMPLATES_DIR

from .errors import ValidationError
from .store import get_compare, list_compares

# Draft-generation concurrency bound (design D2): worst case a compare runs
# 8 drafts + 8 judges in flight, matching the judge ceiling (16) the relay
# tolerated at the 429-incident-adjacent default.
_DRAFT_CONCURRENCY_CEILING = 8


# --- generation ------------------------------------------------------------ #


def _templates_reference() -> str:
    """Load all seed templates into a reference block for the drafter.

    Mirrors ``src/crew.py::_templates_reference`` so compare's drafter-only
    generation sees the same template context the production drafter does,
    without importing (and thus heavy-initializing) the crew.
    """
    if not TEMPLATES_DIR.is_dir():
        return ""
    parts = []
    for tpl in sorted(TEMPLATES_DIR.glob("*.md")):
        parts.append(f"### 模板：{tpl.stem}\n\n{tpl.read_text(encoding='utf-8').strip()}\n")
    return "\n".join(parts)


def _default_draft_fn(task_desc: str, prompt_content: str, templates_ref: str) -> str:
    """Generate one draft with the DRAFTER model (drafter-only mode).

    The prompt ``content`` is the system instruction; the task plus the template
    reference is the user message - the same shape the production drafter task
    assembles. Returns the raw draft text.
    """
    from src.llm import get_llm  # local import: avoid crewai init at module import

    llm = get_llm("DRAFTER")
    user = task_desc
    if templates_ref:
        user += (
            "\n\n以下为参考模板，请参考其结构与标准条款，按本次需求选用并调整：\n\n"
            + templates_ref
        )
    messages = [
        {"role": "system", "content": prompt_content},
        {"role": "user", "content": user},
    ]
    return llm.call(messages)


# --- prompt resolution ----------------------------------------------------- #


def load_prompts(names: list[str], db_path=DEFAULT_DB) -> list[dict]:
    """Resolve prompt names to their full records (raises ``NotFoundError`` if missing)."""
    from .prompt_crud import get_prompt

    return [get_prompt(n, db_path=db_path) for n in names]


# --- orchestration --------------------------------------------------------- #


def run_compare(
    contract_type: str,
    rubric_name: str,
    task_desc: str,
    prompts: list[dict],
    mode: str = "drafter-only",
    n_drafts: int = 1,
    concurrency: int = 1,
    *,
    judge=None,
    draft_fn=None,
    max_workers: int = 8,
    label: Optional[str] = None,
    db_path=DEFAULT_DB,
) -> dict:
    """Draft + evaluate each prompt against ``rubric_name``; persist and return the grouped compare.

    Each entry in ``prompts`` is a prompt record dict with at least ``name`` and
    ``content`` (and optionally ``prompt_type``). ``draft_fn`` and ``judge`` are
    injectable so tests run offline (no DRAFTER LLM, no judge endpoint).

    ``concurrency`` bounds how many drafts are generated simultaneously across
    the prompt × draft matrix (clamped to [1, 8], default 1 = sequential).
    Drafts are generated in a bounded pool first, then evaluated and persisted
    in the sequential path's deterministic order (prompt-major, draft-minor),
    so a compare at any concurrency stores the same rows in the same order as
    a concurrency-1 run of the same inputs.

    Returns the ``get_compare(compare_id)`` grouped result (runs + per-criterion
    verdicts, no ``draft_text``) with ``effective_concurrency`` added.
    """
    from .rubric import load_criteria
    from .scoring import evaluate_contract
    from .store import store_compare, store_result

    if len(prompts) < 2:
        raise ValidationError("A compare needs at least 2 prompts.")
    if mode != "drafter-only":
        raise ValidationError(
            f"Unsupported mode: {mode!r} (only 'drafter-only' is supported)."
        )
    if n_drafts < 1:
        raise ValidationError("n_drafts must be >= 1.")
    effective_concurrency = max(1, min(concurrency, _DRAFT_CONCURRENCY_CEILING))

    # Fail fast if the rubric is unknown/empty before spending any LLM calls.
    load_criteria(rubric_name, db_path=db_path)

    draft_fn = draft_fn or _default_draft_fn
    templates_ref = _templates_reference()

    label = label or f"{contract_type} · {rubric_name} · {len(prompts)} prompts"
    compare_id = store_compare(
        label, contract_type, rubric_name, task_desc, mode, n_drafts, db_path=db_path
    )

    # Phase 1 - drafts: generate the prompt × draft matrix through a bounded
    # pool. ``pool.map`` (and the plain loop at concurrency 1) yield results in
    # job order, so phase 2 consumes them positionally.
    draft_jobs = [(p, draft_idx) for p in prompts for draft_idx in range(n_drafts)]

    def _draft_one(job: tuple[dict, int]) -> str:
        p, _draft_idx = job
        return draft_fn(task_desc, p["content"], templates_ref)

    if effective_concurrency == 1:
        draft_texts = [_draft_one(job) for job in draft_jobs]
    else:
        with ThreadPoolExecutor(max_workers=effective_concurrency) as pool:
            draft_texts = list(pool.map(_draft_one, draft_jobs))

    # Phase 2 - evaluate + persist: the pre-change sequential loop, unchanged
    # except that ``draft_text`` arrives precomputed (prompt-major order).
    idx = 0
    for p in prompts:
        pname = p["name"]
        ptype = p.get("prompt_type")
        variant_label = ptype or pname
        for _ in range(n_drafts):
            draft_text = draft_texts[idx]
            idx += 1
            result = evaluate_contract(
                contract_text=draft_text,
                rubric_name=rubric_name,
                task_desc=task_desc,
                judge=judge,
                max_workers=max_workers,
                db_path=db_path,
            )
            store_result(
                result,
                task_desc=task_desc,
                db_path=db_path,
                compare_run_id=compare_id,
                prompt_name=pname,
                prompt_type=ptype,
                variant_label=variant_label,
                draft_text=draft_text,
            )

    grouped = get_compare(compare_id, db_path=db_path)
    grouped["effective_concurrency"] = effective_concurrency
    return grouped


# --- matrix aggregation ---------------------------------------------------- #


def build_matrix(compare: dict) -> dict:
    """Derive the criteria × prompts matrix from a ``get_compare`` result.

    Cells are binary verdicts when ``n_drafts == 1``; pass-rates (``k/N``) when
    ``n_drafts > 1``. Criteria come from the rubric (shared across runs); each
    cell carries the first available judge ``reasoning`` so the view can show the
    "why" without an extra fetch.
    """
    n_drafts = compare.get("n_drafts") or 1
    runs = compare.get("runs", [])

    # Group runs by prompt_name, preserving first-seen order.
    order: list[str] = []
    by_prompt: dict[str, list[dict]] = {}
    for run in runs:
        pname = run["prompt_name"]
        if pname not in by_prompt:
            by_prompt[pname] = []
            order.append(pname)
        by_prompt[pname].append(run)

    # Criteria union/order from the first run that has verdicts (all runs share
    # the rubric, so the first run's criteria_results defines the rows).
    first_crits = next((r["criteria_results"] for r in runs if r.get("criteria_results")), [])
    criteria = [{"id": c["criterion_id"], "title": c["title"]} for c in first_crits]

    columns = []
    cells: dict[str, dict] = {}
    for pname in order:
        pruns = by_prompt[pname]
        columns.append(
            {
                "prompt_name": pname,
                "prompt_type": pruns[0]["prompt_type"],
                "variant_label": pruns[0]["variant_label"],
            }
        )
        cell_for_prompt: dict[str, dict] = {}
        for crit in criteria:
            cid = crit["id"]
            verdicts: list[str] = []
            reasoning = ""
            for run in pruns:
                cr = next(
                    (x for x in run["criteria_results"] if x["criterion_id"] == cid),
                    None,
                )
                if cr:
                    verdicts.append(cr["verdict"])
                    if not reasoning and cr.get("reasoning"):
                        reasoning = cr["reasoning"]
            n = len(verdicts)
            n_pass = sum(1 for v in verdicts if v == "pass")
            if n_drafts > 1:
                cell_for_prompt[cid] = {
                    "pass_rate": (n_pass / n) if n else 0.0,
                    "n_pass": n_pass,
                    "n": n,
                    "reasoning": reasoning,
                }
            else:
                cell_for_prompt[cid] = {
                    "verdict": verdicts[0] if verdicts else "fail",
                    "reasoning": reasoning,
                }
        cells[pname] = cell_for_prompt

    return {"criteria": criteria, "columns": columns, "cells": cells, "n_drafts": n_drafts}


# --- CLI ------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--contract-type", help="Contract type key (e.g. sale).")
    ap.add_argument("--rubric", help="Rubric name (e.g. contract_sale_v1).")
    ap.add_argument("--task", default=None, help="Original user request (the drafting task).")
    ap.add_argument("--prompts", help="Comma-separated prompt names (>= 2).")
    ap.add_argument("--mode", default="drafter-only", help="Generation mode (default: drafter-only).")
    ap.add_argument("--n", type=int, default=1, help="Drafts per prompt (default: 1).")
    ap.add_argument("--label", default=None, help="Optional label for the compare run.")
    ap.add_argument("--list-compares", action="store_true", help="List recent compares and exit.")
    args = ap.parse_args(argv)

    if args.list_compares:
        comps = list_compares()
        if not comps:
            print("(no compares stored yet)")
            return 0
        print(f"{'id':>3}  {'label':40} {'rubric':24} {'mode':14} {'n':>3} {'created_at'}")
        print("-" * 100)
        for c in comps:
            print(
                f"{c['id']:>3}  {(c['label'] or '')[:40]:40} "
                f"{(c['rubric_name'] or '')[:24]:24} {(c['gen_mode'] or '')[:14]:14} "
                f"{c['n_drafts'] or 0:>3} {c['created_at']}"
            )
        return 0

    if not args.contract_type or not args.rubric or not args.prompts or not args.task:
        ap.error("--contract-type, --rubric, --task, and --prompts are required "
                 "(or use --list-compares)")

    names = [n.strip() for n in args.prompts.split(",") if n.strip()]
    if len(names) < 2:
        ap.error("--prompts must list at least 2 prompt names")

    try:
        prompts = load_prompts(names)
    except Exception as e:
        print(f"Error resolving prompts: {e}", file=sys.stderr)
        return 2

    try:
        compare = run_compare(
            contract_type=args.contract_type,
            rubric_name=args.rubric,
            task_desc=args.task,
            prompts=prompts,
            mode=args.mode,
            n_drafts=args.n,
            label=args.label,
        )
    except ValidationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except (KeyError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Compare failed: {e}", file=sys.stderr)
        return 3

    _print_matrix(compare)
    print("=" * 60)
    print(f"DB compare id: {compare['id']}  (stored in db/evaluation_rules.db)")
    return 0


def _print_matrix(compare: dict) -> None:
    matrix = build_matrix(compare)
    criteria = matrix["criteria"]
    columns = matrix["columns"]
    cells = matrix["cells"]

    print("=" * 60)
    print(f"Compare #{compare['id']}: {compare['label']}")
    print(f"Area   : {compare['contract_type']} / {compare['rubric_name']} / mode={compare['gen_mode']} / n_drafts={compare['n_drafts']}")
    print(f"Task   : {(compare['task_desc'] or '')[:80]}")
    print("-" * 60)

    header = f"{'criterion':28} " + " ".join(
        f"{(c['prompt_type'] or c['prompt_name'])[:14]:14}" for c in columns
    )
    print(header)
    for crit in criteria:
        row = f"{(crit['id'])[:28]:28} "
        for c in columns:
            cell = cells[c["prompt_name"]].get(crit["id"], {})
            if "verdict" in cell:
                mark = "✓ pass" if cell["verdict"] == "pass" else "✗ fail"
            else:
                mark = f"{cell.get('n_pass', 0)}/{cell.get('n', 0)}"
            row += f"{mark[:14]:14} "
        print(row)
    print("-" * 60)
    # run-level n_passed headline per prompt
    by_prompt: dict[str, list[dict]] = {}
    for run in compare["runs"]:
        by_prompt.setdefault(run["prompt_name"], []).append(run)
    for c in columns:
        pruns = by_prompt.get(c["prompt_name"], [])
        if pruns:
            last = pruns[-1]
            print(f"  {c['prompt_name']}: {last['n_passed']}/{last['n_criteria']} criteria passed (last draft)")


if __name__ == "__main__":
    raise SystemExit(main())
