"""Container boot step: land the additive schema before serving traffic.

:func:`src.eval.store.ensure_schema` is the ONLY place the kernel's additive DDL
lives (new tables, new columns). Route-level ``ensure_schema()`` calls keep a
long-running process honest once someone has visited a page that triggers them,
but nothing guarantees that on a *deploy*: a database created before a column
existed has no such request yet, and the first hit on a page that reads the
missing column 500s.

That is not hypothetical — 2026-11-08 the production ``law_bench`` database
still predated C5: ``domain_members`` had no ``last_opened_at`` and none of the
C5 domain tables (the assets catalog, the proposal inbox and its events, the
distribution pull log, the RAG corpus registry, the ontology publications)
existed, so every ``/d`` page 500'd for a signed-in user on a freshly rolled
image. The DDL had only ever run against dev and test databases, whose fixtures
call ``ensure_schema`` explicitly.

So boot ensures it unconditionally, and fails loudly: the entrypoint runs this
module before ``exec uvicorn``, and a schema that cannot be landed exits
non-zero, so the container crash-loops instead of serving a half-schema app.

The public read-only pod deliberately does NOT run this (its entrypoint branch
execs uvicorn directly): its database is a replicated dump, and a read surface
must not perform DDL. Anything missing there arrives with the dump.
"""

from __future__ import annotations

from src.eval.store import ensure_schema


def main() -> int:
    """Ensure the schema on the configured database; print one honest line."""
    from src.eval.db import _dsn
    from src.settings import DEFAULT_DB

    ensure_schema(DEFAULT_DB)
    # The DSN carries a password — print only the database name, never the DSN.
    dbname = _dsn().rsplit("/", 1)[-1].split("?", 1)[0]
    print(f"boot: schema ensured on database {dbname!r}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via docker entrypoint
    raise SystemExit(main())
