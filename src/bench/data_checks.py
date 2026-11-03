"""Deterministic (data) evaluation channel over knowledge units.

The second evaluation channel alongside the text/judge channel: instead of an
LLM rubric, per-kind checker functions run over every knowledge unit of a
kind and the verdicts aggregate into a single ``eval_runs`` row
(``channel='data'``) with one ``eval_criteria_results`` row per
(unit, checker). No LLM or judge is ever invoked — every verdict is the
checker's own deterministic outcome, recorded honestly (``PASS``/``FAIL``,
with the checker's detail as the row's reasoning).

Checkers are plain callables registered against a unit ``kind``:

    register_checker("qa-pair", "body-nonempty",
                     lambda unit: CheckResult("body-nonempty", bool(unit["body"]), "empty body"))

A checker receives the unit's full dict (as returned by the kernel store) and
returns a :class:`CheckResult` or a plain bool (coerced into a CheckResult
with a generic detail). A checker that raises fails the whole run loudly —
results are never silently partial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from src.settings import DEFAULT_DB

from src.eval.store import store_result

from .store import list_knowledge_units

# Upper bound for the "every unit of the kind" listing inside run_data_eval;
# far above any curated per-kind corpus, well below INT_MAX.
_LIST_LIMIT = 100_000

# kind -> {checker name -> callable}; registration order fixes criteria order.
_CHECKERS: dict[str, dict[str, Callable[[dict], Any]]] = {}


@dataclass
class CheckResult:
    """One deterministic checker's verdict on one knowledge unit."""

    name: str
    passed: bool
    detail: str


def register_checker(kind: str, name: str, fn: Callable[[dict], Any]) -> None:
    """Register a deterministic checker for ``kind``.

    ``fn`` is called as ``fn(unit_dict)`` and returns a :class:`CheckResult`
    or a plain bool. Re-registering the same ``(kind, name)`` replaces the
    previous callable.
    """
    _CHECKERS.setdefault(kind, {})[name] = fn


def checkers_for(kind: str) -> dict[str, Callable[[dict], Any]]:
    """The checkers registered for ``kind`` (name -> fn, registration order).

    Returns a copy: mutating it never corrupts the registry.
    """
    return dict(_CHECKERS.get(kind, {}))


def _coerce_result(name: str, outcome: Any) -> CheckResult:
    if isinstance(outcome, CheckResult):
        return outcome
    return CheckResult(name=name, passed=bool(outcome), detail="ok" if outcome else "failed")


def run_data_eval(
    conn: Any,
    *,
    kind: str,
    unit_ids: Optional[list[str]] = None,
    db_path: Any = DEFAULT_DB,
) -> int:
    """Run every checker registered for ``kind`` over the kind's units.

    ``conn`` is the knowledge-unit store connection (kernel store list/get);
    ``db_path`` is passed through to :func:`src.eval.store.store_result` for
    the eval side (accepts a connection, same as everywhere else).

    ``unit_ids=None`` evaluates every unit of the kind (all namespaces);
    otherwise it selects units by ``external_key`` in caller order, raising
    ``KeyError`` for a requested key that does not exist.

    One aggregated run is stored: ``channel='data'``, ``unit_kind=kind``,
    ``rubric_name='data-checks:<kind>'``, ``judge_model='deterministic'``,
    ``score=n_passed``, ``max_score=n_criteria``, ``all_pass`` only when every
    check passed (an empty selection never claims all-pass). Returns the new
    ``eval_runs.id``.
    """
    checkers = checkers_for(kind)
    if not checkers:
        raise ValueError(f"no checkers registered for kind={kind!r}")

    if unit_ids is None:
        units = list_knowledge_units(conn, kind=kind, limit=_LIST_LIMIT)
    else:
        wanted = list(unit_ids)
        found = {
            u["external_key"]: u
            for u in list_knowledge_units(conn, kind=kind, limit=_LIST_LIMIT)
            if u["external_key"] in set(wanted)
        }
        missing = [key for key in wanted if key not in found]
        if missing:
            raise KeyError(
                f"knowledge unit(s) not found for kind={kind!r}: {missing!r}"
            )
        units = [found[key] for key in wanted]

    criteria_results: list[dict] = []
    n_passed = 0
    for unit in units:
        for checker_name, fn in checkers.items():
            outcome = fn(unit)
            res = _coerce_result(checker_name, outcome)
            n_passed += bool(res.passed)
            criteria_results.append(
                {
                    # Unique per (unit, checker): namespace/external_key is the
                    # unit's upsert identity; the checker name completes it.
                    "id": f"{unit['namespace']}/{unit['external_key']}::{res.name}",
                    "title": res.name,
                    "verdict": "PASS" if res.passed else "FAIL",
                    "reasoning": res.detail,
                }
            )

    n_criteria = len(criteria_results)
    return store_result(
        {
            "rubric": f"data-checks:{kind}",
            "score": n_passed,
            "max_score": n_criteria,
            "all_pass": n_criteria > 0 and n_passed == n_criteria,
            "n_criteria": n_criteria,
            "n_passed": n_passed,
            "summary": f"deterministic data checks: {n_passed}/{n_criteria} passed",
            "judge_model": "deterministic",
            "criteria_results": criteria_results,
        },
        db_path=db_path,
        channel="data",
        unit_kind=kind,
    )
