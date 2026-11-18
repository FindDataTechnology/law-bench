"""政务线的键规则：同一份公文只该有一个键。

政务公开语料的标题常以发文主体的国名前缀开头（「中华人民共和国财政部令第110号
--……」）。前缀是主体的称谓，不是标题的身份；不去掉，同一份公文在目录、本体和
抽取结果里会各成一个键。

本文件只钉两件事，都是「少了就会静默出错」的：

- 导入 ``packs.gov`` 就在内核里注册了 ``gov`` 域的规则（不导入则什么都不折，安全默认）；
- 规则只作用于 ``gov``，法律线的规则不会被政务包顺手改掉。
"""

from __future__ import annotations

import packs.gov  # noqa: F401  — registers the gov rules on import
from packs.legal import entity_keys as legal_keys  # noqa: F401
from src.bench import keys


def test_gov_rules_are_registered_on_import():
    assert [r.name for r in keys.rules_for("gov")] == ["drop-prc", "drop-china"]


def test_state_prefix_is_folded_but_the_instrument_identity_is_kept():
    rules = keys.rules_for("gov")
    folded, applied = keys.fold("中华人民共和国财政部令第110号--政府采购框架协议采购方式管理暂行办法", rules)
    assert folded.startswith("财政部令第110号")
    assert applied == ["drop-prc"]


def test_the_two_lines_fold_independently():
    """A gov rule must not leak into the legal domain (and vice versa)."""
    assert keys.rules_for("gov") != keys.rules_for("legal")
    assert [r.name for r in keys.rules_for("legal")] == [
        r.name for r in legal_keys.PREFIX_RULES
    ]


def test_an_unknown_domain_folds_nothing():
    assert keys.rules_for("no-such-line") == ()
    assert keys.fold("中华人民共和国某办法", keys.rules_for("no-such-line")) == (
        "中华人民共和国某办法", [])
