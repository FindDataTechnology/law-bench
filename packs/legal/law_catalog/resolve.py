"""Law-name resolution: clause citation strings → law_catalog entries.

Resolution ladder (deterministic, first hit wins; every result records how it
matched via ``resolved_via``):

  1. exact    - normalized equality against replica titles
  2. alias    - curated alias table (简称/旧称 → 全称), then full-title lookup
  3. trigram  - pg_trgm similarity above ``LAW_TRGM_THRESHOLD`` (needs the
                extension; without it this rung degrades to unresolved)
  4. unresolved - review queue

Normalization (``normalize_name``) aligns with ``src.eval.legal_refs``
``_dedup_key``: strip whitespace and the ``中华人民共和国`` prefix. Book-title
marks (《》) are stripped too - callers may pass cited names with or without
them.
"""

from __future__ import annotations

from typing import Optional

from src.eval.db import connect, now_iso
from src.settings import LAW_TRGM_THRESHOLD

_CN_PREFIX = "中华人民共和国"


def normalize_name(name: str) -> str:
    """Canonical comparison key for a cited law name.

    Strips surrounding whitespace, wrapping 《》, and the leading
    ``中华人民共和国`` (so 民法典 / 中华人民共和国民法典 collapse, matching the
    ``_dedup_key`` convention used by the legal-references aggregator).
    """
    n = (name or "").strip()
    if n.startswith("《") and n.endswith("》"):
        n = n[1:-1].strip()
    if n.startswith(_CN_PREFIX):
        n = n[len(_CN_PREFIX):]
    return n.strip()


