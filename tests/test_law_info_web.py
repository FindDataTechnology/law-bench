"""HTML tests for the law-info web routes (``/law-info``, ``/law-info/{type}``,
``/law-references``) and the nav links.

Uses the ``app_client`` fixture (TestClient against the throwaway DB). A few
``law_info`` rows are seeded directly so the tests stay fast - the full 82-row
seeding is exercised by ``tests/test_law_info.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.eval import harbor_seed


def _seed_law_info(conn):
    harbor_seed.create_schema(conn)
    conn.execute("TRUNCATE law_info RESTART IDENTITY")
    for key, zh in [("sale", "买卖合同"), ("loan", "借款合同")]:
        for source in ("doubao", "deepseek"):
            conn.execute(
                "INSERT INTO law_info (contract_type, source, zh_name, content, created_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    key,
                    source,
                    zh,
                    f"# {zh}法律法规\n\n> 来源：{source}\n\n核心法律：《中华人民共和国民法典》"
                    f"及《最高人民法院关于审理{zh}纠纷案件适用法律问题的解释》。\n\n- 列表项一\n- 列表项二\n",
                    "2026-01-01",
                ),
            )
    conn.commit()


def test_law_info_lists_types(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/law-info")
    assert r.status_code == 200
    assert "买卖合同" in r.text
    assert "借款合同" in r.text
    # both type links present
    assert "/law-info/sale" in r.text
    assert "/law-info/loan" in r.text


def test_law_info_detail_side_by_side(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/law-info/sale")
    assert r.status_code == 200
    # both source labels present
    assert "Doubao" in r.text or "豆包" in r.text
    assert "DeepSeek" in r.text
    # markdown rendered to HTML (heading + list), not raw markdown text
    assert "<h1>" in r.text
    assert "<li>" in r.text
    # the statute name appears
    assert "民法典" in r.text


def test_law_info_detail_unknown_type_404(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/law-info/nonexistent_type")
    assert r.status_code == 404
    # not-found state rendered (no unhandled exception)
    assert "nonexistent_type" in r.text


def test_law_references_lists_and_filters(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/law-references")
    assert r.status_code == 200
    # the 民法典 law appears (deduplicated, once)
    assert "中华人民共和国民法典" in r.text
    # the judicial interpretation appears too
    assert "解释" in r.text

    # source filter: only laws appearing in doubao answers
    r2 = app_client.get("/law-references?source=doubao")
    assert r2.status_code == 200
    assert "中华人民共和国民法典" in r2.text

    # type filter: only laws appearing in the sale answer
    r3 = app_client.get("/law-references?contract_type=sale")
    assert r3.status_code == 200
    assert "中华人民共和国民法典" in r3.text


def test_corpus_tools_are_reachable_from_the_knowledge_area(app_client: TestClient, seeded_db):
    """§5: the corpus pages left the top bar; their entries live in the owning area.

    Reachability is the contract — a reader must still be able to get to 法规库 /
    法规索引 without knowing the URL, and the legacy routes themselves keep working.
    """
    _seed_law_info(seeded_db)
    # The shared seed carries no domain, so this test creates one to render the
    # area page; the point is reachability, not seeding.
    from src.bench import templates, workspaces
    tmpl = templates.create_template(
        conn=seeded_db,
        name="tpl-knowledge-tools",
        schema={
            "entity_types": ["clause"],
            "concept_structures": {"clause": ["id"]},
            "relationship_kinds": ["cites_law"],
            "tier_vocabulary": ["raw", "bronze", "silver", "gold"],
            "sensitivity_vocabulary": ["public", "internal", "confidential"],
            "corpus_declaration": {"source_types": ["uploaded"]},
        },
        created_by="tester",
    )
    workspaces.instantiate_domain(
        seeded_db,
        key="tools-key",
        name="工具测试域",
        template_name=tmpl["name"],
        template_version=tmpl["version"],
        created_by="tester",
    )
    area = app_client.get("/d/tools-key/knowledge")
    assert area.status_code == 200
    assert "/law-info" in area.text
    assert "/law-references" in area.text
    # the pages themselves still render (a 302 is deliberately NOT applied yet)
    for path in ("/law-info", "/law-references"):
        assert app_client.get(path).status_code == 200
