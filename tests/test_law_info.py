"""Tests for the law_info table, seeder, read module, and law-refined v2 helpers.

Covers:
- the ``law_info`` table is created idempotently by both schema paths
  (``create_schema`` and ``ensure_schema``);
- ``seed_law_info`` upserts one row per ``(contract_type, source)`` idempotently
  and never touches ``rubrics``/``criteria``/``prompts``;
- the bundled markdown (41×2 files + ``contract_types.json``) is present;
- the read helpers (``list_law_info_types`` / ``get_law_info`` / ``all_law_info``);
- the law-refined v2 prompt/rubric helpers and the citation registry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from src.eval import harbor_seed, store
from src.eval.db import table_exists
from src.eval.errors import NotFoundError
from src.eval.law_info import all_law_info, get_law_info, list_law_info_types
from src.eval.law_refined_citations import LAW_REFINED_CITATIONS

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "src" / "eval" / "seed" / "law_info"


def _load_seed_module():
    """Import ``scripts/seed_law_info.py`` as a module (scripts/ on sys.path)."""
    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "seed_law_info", scripts / "seed_law_info.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path.pop(0)


# --- schema ----------------------------------------------------------------- #


def test_law_info_table_created_by_create_schema(empty_db):
    harbor_seed.create_schema(empty_db)
    empty_db.commit()
    assert table_exists(empty_db, "law_info") is True
    cols = {r["column_name"] for r in empty_db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'law_info'"
    ).fetchall()}
    assert {"contract_type", "source", "zh_name", "content", "created_at"} <= cols


def test_law_info_table_created_by_ensure_schema(empty_db):
    store.ensure_schema(empty_db)
    assert table_exists(empty_db, "law_info") is True


def test_create_schema_is_idempotent_for_law_info(empty_db):
    harbor_seed.create_schema(empty_db)
    empty_db.commit()
    harbor_seed.create_schema(empty_db)  # second run must not error
    empty_db.commit()
    assert table_exists(empty_db, "law_info") is True


# --- bundled seed data ------------------------------------------------------ #


def _load_contract_types():
    import json

    with (SEED_DIR / "contract_types.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def test_bundled_markdown_files_present():
    types = _load_contract_types()
    assert len(types) == 43
    for ct in types:
        key = ct["key"]
        assert (SEED_DIR / "doubao" / f"{key}.md").is_file(), key
        assert (SEED_DIR / "deepseek" / f"{key}.md").is_file(), key


def test_citation_registry_covers_all_seeded_types():
    types = {ct["key"] for ct in _load_contract_types()}
    assert set(LAW_REFINED_CITATIONS) == types
    # every citation names at least one 《...》 statute
    for key, citation in LAW_REFINED_CITATIONS.items():
        assert "《" in citation and "》" in citation, key


# --- seeder ----------------------------------------------------------------- #


def test_upsert_law_info_is_idempotent(seeded_db):
    m = _load_seed_module()
    now = "2026-01-01T00:00:00+00:00"
    harbor_seed.create_schema(seeded_db)
    seeded_db.commit()
    lid1 = m.upsert_law_info(seeded_db, "sale", "doubao", "买卖合同", "# body", now)
    lid2 = m.upsert_law_info(seeded_db, "sale", "doubao", "买卖合同", "# body v2", now)
    seeded_db.commit()
    assert lid1 == lid2  # same row, updated not inserted
    n = seeded_db.execute(
        "SELECT count(*) AS n FROM law_info WHERE contract_type='sale' AND source='doubao'"
    ).fetchone()["n"]
    assert n == 1
    # content updated on re-upsert
    content = seeded_db.execute(
        "SELECT content FROM law_info WHERE contract_type='sale' AND source='doubao'"
    ).fetchone()["content"]
    assert content == "# body v2"


def test_seed_law_info_does_not_touch_other_tables(seeded_db):
    m = _load_seed_module()
    harbor_seed.create_schema(seeded_db)
    seeded_db.commit()
    now = "2026-01-01T00:00:00+00:00"
    before_rubrics = seeded_db.execute("SELECT count(*) AS n FROM rubrics").fetchone()["n"]
    before_prompts = seeded_db.execute("SELECT count(*) AS n FROM prompts").fetchone()["n"]
    # seed 3 types × 2 sources
    for key, zh in [("sale", "买卖合同"), ("loan", "借款合同"), ("lease", "租赁合同")]:
        for source in ("doubao", "deepseek"):
            m.upsert_law_info(seeded_db, key, source, zh, f"# {key} {source}", now)
    seeded_db.commit()
    assert seeded_db.execute("SELECT count(*) AS n FROM law_info").fetchone()["n"] == 6
    assert seeded_db.execute("SELECT count(*) AS n FROM rubrics").fetchone()["n"] == before_rubrics
    assert seeded_db.execute("SELECT count(*) AS n FROM prompts").fetchone()["n"] == before_prompts


# --- read module ------------------------------------------------------------ #


def _seed_a_few(conn):
    harbor_seed.create_schema(conn)
    conn.execute("TRUNCATE law_info RESTART IDENTITY")
    for key, zh in [("sale", "买卖合同"), ("loan", "借款合同")]:
        for source in ("doubao", "deepseek"):
            conn.execute(
                "INSERT INTO law_info (contract_type, source, zh_name, content, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (key, source, zh, f"# {key} {source}\n\n《中华人民共和国民法典》", "2026-01-01"),
            )
    conn.commit()


def test_list_and_get_law_info(seeded_db):
    _seed_a_few(seeded_db)
    types = list_law_info_types(seeded_db)
    assert {t["key"] for t in types} == {"sale", "loan"}
    sale = next(t for t in types if t["key"] == "sale")
    assert sale["zh_name"] == "买卖合同"
    assert set(sale["sources"]) == {"doubao", "deepseek"}

    info = get_law_info("sale", seeded_db)
    assert info["zh_name"] == "买卖合同"
    assert "民法典" in info["doubao"]
    assert "民法典" in info["deepseek"]


def test_get_law_info_unknown_raises_not_found(seeded_db):
    _seed_a_few(seeded_db)
    with pytest.raises(NotFoundError):
        get_law_info("nonexistent_type", seeded_db)


def test_all_law_info(seeded_db):
    _seed_a_few(seeded_db)
    rows = all_law_info(seeded_db)
    assert len(rows) == 4  # 2 types × 2 sources
    assert {r["contract_type"] for r in rows} == {"sale", "loan"}


# --- law-refined v2 helpers ------------------------------------------------- #


def _load_prompt_seeder():
    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "seed_contract_prompts", scripts / "seed_contract_prompts.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path.pop(0)


def _load_rubric_seeder():
    scripts = REPO_ROOT / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location(
            "seed_contract_rubrics", scripts / "seed_contract_rubrics.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path.pop(0)


def test_v2_prompt_helper():
    m = _load_prompt_seeder()
    v1 = m._p("sale", "买卖合同起草提示词", "起草一份买卖合同。须包含：标的物。")
    citation = LAW_REFINED_CITATIONS["sale"]
    v2 = m._v2_prompt(v1, citation)
    assert v2["name"] == "draft_sale_v2"
    assert v2["prompt_type"] == "law-refined"
    assert v2["contract_type"] == "sale"
    assert v2["content"].startswith("【法律依据】依据《中华人民共和国民法典》")
    # baseline body preserved
    assert "起草一份买卖合同" in v2["content"]
    # baseline v1 unchanged
    assert v1["name"] == "draft_sale"
    assert v1["prompt_type"] == "baseline"


def test_v2_rubric_helper_cites_statutes():
    m = _load_rubric_seeder()
    v1 = m.RUBRICS[0]  # contract_sale_v1
    assert v1["name"] == "contract_sale_v1"
    v2 = m._v2_rubric(v1, LAW_REFINED_CITATIONS["sale"])
    assert v2["name"] == "contract_sale_v2"
    assert v2["context"] == "contract"
    # v1 criteria preserved + one legal_basis_citation added
    names = [c["name"] for c in v2["criteria"]]
    assert "legal_basis_citation" in names
    assert len(v2["criteria"]) == len(v1["criteria"]) + 1
    # the legal_basis criterion's guidance cites the 买卖合同 interpretation
    lb = next(c for c in v2["criteria"] if c["name"] == "legal_basis_citation")
    assert "法释〔2020〕17号" in lb["guidance"]
    # v1 untouched
    assert "legal_basis_citation" not in [c["name"] for c in v1["criteria"]]
