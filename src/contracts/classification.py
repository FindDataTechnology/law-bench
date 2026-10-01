"""Contract type classification: named (民法典典型合同) vs unnamed (无名合同).

Provides the classification logic and metadata for the 41+ contract types,
distinguishing Civil Code typical named contracts from unnamed contracts that
are governed by industry-specific statutes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

# 民法典具名合同（典型合同）- 19 个
# Source: 民法典 第三编 合同 第二分编 典型合同 (Chapters 9-27)
NAMED_CONTRACTS: dict[str, str] = {
    "sale": "买卖合同",                    # 第九章 (595-647)
    "utilities_supply": "供用电水气热力合同",  # 第十章 (648-656)
    "gift": "赠与合同",                      # 第十一章 (657-666)
    "loan": "借款合同",                      # 第十二章 (667-680)
    "guarantee": "保证合同",                 # 第十三章 (681-702)
    "lease": "租赁合同",                     # 第十四章 (703-734)
    "financing_lease": "融资租赁合同",       # 第十五章 (735-760)
    "factoring": "保理合同",                 # 第十六章 (761-769)
    "work": "承揽合同",                      # 第十七章 (770-787)
    "construction": "建设工程合同",          # 第十八章 (788-808)
    "transport": "运输合同",                 # 第十九章 (809-842)
    "technology": "技术合同",                # 第二十章 (843-887)
    "bailment": "保管合同",                  # 第二十一章 (888-903)
    "warehousing": "仓储合同",               # 第二十二章 (904-918)
    "entrustment": "委托合同",               # 第二十三章 (919-936)
    "property_service": "物业服务合同",       # 第二十四章 (937-950)
    "brokerage": "行纪合同",                 # 第二十五章 (951-960)
    "intermediation": "中介合同",            # 第二十六章 (961-966)
    "partnership": "合伙合同",               # 第二十七章 (967-978)
}

# 非具名合同（无名合同）- 24 个
# Governed by statutes beyond the Civil Code
UNNAMED_CONTRACTS: dict[str, str] = {
    # 公司股权类 - 公司法 (2023 修订)
    "company_formation": "公司设立合同",
    "equity_transfer": "股权转让合同",
    "capital_increase": "增资扩股协议",
    "merger_acquisition": "公司并购协议",
    "equity_incentive": "股权激励协议",
    "vam_agreement": "估值调整（对赌）协议",
    "equity_holding_in_trust": "股权代持协议",
    # 房地产类 - 城市房地产管理法
    "real_estate_sale": "房产买卖合同",
    "real_estate_lease": "房屋租赁合同",
    "real_estate_development": "房地产开发合同",
    # 劳动关系类 - 劳动合同法
    "employment": "劳动合同",
    "labor_dispatch": "劳务派遣合同",
    # 知识产权类 - 专利法/商标法/著作权法
    "ip_license": "知识产权许可合同",
    "software_development": "软件开发合同",
    # 金融服务类 - 保险法/信托法/证券投资基金法
    "insurance": "保险合同",
    "trust": "信托合同",
    "private_equity_fund": "私募基金合同",
    # 特定行业类
    "franchise": "特许经营（加盟）合同",       # 商业特许经营管理条例
    "film_production": "影视剧合作制作合同",    # 著作权法/电影产业促进法
    "talent_agency": "演艺经纪合同",           # 营业性演出管理条例
    "ppp_project": "PPP项目合同",              # 基础设施和公用事业特许经营管理办法
    "tourism_service": "旅游服务合同",          # 旅游法
    # 通用服务类 - 民法典合同编通则
    "service": "服务合同",                     # 承揽/劳务/服务合同
    # 土地流转类 - 农村土地承包法
    "land_transfer": "土地流转合同",           # 土地承包经营权流转合同
}

# 民法典章节映射 (for named contracts)
CIVIL_CODE_CHAPTERS: dict[str, tuple[int, str, tuple[int, int]]] = {
    "sale": (9, "买卖合同", (595, 647)),
    "utilities_supply": (10, "供用电水气热力合同", (648, 656)),
    "gift": (11, "赠与合同", (657, 666)),
    "loan": (12, "借款合同", (667, 680)),
    "guarantee": (13, "保证合同", (681, 702)),
    "lease": (14, "租赁合同", (703, 734)),
    "financing_lease": (15, "融资租赁合同", (735, 760)),
    "factoring": (16, "保理合同", (761, 769)),
    "work": (17, "承揽合同", (770, 787)),
    "construction": (18, "建设工程合同", (788, 808)),
    "transport": (19, "运输合同", (809, 842)),
    "technology": (20, "技术合同", (843, 887)),
    "bailment": (21, "保管合同", (888, 903)),
    "warehousing": (22, "仓储合同", (904, 918)),
    "entrustment": (23, "委托合同", (919, 936)),
    "property_service": (24, "物业服务合同", (937, 950)),
    "brokerage": (25, "行纪合同", (951, 960)),
    "intermediation": (26, "中介合同", (961, 966)),
    "partnership": (27, "合伙合同", (967, 978)),
}


@lru_cache(maxsize=1)
def _all_types() -> dict[str, str]:
    """Merge named + unnamed contract types."""
    return {**NAMED_CONTRACTS, **UNNAMED_CONTRACTS}


def is_named_contract(contract_type: str) -> bool:
    """Return True if ``contract_type`` is a Civil Code named contract."""
    return contract_type in NAMED_CONTRACTS


def is_unnamed_contract(contract_type: str) -> bool:
    """Return True if ``contract_type`` is an unnamed contract."""
    return contract_type in UNNAMED_CONTRACTS


def classify_contract(contract_type: str) -> str:
    """Classify a contract type as ``"named_contract"`` or ``"unnamed_contract"``.

    Raises :class:`ValueError` for an unknown contract type.
    """
    if is_named_contract(contract_type):
        return "named_contract"
    if is_unnamed_contract(contract_type):
        return "unnamed_contract"
    # Unknown types default to unnamed (flexible evaluation)
    return "unnamed_contract"


def get_civil_code_chapter(contract_type: str) -> Optional[tuple[int, str, tuple[int, int]]]:
    """Return ``(chapter_number, chapter_name, (start_article, end_article))``
    for a named contract, or ``None`` for unnamed contracts."""
    return CIVIL_CODE_CHAPTERS.get(contract_type)


def get_zh_name(contract_type: str) -> Optional[str]:
    """Return the Chinese name for a contract type, or ``None``."""
    return _all_types().get(contract_type)


def list_named_contracts() -> list[str]:
    """Return the keys of all 19 Civil Code named contracts."""
    return list(NAMED_CONTRACTS.keys())


def list_unnamed_contracts() -> list[str]:
    """Return the keys of all 24 unnamed contracts."""
    return list(UNNAMED_CONTRACTS.keys())


def list_all_contracts() -> list[str]:
    """Return the keys of all 43 known contract types."""
    return list(_all_types().keys())
