"""Read + validate per-type seed manifests (``data/clause_seeds/<type>.yaml``).

A manifest is ``{contract_type, tags[], clauses[], skipped[]}`` where each clause
carries ``body`` (with ``{{slot}}`` placeholders), optional ``stance``/
``strength`` (universal tag dims), ``slot_instructions`` (one entry per body
slot), ``section`` (one of the canonical 10), ``why``, and ``verdict``.

:func:`validate_manifest` enforces the schema and the slot-coverage invariant:
every ``{{slot}}`` in a clause ``body`` MUST have a matching ``slot_instructions``
entry (by ``name``). :func:`clause_to_record` turns a manifest clause into the
dict :func:`src.clauses.store.create_clause` consumes (carrying ``tags`` from
``stance``/``strength`` and the manifest's ``slot_instructions``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .extract import SECTION_ORDER
from .scenario_vocab import SCENARIO_VOCAB
from .tags import TAG_VOCAB

_SLOT_RE = re.compile(r"\{\{([^}]+)\}\}")
_SECTION_SET = set(SECTION_ORDER)
_UNIVERSAL_TAG_FIELDS = ("stance", "strength", "risk", "mandatory")


def load_manifest(path: str | Path) -> dict:
    """Load + validate a manifest at ``path``; return the parsed dict."""
    p = Path(path)
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    validate_manifest(d, expected_type=p.stem)
    return d


def validate_manifest(d: dict, expected_type: str | None = None) -> None:
    """Raise ``ValueError`` if the manifest is malformed."""
    if not isinstance(d, dict):
        raise ValueError("manifest must be a mapping")
    ct = d.get("contract_type")
    if not isinstance(ct, str) or not ct:
        raise ValueError("manifest missing contract_type")
    if expected_type and ct != expected_type:
        raise ValueError(f"contract_type {ct!r} != filename {expected_type!r}")
    for t in d.get("tags") or []:
        if not t.get("name") or not t.get("values"):
            raise ValueError(f"tag dim missing name/values: {t!r}")
    for i, c in enumerate(d.get("clauses") or []):
        if not isinstance(c, dict):
            raise ValueError(f"clause #{i} not a mapping")
        family = c.get("family", f"#{i}")
        for k in ("family", "section", "body", "why", "verdict"):
            if not c.get(k):
                raise ValueError(f"clause {family!r} missing {k}")
        if c["section"] not in _SECTION_SET:
            raise ValueError(f"clause {family!r} unknown section: {c['section']!r}")
        for dim in ("stance", "strength"):
            v = c.get(dim)
            if v is not None and v not in TAG_VOCAB.get(None, {}).get(dim, []):
                raise ValueError(f"clause {family!r} bad {dim}: {v!r}")
        body_slots = {s.strip() for s in _SLOT_RE.findall(c["body"])}
        instr_names = {ins.get("name") for ins in (c.get("slot_instructions") or [])}
        missing = body_slots - instr_names
        if missing:
            raise ValueError(
                f"clause {family!r} body slots without instruction: {sorted(missing)}"
            )
    for s in d.get("skipped") or []:
        if not s.get("item") or not s.get("reason"):
            raise ValueError(f"skipped entry missing item/reason: {s!r}")


def clause_to_record(clause: dict, contract_type: str, source_doc_title: str) -> dict:
    """Turn a manifest clause into a ``create_clause`` record.

    ``tags`` is built from the universal ``stance``/``strength``/``risk``/
    ``mandatory`` fields when present (type-specific dims are registered in the
    vocabulary but not assigned per-clause by the seed - set them via the
    dashboard). ``slot_instructions`` is passed through so ``create_clause``'s
    ``_finalize`` preserves the curated labels/descriptions/examples.
    """
    tags: dict[str, str] = {}
    for k in _UNIVERSAL_TAG_FIELDS:
        v = clause.get(k)
        if v is not None:
            tags[k] = str(v)
    rec: dict[str, Any] = {
        "contract_type": contract_type,
        "category": "custom",
        "section": clause["section"],
        "body": clause["body"],
        "source_doc_title": source_doc_title,
        "slot_instructions": clause.get("slot_instructions") or [],
    }
    if tags:
        rec["tags"] = tags
    return rec


# --- loader ---------------------------------------------------------------- #

_SEEDS_DIR = Path(__file__).resolve().parents[2] / "data" / "clause_seeds"


def _seed_marker(contract_type: str) -> str:
    return f"seed:{contract_type}"


def load_one(contract_type: str, db: Any = None, seeds_dir: Path | None = None) -> int:
    """Load (or refresh) one type's manifest into the ``clauses`` table; return count.

    Deletes existing seed clauses for the type (``source_doc_title =
    'seed:<type>'``) then :func:`create_clause` each. Idempotent (custom clauses
    have no ``(section, body_hash)`` dedup index, so the delete-by-marker is the
    dedup). ``db`` may be a borrowed connection (a request/test scope) - when
    ``None`` a fresh connection is opened and closed here.
    """
    from src.eval.db import connect

    from .store import create_clause

    base = seeds_dir or _SEEDS_DIR
    manifest = load_manifest(base / f"{contract_type}.yaml")
    marker = _seed_marker(contract_type)
    conn = connect(db)
    try:
        conn.execute("DELETE FROM clauses WHERE source_doc_title = %s", (marker,))
        conn.commit()
        n = 0
        for c in manifest.get("clauses") or []:
            create_clause(clause_to_record(c, contract_type, marker), db=conn)
            n += 1
        return n
    finally:
        if db is None:
            conn.close()


def load_all(db: Any = None, seeds_dir: Path | None = None) -> dict[str, int]:
    """Load every manifest under ``seeds_dir``; return ``{contract_type: count}``."""
    from src.eval.db import connect

    base = seeds_dir or _SEEDS_DIR
    types = sorted(p.stem for p in base.glob("*.yaml"))
    conn = connect(db)
    try:
        return {t: load_one(t, db=conn, seeds_dir=base) for t in types}
    finally:
        if db is None:
            conn.close()


def seed_tag_dims(db: Any = None, seeds_dir: Path | None = None) -> int:
    """Seed tag_dims: universal dims (contract_type=NULL) + per-type dims from manifests."""
    import yaml
    from psycopg.types.json import Jsonb

    from src.eval.db import connect

    base = seeds_dir or _SEEDS_DIR
    universal = [
        ("source", "来源", ["base", "tagged", "custom"], False, "来源"),
        ("stance", "利益倾向", ["pro_a", "pro_b", "balanced"], False, "利益倾向"),
        ("strength", "利益倾向", ["strong", "standard", "mild"], False, "强度"),
        ("risk", "风险合规", ["high", "medium", "low"], False, "风险"),
        ("mandatory", "风险合规", ["mandatory", "default", "recommended"], False, "法律性质"),
    ]
    conn = connect(db)
    try:
        for name, cat, vals, ff, zh in universal:
            conn.execute(
                "INSERT INTO tag_dims (name, contract_type, category, values, free_form, zh_label) "
                "VALUES (%s, NULL, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (name, cat, Jsonb(vals), ff, zh),
            )
        # scenario (业务场景): per-type controlled vocab, replaces province region.
        for ct, vals in SCENARIO_VOCAB.items():
            conn.execute(
                "INSERT INTO tag_dims (name, contract_type, category, values, free_form, zh_label) "
                "VALUES (%s, %s, %s, %s, false, %s) ON CONFLICT DO NOTHING",
                ("scenario", ct, "业务场景", Jsonb(vals), "业务场景"),
            )
        n = 0
        for p in sorted(base.glob("*.yaml")):
            ct = p.stem
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                continue
            for t in d.get("tags") or []:
                name = t.get("name")
                # scenario is owned by SCENARIO_VOCAB (业务场景), not manifests.
                if not name or name == "scenario":
                    continue
                vals = [str(v) for v in (t.get("values") or [])]
                if not vals:
                    continue
                conn.execute(
                    "INSERT INTO tag_dims (name, contract_type, category, values, free_form, zh_label) "
                    "VALUES (%s, %s, '类型专属', %s, false, %s) ON CONFLICT DO NOTHING",
                    (name, ct, Jsonb(vals), name),
                )
                n += 1
        conn.commit()
    finally:
        if db is None:
            conn.close()
    return n
