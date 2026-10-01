"""Tests for the contract-context JSON API (``src/web/routes/contract_context.py``).

The endpoints under ``/api/contracts`` are thin routes over existing service
functions. File-backed reads (list, slots, tags, law refs) work with a plain
``app_client``; DB-backed reads (clause catalog, clause counts, rubric/prompt
pointers, law survey markdown, generate) seed minimal data into ``seeded_db``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.eval import manage as M
from src.clauses.store import upsert_clause


# --- seeding helpers ------------------------------------------------------- #


def _clause(
    *,
    category: str,
    section: str,
    body: str,
    tags: dict | None = None,
    slot_instructions: list | None = None,
    cid: int = 1,
) -> dict:
    return {
        "id": cid,
        "contract_type": "sale",
        "category": category,
        "section": section,
        "body": body,
        "slot_instructions": slot_instructions or [],
        "law_refs": [],
        "level": "national" if category == "base" else "local",
        "source_path": f"t/{category}.docx",
        "source_doc_title": "T",
        "body_hash": f"h-{category}-{section}",
        "tags": tags or {"source": category},
    }


def _seed_base(seeded_db) -> None:
    """One base clause covering 当事人 - enough for assembly to succeed."""
    upsert_clause(
        _clause(
            category="base",
            section="当事人",
            body="甲方：{{party_a}}\n乙方：{{party_b}}",
            slot_instructions=[
                {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True},
                {"name": "party_b", "label": "乙方", "description": "d", "example": "x", "required": True},
            ],
        ),
        db=seeded_db,
    )


def _seed_tagged(seeded_db, scenario: str = "生鲜乳购销", stance: str | None = None) -> None:
    tags = {"source": "tagged", "scenario": scenario}
    if stance:
        tags["stance"] = stance
    upsert_clause(
        _clause(
            category="tagged",
            section="合同标的",
            body="标的：{{subject}}",
            tags=tags,
            slot_instructions=[
                {"name": "subject", "label": "标的", "description": "d", "example": "x", "required": True},
            ],
            cid=2,
        ),
        db=seeded_db,
    )


def _seed_law_info(seeded_db) -> None:
    for source in ("doubao", "deepseek"):
        seeded_db.execute(
            "INSERT INTO law_info (contract_type, source, zh_name, content, created_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            ("sale", source, "买卖合同", f"# 买卖合同法律法规\n\n来源：{source}\n\n《中华人民共和国民法典》", "2026-01-01"),
        )
    seeded_db.commit()


# --- list ----------------------------------------------------------------- #


def test_list_types(app_client: TestClient):
    r = app_client.get("/api/contracts")
    assert r.status_code == 200
    types = r.json()
    # 43 母版类型 + 23 Cat B 类型 (generator-rules 导入) = 66
    assert len(types) == 66
    assert {"key": "sale", "zh": "买卖合同"} in types


# --- slots ---------------------------------------------------------------- #


def test_slots_manifest_covers_template(app_client: TestClient):
    r = app_client.get("/api/contracts/sale/slots")
    assert r.status_code == 200
    slots = r.json()
    # every entry has the source field and matches a template slot
    tmpl = app_client.get("/api/contracts/sale").json()["template"]["slots"]
    assert {s["name"] for s in slots} == set(tmpl)
    assert all("source" in s for s in slots)
    # sale's manifest covers all its slots -> all registry
    assert all(s["source"] == "registry" for s in slots)
    assert all(s["label"] for s in slots)


def test_slots_ontology_fills_missing(monkeypatch, app_client: TestClient):
    """A template slot absent from the manifest is resolved via the slot ontology."""
    import src.web.routes.contract_context as cc

    real = cc.get_slot_instructions("sale")
    stripped = [si for si in real if si["name"] != "party_a"]
    monkeypatch.setattr(cc, "get_slot_instructions", lambda _t: stripped)

    r = app_client.get("/api/contracts/sale/slots")
    assert r.status_code == 200
    by_name = {e["name"]: e for e in r.json()}
    assert by_name["party_a"]["source"] == "ontology"
    assert by_name["party_a"]["label"]  # non-empty guidance


def test_slots_uncovered_flagged(monkeypatch, app_client: TestClient):
    """A slot with no manifest entry and no ontology match is flagged uncovered."""
    import src.web.routes.contract_context as cc

    fake = {"type": "sale", "zh_name": "买卖合同", "body": "{{zzz_bogus}}", "slots": ["zzz_bogus"]}
    monkeypatch.setattr(cc, "get_template", lambda _t: fake)
    monkeypatch.setattr(cc, "get_slot_instructions", lambda _t: [])

    r = app_client.get("/api/contracts/sale/slots")
    assert r.status_code == 200
    e = r.json()[0]
    assert e["name"] == "zzz_bogus"
    assert e["source"] == "uncovered"


def test_slots_unknown_type_404(app_client: TestClient):
    assert app_client.get("/api/contracts/does_not_exist/slots").status_code == 404


# --- tags ----------------------------------------------------------------- #


def test_tags(app_client: TestClient):
    r = app_client.get("/api/contracts/sale/tags")
    assert r.status_code == 200
    vocab = r.json()
    assert vocab["stance"] == ["pro_a", "pro_b", "balanced"]
    assert "scenario" in vocab  # type-specific controlled dim


def test_tags_unknown_type_404(app_client: TestClient):
    assert app_client.get("/api/contracts/does_not_exist/tags").status_code == 404


# --- laws ----------------------------------------------------------------- #


def test_laws(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/api/contracts/sale/laws")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["refs"], list)
    assert body["refs"], "sale should have law refs from the bundled answers"
    assert body["survey_md"]["doubao"]  # markdown seeded
    assert body["survey_md"]["deepseek"]


def test_laws_unknown_type_404(app_client: TestClient):
    assert app_client.get("/api/contracts/does_not_exist/laws").status_code == 404


# --- bundle --------------------------------------------------------------- #


def test_bundle(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db)
    M.create_rubric(
        "contract_sale_v3", "contract", "sale v3",
        [{"name": "c1", "description": "d", "guidance": "g"}],
        db_path=seeded_db,
    )
    M.create_prompt("sale_draft", "sale", "draft", "content body", None, None, db_path=seeded_db)

    r = app_client.get("/api/contracts/sale")
    assert r.status_code == 200
    b = r.json()
    assert b["type"] == "sale"
    assert b["zh_name"] == "买卖合同"
    assert b["template"]["body"]
    assert b["template"]["slots"]
    assert b["slot_instructions"]
    assert all("source" in s for s in b["slot_instructions"])
    assert b["laws"]["refs"]
    assert b["tags"]["stance"] == ["pro_a", "pro_b", "balanced"]
    assert b["sections"][0] == "当事人"
    assert b["clauses"] == {"base": 1, "tagged": 1, "custom": 0}
    assert b["rubric"] == {"name": "contract_sale_v3"}
    assert [p["name"] for p in b["prompts"]] == ["sale_draft"]


def test_bundle_unknown_type_404(app_client: TestClient):
    assert app_client.get("/api/contracts/does_not_exist").status_code == 404


def test_bundle_latest_rubric_version(app_client: TestClient, seeded_db):
    """The bundle picks the highest v<N>, not the alphabetically-last."""
    _seed_base(seeded_db)
    M.create_rubric("contract_sale_v2", "contract", "v2", [], db_path=seeded_db)
    M.create_rubric("contract_sale_v10", "contract", "v10", [], db_path=seeded_db)
    M.create_rubric("contract_sale_v3", "contract", "v3", [], db_path=seeded_db)
    b = app_client.get("/api/contracts/sale").json()
    assert b["rubric"] == {"name": "contract_sale_v10"}


# --- clauses -------------------------------------------------------------- #


def test_clauses_default(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db)
    r = app_client.get("/api/contracts/sale/clauses")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["clauses"]) == 2
    c = body["clauses"][0]
    assert {k in c for k in ("id", "section", "source", "manual", "tags", "body", "slot_instructions", "law_refs")}


def test_clauses_filter_by_scenario(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, scenario="生鲜乳购销")
    r = app_client.get("/api/contracts/sale/clauses", params={"scenario": "生鲜乳购销"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["clauses"][0]["tags"]["scenario"] == "生鲜乳购销"


def test_clauses_filter_by_source(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db)
    r = app_client.get("/api/contracts/sale/clauses", params={"source": "base"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["clauses"][0]["source"] == "base"


def test_clauses_pagination(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db)
    r = app_client.get("/api/contracts/sale/clauses", params={"limit": 1, "offset": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["clauses"]) == 1
    assert body["limit"] == 1
    assert body["offset"] == 1


def test_clauses_limit_clamped(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    r = app_client.get("/api/contracts/sale/clauses", params={"limit": 9999})
    assert r.status_code == 200
    assert r.json()["limit"] == 200  # clamped to max


def test_clauses_unknown_type_404(app_client: TestClient):
    assert app_client.get("/api/contracts/does_not_exist/clauses").status_code == 404


# --- generate ------------------------------------------------------------- #


def test_generate_markdown(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate", json={"format": "markdown"})
    assert r.status_code == 200
    body = r.json()
    assert body["body_text"]
    assert body["slots"]
    assert body["docx_url"] is None
    assert body["pdf_url"] is None


def test_generate_docx_default(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["body_text"]  # always present
    assert body["docx_url"] == "/api/contracts/sale/files/sale.docx"
    assert body["pdf_url"] is None
    # the download URL serves the generated file
    d = app_client.get(body["docx_url"])
    assert d.status_code == 200
    assert d.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert len(d.content) > 0


def test_generate_with_tags(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    _seed_tagged(seeded_db, scenario="生鲜乳购销")
    r = app_client.post(
        "/api/contracts/sale/generate",
        json={"scenario": "生鲜乳购销", "format": "markdown"},
    )
    assert r.status_code == 200
    assert r.json()["body_text"]


def test_generate_unknown_type_404(app_client: TestClient):
    r = app_client.post("/api/contracts/does_not_exist/generate", json={})
    assert r.status_code == 404


def test_generate_invalid_format_422(app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    r = app_client.post("/api/contracts/sale/generate", json={"format": "xls"})
    assert r.status_code == 422  # pydantic Literal validation


def test_generate_coherence_failure_422(monkeypatch, app_client: TestClient, seeded_db):
    _seed_base(seeded_db)
    import src.web.routes.contract_context as cc
    from src.clauses.coherence import CoherenceError

    def _raise(*_a, **_kw):
        raise CoherenceError("missing canonical sections: ['价款及支付']")

    monkeypatch.setattr(cc, "generate_contract_assembled", _raise)
    r = app_client.post("/api/contracts/sale/generate", json={"format": "markdown"})
    assert r.status_code == 422
    assert "价款及支付" in r.json()["detail"]


# --- file download safety ------------------------------------------------- #


def test_download_rejects_traversal(app_client: TestClient):
    assert app_client.get("/api/contracts/sale/files/..%2f..%2fetc%2fpasswd").status_code == 404
    assert app_client.get("/api/contracts/sale/files/nonexistent.docx").status_code == 404


# --- schema --------------------------------------------------------------- #


def test_openapi_includes_all_paths(app_client: TestClient):
    paths = set(app_client.get("/openapi.json").json()["paths"].keys())
    expected = {
        "/api/contracts",
        "/api/contracts/{contract_type}",
        "/api/contracts/{contract_type}/slots",
        "/api/contracts/{contract_type}/laws",
        "/api/contracts/{contract_type}/tags",
        "/api/contracts/{contract_type}/clauses",
        "/api/contracts/{contract_type}/generate",
    }
    assert expected <= paths
