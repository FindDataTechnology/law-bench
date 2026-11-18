"""The concept layer (§1-5): type, key branch, text-table sampling, starter set.

Two things make this layer different from laws and clauses, and both are pinned
here: a concept is addressed by its *name alone* (it is the same concept in every
instrument that mentions it), and a concept is only trustworthy when it can be
traced to the article it rests on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import packs.legal  # noqa: F401 — registers fold rules + the category predicate
from packs.legal import entity_keys as legal_keys
from src.bench import extraction, keys, ontology_import

# scripts/ is not a package: import the publisher by path so the v2 schema and
# the test that guards it cannot drift.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from publish_legal_template_v2 import build_v2_schema  # noqa: E402


def test_v2_adds_the_concept_layer_and_nothing_else():
    v1 = {
        "entity_types": ["clause", "law"],
        "relationship_kinds": ["cites_law"],
        "concept_structures": {"clause": ["body"]},
        "tier_vocabulary": ["raw", "bronze", "silver", "gold"],
        "sensitivity_vocabulary": ["public", "internal", "confidential"],
        "corpus_declaration": {"source_types": []},
    }
    v2 = build_v2_schema(v1)
    assert v2["entity_types"] == ["clause", "law", "concept"]
    assert v2["relationship_kinds"] == ["cites_law", "defines"]
    assert v2["tier_vocabulary"] == v1["tier_vocabulary"]      # untouched
    assert v1["entity_types"] == ["clause", "law"]             # input not mutated


def test_concept_key_is_name_only():
    key, reason, meta = extraction.resolve_entity_key(
        "连带清偿责任", kind="concept", chunk={"title": "指导案例9号"}, domain_key="legal"
    )
    assert key == "连带清偿责任" and reason is None
    assert "law_key" not in meta          # a concept has no parent document


def test_concept_is_cross_instrument():
    """Same concept, two different source documents → one key."""
    a, _r, _m = extraction.resolve_entity_key(
        "违约责任", kind="concept", chunk={"title": "中华人民共和国合同法"}, domain_key="legal")
    b, _r2, _m2 = extraction.resolve_entity_key(
        "违约责任", kind="concept", chunk={"title": "中华人民共和国民法典"}, domain_key="legal")
    assert a == b == "违约责任"


def test_case_category_labels_are_not_concepts():
    """Measured: 715 keyword tags, top four are 民事/刑事/行政/执行."""
    for label in ("民事", "刑事", "行政", "执行", "国家赔偿"):
        key, reason, _meta = extraction.resolve_entity_key(
            label, kind="concept", chunk={}, domain_key="legal")
        assert key is None and reason == "not_concept"


def test_clause_branch_still_carries_its_parent():
    """The concept branch must not weaken the clause rule."""
    key, reason, meta = extraction.resolve_entity_key(
        "第十二条", kind="clause", chunk={"title": "中华人民共和国合同法"}, domain_key="legal")
    assert key == "合同法#第12条" and meta["clause_no"] == 12


def test_concept_mode_prompt_asks_for_concepts_and_grounding():
    schema = {"entity_types": ["clause", "law", "concept"],
              "relationship_kinds": ["cites_law", "defines"]}
    chunk = {"chunk_id": "9", "text": "股东应当依法履行清算义务", "title": "指导案例9号",
             "source_key": "guide_cases"}
    concept = extraction.build_prompt(schema=schema, chunks=[chunk], concept_mode=True,
                                     domain_key="legal")
    plain = extraction.build_prompt(schema=schema, chunks=[chunk], concept_mode=False)
    assert "法律概念" in concept
    # The criteria are the point of this prompt: without them the model proposed
    # case descriptions as concepts.
    assert "名词短语" in concept and "可跨案复用" in concept
    # Examples (positive *and* negative) come from the pack, so this also proves
    # the registration ran.
    assert "居间合同" in concept and "没收较大数额" in concept
    assert "法律概念" not in plain
    assert "defines" in concept and "concept" in concept


def test_starter_set_is_grounded_and_free_of_categories():
    path = Path("packs/legal/starters/concepts-v1.json")
    data = json.loads(path.read_text())
    units = data["units"]
    assert units, "the starter set must not be empty"
    concepts = [u for u in units if u["kind"] == "concept"]
    laws = [u for u in units if u["kind"] == "law"]
    assert concepts and laws, "the set must carry both concepts and the instruments they rest on"
    for unit in laws:
        # An instrument unit carries its full title and nothing invented.
        assert unit["attrs"].get("full_title"), unit["external_key"]
        assert unit["body"] == unit["attrs"]["full_title"]
    for unit in concepts:
        assert not legal_keys.is_case_category(unit["external_key"]), unit["external_key"]
        attrs = unit["attrs"]
        grounded = bool(attrs.get("statute_refs"))
        # "no statute, rests on case law" is allowed — but it must *say so*.
        declared_case = bool(attrs.get("source_case_no")) or attrs.get("grounding") == "case"
        # Either it cites an article, or it says outright that it rests on case
        # law — an empty both-ways entry is exactly what the spec forbids.
        assert grounded or declared_case, unit["external_key"]
    assert all(rel["kind"] == "defines" for rel in data["relationships"])
    # `defines` points at an instrument that is *in the same set* — a relation to
    # something nobody created is how a concept ends up dangling.
    law_keys = {u["external_key"] for u in laws}
    for rel in data["relationships"]:
        assert rel["to_key"] in law_keys, rel
        assert rel["from_key"] in {u["external_key"] for u in concepts}, rel


def test_starter_set_passes_the_import_planner(empty_db):
    """The set must be importable without a single error row (dry run only)."""
    from src.bench import templates, workspaces
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    conn = empty_db
    schema = build_v2_schema({
        "entity_types": ["clause", "law"], "relationship_kinds": ["cites_law"],
        "concept_structures": {}, "tier_vocabulary": ["raw", "bronze", "silver", "gold"],
        "sensitivity_vocabulary": ["public", "internal", "confidential"],
        "corpus_declaration": {"source_types": []},
    })
    templates.create_template(conn=conn, name="legal-v2", schema=schema, created_by="t")
    workspaces.instantiate_domain(
        conn, key="legal", name="法律域", template_name="legal-v2",
        template_version=None, created_by="t",
    )
    data = json.loads(Path("packs/legal/starters/concepts-v1.json").read_text())
    rows = ontology_import.plan(conn, domain_key="legal", payload={
        "units": data["units"], "relationships": [],
    })
    errors = [r for r in rows if r["action"] == "error"]
    assert not errors, [e["reason"] for e in errors][:3]
    assert all(r["action"] == "create" for r in rows)


def test_text_table_sampling_reads_without_vectors(monkeypatch):
    """The guide cases are read in place: extraction only needs text.

    Re-embedding 293 cases into the statute collection would mix judgment
    reasoning into a vector space people query for statutes.
    """
    import psycopg

    calls = {}

    class _Cur:
        def __init__(self, rows, one=False):
            self._rows, self._one = rows, one

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return (self._rows or [None])[0] if self._one else (self._rows or [None])[0]

    class _Conn:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            calls.setdefault("sql", []).append(sql)
            if "information_schema" in sql:
                return _Cur([("case_no",), ("title",), ("gist",)])
            return _Cur([(1, "居间合同要点", "指导案例1号"),
                         (2, "和解协议要点", "指导案例2号")])

    monkeypatch.setattr(psycopg, "connect", _Conn)
    from src.bench import libraries as libs

    lib = {"id": 1, "library_key": "case-library",
           "backend": "pgvector-external", "location": {"dsn_env": "X"}
           if False else {}}
    monkeypatch.setattr(libs, "resolve_location", lambda lbl: {"dsn_env": "postgresql://x"})
    monkeypatch.setattr(libs, "list_sources", lambda conn, library_id: [
        {"source_key": "guide_cases", "uri": "guide_cases",
         "ingest_rule": {"columns": {"text": "gist", "title": "title", "id": "case_no"}}}
    ])
    rows = extraction._sample_text_tables(None, lib={"id": 1, "library_key": "case-library"},
                                          allowed={"guide_cases"}, limit=2)
    assert [r["chunk_id"] for r in rows] == ["1", "2"]
    assert rows[0]["text"] == "居间合同要点" and rows[0]["title"] == "指导案例1号"
    assert rows[0]["law_id"] is None       # a case is not an instrument


def test_missing_column_is_an_error_not_an_empty_page(monkeypatch):
    import psycopg

    class _Cur:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return None

    class _Conn:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            return _Cur([("case_no",), ("title",)])   # no `gist`

    monkeypatch.setattr(psycopg, "connect", _Conn)
    from src.bench import libraries as libs

    monkeypatch.setattr(libs, "resolve_location", lambda lbl: {"dsn_env": "postgresql://x"})
    monkeypatch.setattr(libs, "list_sources", lambda conn, library_id: [
        {"source_key": "guide_cases", "uri": "guide_cases",
         "ingest_rule": {"columns": {"text": "gist", "title": "title", "id": "case_no"}}}
    ])
    with pytest.raises(ValueError, match="no column"):
        extraction._sample_text_tables(None, lib={"id": 1, "library_key": "case-library"},
                                       allowed={"guide_cases"}, limit=2)


def test_concept_shape_and_fact_markers_reject_real_bad_candidates():
    """The two candidates the live run actually produced, pinned.

    2026-11-09: with positives only and no shape rules, extraction proposed
    「没收较大数额涉案财产的行政处罚决定」 and 「行政处罚违反法定程序」 as concepts —
    both are statements about one case.
    """
    for bad in ("没收较大数额涉案财产的行政处罚决定", "行政处罚违反法定程序",
                "罚款1395228元", "民事"):
        key, reason, _meta = extraction.resolve_entity_key(
            bad, kind="concept", chunk={}, domain_key="legal")
        assert key is None and reason == "not_concept", bad


def test_real_concepts_survive_the_gate():
    """「较大数额财产」 is a legal standard — banning the word 数额 would kill it."""
    for good in ("听证程序", "较大数额财产", "违约责任", "清算义务", "连带清偿责任"):
        key, reason, meta = extraction.resolve_entity_key(
            good, kind="concept", chunk={}, domain_key="legal")
        assert key == good and reason is None, good


def test_sentence_shaped_names_fail_on_shape_alone():
    """Generic rule: a concept is a noun phrase; length/punctuation catch the rest."""
    assert keys.concept_shape_ok("听证程序") is True
    assert keys.concept_shape_ok("这是一个非常长的描述性句子用来验证长度上限确实生效了") is False
    assert keys.concept_shape_ok("程序违法，应当撤销") is False


def test_defines_direction_is_concept_to_document():
    """Direction is domain policy, registered by the pack."""
    rule = keys.relationship_rule_for("legal")
    assert rule is not None
    assert rule("defines", "concept", "law") is None
    assert rule("defines", "concept", "clause") is None
    assert "must start at a concept" in rule("defines", "law", "concept")
    assert "must land on a document" in rule("defines", "concept", "concept")
    # Other relationship kinds are not constrained by this rule.
    assert rule("cites_law", "clause", "law") is None


def test_import_planner_refuses_a_reversed_defines(empty_db):
    """公司法 defines 清算义务 reads backwards — refuse it at planning time."""
    from src.bench import ontology_import, templates, workspaces
    from src.eval.store import ensure_schema

    ensure_schema(db_path=empty_db)
    schema = {
        "entity_types": ["clause", "law", "concept"],
        "concept_structures": {},
        "relationship_kinds": ["defines"],
        "tier_vocabulary": ["raw", "bronze", "silver", "gold"],
        "sensitivity_vocabulary": ["public", "internal", "confidential"],
        "corpus_declaration": {"source_types": []},
    }
    templates.create_template(conn=empty_db, name="tpl", schema=schema, created_by="t")
    workspaces.instantiate_domain(conn=empty_db, key="legal", name="法律域",
                                  template_name="tpl", template_version=None, created_by="t")
    payload = {
        "units": [
            {"kind": "concept", "external_key": "清算义务", "body": "清算义务"},
            {"kind": "law", "external_key": "公司法", "body": "中华人民共和国公司法"},
        ],
        "relationships": [
            {"kind": "defines", "from_key": "公司法", "to_key": "清算义务"},   # reversed
            {"kind": "defines", "from_key": "清算义务", "to_key": "公司法"},   # correct
        ],
    }
    rows = ontology_import.plan(conn=empty_db, domain_key="legal", payload=payload)
    verdicts = {r["external_key"]: r["action"] for r in rows if r["section"] == "relationships"}
    assert verdicts["公司法->清算义务"] == "error"
    assert verdicts["清算义务->公司法"] == "create"


def test_instrument_types_and_party_roles_are_not_concepts():
    """文种名与角色名回答的不是"这是什么原理"。

    实测（2026-11-10）抽取把「地方政府规章」「地方性法规」「工业盐准运证」
    「请托人」当概念提了出来——短名词短语，形状闸拦不住，只有词表能拦。
    """
    from packs.legal.entity_keys import concept_reject

    for name in ("地方政府规章", "地方性法规", "条例", "工业盐准运证", "调解书",
                 "请托人", "被告人", "第三人"):
        assert concept_reject(name), f"{name} 不该被当作概念"

    for name in ("死刑缓期二年执行", "违约责任", "主观恶性", "和解协议",
                 "国家工作人员", "限制减刑"):
        assert not concept_reject(name), f"{name} 是可复用的法律概念"
