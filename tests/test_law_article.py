"""Tests for article-level citation parsing and resolution (integrate-law-semantic-search).

Numeral behavior is snapshotted against the ported reference
(law-rag-pipeline law-query-api.js, scripts/dev/_ref_law-query-api.js).
"""

from __future__ import annotations

import json

import pytest

from src.law_catalog import article as art
from src.law_catalog.resolve import LawCatalogIndex

# --- numeral conversion (reference snapshots) --------------------------------


def test_cn_to_int_snapshots():
    assert art.cn_to_int("1085") == 1085
    assert art.cn_to_int("五百九十五") == 595
    assert art.cn_to_int("一千零八十五") == 1085
    assert art.cn_to_int("一百零五") == 105
    assert art.cn_to_int("一百五") == 105  # colloquial short form, JS parity
    assert art.cn_to_int("十") == 10
    assert art.cn_to_int("零") == 0
    assert art.cn_to_int("二〇二五") is None  # unsupported digit circle


def test_int_to_cn_roundtrip():
    for n in (1, 9, 10, 15, 105, 595, 1085, 1260, 9999):
        assert art.cn_to_int(art.int_to_cn(n)) == n
    assert art.int_to_cn(10) == "十"
    assert art.int_to_cn(1085) == "一千零八十五"


# --- citation parsing ---------------------------------------------------------


def test_parse_arabic_and_chinese():
    a = art.parse_citations("根据《民法典》第1085条的规定")
    assert len(a) == 1
    assert (a[0].law_hint, a[0].article) == ("民法典", 1085)

    b = art.parse_citations("依照民法典第一千零八十五条处理")
    assert (b[0].law_hint, b[0].article) == ("民法典", 1085)


def test_parse_sub_parts_preserved():
    a = art.parse_citations("依《中华人民共和国民法典》第595条第2款履行")
    assert a[0].article == 595
    assert a[0].sub_parts == ["第2款"]
    assert a[0].law_hint == "中华人民共和国民法典"


def test_parse_strips_leading_verbs_and_connectors():
    a = art.parse_citations("查询合同法第五百九十五条")
    assert a[0].law_hint == "合同法"
    b = art.parse_citations("依据的关于保险法第十六条")
    assert b[0].law_hint == "保险法"
    c = art.parse_citations("根据《民法典》第1085条")
    assert c[0].law_hint == "民法典"


def test_parse_dedups_same_citation():
    text = "民法典第595条…民法典第595条…民法典第596条"
    cites = art.parse_citations(text)
    assert [(c.law_hint, c.article) for c in cites] == [
        ("民法典", 595), ("民法典", 596)]


def test_parse_ignores_non_citations():
    assert art.parse_citations("本合同自双方签字之日起生效") == []
    assert art.parse_citations("第条没有数字") == []


# --- article location ---------------------------------------------------------

_LAW_TEXT = (
    "第一条 为了规范…\n"
    "第五百九十五条 买卖合同是出卖人转移标的物的所有权于买受人，买受人支付价款的合同。\n"
    "第五百九十六条 出卖人应当按照约定…\n"
    "第一千零八十五条 离婚后，子女由一方直接抚养的…\n"
)


def test_find_article_arabic_anchor():
    text = art.find_article(_LAW_TEXT, 595)
    assert text.startswith("第五百九十五条")
    assert "第五百九十六条" not in text


def test_find_article_chinese_anchor_and_bounds():
    assert art.find_article(_LAW_TEXT, 1085).startswith("第一千零八十五条")
    assert art.find_article(_LAW_TEXT, 9999) is None  # beyond the statute


# --- resolution outcomes (fake law-api) ---------------------------------------


class FakeIndex:
    def __init__(self, mapping):
        self.mapping = mapping

    def resolve(self, name, db=None):
        hit = self.mapping.get(name)
        if hit is None:
            return {"cited_name": name, "law_id": None, "title": None,
                    "status": None, "resolved_via": "unresolved"}
        return {"cited_name": name, "law_id": hit[0], "title": hit[1],
                "status": hit[2], "resolved_via": "exact"}


def _fake_law_api(monkeypatch, laws):
    """Patch src.law_api.client.get_law with a dict-backed fake; records calls."""
    calls = []

    def get_law(law_id, client=None):
        calls.append(law_id)
        return laws.get(law_id)

    from src.law_api import client as law_api

    monkeypatch.setattr(law_api, "get_law", get_law)
    return calls


def test_resolve_article_outcomes(monkeypatch):
    index = FakeIndex({"民法典": (1, "中华人民共和国民法典", "有效")})
    calls = _fake_law_api(monkeypatch, laws={
        "1": {"law_id": "1", "title": "中华人民共和国民法典", "status": "有效",
              "full_text": _LAW_TEXT},
    })

    ok = art.resolve_article(art.parse_citations("民法典第1085条")[0], index)
    assert ok["outcome"] == "resolved"
    assert ok["law_id"] == "1"  # opaque string, not int
    assert ok["article_text"].startswith("第一千零八十五条")

    oor = art.resolve_article(art.parse_citations("民法典第9999条")[0], index)
    assert oor["outcome"] == "out_of_range"

    un = art.resolve_article(art.parse_citations("加缪法第1条")[0], index)
    assert un["outcome"] == "unresolved_name"
    assert un["law_id"] is None

    # fetch failure is distinct from out_of_range
    fail = art.resolve_article(art.parse_citations("民法典第595条")[0], index)
    _fake_law_api(monkeypatch, laws={})  # gateway returns nothing now
    fail = art.resolve_article(art.parse_citations("民法典第595条")[0], index)
    assert fail["outcome"] == "fetch_failed"
    assert "1" in calls


