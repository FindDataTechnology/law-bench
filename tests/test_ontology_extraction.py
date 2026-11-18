"""Candidate extraction (§§1-4): the gates, not the model.

Nothing here calls a model: `complete_fn` is injected. What is pinned is exactly
what a hallucinating model would try to get past — a paraphrased quote, an
out-of-vocabulary kind, a relationship pointing at nothing — plus the two
operational facts an operator needs: re-running is idempotent, and a cap stops
the run loudly.
"""

from __future__ import annotations

import json

import pytest

import packs.legal  # noqa: F401  — importing the pack registers its key rules,
                     # exactly as the web app does; without it nothing folds.
from src.bench import authoring, extraction, libraries, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

SCHEMA = {
    "entity_types": ["clause", "law"],
    "concept_structures": {"clause": ["id"]},
    "relationship_kinds": ["cites_law"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}

CHUNK_TEXT = "第一条 为了规范合同的订立，制定本法。第二条 合同应当采用书面形式。"


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="legal", name="法律域", template_name="tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def _fake_qdrant(chunks):
    """Return a _post replacement that scrolls the given chunks once."""
    calls = {"n": 0}

    def post(url, path, body, timeout=30.0):
        calls["n"] += 1
        points = []
        for c in (chunks if calls["n"] == 1 else []):
            payload = {"chunk_text": c["text"], "category": "法律"}
            # Only carry what the chunk declares: defaulting `law_id` here would
            # silently give every block a parent document.
            for field in ("title", "law_id", "chunk_no"):
                if c.get(field) is not None:
                    payload[field] = c[field]
            points.append({"id": c["chunk_id"], "payload": payload})
        return {"result": {"points": points, "next_page_offset": None}}

    return post, calls


def _library(conn):
    libraries.create_library(conn, library_key="law-library", name="法规大库", created_by="t",
                             backend="qdrant", embedding_model="Qwen/Qwen3-Embedding-0.6B",
                             dims=1024,
                             location={"url_env": "TEST_QDRANT", "collection": "law_chunks_v2"})
    libraries.add_source(conn, library_key="law-library", source_key="statutes",
                         uri="x", created_by="t", ingest_rule={"match": {"category": "法律"}})
    dom = conn.execute("SELECT id FROM domains WHERE key='legal'").fetchone()
    libraries.subscribe(conn, domain_id=dom["id"], library_key="law-library", created_by="t")
    conn.commit()
    return dom


def _run(conn, monkeypatch, answer, *, chunks=None, **kw):
    _library(conn)
    chunks = chunks or [{"chunk_id": "c1", "text": CHUNK_TEXT, "title": "某法"}]
    post, calls = _fake_qdrant(chunks)
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    return extraction.run(
        conn, domain_key="legal",
        complete_fn=lambda prompt: answer if isinstance(answer, str) else json.dumps(answer),
        **kw,
    )


def test_good_candidates_land_as_pending_proposals(conn, monkeypatch):
    # The name has to be the document this block belongs to — that is the gate
    # added by fix-ontology-extraction-quality, not a loosened test.
    answer = {"entities": [
        {"kind": "law", "name": "中华人民共和国合同法", "chunk_id": "c1",
         "quote": "为了规范合同的订立"}], "relationships": []}
    before = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    report = _run(conn, monkeypatch, answer,
                  chunks=[{"chunk_id": "c1", "text": CHUNK_TEXT,
                           "title": "中华人民共和国合同法", "law_id": 1, "chunk_no": 0}])
    after = conn.execute("SELECT COUNT(*) AS n FROM knowledge_units").fetchone()["n"]
    assert report["submitted"] == 1 and report["skipped"]["bad_quote"] == 0
    assert after == before, "extraction must never write the ontology"
    rows = conn.execute("SELECT source, evidence, impact FROM domain_proposals").fetchall()
    assert len(rows) == 1
    assert rows[0]["source"].startswith("extract:")
    evidence = rows[0]["evidence"]
    assert evidence["chunk_id"] == "c1" and evidence["batch"]
    assert "原文：" in rows[0]["impact"]


def test_paraphrased_quote_is_dropped(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "合同法", "chunk_id": "c1", "quote": "为了管制合同的签署"}],
        "relationships": []}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0
    assert report["skipped"]["bad_quote"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM domain_proposals").fetchone()["n"] == 0


def test_out_of_vocabulary_kind_is_dropped(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "penalty", "name": "罚款", "chunk_id": "c1", "quote": "合同应当采用书面形式"}],
        "relationships": []}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0 and report["skipped"]["bad_kind"] == 1


