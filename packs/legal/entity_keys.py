"""Legal pack's key rules: how this corpus's entity names fold together.

The kernel (``src.bench.keys``) owns the *mechanisms* — slugging, clause
addressing, ordered rule application. This module owns the **vocabulary**: which
prefixes and suffixes this domain actually uses, and — just as important — which
ones must **not** be folded away.

The exclusion list is the load-bearing part. "中华人民共和国宪法" and
"中华人民共和国宪法修正案" differ only by a suffix, and merging them would silently
destroy the distinction between an instrument and the amendment that rewrote it.
Under-merging costs a reviewer one glance; over-merging costs a wrong citation in
a published snapshot. So the rules are a short, explicit, testable list rather
than a similarity threshold.
"""

from __future__ import annotations

import re

from src.bench.keys import FoldRule, clause_no, register_rules

#: Prefixes that name the issuing state rather than the instrument. Dropping them
#: merges "中华人民共和国宪法" with "宪法" — the same document, two spellings.
PREFIX_RULES: tuple[FoldRule, ...] = (
    FoldRule("drop-prc", "prefix", "中华人民共和国"),
    FoldRule("drop-china", "prefix", "中国"),
)

#: Suffixes that name a *different* document. Listed so the intent is explicit
#: and so a future rule addition has to consciously step over them: a name
#: ending in one of these is never folded to the bare stem.
DOCUMENT_SUFFIXES: tuple[str, ...] = (
    "修正案",
    "实施条例",
    "实施细则",
    "司法解释",
    "决定",
)

#: The ordered rule list applied by :func:`canonical_name`.
RULES: tuple[FoldRule, ...] = PREFIX_RULES

#: Trading labels that look like concepts but are case *categories*. Measured
#: 2026-11-09 on the guide cases: 715 keyword tags, 603 occurring once, and the
#: top four are 民事/刑事/行政/执行 — case types, not legal concepts. Importing
#: them would fill the ontology with filing metadata.
CASE_CATEGORY_LABELS: frozenset[str] = frozenset({
    "民事", "刑事", "行政", "执行", "国家赔偿", "民事诉讼", "行政诉讼",
    "刑事诉讼", "民事诉讼", "执行实施", "执行监督", "执行复议",
    "刑事附带民事", "民事公益诉讼", "行政公益诉讼", "司法协助",
    "再审", "审判监督", "特别程序", "督促程序", "破产", "非诉",
})

#: Suffixes/stems that mark a concept-shaped name (used only to *prefer* the
#: concept branch when a chunk is concept-rich; never to force a kind).
CONCEPT_LIKE_SUFFIXES: tuple[str, ...] = ("责任", "义务", "权利", "合同", "行为", "原则", "制度")


#: Party roles and deictic references: they tie a phrase to one case.
FACTUAL_MARKERS: tuple[str, ...] = (
    "被告", "原告", "上诉人", "被上诉人", "申请人", "被申请人",
    "本院", "本案", "本决定", "本判决", "该决定", "涉案", "上述", "下列",
)

#: Predicate verbs: a concept is a noun phrase, so a name carrying one of these
#: is a *sentence* about a case ("行政处罚违反法定程序"), not an abstraction.
#: Note this deliberately does not include 数额: 「较大数额财产」 is a real legal
#: standard, and banning the word would reject the concept along with the noise.
STATEMENT_MARKERS: tuple[str, ...] = (
    "违反", "构成", "属于", "应当", "不得", "予以", "系于", "即应", "判处",
)

#: A concrete amount ("1395228.6元", "500万元") pins a phrase to one case.
_AMOUNT = re.compile(r"\d[\d,.]*\s*(?:万?亿元?|万?元)")

#: Suffixes that mark a document/decision type rather than a concept. A concept
#: may contain these words; it may not *end* with them.
DOCUMENT_LIKE_SUFFIXES: tuple[str, ...] = (
    "决定", "判决", "裁定", "通知", "批复", "答复",
    # 文种名：这些是**文书的种类**，不是法律概念（实测抽出来过「地方政府规章」
    # 「地方性法规」——它们回答"这是什么文书"，不回答"这是什么原理"）。
    "规章", "法规", "条例", "办法", "规定", "解释", "法典", "法",
    # 证照/文书名同样是文种，不是概念。
    "准运证", "许可证", "调解书", "判决书", "裁定书", "决定书",
)

#: 当事人角色：一个概念要能跨案复用，角色名只指向某个案子里的某个人。
PARTY_ROLE_MARKERS: tuple[str, ...] = (
    "请托人", "当事人", "被告人", "被害人", "原告", "被告", "第三人",
    "申请人", "被申请人", "犯罪嫌疑人",
)


