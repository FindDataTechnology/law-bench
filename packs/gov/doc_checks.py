"""政务公文的确定性质量判据（八条），供评测跑一次真测量。

这里**没有任何模型判断**：每条判据都是对公文元数据与正文的事实核对。这样做的理由
和整套平台一致——能核对的就别让模型打分，打了分也没法复核。

判据与 `scripts/seed_gov_rubric.py` 里登记的八条一一对应（名称必须逐字一致，否则
评测结果挂不到 rubric 上）。
"""

from __future__ import annotations

import re
from typing import Any, Optional

#: 文号有两种合法形态，缺一不可：
#:   ① 机关代字〔四位年份〕序号 —— 「财办会〔2026〕31号」
#:   ② 部门令编号 —— 「财政部令第101号」（部门规章以令发布，没有年份括号）
#: 只认①会把全部部门规章判成"无文号"，那是假阴性，和假阳性一样坏。
_DOC_NO = re.compile(
    r"(?:[〔\[（(]\s*\d{4}\s*[〕\]）)]\s*第?\s*\d+\s*号)"
    r"|(?:令\s*第\s*\d+\s*号)"
)
#: 日期：2026-09-09 / 2026年9月9日
_DATE = re.compile(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})")
#: 「附件：X」/「附件1：X」
_ATTACH = re.compile(r"附\s*件\s*\d*\s*[:：]\s*([^\n]{2,40})")
#: 「《X》」引用
_CITE = re.compile(r"《([^》]{2,40})》")

PLACEHOLDER_ISSUERS = {"", "其他", "未知", "-", "—", "无"}


def _norm(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", text or "")


def check_document_no(doc: dict) -> tuple[bool, str]:
    """文号规范：正文首段或元数据里出现规范文号。"""
    text = _norm(doc.get("text"))
    m = _DOC_NO.search(text)
    if m:
        found = m.group(0)
        return True, f"文号 {found}"
    return False, "未找到形如「机关代字〔年份〕序号」或「…令第N号」的文号"


def check_issuer(doc: dict) -> tuple[bool, str]:
    issuer = (doc.get("issuer") or "").strip()
    if issuer in PLACEHOLDER_ISSUERS:
        return False, f"发文机关缺失或为占位：{issuer!r}"
    if issuer not in _norm(doc.get("text")):
        # 元数据说了一个机关，正文里却没有它的名字：可能抓串页
        return False, f"发文机关 {issuer!r} 未出现在正文中"
    return True, f"机关 {issuer}"


def check_doc_date(doc: dict) -> tuple[bool, str]:
    m = _DATE.search(doc.get("date") or "") or _DATE.search(_norm(doc.get("text"))[:400])
    if not m:
        return False, "未找到成文日期"
    year, month, day = (int(x) for x in m.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False, f"日期不合法：{year}-{month}-{day}"
    return True, f"成文日期 {year}-{month:02d}-{day:02d}"


def check_title_in_lead(doc: dict) -> tuple[bool, str]:
    """标题的**核心部分**应出现在正文开头。

    标题常带主体称谓前缀（「中华人民共和国财政部令第101号--…」），而正文首段往往
    不带；直接逐字比会把全部部门规章判成抓串页。所以两侧都用归名后的核心名比对，
    并且只在核心名确实有内容时才判不通过。
    """
    from src.bench import keys

    raw_title = (doc.get("title") or "").strip()
    if not raw_title:
        return False, "无标题，无法核对"
    rules = keys.rules_for("gov")
    core = _norm(keys.fold(raw_title, rules)[0])
    lead = _norm(doc.get("text"))[:400]
    if core and core in lead:
        return True, "标题核心出现在正文开头"
    if core:
        # 再退一步：标题里「--」之后的部分（「财政部令第101号--政府采购信息发布管理办法」）
        tail = _norm(raw_title.split("--")[-1])
        if tail and tail in lead:
            return True, f"标题主体出现在正文开头（{tail[:16]}）"
    return False, "标题未出现在正文开头（可能抓串页）"


def check_substantive(doc: dict) -> tuple[bool, str]:
    """去掉标题、目录、机关、日期行后仍有实质正文。"""
    text = doc.get("text") or ""
    body = "\n".join(
        line for line in text.splitlines()
        if not re.search(r"^(目\s*录|第[一二三四五六七八九十]+章|发文机关|文号|成文日期|文种)", line.strip())
        and _norm(line) != _norm(doc.get("title"))
    )
    size = len(_norm(body))
    return (True, f"正文 {size} 字") if size >= 120 else (False, f"正文仅 {size} 字，疑为空壳")


def check_no_duplicate(doc: dict) -> tuple[bool, str]:
    seen = doc.get("seen_hashes") or {}
    h = doc.get("content_hash")
    if not h:
        return False, "无正文哈希，无法判重"
    return (True, "正文唯一") if seen.get(h, 0) <= 1 else (False, f"同哈希出现 {seen[h]} 次")


def check_citations(doc: dict) -> tuple[bool, str]:
    """引用可解析：出现「有关规定」这类无指向说法即不通过。"""
    text = doc.get("text") or ""
    vague = re.search(r"(有关规定|相关文件|等文件)", text)
    cited = _CITE.findall(text)
    if cited:
        return True, f"引用 {len(cited)} 处，如《{cited[0]}》"
    if vague:
        return False, "只写了「有关规定」这类不可解析的引用"
    return True, "无引用（不构成缺陷）"


def check_attachments(doc: dict) -> tuple[bool, str]:
    """声明了附件就要能在正文里**再出现一次**（第一次出现是声明本身）。

    「声明」不算定位：`附件：X` 里已经写了 X，若只查"X 是否在正文中"，任何声明都
    自动通过——这条判据就永远不报警。所以要求去掉声明行之后仍能找到 X 的标题。
    """
    text = doc.get("text") or ""
    declared = [m.strip() for m in _ATTACH.findall(text)]
    if not declared:
        return True, "未声明附件"
    body_without_decl = _norm(_ATTACH.sub("", text))
    missing = [name for name in declared if _norm(name) not in body_without_decl]
    return (True, f"附件 {len(declared)} 个可定位") if not missing else (False, f"附件不可定位：{missing[:2]}")


#: 顺序与 rubric 里的 ordinal 一致。
CHECKS: list[tuple[str, Any]] = [
    ("文号规范", check_document_no),
    ("发文机关明确", check_issuer),
    ("成文日期在册", check_doc_date),
    ("标题与首段一致", check_title_in_lead),
    ("正文有实质内容", check_substantive),
    ("无重复正文", check_no_duplicate),
    ("引用可解析", check_citations),
    ("附件与正文对应", check_attachments),
]