def test_relationship_needs_a_closed_endpoint(conn, monkeypatch):
    answer = {"entities": [],
              "relationships": [
                  {"kind": "cites_law", "from_name": "合同法", "to_name": "民法典",
                   "chunk_id": "c1", "quote": "合同应当采用书面形式"}]}
    report = _run(conn, monkeypatch, answer)
    assert report["submitted"] == 0 and report["skipped"]["bad_endpoint"] == 1


def test_same_batch_entity_closes_the_endpoint(conn, monkeypatch):
    """`A→B` must be proposable when B is nominated in the same batch."""
    answer = {"entities": [
        {"kind": "clause", "name": "第一条", "chunk_id": "c1", "quote": "规范合同的订立"},
        {"kind": "clause", "name": "第二条", "chunk_id": "c1", "quote": "合同应当采用书面形式"}],
        "relationships": [
        {"kind": "cites_law", "from_name": "第一条", "to_name": "第二条",
         "chunk_id": "c1", "quote": "合同应当采用书面形式"}]}
    report = _run(conn, monkeypatch, answer, max_per_chunk=8,
                  chunks=[{"chunk_id": "c1", "text": CHUNK_TEXT,
                           "title": "中华人民共和国合同法", "law_id": 1, "chunk_no": 0}])
    assert report["submitted"] == 3
    assert report["skipped"]["bad_endpoint"] == 0


def test_rerun_is_idempotent(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "中华人民共和国合同法", "chunk_id": "c1",
         "quote": "规范合同的订立"}], "relationships": []}
    first = _run(conn, monkeypatch, answer,
                 chunks=[{"chunk_id": "c1", "text": CHUNK_TEXT,
                          "title": "中华人民共和国合同法", "law_id": 1, "chunk_no": 0}])
    assert first["submitted"] == 1
    # The library already exists from _run; only reset the scroll stub so the
    # second run samples the same chunk again.
    post, _ = _fake_qdrant([{"chunk_id": "c1", "text": CHUNK_TEXT,
                             "title": "中华人民共和国合同法", "law_id": 1, "chunk_no": 0}])
    monkeypatch.setattr(extraction, "_post", post)
    second = extraction.run(conn, domain_key="legal",
                            complete_fn=lambda p: json.dumps(answer))
    assert second["submitted"] == 0
    assert second["duplicate"] == 1


def test_cap_stops_the_run_and_says_so(conn, monkeypatch):
    chunks = [{"chunk_id": f"c{i}", "text": CHUNK_TEXT, "title": f"法{i}"} for i in range(5)]
    answer = {"entities": [
        {"kind": "law", "name": "甲法", "chunk_id": "c0", "quote": "规范合同的订立"},
        {"kind": "law", "name": "乙法", "chunk_id": "c0", "quote": "合同应当采用书面形式"}],
        "relationships": []}
    _library(conn)
    # each chunk yields the same two candidates but with distinct chunk ids
    def post(url, path, body, timeout=30.0):
        if getattr(post, "done", False):
            return {"result": {"points": []}}
        post.done = True
        return {"result": {"points": [
            {"id": c["chunk_id"], "payload": {"chunk_text": c["text"], "title": c["title"],
                                              "category": "法律"}} for c in chunks]}}
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    report = extraction.run(conn, domain_key="legal", max_chunks=5, max_total=3,
                            complete_fn=lambda p: json.dumps(answer))
    assert report["stopped"] == "cap"
    assert report["produced"] <= 3


def test_no_corpus_is_an_error_not_an_empty_report(conn):
    with pytest.raises(extraction.ExtractionError, match="subscribes to no corpus"):
        extraction.sample_chunks(conn, domain_path="legal")


def test_scope_is_enforced_for_explicit_sources(conn):
    _library(conn)
    with pytest.raises(extraction.ExtractionError, match="not in this domain's scope"):
        extraction.sample_chunks(conn, domain_path="legal", sources=["judicial"])


def test_prompt_carries_the_vocabularies_and_version():
    prompt = extraction.build_prompt(schema=SCHEMA, chunks=[{"chunk_id": "c1", "text": "x",
                                                             "source_key": "statutes", "title": "t"}])
    assert "clause" in prompt and "cites_law" in prompt
    assert extraction.PROMPT_VERSION in prompt


@pytest.mark.parametrize("name,expected", [
    ("中华人民共和国 民法典", "中华人民共和国-民法典"),
    ("民法典（总则）", "民法典-总则"),
    ("  空格  很多  ", "空格-很多"),
])
def test_entity_keys_are_stable(name, expected):
    assert extraction.normalize_entity_key(name) == expected


def test_parse_survives_fences_and_prose():
    raw = '好的，结果如下：\n```json\n{"entities":[{"kind":"law","name":"民法典","quote":"q"}],"relationships":[]}\n```\n以上。'
    parsed = extraction.parse_candidates(raw)
    assert len(parsed["entities"]) == 1 and parsed["bad_rows"] == 0


