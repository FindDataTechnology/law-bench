"""Per-type ``scenario`` (业务场景) controlled vocabulary for clauses.

``scenario`` replaces the former province ``region`` dimension: analysis of the
extracted 示范文本 corpus showed clauses vary by transaction **sub-type**, not
geography (e.g. ``sale`` collapses 混凝土建材 / 消费零售 / 学校采购 / 展销会;
``service`` collapses 驾校 / 养老 / 教育 / 消费). Province was provenance, not a
legal axis. ``scenario`` is the curatorial replacement.

``SCENARIO_VOCAB[contract_type] = [allowed values]`` is seeded into ``tag_dims``
by :func:`src.clauses.seed_manifest.seed_tag_dims` (one ``scenario`` dim per type,
``category='业务场景'``). Types not listed here have no seeded ``scenario`` vocab;
the extraction/retag LLM registers values on the fly via
:func:`src.clauses.tags.register_tag_dim` (reuse-or-create governance), so the
vocab is extensible without code changes. Every vocab ends with ``其他`` as the
fallback for sub-types outside the seeded set.

Values are derived from analyzing the ``当事人`` / ``合同标的`` sections of the
extracted corpus (587 docs, 33 provinces); they are a seed, not an exhaustive
taxonomy.
"""

from __future__ import annotations

SCENARIO_VOCAB: dict[str, list[str]] = {
    # high-variation types (sub-types confirmed from the extracted corpus)
    "sale": ["农产品买卖", "消费品零售", "工业品建材", "展销会", "共享服务", "其他"],
    "service": ["教育培训", "驾校培训", "养老服务", "消费会员", "招投标服务", "其他"],
    "real_estate_lease": ["住宅租赁", "商业场地租赁", "其他"],
    "real_estate_sale": ["二手房买卖", "商品房买卖", "其他"],
    "entrustment": ["农业委托", "工程咨询", "设备管理委托", "其他"],
    "property_service": ["住宅物业", "电梯维保", "其他"],
    "construction": ["建设工程", "家庭装饰装修", "工程检测", "其他"],
    "lease": ["土地经营权流转", "水面承包", "物资租赁", "其他"],
    "work": ["测绘", "装饰装修", "种子繁育", "广告发布", "其他"],
    "intermediation": ["房地产经纪", "家政中介", "租赁中介", "电商服务", "其他"],
    "utilities_supply": ["燃气供应", "供热供应", "电力供应", "其他"],
    "tourism_service": ["团队境内游", "研学旅游", "出境旅游", "组团委托", "其他"],
    "transport": ["船舶租赁", "快递", "旅游用车", "港口作业", "多式联运", "其他"],
    "land_transfer": ["土地出让", "其他"],
    # lower-variation types: minimal split where an obvious one exists
    "insurance": ["人寿保险", "财产保险", "其他"],
    "loan": ["经营贷款", "消费贷款", "其他"],
    "employment": ["全日制用工", "非全日制用工", "其他"],
    "technology": ["技术开发", "技术转让", "其他"],
    "ip_license": ["许可使用", "其他"],
    "bailment": ["保管服务", "其他"],
    "warehousing": ["仓储服务", "其他"],
    "guarantee": ["保证担保", "其他"],
    "factoring": ["保理", "其他"],
    "franchise": ["特许经营", "其他"],
}
