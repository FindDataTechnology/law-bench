"""空约束集的 ``passed: true`` 是假绿（6.1 评审跳的诚实性）。

线上实测（2026-11-11，`http://cheap6.mesh.finddata.cn:30840/mcp`）：

```
validation_list({'contract_type': 'sale'})  →  {"result": []}
validation_check({'contract_type': 'sale'}) →  {"errors": [], "warnings": [], "passed": true}
```

同一台服务，两条回答放在一起才看得出问题：**一条约束都没配，却报"通过"**。
``passed = not errors`` 在空集上恒真，那是"没有东西可违反"，不是"查过且合规"。
法务产品把后者读成"合同评审通过"，是很贵的假绿。

所以判据从「`passed` 是不是 True」改成三态：
- ``checked_constraints == 0`` → ``degraded=True``（什么也没查，MUST NOT 声称合规）
- 有约束且违例 → ``passed=False``
- 有约束且都满足 → ``passed=True`` 且 ``degraded=False``（这才是有意义的通过）

负例是主判据：把 ``degraded`` 去掉后，同一段断言必须判红——否则"字段加了"与
"字段有人读"分不开（同族见 tests/test_validation_provenance.py 末条）。
"""

from __future__ import annotations

from src.validations.validate import validate_draft

# 真会咬人的约束：party_b 缺值即违反 required
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
]


def test_empty_constraint_set_is_degraded_not_passed():
    r = validate_draft("sale", _constraints=[])
    assert r["checked_constraints"] == 0
    assert r["degraded"] is True
    assert "未配置任何验证约束" in r["degraded_reason"]
    # passed 仍是 True（向后兼容），但它单独不足以支撑"合规"的结论
    assert r["passed"] is True


def test_violation_is_not_degraded():
    r = validate_draft("sale", slots={}, _constraints=CONSTRAINTS)
    assert r["checked_constraints"] == 1
    assert r["degraded"] is False
    assert r["passed"] is False
    assert "degraded_reason" not in r
    assert len(r["errors"]) == 1


def test_real_pass_is_flagged_as_real():
    """有约束且满足 → passed=True 且 NOT degraded：与空集那种"通过"必须可分。"""
    r = validate_draft("sale", slots={"party_b": "乙公司"}, _constraints=CONSTRAINTS)
    assert r["checked_constraints"] == 1
    assert r["degraded"] is False
    assert r["passed"] is True


def test_consuming_only_passed_cannot_tell_the_two_apart():
    """负例：只看 passed 的消费方在两个场景里读到同一个值——这正是要修的形态。

    这条不是"验证 bug"，是把危险本身钉成断言：若将来有人把 degraded 删掉，
    上面的三态用例会红，而这条会提醒为什么不能删。
    """
    empty = validate_draft("sale", _constraints=[])
    real = validate_draft("sale", slots={"party_b": "乙公司"}, _constraints=CONSTRAINTS)
    assert empty["passed"] == real["passed"] is True
    assert empty["degraded"] != real["degraded"]


def test_stripped_degraded_is_detectable():
    """负例：把 degraded 摘掉后，区分能力必须消失（证明它是唯一判据）。"""
    r = validate_draft("sale", _constraints=[])
    stripped = {k: v for k, v in r.items() if k != "degraded"}
    assert "degraded" not in stripped
    # 只剩 passed=True，与"真通过"无法区分
    assert stripped["passed"] is True
