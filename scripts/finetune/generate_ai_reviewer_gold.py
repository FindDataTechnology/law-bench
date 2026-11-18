#!/usr/bin/env python3
"""Generate fresh Judge-C gold by LLM-judging real (filled_contract,
type_validation_rule) pairs as ai_reviewer.

For each same-type (contract, rule) pair, an LLM acting as ai_reviewer
judges whether the filled contract satisfies the rule, emitting
{"verdict", "justification", "citation"} JSON. The result is assembled
into a validated quadruple (reviewer=ai_reviewer, tier=gold) and written
to data/finetune/judge-c/judge_c_gold.ai_reviewer.jsonl.

This is the viable expansion path after scaffold fuzzy-match regrounding
was proven blocked (scaffold clause templates too specialized - 0/52
matches; scaffold reasoning is the rule message verbatim 608/608).

Run (smoke):
    uv run --no-project --with litellm --with python-dotenv python -X utf8 \\
        scripts/finetune/generate_ai_reviewer_gold.py --limit 5

Run (full, resume-safe):
    uv run --no-project --with litellm --with python-dotenv python -X utf8 \\
        scripts/finetune/generate_ai_reviewer_gold.py

Materialize:
    uv run --no-project --with litellm --with python-dotenv python -X utf8 \\
        scripts/finetune/export_dataset.py judge-c \\
        --gold data/finetune/judge-c/judge_c_gold.ai_reviewer.jsonl
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    FINETUNE_ROOT,
    JUDGE_C_DIR,
    append_jsonl,
)
from export_dataset import validate_quadruple  # noqa: E402

WAREHOUSE = FINETUNE_ROOT / "warehouse"
DEFAULT_OUTPUT = JUDGE_C_DIR / "judge_c_gold.ai_reviewer.jsonl"

JUDGE_C_SYSTEM = (
    "你是一名合同合规审查员，对照给定法条/规则审查条款正文，"
    "输出 pass/fail 判决及法律推理。"
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _load_warehouse(table: str) -> list[dict]:
    """Load a warehouse table, extracting the nested ``row`` key.

    Mirrors reground_judge_c.py::_load_warehouse - both pipeline_runs.jsonl
    and type_validations.jsonl wrap the real row in a top-level ``row``.
    """
    path = WAREHOUSE / f"{table}.jsonl"
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if "row" in obj:
            rows.append(obj["row"])
        else:
            rows.append(obj)
    return rows


def _build_pairs() -> list[tuple[dict, dict]]:
    """Cross-join filled contracts with rules by contract_type.

    Returns a list of (contract_row, rule_row) where contract_row is a
    pipeline_runs row with filled_text and rule_row is a type_validations
    row with law_ref + message. 1497 pairs across 25 contract types.
    """
    runs = _load_warehouse("pipeline_runs")
    contracts = [r for r in runs if (r.get("filled_text") or "").strip()]
    by_type_c: dict[str, list[dict]] = {}
    for c in contracts:
        ct = c.get("contract_type")
        if ct:
            by_type_c.setdefault(ct, []).append(c)

    rules_raw = _load_warehouse("type_validations")
    rules = [
        r for r in rules_raw
        if (r.get("law_ref") or "").strip() and (r.get("message") or "").strip()
    ]
    by_type_r: dict[str, list[dict]] = {}
    for r in rules:
        ct = r.get("contract_type")
        if ct:
            by_type_r.setdefault(ct, []).append(r)

    pairs: list[tuple[dict, dict]] = []
    for ct in sorted(set(by_type_c) & set(by_type_r)):
        for c in by_type_c[ct]:
            for r in by_type_r[ct]:
                pairs.append((c, r))
    return pairs


def _build_legal_base(rule: dict) -> dict:
    """Construct legal_base for both the prompt and the quadruple.

    source uses type_validations provenance (NOT law_info:* - hygiene rule
    from _promote_envelope). text combines rule message + law_ref with NO
    retrieval hint.
    """
    source = f"type_validations:{rule.get('id')}:{rule.get('constraint_id')}"
    message = (rule.get("message") or "").strip()
    law_ref = (rule.get("law_ref") or "").strip()
    if law_ref:
        text = f"{message}\n法律依据：{law_ref}"
    else:
        text = message
    return {"source": source, "text": text}


def _build_prompt(contract: dict, rule: dict) -> str:
    """Construct the judge prompt via string concatenation (brace-safe).

    Produces output identical to
    export_sft_dataset.py::JUDGE_C_USER_TEMPLATE.format() for brace-free
    bodies, but does NOT raise KeyError on stray braces. 26/356 contracts
    contain single braces that would break str.format().
    """
    lb = _build_legal_base(rule)
    body = (contract.get("filled_text") or "").strip()
    return (
        "【审查依据】" + lb["source"] + "\n" + lb["text"] + "\n\n"
        "【待审合同正文】\n" + body + "\n\n"
        '请按 JSON 输出：{"verdict": "pass|fail", '
        '"justification": "...", "citation": ["..."]}'
    )


def _call_llm(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.0,
    max_tokens: int = 800,
    api_base: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """Call LLM via litellm with retry (mirrors src/clauses/audit.py).

    Returns the raw text response, or None on failure. Never prints
    credentials - error messages are truncated to 150 chars.
    """
    import litellm

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if api_base:
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key

    for attempt in range(3):
        try:
            resp = litellm.completion(**kwargs)
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return text
        except Exception as e:
            s = str(e)
            if "No available channel" in s:
                return None
            if (
                "RateLimit" in s
                or "ServiceUnavailable" in s
                or "429" in s
                or "503" in s
            ):
                if attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
            err_type = type(e).__name__
            print(f"  ⚠ LLM error ({model}): {err_type}: {s[:150]}")
            return None
    return None


def _extract_json(raw: str) -> dict | None:
    """Parse JSON from LLM output, fence-tolerant (mirrors audit.py)."""
    text = (raw or "").strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _assemble_quadruple(contract: dict, rule: dict, result: dict) -> dict:
    """Assemble a quadruple from the LLM result.

    clause_text shape mirrors reground_judge_c.py (body=filled_text,
    section=pipeline_runs:<id>:filled_text (eval_run:<id>)).
    provenance.reviewer=ai_reviewer enables tier=gold + verdict=pass.
    """
    lb = _build_legal_base(rule)
    body = (contract.get("filled_text") or "").strip()
    pr_id = contract.get("id")
    eval_run_id = contract.get("eval_run_id")
    section = f"pipeline_runs:{pr_id}:filled_text (eval_run:{eval_run_id})"

    verdict = (result.get("verdict") or "").strip().lower()
    justification = (result.get("justification") or "").strip()

    citation = result.get("citation")
    if not isinstance(citation, list) or not citation:
        law_ref = (rule.get("law_ref") or "").strip()
        citation = [law_ref] if law_ref else []
    else:
        citation = [str(c).strip() for c in citation if str(c).strip()]

    contract_type = contract.get("contract_type") or "unknown"
    rule_id = rule.get("id")
    constraint_id = rule.get("constraint_id")

    return {
        "legal_base": lb,
        "clause_text": {"body": body, "section": section},
        "verdict": verdict,
        "reasoning": {"justification": justification, "citation": citation},
        "provenance": {
            "annotated_by": "ai_reviewer",
            "reviewer": "ai_reviewer",
            "id": f"gold:ai_reviewer:{contract_type}:{rule_id}:{pr_id}",
            "grounded_from": f"pipeline_runs:{pr_id}.filled_text",
            "rule_constraint": f"{rule_id}:{constraint_id}",
        },
        "tier": "gold",
    }


def _load_done_ids(path: pathlib.Path) -> set[str]:
    """Load provenance ids from existing output (resume support).

    Tolerant of a partial last line from an interrupted write.
    """
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        pid = (obj.get("provenance") or {}).get("id")
        if pid:
            done.add(pid)
    return done


def _process_one(
    idx: int,
    total: int,
    contract: dict,
    rule: dict,
    model: str,
    api_base: str,
    api_key: str,
) -> tuple[dict | None, str]:
    """Judge one (contract, rule) pair. Returns (quadruple | None, status).

    status is one of: "written", "llm_error", "invalid".
    validate_quadruple is called here so a bad row never reaches the writer.
    """
    user_prompt = _build_prompt(contract, rule)
    messages = [
        {"role": "system", "content": JUDGE_C_SYSTEM},
        {"role": "user", "content": user_prompt},
    ]
    raw = _call_llm(model, messages, api_base=api_base, api_key=api_key)
    if raw is None:
        return None, "llm_error"

    result = _extract_json(raw)
    if result is None:
        ct = contract.get("contract_type") or "?"
        print(
            f"  [{idx + 1}/{total}] {ct} rule={rule.get('id')} "
            f"pr={contract.get('id')}: JSON parse failed, skipping."
        )
        return None, "invalid"

    verdict = (result.get("verdict") or "").strip().lower()
    if verdict not in ("pass", "fail"):
        return None, "invalid"

    justification = (result.get("justification") or "").strip()
    if not justification:
        return None, "invalid"

    quad = _assemble_quadruple(contract, rule, result)
    try:
        validate_quadruple(quad, idx)
    except Exception as e:
        ct = contract.get("contract_type") or "?"
        print(
            f"  [{idx + 1}/{total}] {ct} rule={rule.get('id')} "
            f"pr={contract.get('id')}: validate_quadruple failed: {e}"
        )
        return None, "invalid"
    return quad, "written"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max pairs to process (smoke test)",
    )
    ap.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"output JSONL (default: {DEFAULT_OUTPUT})",
    )
    ap.add_argument(
        "--no-resume",
        action="store_true",
        help="start fresh (ignore existing output)",
    )
    ap.add_argument(
        "--model",
        default=None,
        help="LLM model id (default: $EVAL_MODEL)",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=8,
        help="concurrent LLM workers (default 8)",
    )
    args = ap.parse_args()

    model = args.model or os.environ.get("EVAL_MODEL")
    if not model:
        print("ERROR: no model. Set EVAL_MODEL in .env or pass --model.")
        return 2
    api_base = os.environ.get("OPENAI_API_BASE")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_base or not api_key:
        print("ERROR: OPENAI_API_BASE / OPENAI_API_KEY not set. Check .env.")
        return 2

    pairs = _build_pairs()
    print(f"Built {len(pairs)} (contract, rule) pairs across contract types.")

    done = (
        set()
        if args.no_resume
        else _load_done_ids(args.output)
    )
    if done:
        print(f"Resume: {len(done)} pairs already done in {args.output}.")

    if args.limit is not None:
        pairs = pairs[: args.limit]
        print(f"Smoke limit: processing {len(pairs)} pairs.")

    # Filter out already-done pairs up front so workers only process pending work.
    pending: list[tuple[int, dict, dict]] = []
    skipped_done = 0
    for i, (contract, rule) in enumerate(pairs):
        ct = contract.get("contract_type") or "?"
        pr_id = contract.get("id")
        rule_id = rule.get("id")
        prov_id = f"gold:ai_reviewer:{ct}:{rule_id}:{pr_id}"
        if prov_id in done:
            skipped_done += 1
            continue
        pending.append((i, contract, rule))
    total = len(pairs)

    written = 0
    skipped_invalid = 0
    skipped_llm = 0
    verdict_counts: dict[str, int] = {"pass": 0, "fail": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(args.workers, len(pending) or 1))
    print(
        f"Processing {len(pending)} pending pairs with {workers} workers "
        f"(skipping {skipped_done} done)."
    )

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(
                _process_one,
                i,
                total,
                contract,
                rule,
                model,
                api_base,
                api_key,
            ): (i, contract, rule)
            for (i, contract, rule) in pending
        }
        for fut in as_completed(futs):
            i, contract, rule = futs[fut]
            ct = contract.get("contract_type") or "?"
            try:
                quad, status = fut.result()
            except Exception as e:
                print(
                    f"  [{i + 1}/{total}] {ct} rule={rule.get('id')} "
                    f"pr={contract.get('id')}: worker raised: {e}"
                )
                skipped_invalid += 1
                completed += 1
                continue
            if status == "written" and quad is not None:
                append_jsonl(args.output, [quad])
                written += 1
                v = quad["verdict"]
                if v in verdict_counts:
                    verdict_counts[v] += 1
            elif status == "llm_error":
                skipped_llm += 1
            else:
                skipped_invalid += 1
            completed += 1
            if completed % 50 == 0:
                print(
                    f"  progress {completed}/{len(pending)} written={written} "
                    f"pass={verdict_counts['pass']} fail={verdict_counts['fail']} "
                    f"llm_err={skipped_llm} invalid={skipped_invalid}"
                )

    print()
    print(
        f"Done. written={written} "
        f"(pass={verdict_counts['pass']}, fail={verdict_counts['fail']})"
    )
    print(
        f"  skipped: done={skipped_done} llm_error={skipped_llm} "
        f"invalid={skipped_invalid}"
    )
    print(f"  output: {args.output}")
    if args.output.exists():
        total_rows = len(
            args.output.read_text(encoding="utf-8").splitlines()
        )
        print(f"  total rows in file: {total_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