# --- corpus pass over the seeded DB -------------------------------------------


@pytest.fixture
def catalog(seeded_db):
    from src.law_catalog import store

    store.import_catalog([
        {"id": 1, "title": "中华人民共和国民法典", "category": "core_law",
         "publish": "2020-05-28", "expiry": "2021-01-01", "status": "有效",
         "src_db": "lawv2", "content_status": "ok"},
        {"id": 2, "title": "中华人民共和国旅游法", "category": "core_law",
         "publish": "2013-04-25", "expiry": "2013-10-01", "status": "有效",
         "src_db": "law", "content_status": "ok"},
    ], db=seeded_db)
    return seeded_db


def _clause(db, cid, body):
    db.execute(
        "INSERT INTO clauses (id, contract_type, tags, section, body, law_refs, "
        "body_hash, created_at, updated_at) OVERRIDING SYSTEM VALUE "
        "VALUES (%s, 'sale', %s, '法律依据', %s, '[]'::jsonb, %s, '2026-01-01', '2026-01-01')",
        (cid, json.dumps({"source": "base"}), body, f"h{cid}"),
    )
    db.commit()


def test_corpus_pass_resolves_and_prunes(catalog, monkeypatch):
    _fake_law_api(monkeypatch, laws={
        "1": {"law_id": "1", "title": "中华人民共和国民法典", "status": "有效",
              "full_text": _LAW_TEXT},
        "2": {"law_id": "2", "title": "中华人民共和国旅游法", "status": "有效",
              "full_text": "第十条 旅游者有权…\n"},
    })
    _clause(catalog, 701, "依据《民法典》第595条与民法典第1085条约定。")
    _clause(catalog, 702, "按《旅游法》第9999条执行。")

    stats = art.resolve_all_article_citations(db=catalog)
    assert stats["outcomes"]["resolved"] == 2
    assert stats["outcomes"]["out_of_range"] == 1
    assert stats["distinct_laws_fetched"] == 2

    rows = catalog.execute(
        "SELECT * FROM law_catalog.clause_article_refs ORDER BY clause_id, article_ordinal"
    ).fetchall()
    assert len(rows) == 3
    r595 = [r for r in rows if r["article_ordinal"] == 595][0]
    assert r595["law_id"] == 1 and r595["outcome"] == "resolved"
    assert r595["article_text"].startswith("第五百九十五条")
    assert r595["law_status"] == "有效"
    r9999 = [r for r in rows if r["article_ordinal"] == 9999][0]
    assert r9999["law_id"] == 2 and r9999["outcome"] == "out_of_range"

    # clause edited: citations change, stale rows pruned, clauses.law_refs untouched
    before_refs = catalog.execute(
        "SELECT law_refs FROM clauses WHERE id = 701").fetchone()["law_refs"]
    catalog.execute(
        "UPDATE clauses SET body = '只引民法典第596条。', body_hash = 'h701b' WHERE id = 701")
    catalog.commit()
    stats = art.resolve_all_article_citations(db=catalog)
    assert stats["outcomes"]["resolved"] == 1
    rows = catalog.execute(
        "SELECT clause_id, article_ordinal FROM law_catalog.clause_article_refs ORDER BY clause_id"
    ).fetchall()
    assert [(r["clause_id"], r["article_ordinal"]) for r in rows] == [(701, 596), (702, 9999)]
    after_refs = catalog.execute(
        "SELECT law_refs FROM clauses WHERE id = 701").fetchone()["law_refs"]
    assert before_refs == after_refs  # derived column untouched by the pass


def test_parse_skips_contract_self_references():
    text = "甲方如违反本合同第十条第6款应承担违约责任。乙方有权按本协议第七条处理。但《民法典》第595条仍适用。"
    cites = art.parse_citations(text)
    assert [(c.law_hint, c.article) for c in cites] == [("民法典", 595)]


def test_find_article_tolerates_page_footer_dash():
    # extracted texts run "—７９—\n—第六百七十三条" (footer dash on the anchor line)
    text = (
        "第六百七十二条　借款人应当按照约定提供资料。\n"
        "—７９—\n"
        "—第六百七十三条　借款人未按照约定的借款用途使用借款的，贷款人可以停止发放借款。\n"
        "第六百七十四条　借款人应当按照约定支付利息。\n"
    )
    hit = art.find_article(text, 673)
    assert hit is not None and hit.startswith("第六百七十三条")
    assert art.find_article(text, 672).startswith("第六百七十二条")


def test_find_article_tolerates_chapter_heading_prefix():
    # extraction drops the blank line after a chapter heading: the chapter's
    # first article shares the heading's line
    text = (
        "第一章 总则\n第一条 为了规范建筑垃圾处置。\n"
        "第二章 一般处置要求 第十条 居民装饰装修房屋产生的建筑垃圾应当单独堆放。\n"
        "第十一条 装修垃圾由责任人清运。\n"
    )
    hit = art.find_article(text, 10)
    assert hit is not None and hit.startswith("第十条")
    assert art.find_article(text, 1).startswith("第一条")
    # a mid-sentence reference after a chapter heading must NOT match
    sneaky = "第二章 处置 本办法第十二条另有规定的从其规定。\n"
    assert art.find_article(sneaky, 12) is None
