"""政务线的评测尺子：可机器核对的公文质量判据。

要钉住的是"尺子是事实而不是印象分"，以及"建了尺子不等于尺子生效"：

- 八条判据必须全部是可用事实核对的（文号/机关/日期/逐字/哈希/引用/附件），
  不留"表达清晰"这类无法核对的口径；
- 尺子挂在该域上，且 `effective_rubrics` 能看见它（挂错域等于没建）；
- 重复运行幂等（判据不重复堆积）；
- 只看 `standards > 0` 不能说明它跑过——`last_run` 仍应是 None，直到真正评测一次。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.bench import domain_rubrics, templates, workspaces
from src.bench.promotion import SENSITIVITY_LEVELS
from src.bench.tiers import TIERS
from src.eval.store import ensure_schema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import seed_gov_rubric  # noqa: E402

SCHEMA = {
    "entity_types": ["document", "agency", "policy"],
    "concept_structures": {},
    "relationship_kinds": ["issued_by"],
    "tier_vocabulary": list(TIERS),
    "sensitivity_vocabulary": list(SENSITIVITY_LEVELS),
    "corpus_declaration": {"source_types": []},
}


@pytest.fixture()
def conn(empty_db):  # noqa: F811 - provided by tests/conftest.py
    ensure_schema(db_path=empty_db)
    # rubrics/criteria 来自遗留 seed，不在 ensure_schema 里
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS rubrics (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, name TEXT NOT NULL, context TEXT NOT NULL, source TEXT NOT NULL, "
        "source_path TEXT, description TEXT, created_at TEXT NOT NULL, domain_id BIGINT)"
    )
    empty_db.execute(
        "CREATE TABLE IF NOT EXISTS criteria (id BIGINT GENERATED ALWAYS AS IDENTITY "
        "PRIMARY KEY, rubric_id BIGINT NOT NULL REFERENCES rubrics(id) ON DELETE CASCADE, "
        "name TEXT NOT NULL, description TEXT, guidance TEXT, "
        "ordinal INTEGER NOT NULL DEFAULT 0)"
    )
    empty_db.commit()
    from src.eval import store as eval_store
    eval_store._ensured_dbs.clear()
    ensure_schema(db_path=empty_db)
    templates.create_template(conn=empty_db, name="gov-tpl", schema=dict(SCHEMA), created_by="t")
    workspaces.instantiate_domain(
        conn=empty_db, key="gov", name="政务公开", template_name="gov-tpl",
        template_version=None, created_by="t",
    )
    yield empty_db
    from src.eval.db import close_shared_conn
    close_shared_conn()


def test_every_criterion_is_a_checkable_fact():
    """判据必须是可核对的事实，不能是"表达清晰"这类印象分。"""
    assert len(seed_gov_rubric.CRITERIA) == 8
    names = [c[0] for c in seed_gov_rubric.CRITERIA]
    assert "文号规范" in names and "无重复正文" in names and "引用可解析" in names
    for _name, _desc, guide in seed_gov_rubric.CRITERIA:
        assert guide.strip(), "每条都要写清判定指引，否则复核各凭感觉"
        assert any(k in guide for k in ("通过", "不通过")), "指引要给出通过与否的判据"


def test_the_rubric_lands_on_the_domain_and_is_visible(conn):
    out = seed_gov_rubric.seed(conn, domain_key="gov")
    assert out["criteria"] == 8
    assert out["visible"] == ["gov-document-quality"]
    visible = domain_rubrics.effective_rubrics(conn, domain_path="gov")
    assert visible[0]["origin"] == "own"


def test_seeding_twice_does_not_duplicate_criteria(conn):
    seed_gov_rubric.seed(conn, domain_key="gov")
    seed_gov_rubric.seed(conn, domain_key="gov")
    n = conn.execute("SELECT COUNT(*) AS n FROM criteria").fetchone()["n"]
    assert n == 8, "重复运行只能刷新判据，不能堆积"
    assert conn.execute("SELECT COUNT(*) AS n FROM rubrics").fetchone()["n"] == 1


def test_an_empty_domain_is_still_a_gap(conn):
    """尺子存在但还没跑过评测：standards>0，last_run 仍为 None。

    这条提醒"建了尺子"不等于"尺子生效"——缺口消失不该由一次 seed 造成。
    """
    from src.bench import estate

    before = estate.matrix(conn, domains=workspaces.list_domains(conn))[0]
    assert "eval" in before["gaps"]
    seed_gov_rubric.seed(conn, domain_key="gov")
    after = estate.matrix(conn, domains=workspaces.list_domains(conn))[0]
    assert after["eval"]["standards"] == 1
    assert after["eval"]["last_run"] is None
    assert "eval" not in after["gaps"]
