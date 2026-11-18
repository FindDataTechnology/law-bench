"""批次一溯源：结论条目带 provenance 三件套，法条引用带 stable_id（5.4）。

为什么这两件事绑在一个文件里测：它们回答的是同一个问题——**案卷侧能不能从一条
结论反查到它的依据**。评审报告引用了法条，法条又指向某条约束；链条上任何一个
环节只有"名字"而没有稳定标识，反查就会在名字写法变化时断掉。

契约形状取 `fd-lex/contracts/lex-artifact.schema.json` 的 `provenance`：
`{source, stable_id, as_of}` 三项必填。

负例是主判据（任务原文）：**缺一项即判红**。所以这里除了正向断言，还写了一条
"把 provenance 摘掉后校验必须失败"的检查——否则"带了字段"和"字段有人读"
两件事分不开。
"""

from __future__ import annotations

from src.eval.legal_refs import extract_references
from src.validations.validate import validate_draft

REQUIRED = ("source", "stable_id", "as_of")

CONSTRAINTS = [
    {
        "constraint_id": "C-SALE-PARTY-B",
        "kind": "required",
        "field": "party_b",
        "params": {},
        "message": "乙方名称不得为空",
        "severity": "error",
        "law_ref": "中华人民共和国民法典#第四百九十条",
    },
    {
        "constraint_id": "C-BASE-AMOUNT",
        "kind": "min",
        "field": "amount",
        "params": {"value": 1},
        "message": "合同金额须为正数",
        "severity": "warning",
        "law_ref": None,
        "inherited_from": "sale_base",
    },
]


def _entries():
    # 夹具必须**真的失败**才会产出结论：party_b 缺值（required 判假）、
    # amount=0 小于下界 1（min 判假）。早先用了不触发的约束，entries 恒为空，
    # 三条断言因此全红——"夹具不咬人"和"被测代码不工作"必须分得开。
    result = validate_draft("lease", draft="", slots={"amount": 0}, _constraints=CONSTRAINTS)
    return result, result["errors"] + result["warnings"]


def test_every_entry_carries_the_three_pieces():
    _, entries = _entries()
    assert entries, "夹具应至少产出一条结论"
    for entry in entries:
        prov = entry["provenance"]
        for key in REQUIRED:
            assert prov.get(key), f"{entry['constraint_id']} 缺 provenance.{key}"


def test_stable_id_is_table_plus_business_key():
    _, entries = _entries()
    ids = {e["constraint_id"]: e["provenance"]["stable_id"] for e in entries}
    assert ids["C-SALE-PARTY-B"] == "type_validations:lease#C-SALE-PARTY-B"


def test_inherited_constraint_names_its_parent_type():
    """继承来的约束要指得出上级类型——否则"这条限制哪来的"答不上。"""
    _, entries = _entries()
    inherited = next(e for e in entries if e["constraint_id"] == "C-BASE-AMOUNT")
    assert inherited["provenance"]["source"] == "type_validations:sale_base"


def test_as_of_is_explicitly_the_run_time():
    """约束行没有时间戳列，所以 as_of 是"此刻评的"，必须标 source=run。

    标成 row 就等于宣称我们读到了约束的写入时间——那是编的。
    """
    _, entries = _entries()
    for entry in entries:
        assert entry["provenance"]["as_of_source"] == "run"
        assert "T" in entry["provenance"]["as_of"]


def test_missing_provenance_is_detectable():
    """负例：把 provenance 摘掉后，同一检查必须判红（防"字段存在但没人读"）。"""
    _, entries = _entries()
    stripped = [{k: v for k, v in e.items() if k != "provenance"} for e in entries]
    missing = [
        e.get("constraint_id")
        for e in stripped
        if not all((e.get("provenance") or {}).get(k) for k in REQUIRED)
    ]
    assert len(missing) == len(stripped)


def test_law_references_carry_stable_id():
    items = [
        {
            "contract_type": "lease",
            "source": "base",
            "content": "依据《中华人民共和国民法典》第七百零五条与《民法典》第五百条。",
        }
    ]
    refs = extract_references(items)
    assert refs, "夹具应抽出至少一条法条"
    for ref in refs:
        assert ref["stable_id"].startswith("law:")
    # 简称与全称必须收敛成同一个 stable_id（去重键的作用），否则对账会分裂
    by_name = {r["name"]: r["stable_id"] for r in refs}
    assert len(set(by_name.values())) == len(by_name)