def test_parse_counts_bad_rows_without_failing():
    raw = json.dumps({"entities": [{"kind": "law", "name": "民法典", "quote": "q"},
                                   {"kind": "law"}], "relationships": []})
    parsed = extraction.parse_candidates(raw)
    assert len(parsed["entities"]) == 1 and parsed["bad_rows"] == 1


def test_sampling_spreads_across_documents():
    """Scroll is ordered by point id, and points are written document by
    document: a naive page of N chunks can be 1–2 laws (measured in production:
    20 chunks from 2 law_ids). `_spread` takes at most 2 per document, round
    robin, so a page covers many documents."""
    chunks = []
    for law in range(1, 6):                     # 5 documents
        for no in range(5):                     # 5 chunks each, consecutive ids
            chunks.append({"chunk_id": f"{law}-{no}", "law_id": law, "text": "t"})
    picked = extraction._spread(chunks, 8)
    assert len(picked) == 8
    assert len({c["law_id"] for c in picked}) == 5      # every document represented
    # Never more than two per document on the first pass.
    from collections import Counter
    assert max(Counter(c["law_id"] for c in picked).values()) <= 2


def test_spread_returns_everything_when_the_page_is_large_enough():
    chunks = [{"chunk_id": f"{law}-0", "law_id": law, "text": "t"} for law in range(3)]
    assert len(extraction._spread(chunks, 10)) == 3


def test_spread_tolerates_a_document_rich_window():
    """If one document dominates the window, fill the page from it rather than
    returning a short page."""
    chunks = [{"chunk_id": f"1-{i}", "law_id": 1, "text": "t"} for i in range(10)]
    picked = extraction._spread(chunks, 4)
    assert len(picked) == 4


def test_complete_sends_an_explicit_token_budget(monkeypatch):
    """Reasoning models with no budget spend it all on reasoning and answer with
    `finish_reason=length` / `content=None` — which looks like a timeout."""
    seen = {}

    class _Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, **kw):
        seen.update(kw)
        return _Resp()

    monkeypatch.setenv("OPENAI_API_BASE", "https://x/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("EVAL_MODEL", "openai/m")
    monkeypatch.setattr(extraction, "httpx", type("h", (), {"post": staticmethod(fake_post)}))
    extraction.complete("prompt")
    assert seen["json"]["max_tokens"] >= 1000
    assert seen["timeout"] >= 60


def _chunk(title, text=CHUNK_TEXT, cid="c1"):
    return {"chunk_id": cid, "text": text, "title": title, "law_id": 1, "chunk_no": 0}


def _run_on(conn, monkeypatch, answer, *, chunk):
    _library(conn)
    post, _calls = _fake_qdrant([chunk])
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)
    return extraction.run(conn, domain_key="legal", max_chunks=1, max_total=10,
                          complete_fn=lambda p: json.dumps(answer))


