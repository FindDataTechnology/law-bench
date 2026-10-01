#!/usr/bin/env python3
"""Reground Judge-C gold quadruples on the real judged contract text.

**The defect this fixes.** ``bootstrap_gold_from_evals.py`` had no access to
the contract that was judged, so ``_extract_clause_text`` fell back to
``reasoning[:200]`` — the judge's *own justification*, truncated. Measured on
the 1969-row gold set: ``clause_text.body`` is a literal prefix of
``reasoning.justification`` in 1891 rows (96.0%) and exactly equal in 645
(32.8%). The model's input was therefore derived from its target: the task as
posed was "copy this text, extend it, and emit the verdict it was written to
support". That trains a paraphraser, not a judge — and it would score
excellently on val while being useless on a real clause, because at inference
the model receives an actual contract, a distribution it never saw.

**The repair.** ``eval_runs.draft_text`` is null for all 924 extracted rows, so
the judged text is not recoverable from the eval tables. But ``pipeline_runs``
carries both ``filled_text`` (the drafted contract) and ``eval_run_id``, which
is a join path back to the run that judged it. Each gold row's
``provenance.id`` is ``seed:bootstrap:run:<eval_run_id>:crit:<name>``, so the
join is exact.

**Why the join is trusted.** Justifications quote contract section headings
(e.g. "the '价款及支付' and '乙方义务' sections"). Extracting those quoted CJK
spans and testing membership in the joined contract gives 93.8% verbatim hits
(90.3% of rows have *every* reference land), against a 42.5% negative control
where the same justification is tested against a randomly chosen other
contract. The gap is the evidence; the 42.5% floor is shared boilerplate
headings across contract types. ``check`` re-runs both arms, and ``build``
refuses to write if the margin collapses.

Rows whose run has no ``filled_text`` are **dropped, not downgraded** — a
leaked row is not weak supervision, it is anti-supervision, and
``provenance.confidence`` cannot mitigate it because ``_confidence()`` scores
the leaked ``reasoning`` string itself.

Subcommands::

    reground_judge_c.py check              # measure leak + join quality, write nothing
    reground_judge_c.py build [--out PATH] # write regrounded gold
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    FINETUNE_ROOT,
    JUDGE_C_DIR,
    read_jsonl,
    write_jsonl,
)

WAREHOUSE = FINETUNE_ROOT / "warehouse"
PROV_ID_RE = re.compile(r"^seed:bootstrap:run:(\d+):crit:(.+)$")
# Quoted CJK spans in a justification — these are contract section headings the
# judge referred to, and they are what makes the join falsifiable.
QUOTED_CJK_RE = re.compile(r"['‘’\"“”「」『』]([一-鿿][一-鿿、（）()· ]{1,15})['‘’\"“”「」『』]")

# `check` fails if the correct-contract hit rate does not clear the
# random-contract control by this margin. Boilerplate headings are shared
# across contract types, so the control floor is high (~40%) by nature; what
# proves the join is the gap, not the absolute number.
MIN_GROUNDING_MARGIN = 0.25

NEG_CONTROL_SEED = 7

# The justifications were written by a judge running inside an eval harness, so
# they refer to the contract as "the Actual Output" (62.8% of rows) and to the
# criterion as "the Input" (36.6%). Those names do not exist at inference time —
# training on them teaches the model to describe a contract as an "Actual
# Output". This is a purely lexical rename of harness vocabulary; no claim,
# verdict, or citation is altered. Disable with --no-normalize to inspect the
# raw targets.
#
# Boundaries are ``(?![A-Za-z])`` rather than ``\b``: CJK codepoints are word
# characters to ``re``, so ``\b`` never fires in "Actual Output引用了" — the
# Chinese-context occurrences (the majority here) would silently survive.
_NO_ALPHA = r"(?![A-Za-z])"
HARNESS_TERMS: list[tuple[re.Pattern, str]] = [
    # Chinese context first: a Chinese noun reads correctly mid-sentence, where
    # "the contract引用了" would not.
    (re.compile(r"(?:[Tt]he\s+)?Actual\s+Output(?=[一-鿿])"), "本合同"),
    (re.compile(r"(?:[Tt]he\s+)?Expected\s+Output(?=[一-鿿])"), "审查依据"),
    (re.compile(r"(?:[Tt]he\s+)?Input(?=[一-鿿])"), "审查依据"),
    # English context.
    (re.compile(r"\bThe\s+Actual\s+Output" + _NO_ALPHA), "The contract"),
    (re.compile(r"\bthe\s+Actual\s+Output" + _NO_ALPHA), "the contract"),
    (re.compile(r"\bActual\s+Output" + _NO_ALPHA), "the contract"),
    (re.compile(r"\bThe\s+Expected\s+Output" + _NO_ALPHA), "The review criterion"),
    (re.compile(r"\bthe\s+Expected\s+Output" + _NO_ALPHA), "the review criterion"),
    (re.compile(r"\bExpected\s+Output" + _NO_ALPHA), "the review criterion"),
    (re.compile(r"\bThe\s+Input" + _NO_ALPHA), "The review criterion"),
    (re.compile(r"\bthe\s+Input" + _NO_ALPHA), "the review criterion"),
    (re.compile(r"\bInput" + _NO_ALPHA), "the review criterion"),
]


def _normalize_harness_terms(text: str) -> tuple[str, bool]:
    """Rename eval-harness vocabulary to production-valid wording."""
    out = text
    for pat, repl in HARNESS_TERMS:
        out = pat.sub(repl, out)
    return out, out != text


def _load_warehouse(table: str) -> list[dict]:
    path = WAREHOUSE / f"{table}.jsonl"
    if not path.exists():
        raise SystemExit(
            f"missing warehouse extract: {path}\n"
            "run: kubectl -n law-bench exec deployment/law-bench -- "
            "python scripts/finetune/extract_warehouse.py"
        )
    return [json.loads(line)["row"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _contract_by_eval_run() -> dict[int, dict]:
    """eval_run_id -> pipeline_run carrying a non-empty filled_text."""
    out: dict[int, dict] = {}
    for row in _load_warehouse("pipeline_runs"):
        eval_run_id = row.get("eval_run_id")
        if eval_run_id and (row.get("filled_text") or "").strip():
            out[eval_run_id] = row
    return out


def _eval_run_id(row: dict) -> int | None:
    m = PROV_ID_RE.match((row.get("provenance") or {}).get("id") or "")
    return int(m.group(1)) if m else None


def _grounding_rate(
    rows: list[dict],
    contracts: dict[int, dict],
    *,
    scramble: bool,
) -> tuple[int, int, int, int]:
    """(refs_hit, refs_total, rows_fully_grounded, rows_with_refs).

    With ``scramble=True`` each justification is tested against a randomly
    chosen *other* contract — the negative control.
    """
    rng = random.Random(NEG_CONTROL_SEED)
    keys = sorted(contracts)
    refs_hit = refs_total = rows_full = rows_with_refs = 0
    for row in rows:
        run_id = _eval_run_id(row)
        if run_id is None or run_id not in contracts:
            continue
        refs = set(QUOTED_CJK_RE.findall((row.get("reasoning") or {}).get("justification") or ""))
        if not refs:
            continue
        source = contracts[rng.choice(keys)] if scramble else contracts[run_id]
        text = source["filled_text"]
        hits = sum(1 for r in refs if r in text)
        rows_with_refs += 1
        refs_hit += hits
        refs_total += len(refs)
        if hits == len(refs):
            rows_full += 1
    return refs_hit, refs_total, rows_full, rows_with_refs


def _leak_stats(rows: list[dict]) -> dict:
    """How much of clause_text.body is lifted from reasoning.justification."""
    prefix = exact = 0
    for row in rows:
        body = ((row.get("clause_text") or {}).get("body") or "").strip()
        just = ((row.get("reasoning") or {}).get("justification") or "").strip()
        if not body or not just:
            continue
        if just.startswith(body):
            prefix += 1
            if just == body:
                exact += 1
    return {"prefix": prefix, "exact": exact, "total": len(rows)}


def _pct(num: int, den: int) -> str:
    return f"{100.0 * num / den:.1f}%" if den else "n/a"


def cmd_check(args: argparse.Namespace) -> int:
    gold = read_jsonl(pathlib.Path(args.gold))
    if not gold:
        print(f"no gold quadruples at {args.gold}")
        return 1
    contracts = _contract_by_eval_run()

    leak = _leak_stats(gold)
    print(f"gold rows: {leak['total']}")
    print("LEAK (clause_text.body lifted from reasoning.justification):")
    print(f"  body is a prefix of justification: {leak['prefix']} ({_pct(leak['prefix'], leak['total'])})")
    print(f"  body == justification exactly:     {leak['exact']} ({_pct(leak['exact'], leak['total'])})")

    joinable = [r for r in gold if (_eval_run_id(r) or -1) in contracts]
    print(f"\nJOIN (pipeline_runs.filled_text via eval_run_id):")
    print(f"  repairable: {len(joinable)} ({_pct(len(joinable), len(gold))})"
          f"  dropped: {len(gold) - len(joinable)}")
    print(f"  distinct contracts: {len(set(_eval_run_id(r) for r in joinable))}")
    print(f"  verdicts: {dict(collections.Counter(r.get('verdict') for r in joinable))}")

    hit, tot, full, nrows = _grounding_rate(gold, contracts, scramble=False)
    nhit, ntot, _, _ = _grounding_rate(gold, contracts, scramble=True)
    real = hit / tot if tot else 0.0
    ctrl = nhit / ntot if ntot else 0.0
    print(f"\nGROUNDING (quoted section headings found in the joined contract):")
    print(f"  correct contract: {hit}/{tot} ({_pct(hit, tot)})"
          f"  rows fully grounded: {full}/{nrows} ({_pct(full, nrows)})")
    print(f"  random  contract: {nhit}/{ntot} ({_pct(nhit, ntot)})   <- negative control")
    print(f"  margin: {real - ctrl:+.3f} (need >= {MIN_GROUNDING_MARGIN})")

    if not joinable:
        print("\nFAIL: nothing repairable — the join produced zero rows.")
        return 1
    if real - ctrl < MIN_GROUNDING_MARGIN:
        print("\nFAIL: grounding margin collapsed; the join is not trustworthy.")
        return 1
    print("\nCHECK PASSED")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    gold = read_jsonl(pathlib.Path(args.gold))
    if not gold:
        print(f"no gold quadruples at {args.gold}")
        return 1
    contracts = _contract_by_eval_run()

    hit, tot, _, _ = _grounding_rate(gold, contracts, scramble=False)
    nhit, ntot, _, _ = _grounding_rate(gold, contracts, scramble=True)
    margin = (hit / tot if tot else 0.0) - (nhit / ntot if ntot else 0.0)
    if margin < MIN_GROUNDING_MARGIN:
        print(f"refusing to build: grounding margin {margin:+.3f} < {MIN_GROUNDING_MARGIN}; "
              "run 'check' for the breakdown")
        return 1

    out_rows: list[dict] = []
    dropped: list[str] = []
    normalized = 0
    for row in gold:
        run_id = _eval_run_id(row)
        run = contracts.get(run_id) if run_id is not None else None
        if run is None:
            dropped.append((row.get("provenance") or {}).get("id") or "?")
            continue
        new = json.loads(json.dumps(row))  # don't mutate the source rows
        new["clause_text"] = {
            "body": run["filled_text"].strip(),
            "section": f"pipeline_runs:{run.get('id')}:filled_text (eval_run:{run_id})",
        }
        new["provenance"]["grounded_from"] = f"pipeline_runs:{run.get('id')}.filled_text"
        if args.normalize:
            fixed, changed = _normalize_harness_terms(new["reasoning"]["justification"])
            if changed:
                new["reasoning"]["justification"] = fixed
                normalized += 1
        out_rows.append(new)

    if not out_rows:
        print("FAIL: zero rows survived regrounding")
        return 1

    out_path = pathlib.Path(args.out)
    write_jsonl(out_path, out_rows)

    lengths = sorted(len(r["clause_text"]["body"]) for r in out_rows)
    print(f"regrounded: {len(out_rows)} / {len(gold)} ({_pct(len(out_rows), len(gold))})")
    print(f"  dropped (no real contract text): {len(dropped)}")
    print(f"  verdicts: {dict(collections.Counter(r['verdict'] for r in out_rows))}")
    print(f"  distinct contracts: {len(set(r['clause_text']['section'] for r in out_rows))}")
    print(f"  contract chars: p50={lengths[len(lengths) // 2]} "
          f"p90={lengths[int(len(lengths) * 0.9)]} max={lengths[-1]}")
    print(f"  harness terms renamed in justification: {normalized} "
          f"({_pct(normalized, len(out_rows))})"
          f"{'' if args.normalize else '  [--no-normalize]'}")
    print(f"  out: {out_path}")

    post = _leak_stats(out_rows)
    print(f"  post-repair leak check: body-is-prefix-of-justification "
          f"{post['prefix']} ({_pct(post['prefix'], post['total'])})")
    if post["prefix"]:
        print("  WARN: some rows still look leaked — inspect before training")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    common_args = argparse.ArgumentParser(add_help=False)
    common_args.add_argument("--gold", default=str(JUDGE_C_DIR / "judge_c_gold.jsonl"),
                             help="source gold quadruples (default canonical)")

    p_check = sub.add_parser("check", parents=[common_args],
                             help="measure the leak + join quality, write nothing")
    p_check.set_defaults(func=cmd_check)

    p_build = sub.add_parser("build", parents=[common_args], help="write regrounded gold")
    p_build.add_argument("--out", default=str(JUDGE_C_DIR / "judge_c_gold.grounded.jsonl"),
                         help="output path")
    p_build.add_argument("--no-normalize", dest="normalize", action="store_false",
                         help="keep the raw eval-harness wording "
                              "('the Actual Output') in justifications")
    p_build.set_defaults(func=cmd_build, normalize=True)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
