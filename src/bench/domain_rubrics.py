"""Domain-scoped evaluation standards (change add-domain-tree-and-shared-libraries §3.4/§3.5).

Rubrics used to be global (looked up by name, no owner). Evaluation standards
are per-domain now, and inheritance is **by reference**: a child domain sees its
ancestors' rubrics as effective standards, and "forking" one is an explicit,
recorded act.

Why fork must carry a diff: a fork that silently copies is indistinguishable
from the parent forever after. Requiring a written difference summary means a
later reader can tell "this is the same standard" from "this one was changed,
here is how".

Legacy CRUD (``src/eval/rubric_crud.py``) stays untouched: it keeps working on
rows with a NULL domain, and this module is what the domain console and the
domain-aware evaluation path use.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from psycopg.types.json import Jsonb

from . import inheritance

#: Rubric fields an effective-resolution row exposes to callers.
_COLS = (
    "r.id, r.name, r.context, r.source, r.source_path, r.description, "
    "r.domain_id, r.derived_from, r.fork_diff, r.created_at"
)


class ForkError(ValueError):
    """A fork was requested without the difference summary that makes it auditable."""


def create_for_domain(
    conn: Any,
    *,
    domain_id: int,
    name: str,
    context: str,
    criteria: Iterable[dict] = (),
    description: Optional[str] = None,
    source: str = "local",
    derived_from: Optional[int] = None,
    fork_diff: Optional[dict] = None,
    commit: bool = True,
) -> dict:
    """Create a rubric owned by ``domain_id`` (name unique per domain)."""
    name = (name or "").strip()
    context = (context or "").strip()
    if not name:
        raise ValueError("rubric name is required")
    if not context:
        raise ValueError("rubric context must not be empty")
    if derived_from is not None and not fork_diff:
        raise ForkError(
            "a forked rubric must record its difference from the parent (fork_diff)"
        )

    cur = conn.execute(
        "INSERT INTO rubrics (name, context, source, source_path, description, "
        "domain_id, derived_from, fork_diff, created_at) "
        "VALUES (%s, %s, %s, NULL, %s, %s, %s, %s, now()) RETURNING id",
        (
            name,
            context,
            source,
            description,
            domain_id,
            derived_from,
            Jsonb(fork_diff) if fork_diff else None,
        ),
    )
    rubric_id = cur.fetchone()["id"]
    for ordinal, c in enumerate(criteria):
        conn.execute(
            "INSERT INTO criteria (rubric_id, name, description, guidance, ordinal) "
            "VALUES (%s, %s, %s, %s, %s)",
            (rubric_id, c.get("name"), c.get("description"), c.get("guidance"), ordinal),
        )
    if commit:
        conn.commit()
    return get_by_id(conn, rubric_id=rubric_id)


def get_by_id(conn: Any, *, rubric_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_COLS} FROM rubrics r WHERE r.id = %s", (rubric_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"rubric {rubric_id} not found")
    out = dict(row)
    out["criteria"] = [
        dict(c)
        for c in conn.execute(
            "SELECT name, description, guidance, ordinal FROM criteria "
            "WHERE rubric_id = %s ORDER BY ordinal",
            (rubric_id,),
        ).fetchall()
    ]
    return out


def effective_rubrics(conn: Any, *, domain_path: str) -> list[dict]:
    """Every rubric visible to ``domain_path``, nearest definition winning.

    Two rubrics with the same name in different ancestors are one standard with
    an override: only the nearest is returned, and its row keeps its own
    ``domain_id`` so the caller can see where the definition lives.
    """
    chain = inheritance.ancestors(domain_path)
    rows = conn.execute(
        f"SELECT {_COLS} FROM rubrics r WHERE r.domain_id IN ("
        "  SELECT id FROM domains WHERE path = ANY(%s))",
        (chain,),
    ).fetchall()
    depth = {
        r["id"]: r["path"]
        for r in conn.execute(
            "SELECT id, path FROM domains WHERE path = ANY(%s)", (chain,)
        ).fetchall()
    }
    order = {p: i for i, p in enumerate(chain)}
    best: dict[str, dict] = {}
    for row in rows:
        item = dict(row)
        key = item["name"]
        cur = best.get(key)
        if cur is None or order.get(depth.get(item["domain_id"]), -1) > order.get(
            depth.get(cur["domain_id"]), -1
        ):
            best[key] = item
    out = []
    for item in sorted(best.values(), key=lambda r: r["name"]):
        item["origin"] = "own" if depth.get(item["domain_id"]) == domain_path else "inherited"
        out.append(item)
    return out


def get_effective(conn: Any, *, domain_path: str, name: str) -> Optional[dict]:
    for item in effective_rubrics(conn, domain_path=domain_path):
        if item["name"] == name:
            return get_by_id(conn, rubric_id=item["id"])
    return None


def fork(
    conn: Any,
    *,
    source_rubric_id: int,
    domain_id: int,
    fork_diff: dict,
    name: Optional[str] = None,
    commit: bool = True,
) -> dict:
    """Copy a rubric into ``domain_id`` as a recorded fork.

    ``fork_diff`` is mandatory and free-form; a caller that cannot describe how
    the fork differs has no business forking it.
    """
    if not fork_diff:
        raise ForkError("a fork must record how it differs from its parent")
    src = get_by_id(conn, rubric_id=source_rubric_id)
    return create_for_domain(
        conn,
        domain_id=domain_id,
        name=name or src["name"],
        context=src["context"],
        criteria=src["criteria"],
        description=src["description"],
        source=src["source"],
        derived_from=source_rubric_id,
        fork_diff=fork_diff,
        commit=commit,
    )


def attribute_run(
    conn: Any, *, run_id: int, rubric_id: Optional[int], commit: bool = True
) -> None:
    """Stamp which rubric (and therefore which domain) a run actually used.

    Nullable on purpose: legacy runs predate domain ownership, and claiming a
    domain for them would be inventing provenance.
    """
    domain_id = None
    if rubric_id is not None:
        row = conn.execute(
            "SELECT domain_id FROM rubrics WHERE id = %s", (rubric_id,)
        ).fetchone()
        domain_id = row["domain_id"] if row else None
    conn.execute(
        "UPDATE eval_runs SET rubric_domain_id = %s WHERE id = %s",
        (domain_id, run_id),
    )
    if commit:
        conn.commit()


def runs_for_domain(conn: Any, *, domain_path: str, limit: int = 50) -> list[dict]:
    """Runs attributed to this domain's subtree (own + inherited standards)."""
    chain = inheritance.ancestors(domain_path)
    rows = conn.execute(
        "SELECT e.id, e.rubric_name, e.score, e.max_score, e.all_pass, e.scored_at, "
        "       e.rubric_domain_id, d.path AS domain_path "
        "FROM eval_runs e LEFT JOIN domains d ON d.id = e.rubric_domain_id "
        "WHERE d.path = ANY(%s) ORDER BY e.id DESC LIMIT %s",
        (chain, limit),
    ).fetchall()
    return [dict(r) for r in rows]
