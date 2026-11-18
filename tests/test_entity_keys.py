"""The key scheme (§1-2): slugs, clause addressing, explicit folding.

The asymmetry that shapes these tests: under-merging is noisy but recoverable,
over-merging silently destroys a distinction — and the pair that must never
collapse is 「…宪法」 vs 「…宪法修正案」.
"""

from __future__ import annotations

import pytest

from packs.legal import entity_keys as legal_keys
from src.bench import keys


@pytest.mark.parametrize("text,expected", [
    ("中华人民共和国 宪法", "中华人民共和国-宪法"),
    ("民法典（总则）", "民法典-总则"),
    ("  空格  很多  ", "空格-很多"),
    ("", "unnamed"),
])
def test_slug_is_stable_and_separator_free(text, expected):
    assert keys.slug(text) == expected
    assert keys.slug(text) == keys.slug(text)      # deterministic


def test_slug_folds_full_width_and_brackets():
    assert keys.slug("序　言") == "序-言"
    assert keys.slug("《民法典》") == "民法典"


@pytest.mark.parametrize("text,expected", [
    ("第十二条", 12),
    ("第十二条 合同的订立", 12),
    ("第一百二十三条", 123),
    ("第 3 条", 3),
    ("第二百零五条", 205),
])
def test_clause_numbers_parse(text, expected):
    assert keys.clause_no(text) == expected


@pytest.mark.parametrize("text", ["序　言", "序言", "目录", "第二章 合同的订立",
                                  "第三节 履行", "附则", "总则", "前言"])
def test_structure_is_not_a_clause(text):
    """「第二章」 must never become clause 2, and a preface is not an article."""
    assert keys.clause_no(text) is None


def test_clause_key_needs_a_parent():
    assert keys.clause_key("宪法", 12) == "宪法#第12条"
    with pytest.raises(ValueError, match="parent"):
        keys.clause_key("", 12)


def test_same_article_in_two_documents_stays_two_keys():
    """`第十二条` alone matches nearly every instrument — the parent is the key."""
    assert keys.clause_key("宪法", 12) != keys.clause_key("民法典", 12)


def test_fold_reports_which_rules_fired():
    folded, applied = keys.fold("中华人民共和国宪法", legal_keys.RULES)
    assert folded == "宪法"
    assert applied == ["drop-prc"]


def test_country_prefix_folds_but_amendment_does_not():
    """The load-bearing pair: same document vs a different document."""
    assert legal_keys.canonical_name("中华人民共和国宪法")[0] == "宪法"
    assert legal_keys.canonical_name("宪法")[0] == "宪法"
    assert legal_keys.canonical_name("中华人民共和国宪法修正案")[0] == "宪法修正案"
    assert legal_keys.canonical_name("中华人民共和国宪法修正案")[0] != "宪法"


def test_trailing_qualifier_is_stripped():
    assert keys.strip_trailing_qualifier("中华人民共和国宪法（2018年修正文本）") == "中华人民共和国宪法"
    assert keys.strip_trailing_qualifier("劳动合同法(2012修正)") == "劳动合同法"


def test_distinct_document_markers_are_explicit():
    for name in ("宪法修正案", "劳动合同法实施条例", "某规定实施细则", "某司法解释", "某决定"):
        assert legal_keys.is_distinct_document(name) is True
    for name in ("宪法", "劳动合同法", "民法典"):
        assert legal_keys.is_distinct_document(name) is False
