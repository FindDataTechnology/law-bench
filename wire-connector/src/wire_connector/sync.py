"""Real-wire → public-kernel sync flow (fetch_entities + promote staging).

Wires ``wire_connector.client.WireClient.get_graph()`` into the PUBLIC bench
kernel's promotion machine (``law-bench/src/bench/promotion.py``): graph
nodes/edges are mirrored into ``knowledge_units`` as bronze entities (machine
pre-annotation), idempotent by wire identity key — the bench never keeps a
second identity store (contract: 柏讯实体升格契约).

Cross-repo import (VAAS precedent in this repo, fd-coding-law-bench-mcp: the
package root puts the law template repo on sys.path the same way):

    dependency direction = internal → public, NEVER the reverse.

``law-bench`` is located via the ``LAW_BENCH_REPO`` env (path to the public
repo checkout); its repo root is prepended to ``sys.path`` so
``from src.bench import promotion`` resolves exactly as it does inside the
public repo's own test suite. Nothing in law-bench ever imports this package.

DB connection: the bench store is Postgres; the connector takes a connection
(or opens one from ``BENCH_DATABASE_URL`` / ``database_url`` via psycopg).
The connector itself holds no SQL — every write goes through the kernel.

CLI-ish entry: ``sync_now()`` returns the kernel's sync result dict
(created/updated/unchanged key lists), which is what the README's "run a real
sync" command prints.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from .client import WireClient

WIRE_NAMESPACE = "wire"

#: kernel kinds the promotion machine syncs (entity graph nodes/edges).
KIND_ENTITY = "entity"
KIND_RELATION = "relation"


def _law_bench_repo() -> Path:
    """Locate the public law-bench checkout (env override, sibling default)."""
    raw = os.environ.get("LAW_BENCH_REPO", "").strip()
    if raw:
        root = Path(raw).expanduser().resolve()
    else:
        # 本仓 wire-connector/src/wire_connector/sync.py 往上四层到工作区根，
        # 再进同级的 law-bench/（依赖方向：内部 → 公开）
        root = Path(__file__).resolve().parents[4] / "law-bench"
    if not (root / "src" / "bench" / "promotion.py").is_file():
        raise RuntimeError(
            f"law-bench kernel not found at {root} — set LAW_BENCH_REPO to the "
            "public repo checkout (dependency direction: internal → public)"
        )
    return root


def import_kernel() -> Any:
    """Make ``src.bench.promotion`` importable and return the module.

    The public repo root goes on sys.path (its tests import the kernel as
    ``src.bench.*``), so the very same kernel code runs for bench-native and
    connector-driven promotions.
    """
    root = _law_bench_repo()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.bench import promotion  # noqa: PLC0415 (post sys.path wiring)

    return promotion


def bench_connect(dsn: Optional[str] = None) -> Any:
    """Open the bench Postgres connection (psycopg, dict rows)."""
    url = dsn or os.environ.get("BENCH_DATABASE_URL") or os.environ.get("database_url") or ""
    if not url:
        raise RuntimeError(
            "no bench database URL: set BENCH_DATABASE_URL (or database_url) "
            "to the knowledge-bench Postgres DSN"
        )
    import psycopg  # noqa: PLC0415 - runtime dependency of the real sync path
    from psycopg.rows import dict_row  # noqa: PLC0415

    conn = psycopg.connect(url, row_factory=dict_row)
    return conn


def ensure_kernel_schema(conn: Any) -> None:
    """Bootstrap the kernel schema (idempotent DDL) via the public repo."""
    root = _law_bench_repo()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from src.eval.store import ensure_schema  # noqa: PLC0415

    ensure_schema(db_path=conn)


def sync_graph(
    conn: Any,
    *,
    client: Optional[WireClient] = None,
    fetch_fn: Optional[Callable[[], dict]] = None,
    namespace: str = WIRE_NAMESPACE,
) -> dict:
    """One sync pass: wire graph → bronze knowledge units (idempotent).

    Either pass a live ``client`` (real fd-wire) or a ``fetch_fn`` returning
    the graph dict (tests/imports of another registry). The kernel's
    ``promotion.sync_graph`` owns the upsert/state rules; this function only
    provides the transport.
    """
    if fetch_fn is None:
        if client is None:
            client = WireClient()
        fetch_fn = client.get_graph
    promotion = import_kernel()
    return promotion.sync_graph(conn, fetch_fn=fetch_fn, namespace=namespace)


def sync_now(dsn: Optional[str] = None, **client_kwargs: Any) -> dict:
    """Open bench DB + live wire client and run one sync (command entry)."""
    client = WireClient(**client_kwargs)
    conn = bench_connect(dsn)
    try:
        ensure_kernel_schema(conn)
        result = sync_graph(conn, client=client)
        conn.commit()
        return result
    finally:
        conn.close()


__all__ = [
    "WIRE_NAMESPACE",
    "bench_connect",
    "ensure_kernel_schema",
    "import_kernel",
    "sync_graph",
    "sync_now",
]
