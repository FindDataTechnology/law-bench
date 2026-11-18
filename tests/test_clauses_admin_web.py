"""Tests for the clause-admin web routes (create/edit/delete + search)."""

from __future__ import annotations

from src.clauses.store import list_clauses, upsert_clause


def _seed_base(seeded_db) -> int:
    return upsert_clause(
        {
            "contract_type": "sale", "category": "base", "section": "当事人",
            "body": "甲方：{{party_a}}", "slot_instructions": [
                {"name": "party_a", "label": "甲方", "description": "d", "example": "x", "required": True}],
            "law_refs": [], "level": "national", "source_path": "t/base.docx",
            "source_doc_title": "T", "body_hash": "b1",
        },
        db=seeded_db,
    )


def test_new_form_renders(app_client):
    r = app_client.get("/clauses/sale/new")
    assert r.status_code == 200
    assert "新建条款" in r.text


def test_new_form_unknown_type_404(app_client):
    assert app_client.get("/clauses/does_not_exist/new").status_code == 404


def test_create_custom_clause_via_post(app_client, seeded_db):
    r = app_client.post(
        "/clauses/sale/new",
        data={"section": "附则", "body": "网页创建条款 {{n}}", "category": "custom"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/clauses/sale")
    rows = list_clauses("sale", category="custom", db=seeded_db)
    assert any("网页创建条款" in c["body"] for c in rows)
    created = [c for c in rows if "网页创建条款" in c["body"]][0]
    assert created["manual"] is True
    assert {s["name"] for s in created["slot_instructions"]} == {"n"}


def test_edit_form_renders(app_client, seeded_db):
    cid = _seed_base(seeded_db)
    r = app_client.get(f"/clauses/sale/clauses/{cid}")
    assert r.status_code == 200
    assert "编辑条款" in r.text
    assert "甲方：{{party_a}}" in r.text  # body pre-filled


def test_edit_form_unknown_clause_404(app_client):
    assert app_client.get("/clauses/sale/clauses/999999").status_code == 404


def test_update_clause_via_post(app_client, seeded_db):
    cid = _seed_base(seeded_db)
    r = app_client.post(
        f"/clauses/sale/clauses/{cid}",
        data={"section": "违约责任", "body": "违约金{{penalty}} 依据《民法典》", "category": "tagged", "scenario": "农产品买卖"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    rows = list_clauses("sale", db=seeded_db)
    c = [x for x in rows if x["id"] == cid][0]
    assert c["section"] == "违约责任"
    assert c["category"] == "tagged"
    assert c["tags"]["scenario"] == "农产品买卖"
    assert c["manual"] is True
    assert {s["name"] for s in c["slot_instructions"]} == {"penalty"}
    assert any(l["name"] == "民法典" for l in c["law_refs"])


def test_delete_clause_via_post(app_client, seeded_db):
    cid = _seed_base(seeded_db)
    r = app_client.post(f"/clauses/sale/clauses/{cid}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert all(x["id"] != cid for x in list_clauses("sale", db=seeded_db))


def test_delete_unknown_clause_404(app_client):
    assert app_client.post("/clauses/sale/clauses/999999/delete").status_code == 404


def test_detail_search_filters_by_body(app_client, seeded_db):
    _seed_base(seeded_db)
    r = app_client.get("/clauses/sale", params={"q": "甲方"})
    assert r.status_code == 200
    assert "当事人" in r.text  # the seeded base clause matches
    r2 = app_client.get("/clauses/sale", params={"q": "不存在的文本xyz"})
    assert r2.status_code == 200
    assert "暂无条款" in r2.text or "当事人" not in r2.text


def test_list_search_returns_results(app_client, seeded_db):
    _seed_base(seeded_db)
    r = app_client.get("/clauses", params={"q": "甲方"})
    assert r.status_code == 200
    assert "搜索结果" in r.text


def test_new_form_has_tag_dropdowns(app_client):
    r = app_client.get("/clauses/sale/new")
    assert r.status_code == 200
    assert 'name="stance"' in r.text
    assert 'name="strength"' in r.text


def test_create_with_tags_via_post(app_client, seeded_db):
    r = app_client.post(
        "/clauses/sale/new",
        data={"section": "违约责任", "body": "偏甲 {{a}}", "category": "custom",
              "stance": "pro_a", "strength": "strong"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    rows = list_clauses("sale", category="custom", tags={"stance": "pro_a"}, db=seeded_db)
    assert len(rows) == 1
    assert rows[0]["tags"] == {"stance": "pro_a", "strength": "strong", "source": "custom"}


def test_update_with_tags_via_post(app_client, seeded_db):
    cid = _seed_base(seeded_db)
    r = app_client.post(
        f"/clauses/sale/clauses/{cid}",
        data={"section": "当事人", "body": "甲方 {{party_a}}", "category": "base",
              "stance": "pro_b"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    c = [x for x in list_clauses("sale", db=seeded_db) if x["id"] == cid][0]
    assert c["tags"] == {"stance": "pro_b", "source": "base"}


def test_detail_filter_by_stance(app_client, seeded_db):
    from src.clauses.store import create_clause

    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏甲违约金 {{a}}", "tags": {"stance": "pro_a"}}, db=seeded_db)
    create_clause({"contract_type": "sale", "category": "custom", "section": "违约责任",
                   "body": "偏乙违约金 {{b}}", "tags": {"stance": "pro_b"}}, db=seeded_db)
    r = app_client.get("/clauses/sale", params={"stance": "pro_a"})
    assert r.status_code == 200
    assert "偏甲" in r.text
    assert "偏乙" not in r.text