class LawCatalogIndex:
    """In-memory replica + alias snapshot for batch resolution.

    Loads the whole catalog once (~tens of thousands of rows) so exact/alias
    rungs never touch SQL per name; only the trigram rung queries. One index
    per resolve pass - refreshes (re-imports) after construction are invisible
    until the next pass, which is the intended snapshot semantics.
    """

    def __init__(self, db=None, threshold: Optional[float] = None) -> None:
        from . import store

        self.threshold = LAW_TRGM_THRESHOLD if threshold is None else threshold
        conn = connect(db)
        try:
            self._laws: dict[str, dict] = {}
            self._by_id: dict[int, dict] = {}
            for r in conn.execute(
                "SELECT id, title, status FROM law_catalog.laws"
            ).fetchall():
                row = dict(r)
                self._by_id[row["id"]] = row
                self._laws.setdefault(normalize_name(row["title"]), row)
            self._aliases = store.list_aliases(db=conn)
        finally:
            conn.close()

    def resolve(self, name: str, db=None) -> dict:
        """Resolve one cited name. Returns::

            {"cited_name", "law_id", "title", "status", "resolved_via"}

        with ``law_id``/``title``/``status`` None when unresolved.
        """
        raw = (name or "").strip()
        norm = normalize_name(raw)
        if not norm:
            return {"cited_name": raw, "law_id": None, "title": None,
                    "status": None, "resolved_via": "unresolved"}

        hit = self._laws.get(norm)
        if hit:
            return self._hit(raw, hit, "exact")

        alias = self._aliases.get(norm)
        if alias and alias["source"] != "non_match":
            if alias["law_id"] is not None and alias["law_id"] in self._by_id:
                return self._hit(raw, self._by_id[alias["law_id"]], "alias")
            target = alias.get("target_title") or ""
            hit = self._laws.get(normalize_name(target))
            if hit:
                return self._hit(raw, hit, "alias")

        hit = self._trigram(norm, db=db)
        if hit:
            return self._hit(raw, hit, "trigram")

        return {"cited_name": raw, "law_id": None, "title": None,
                "status": None, "resolved_via": "unresolved"}

    @staticmethod
    def _hit(cited: str, law: dict, via: str) -> dict:
        return {"cited_name": cited, "law_id": law["id"],
                "title": law["title"], "status": law.get("status"), "resolved_via": via}

    def _trigram(self, norm: str, db=None) -> Optional[dict]:
        from . import store

        if not store.has_trgm(db):
            return None
        conn = connect(db)
        try:
            row = conn.execute(
                "SELECT id, title, status "
                "FROM law_catalog.laws "
                "WHERE similarity(regexp_replace(title, '^中华人民共和国', ''), %s) >= %s "
                "ORDER BY similarity(regexp_replace(title, '^中华人民共和国', ''), %s) DESC "
                "LIMIT 1",
                (norm, self.threshold, norm),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()


def resolve_all_clauses(db=None, threshold: Optional[float] = None) -> dict:
    """Re-run the full clause → law resolution pass (idempotent).

    Reads every clause's ``law_refs`` (derived column - read-only here),
    resolves each cited name, and batch-upserts ``law_catalog.clause_law_refs``
    (one executemany, single transaction). Rows for clauses/citations that no
    longer exist are removed. Clause bodies and ``clauses.law_refs`` are never
    written.
    """
    from . import store

    index = LawCatalogIndex(db=db, threshold=threshold)
    cache: dict[str, dict] = {}

    conn = connect(db)
    try:
        clauses = conn.execute(
            "SELECT id, law_refs FROM clauses ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    citations = 0
    resolved: dict[str, int] = {"exact": 0, "alias": 0, "trigram": 0}
    unresolved_names: dict[str, int] = {}
    results: list[tuple] = []
    current: set[tuple[int, str]] = set()

    for c in clauses:
        clause_id = c["id"]
        for ref in c["law_refs"] or []:
            name = (ref.get("name") or "").strip()
            if not name:
                continue
            key = normalize_name(name)
            current.add((clause_id, name))
            citations += 1
            if key not in cache:
                cache[key] = index.resolve(name, db=db)
            res = cache[key]
            if res["resolved_via"] == "unresolved":
                unresolved_names[name] = unresolved_names.get(name, 0) + 1
            else:
                resolved[res["resolved_via"]] += 1
            results.append(
                (clause_id, name, res["law_id"], res["status"], res["resolved_via"])
            )

    _write_results(results, current, db=db)
    return {
        "clauses": len(clauses),
        "citations": citations,
        "resolved": resolved,
        "unresolved_names": unresolved_names,
    }


def _write_results(
    results: list[tuple], current: set[tuple[int, str]], db=None
) -> None:
    """Batch-upsert all resolution rows and prune stale ones (one transaction)."""
    from . import store

    conn = connect(db)
    try:
        store.ensure_schema(conn)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO law_catalog.clause_law_refs "
                    "(clause_id, cited_name, law_id, status, resolved_via, resolved_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (clause_id, cited_name) DO UPDATE SET "
                    "law_id = EXCLUDED.law_id, status = EXCLUDED.status, "
                    "resolved_via = EXCLUDED.resolved_via, resolved_at = EXCLUDED.resolved_at",
                    [(cid, name, lid, st, via, now_iso()) for cid, name, lid, st, via in results],
                )
                cur.execute("DROP TABLE IF EXISTS _law_catalog_current_refs")
                cur.execute(
                    "CREATE TEMP TABLE _law_catalog_current_refs "
                    "(clause_id BIGINT, cited_name TEXT) ON COMMIT DROP"
                )
                if current:
                    cur.executemany(
                        "INSERT INTO _law_catalog_current_refs (clause_id, cited_name) VALUES (%s, %s)",
                        list(current),
                    )
                cur.execute(
                    "DELETE FROM law_catalog.clause_law_refs r "
                    "WHERE NOT EXISTS (SELECT 1 FROM clauses c WHERE c.id = r.clause_id) "
                    "OR NOT EXISTS (SELECT 1 FROM _law_catalog_current_refs t "
                    "WHERE t.clause_id = r.clause_id AND t.cited_name = r.cited_name)"
                )
        conn.commit()
    finally:
        conn.close()
