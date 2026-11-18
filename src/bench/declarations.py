"""Corpus declarations: what a domain says it needs, checked against what it has.

A domain template carries ``corpus_declaration.source_types`` — until now a list
of free-form strings ("stored_clauses", "clause_seed_manifests", …). Those names
described the old world where each corpus had its own hand-written pipeline; with
shared libraries the actionable question is different: *does this domain get the
corpus it says it needs?*

So a declaration entry may now name a real library source::

    "source_types": ["library:<library_key>/<source_key>", "stored_clauses"]

:: 

- ``library:<library_key>/<source_key>`` — checkable. Resolved against the
  domain's **effective** subscriptions (inheritance included), and unsubscribed
  refs are reported as missing rather than silently ignored.
- anything else — a legacy/free-form label. Kept verbatim, never counted as
  satisfied: pretending an old name is covered because it appears in the same
  list is exactly the kind of green that hides a gap.

Nothing here writes. The estate matrix and the knowledge area read the same
resolution, so "declared but not subscribed" cannot mean two different things.
"""

from __future__ import annotations

from typing import Any, Optional

from . import libraries

#: Marks a declaration entry that points at a real library source.
LIBRARY_PREFIX = "library:"


def parse(decl: Optional[dict]) -> tuple[list[tuple[str, str]], list[str]]:
    """Split a declaration into ``[(library_key, source_key), …]`` and legacy labels."""
    refs: list[tuple[str, str]] = []
    legacy: list[str] = []
    for raw in (decl or {}).get("source_types") or []:
        entry = str(raw).strip()
        if not entry:
            continue
        if entry.startswith(LIBRARY_PREFIX):
            body = entry[len(LIBRARY_PREFIX):]
            if body.count("/") != 1:
                raise ValueError(
                    f"corpus declaration entry {entry!r} must be "
                    f"'{LIBRARY_PREFIX}<library_key>/<source_key>'"
                )
            lib_key, src_key = body.split("/")
            if not lib_key or not src_key:
                raise ValueError(f"corpus declaration entry {entry!r} is incomplete")
            refs.append((lib_key, src_key))
        else:
            legacy.append(entry)
    return refs, legacy


def check_refs(conn: Any, decl: Optional[dict]) -> None:
    """Raise if a declaration names a library source that does not exist.

    Called when a template is created: a declaration pointing at nothing is a
    promise nobody can keep, and it would only be discovered when someone later
    asks why the domain is missing corpus.
    """
    refs, _legacy = parse(decl)
    problems: list[str] = []
    for lib_key, src_key in refs:
        lib = libraries.get_library(conn, library_key=lib_key)
        if lib is None:
            problems.append(f"unknown library {lib_key!r}")
            continue
        known = {s["source_key"] for s in libraries.list_sources(conn, library_id=lib["id"])}
        if src_key not in known:
            problems.append(f"library {lib_key!r} has no source {src_key!r}")
    if problems:
        raise ValueError("; ".join(problems))


def resolve(conn: Any, *, domain_path: str, decl: Optional[dict]) -> dict:
    """Per-entry status of a declaration for one domain.

    ``satisfied`` means the entry is a real library source **and** the domain's
    effective scope contains it (own subscription or inherited). Legacy labels
    are returned as-is with ``satisfied=None``: unknown, not healthy.
    """
    refs, legacy = parse(decl)
    try:
        scope = libraries.effective_sources(conn, domain_path=domain_path)
        scope_error = None
    except ValueError as exc:
        scope, scope_error = {}, str(exc)

    entries: list[dict] = []
    for lib_key, src_key in refs:
        granted = src_key in scope.get(lib_key, set())
        entries.append(
            {
                "entry": f"{LIBRARY_PREFIX}{lib_key}/{src_key}",
                "library_key": lib_key,
                "source_key": src_key,
                "satisfied": granted,
                "reason": None if granted else "not in this domain's effective scope",
            }
        )
    for label in legacy:
        entries.append(
            {
                "entry": label,
                "library_key": None,
                "source_key": None,
                "satisfied": None,
                "reason": "free-form label (not bound to a library source)",
            }
        )
    missing = [e for e in entries if e["satisfied"] is False]
    return {
        "entries": entries,
        "missing": missing,
        "error": scope_error,
        "all_satisfied": not missing and not scope_error,
    }
