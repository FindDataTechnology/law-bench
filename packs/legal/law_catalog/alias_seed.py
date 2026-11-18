"""Seed alias table: known 简称/旧称 → full catalog titles.

Distilled from the writing already in the corpus and its surroundings:
``law_refined_citations.py`` shorthand-heavy citation strings, the law_info
surveys, and ``docs/legal_references.md``. Seeds never overwrite curated rows
(``seed_aliases`` skips existing aliases); the table keeps growing via the
review queue. Targets are full titles as they appear in the 法规库 catalog -
an unmatched target falls through to unresolved rather than guessing.
"""

from __future__ import annotations

ALIAS_SEEDS: dict[str, str] = {
    "九民纪要": "全国法院民商事审判工作会议纪要",
    "民法典合同编通则解释": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
    "合同编通则解释": "最高人民法院关于适用《中华人民共和国民法典》合同编通则若干问题的解释",
    "买卖合同司法解释": "最高人民法院关于审理买卖合同纠纷案件适用法律问题的解释",
    "担保制度解释": "最高人民法院关于适用《中华人民共和国民法典》有关担保制度的解释",
    "建工解释（一）": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）",
    "建工解释（二）": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（二）",
    "建设工程施工合同解释（一）": "最高人民法院关于审理建设工程施工合同纠纷案件适用法律问题的解释（一）",
    "融资租赁司法解释": "最高人民法院关于审理融资租赁合同纠纷案件适用法律问题的解释",
    "城镇房屋租赁合同解释": "最高人民法院关于审理城镇房屋租赁合同纠纷案件具体应用法律若干问题的解释",
    "劳动争议解释（一）": "最高人民法院关于审理劳动争议案件适用法律问题的解释（一）",
    "劳动争议解释（二）": "最高人民法院关于审理劳动争议案件适用法律问题的解释（二）",
    "技术合同司法解释": "最高人民法院关于审理技术合同纠纷案件适用法律若干问题的解释",
    "保险法解释（二）": "最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（二）",
    "保险法解释（三）": "最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（三）",
    "保险法解释（四）": "最高人民法院关于适用《中华人民共和国保险法》若干问题的解释（四）",
    "商品房买卖合同解释": "最高人民法院关于审理商品房买卖合同纠纷案件适用法律问题的解释",
    "旅游纠纷规定": "最高人民法院关于审理旅游纠纷案件适用法律若干问题的规定",
    "物业服务解释": "最高人民法院关于审理物业服务纠纷案件适用法律若干问题的解释",
    "特许经营条例": "商业特许经营管理条例",
    "私募条例": "私募投资基金监督管理条例",
    "住房租赁条例": "住房租赁条例",
    "民间借贷规定": "最高人民法院关于审理民间借贷案件适用法律若干问题的规定",
    "公司法解释（三）": "最高人民法院关于适用《中华人民共和国公司法》若干问题的规定（三）",
    "公司法解释（四）": "最高人民法院关于适用《中华人民共和国公司法》若干问题的规定（四）",
    "人身损害赔偿解释": "最高人民法院关于审理人身损害赔偿案件适用法律若干问题的解释",
    "劳务派遣暂行规定": "劳务派遣暂行规定",
}


def seed(db=None) -> int:
    """Load ``ALIAS_SEEDS`` into the alias table; returns the added count."""
    from .store import seed_aliases

    return seed_aliases(ALIAS_SEEDS, source="seed", db=db)