def is_case_category(name: str) -> bool:
    """True when ``name`` is a case category rather than a legal concept."""
    return (name or "").strip() in CASE_CATEGORY_LABELS


def concept_reject(name: str) -> bool:
    """The pack's full "not a concept" verdict.

    Three ways a string fails: it is a case category (民事/执行), it is a
    statement about one case (contains 数额/被告/本案…), or it ends in a document
    type (…决定/…判决). The concept layer's whole value is that it holds reusable
    abstractions, so admitting any of these silently degrades it.
    """
    value = (name or "").strip()
    if not value:
        return True
    if value in CASE_CATEGORY_LABELS:
        return True
    if any(marker in value for marker in FACTUAL_MARKERS):
        return True
    if any(marker in value for marker in STATEMENT_MARKERS):
        return True
    if any(marker in value for marker in PARTY_ROLE_MARKERS):
        return True
    if _AMOUNT.search(value):
        return True
    if any(value.endswith(suffix) for suffix in DOCUMENT_LIKE_SUFFIXES):
        return True
    return False


#: 一条可引用的法条出处：「《文档名》第N条（可带款）」。起始概念集里就是这么写的，
#: 它是**人工读过原文后留下的溯源**，所以能直接变成 defines 的端点。
_CITATION = re.compile(r"^《(?P<doc>[^》]+)》\s*(?P<rest>.+)$")


def parse_citation(text: str) -> tuple[str, int] | None:
    """把「《X》第N条…」解析成 (归名后的文档名, 条款号)；解不出就返回 None。

    条款号复用内核的 ``clause_no``（认中文数字、不认章节名）；文档名复用
    ``canonical_name``，所以两种写法会落到同一个键上。
    """
    match = _CITATION.match((text or "").strip())
    if not match:
        return None
    number = clause_no(match.group("rest"))
    if number is None:
        return None
    doc, _applied = canonical_name(match.group("doc"))
    if not doc:
        return None
    return doc, number


def canonical_name(name: str) -> tuple[str, list[str]]:
    """Fold one entity name; ``(canonical, applied_rule_names)``."""
    from src.bench import keys

    stripped = keys.strip_trailing_qualifier(name or "")
    return keys.fold(stripped, RULES)


def is_distinct_document(name: str) -> bool:
    """True when the name carries a suffix that marks a separate document.

    Used to refuse a fold that would otherwise collapse "…宪法" into
    "…宪法修正案" (or vice versa) just because one is a prefix of the other.
    """
    value = (name or "").strip()
    return any(value.endswith(suffix) for suffix in DOCUMENT_SUFFIXES)


# Registering on import is what makes the kernel's ``rules_for`` answer for this
# domain; a deployment that never imports the pack folds nothing (safe).
#: Shown to the model as examples of the *shape* of a concept.
CONCEPT_EXAMPLES: tuple[str, ...] = (
    "违约责任", "连带清偿责任", "居间合同", "举证责任", "清算义务",
)

#: Shown alongside the positives so the model sees the boundary, not just the
#: target. Measured 2026-11-09: with positives only, it produced
#: 「没收较大数额涉案财产的行政处罚决定」 — a case description.
CONCEPT_COUNTER_EXAMPLES: tuple[str, ...] = (
    "没收较大数额涉案财产的行政处罚决定", "行政处罚违反法定程序", "民事", "执行",
)

#: Relationship shapes this domain insists on. ``defines`` runs concept →
#: document: a definition starts at the concept and lands on the instrument that
#: establishes it. The reverse ("公司法 defines 清算义务") reads backwards and, in
#: practice, lets a document accumulate definitions of unrelated things.
DOCUMENT_KINDS: tuple[str, ...] = ("law", "clause")


def relationship_shape(kind: str, from_kind: str, to_kind: str):
    """A reason string when the endpoints are the wrong way round, else None."""
    if kind == "defines":
        if from_kind != "concept":
            return f"'defines' must start at a concept, not {from_kind!r}"
        if to_kind not in DOCUMENT_KINDS:
            return f"'defines' must land on a document, not {to_kind!r}"
    return None


def concept_counters() -> tuple[str, ...]:
    """Negative examples for the prompt (kept here, not in the kernel)."""
    return CONCEPT_COUNTER_EXAMPLES


# Registering last: every rule above must exist before the kernel can be handed
# one (an earlier draft referenced relationship_shape before its definition).
register_rules("legal", RULES, is_distinct_document, concept_reject,
               CONCEPT_EXAMPLES, CONCEPT_COUNTER_EXAMPLES,
               relationship_rule=relationship_shape)
