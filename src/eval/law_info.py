"""Read helpers for the ``law_info`` table (per-contract-type 法律法规 surveys).

Used by the web layer (``src/web/routes/law_info.py``). Read-only; the seeded
content comes from ``scripts/seed_law_info.py`` which reads the bundled
markdown under ``src/eval/seed/law_info/``.

Connection model matches the rest of the eval layer: ``connect(db)`` returns a
``_BorrowedConn`` when ``db`` is a live connection (request / test fixture),
so the caller's ``finally: conn.close()`` is a no-op on a borrowed connection
and a real close on a self-opened one.
"""

from __future__ import annotations

from typing import Any

from .db import connect
from .errors import NotFoundError


def list_law_info_types(db: Any = None) -> list[dict]:
    """List contract types that have at least one law_info row.

    Returns ``[{key, zh_name, sources}]`` ordered by ``contract_type``, where
    ``sources`` lists the sources present for that type (``doubao``/``deepseek``).
    """
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT contract_type, zh_name, source FROM law_info "
            "ORDER BY contract_type, source"
        ).fetchall()
    finally:
        conn.close()
    by_type: dict[str, dict] = {}
    for r in rows:
        entry = by_type.setdefault(
            r["contract_type"],
            {"key": r["contract_type"], "zh_name": r["zh_name"], "sources": []},
        )
        entry["sources"].append(r["source"])
    return list(by_type.values())


def get_law_info(contract_type: str, db: Any = None) -> dict:
    """Return both sources' content for a contract type.

    Returns ``{type, zh_name, doubao, deepseek}`` where each source field is
    the markdown content string or ``None`` when that source is absent. Raises
    ``NotFoundError`` when no law_info row exists for the type.
    """
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT source, content, zh_name FROM law_info WHERE contract_type = %s",
            (contract_type,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise NotFoundError(f"law_info not found for contract type: {contract_type!r}")
    out: dict = {"type": contract_type, "zh_name": rows[0]["zh_name"], "doubao": None, "deepseek": None}
    for r in rows:
        out[r["source"]] = r["content"]
    return out


def all_law_info(db: Any = None) -> list[dict]:
    """Return every law_info row as ``{contract_type, source, zh_name, content}``.

    Used by the legal-references extractor to compute the aggregated index from
    the seeded content.
    """
    conn = connect(db)
    try:
        rows = conn.execute(
            "SELECT contract_type, source, zh_name, content FROM law_info "
            "ORDER BY contract_type, source"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