def test_clause_candidate_gets_a_parent_qualified_key(conn, monkeypatch):
    answer = {"entities": [{"kind": "clause", "name": "第十二条", "chunk_id": "c1",
                            "quote": "合同应当采用书面形式"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer, chunk=_chunk("中华人民共和国宪法（2018年修正文本）"))
    assert report["submitted"] == 1
    row = conn.execute("SELECT external_key, evidence FROM domain_proposals").fetchone()
    assert row["external_key"] == "宪法#第12条"
    assert row["evidence"]["law_key"] == "宪法" and row["evidence"]["clause_no"] == 12


def test_structural_name_is_not_accepted_as_a_clause(conn, monkeypatch):
    answer = {"entities": [{"kind": "clause", "name": "序　言", "chunk_id": "c1",
                            "quote": "合同应当采用书面形式"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer, chunk=_chunk("中华人民共和国宪法"))
    assert report["submitted"] == 0
    assert report["skipped"]["not_clause"] == 1


def test_missing_parent_is_reported(conn, monkeypatch):
    """A block with neither title nor law_id cannot host a clause."""
    answer = {"entities": [{"kind": "clause", "name": "第十二条", "chunk_id": "c1",
                            "quote": "合同应当采用书面形式"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer,
                     chunk={"chunk_id": "c1", "text": CHUNK_TEXT, "title": None})
    assert report["submitted"] == 0
    assert report["skipped"]["missing_parent"] == 1


def test_a_country_name_is_not_a_law(conn, monkeypatch):
    answer = {"entities": [{"kind": "law", "name": "中华人民共和国", "chunk_id": "c1",
                            "quote": "规范合同的订立"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer,
                     chunk=_chunk("中华人民共和国宪法修正案（2018年）"))
    assert report["submitted"] == 0
    assert report["skipped"]["type_mismatch"] == 1


def test_the_real_document_name_passes(conn, monkeypatch):
    answer = {"entities": [{"kind": "law", "name": "中华人民共和国宪法", "chunk_id": "c1",
                            "quote": "规范合同的订立"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer,
                     chunk=_chunk("中华人民共和国宪法（2018年修正文本）"))
    assert report["submitted"] == 1
    row = conn.execute("SELECT external_key FROM domain_proposals").fetchone()
    assert row["external_key"] == "宪法"          # canonical key


def test_two_spellings_of_one_entity_yield_one_proposal(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "宪法", "chunk_id": "c1", "quote": "规范合同的订立"},
        {"kind": "law", "name": "中华人民共和国宪法", "chunk_id": "c1",
         "quote": "合同应当采用书面形式"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer, chunk=_chunk("中华人民共和国宪法"))
    assert report["submitted"] == 1
    assert report["skipped"]["normalised"] == 1


def test_usable_rate_and_low_yield_flag(conn, monkeypatch):
    answer = {"entities": [
        {"kind": "law", "name": "中华人民共和国", "chunk_id": "c1", "quote": "规范合同的订立"},
        {"kind": "law", "name": "中华人民共和国宪法", "chunk_id": "c1",
         "quote": "合同应当采用书面形式"}], "relationships": []}
    report = _run_on(conn, monkeypatch, answer, chunk=_chunk("中华人民共和国宪法"))
    assert report["produced"] == 2 and report["submitted"] == 1
    assert report["usable_rate"] == 0.5
    assert report["low_yield"] is False        # threshold is 0.5, not strictly greater


def test_endpoint_closure_sees_units_past_the_picker_cap(conn, monkeypatch):
    """A relationship to an existing clause must resolve even past 1000 units.

    Measured 2026-11-10 in production: the legal domain held 1,923 clause units
    and the first 1000 contained no 民法典 clause, so grounding proposals were
    refused as bad_endpoint purely because the endpoint set was capped.
    """
    from src.bench import authoring

    _library(conn)
    # 1,001 placeholder clauses whose keys sort *before* 民法典, so any capped
    # list is guaranteed not to contain the target below.
    authoring.authoring_create_units(
        conn, domain_key="legal", operator="t",
        units=[{"kind": "clause", "external_key": f"甲法#第{i}条", "body": "占位"}
               for i in range(1, 1002)],
    )
    authoring.authoring_create_unit(
        conn, domain_key="legal", kind="clause", external_key="民法典#第585条",
        body="第五百八十五条 违约金", operator="t",
    )
    # `clause` is in this schema's vocabulary; the target below exists in the
    # ontology but sits past the 1000-row picker cap.
    answer = {"entities": [
        {"kind": "clause", "name": "第二条", "chunk_id": "c1",
         "quote": "合同应当采用书面形式"}],
        "relationships": []}
    post, _calls = _fake_qdrant([{"chunk_id": "c1", "text": CHUNK_TEXT, "title": "某法"}])
    monkeypatch.setenv("TEST_QDRANT", "http://qdrant.test:6333")
    monkeypatch.setattr(extraction, "_post", post)

    answer["relationships"] = [
        {"kind": "cites_law", "from_name": "第二条", "to_name": "民法典#第585条",
         "to_kind": "clause",
         "chunk_id": "c1", "quote": "合同应当采用书面形式"}]
    report = extraction.run(
        conn, domain_key="legal",
        complete_fn=lambda prompt: json.dumps(answer),
        max_per_chunk=8,
    )
    assert report["skipped"]["bad_endpoint"] == 0, json.dumps(report, ensure_ascii=False)


def test_report_carries_the_out_of_vocabulary_bucket(conn, monkeypatch):
    """报告里必须有 `kind_not_in_vocabulary` 这个桶——**哪怕它结构上恒为 0**。

    提交处的写法是 `report["skipped"][exc.reason] += 1`，所以预检每多一个理由词、
    这里就多一次 KeyError 风险，而 KeyError 会打断整批（几百行）。这一侧提交前已
    用同一张模板词表预筛（`bad_kind`），只有直连提交方能把词表外的 kind 送进箱，
    因此这一桶在本路径上不可达——正常一轮就该是 0。
    """
    answer = {"entities": [
        {"kind": "law", "name": "中华人民共和国合同法", "chunk_id": "c1",
         "quote": "为了规范合同的订立"}], "relationships": []}
    report = _run(conn, monkeypatch, answer,
                  chunks=[{"chunk_id": "c1", "text": CHUNK_TEXT,
                           "title": "中华人民共和国合同法", "law_id": 1, "chunk_no": 0}])
    assert "kind_not_in_vocabulary" in report["skipped"]
    assert report["skipped"]["kind_not_in_vocabulary"] == 0
