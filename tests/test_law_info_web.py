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


def test_nav_links_present_on_other_pages(app_client: TestClient, seeded_db):
    _seed_law_info(seeded_db)
    r = app_client.get("/prompts")
    assert r.status_code == 200
    # both nav links rendered in zh (default locale)
    assert "/law-info" in r.text
    assert "/law-references" in r.text
