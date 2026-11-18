"""政务公文判据：每条都要能判「不过」，否则尺子只是装饰。

生产实跑 13 份财政部令全部通过——那不能证明尺子有用，只能证明样本干净。
所以这里给每条判据配一个**坏样本**，钉住它确实会报不通过：

- 文号：认两种合法形态（〔年份〕序号 / 部门令第N号），两者都不认才判不过；
- 机关：占位值（其他/未知）与"元数据说了一个机关但正文里没有"都判不过；
- 日期：缺失或不合法判不过；
- 标题：主体称谓前缀不算差异，但标题核心不在正文开头判不过（抓串页）；
- 正文：去掉标题/目录/机关行后不足阈值判不过（空壳）；
- 去重：同哈希出现两次判不过；
- 引用：只写「有关规定」这类不可解析说法判不过；
- 附件：声明了却定位不到判不过。
"""

from __future__ import annotations

from packs.gov.doc_checks import (
    check_attachments,
    check_citations,
    check_doc_date,
    check_document_no,
    check_issuer,
    check_no_duplicate,
    check_substantive,
    check_title_in_lead,
)


def _doc(**over):
    base = {
        "title": "财政部令第101号--政府采购信息发布管理办法",
        "text": (
            "财政部令第101号\n政府采购信息发布管理办法\n"
            "第一条 为了规范政府采购信息发布行为，根据《中华人民共和国政府采购法》，制定本办法。\n"
            "第二条 政府采购信息应当及时、准确、完整发布。\n"
            "第三条 财政部门依法对政府采购信息发布活动实施监督管理。\n"
        ),
        "issuer": "财政部",
        "date": "2019-11-27",
        "content_hash": "h1",
        "seen_hashes": {"h1": 1},
    }
    base.update(over)
    return base


# ── 文号 ────────────────────────────────────────────────────────────────────


def test_a_departmental_order_number_is_a_valid_document_number():
    """「财政部令第101号」是合法文号：部门规章以令发布，没有年份括号。"""
    ok, note = check_document_no(_doc())
    assert ok, note


def test_a_bracket_style_document_number_is_also_valid():
    ok, note = check_document_no(_doc(text="财办会〔2026〕31号\n关于…的通知\n" + "正文" * 80))
    assert ok, note


def test_text_without_any_document_number_fails():
    ok, note = check_document_no(_doc(text="关于某事的通知\n" + "正文" * 80))
    assert not ok and "文号" in note


# ── 机关 / 日期 ─────────────────────────────────────────────────────────────


def test_a_placeholder_issuer_fails():
    assert not check_issuer(_doc(issuer="其他"))[0]
    assert not check_issuer(_doc(issuer=""))[0]


def test_an_issuer_absent_from_the_body_fails():
    """元数据写了一个正文里根本没有的机关——这正是抓串页的样子。"""
    ok, note = check_issuer(_doc(issuer="国家能源局"))
    assert not ok and "未出现在正文" in note


def test_a_missing_date_fails():
    ok, note = check_doc_date(_doc(date="", text="财政部令第101号\n正文" * 40))
    assert not ok and "日期" in note


# ── 标题 ────────────────────────────────────────────────────────────────────


def test_the_state_prefix_is_not_a_difference():
    """标题带主体称谓前缀、正文不带，不算抓串页。"""
    ok, note = check_title_in_lead(_doc())
    assert ok, note


def test_a_lead_that_is_another_document_fails():
    ok, note = check_title_in_lead(_doc(text="中华人民共和国政府采购法\n第一条 为了…\n" + "正文" * 60))
    assert not ok and "未出现在正文开头" in note


# ── 正文 / 去重 / 引用 / 附件 ──────────────────────────────────────────────


def test_a_shell_with_only_a_title_fails():
    ok, note = check_substantive(_doc(text="政府采购信息发布管理办法\n目　录\n第一章 总则\n"))
    assert not ok and "空壳" in note


def test_a_repeated_body_fails():
    ok, note = check_no_duplicate(_doc(seen_hashes={"h1": 3}))
    assert not ok and "3 次" in note


def test_a_vague_reference_without_a_title_fails():
    ok, note = check_citations(_doc(text="依据有关规定执行。\n" + "正文" * 60))
    assert not ok and "不可解析" in note


def test_a_named_reference_passes():
    ok, _note = check_citations(_doc(text="依据《中华人民共和国政府采购法》执行。\n" + "正文" * 60))
    assert ok


def test_a_declared_but_missing_attachment_fails():
    ok, note = check_attachments(_doc(text="附件：政府采购信息发布格式\n" + "正文" * 60))
    assert not ok and "不可定位" in note


def test_a_declared_and_present_attachment_passes():
    body = "附件：政府采购信息发布格式\n政府采购信息发布格式\n" + "正文" * 60
    assert check_attachments(_doc(text=body))[0]
