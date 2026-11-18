"""The submission contract doc must not drift from the code that enforces it.

``docs/domain-proposal-contract.md`` is what the fleet-side integration reads
instead of this repo. Every user-facing refusal that a caller has to handle is
a string in the code; if one changes and the doc keeps the old wording, the
integration silently matches on nothing. These assertions are the cheap half of
that guard — the behavioural half lives in ``tests/test_domain_console.py``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "domain-proposal-contract.md"

#: (text the doc quotes to callers, what to look for in the code). They differ
#: only where the code builds the message with a format string.
REFUSALS = (
    ("提案必须携带依据", "提案必须携带依据"),
    ("同键已驳回，需新证据", "同键已驳回，需新证据"),
    ("不在模板 v", "不在模板 v"),
    (
        "relationship 提案的 evidence 缺少非空的 from_key/to_key 端点",
        "relationship 提案的 evidence 缺少非空的 from_key/to_key 端点",
    ),
    (
        "relationship 提案的 evidence 必须是对象并携带 from_key/to_key",
        "relationship 提案的 evidence 必须是对象并携带 from_key/to_key",
    ),
    ("驳回必须写明理由", "驳回必须写明理由"),
    ("无该域权限", "无该域权限"),
    ("missing scope: content:write", "missing scope: {scope}"),
    # 来源校验（add-fleet-execution-loop §2）：九类结论各自是一句可读原话。
    ("来源未登记", "来源未登记"),
    ("来源登记已吊销", "来源登记已吊销"),
    ("域不在绑定范围", "域不在绑定范围"),
    ("该类来源仅限进程内调用", "该类来源仅限进程内调用"),
    ("身份与域不一致", "身份与域不一致"),
    ("身份不是该域活跃成员", "身份不是该域活跃成员"),
    ("只能以自己的身份提交", "只能以自己的身份提交"),
    ("来源形状不合法", "来源形状不合法"),
    ("未知来源类别", "未知来源类别"),
    # 结局与回执读面
    ("只能读取自己来源的结局", "只能读取自己来源的结局"),
)


def test_doc_exists():
    assert DOC.is_file()


def test_doc_states_the_endpoint_and_its_identity():
    text = DOC.read_text(encoding="utf-8")
    assert "POST /api/d/{domain_key}/proposals" in text
    for field in (
        "source", "kind", "external_key", "body", "evidence", "submitted_by", "created"
    ):
        assert f"`{field}`" in text, f"contract field {field!r} undocumented"


def test_doc_quotes_every_refusal_verbatim():
    text = DOC.read_text(encoding="utf-8")
    missing = [doc for doc, _ in REFUSALS if doc not in text]
    assert missing == [], f"contract doc is stale on: {missing}"


def test_doc_names_all_four_source_classes():
    """四类来源与各自的信任依据是这一面的全部内容；少一类就等于少一条绕过口。"""
    text = DOC.read_text(encoding="utf-8")
    for prefix in ("fleet:", "extract:", "agent:", "user:"):
        assert f"`{prefix}`" in text, f"source class {prefix} undocumented"
    # 每类的可信依据都要说清，否则接线方会以为「有前缀就放行」。
    for basis in ("登记 + 凭据", "调用位置", "已铸身份 + 域成员", "已认证身份"):
        assert basis in text, f"trust basis {basis!r} undocumented"


def test_doc_names_the_read_faces_a_submitter_needs():
    text = DOC.read_text(encoding="utf-8")
    for route in (
        "GET /api/d/{domain_key}/proposals/outcomes",
        "GET /api/d/{domain_key}/runs",
        "GET /api/v1/distribution/{domain_key}/runs",
        "GET /api/v1/distribution/legacy-sources",
        # 舰队执行面（机器凭据）：三个写面 + 一个读面的闭环
        "POST /api/v1/distribution/{domain_key}/work-orders/{task_id}/claim",
        "POST /api/v1/distribution/{domain_key}/work-orders/{task_id}/complete",
        "POST /api/v1/distribution/{domain_key}/runs",
    ):
        assert route in text, f"read face {route!r} undocumented"


def test_every_endpoint_the_reference_client_calls_is_documented():
    """文档 ↔ 参照客户端：客户端真打的每个面，契约档里必须有一行 `METHOD path`。

    手工维护的清单会漏。这条不靠清单，而是从 `scripts/fleet_client.py` 里把
    `_call("METHOD", f"{PREFIX}/…")` 逐条抽出来，再要求文档里有对应的一行。
    2026-11-14 实测抓到过一次：`GET /work-orders`（列工单，舰队这条链的第一步）
    文档里根本没有独立一行——它只能作为 `…/work-orders/{task_id}/claim` 的前缀
    子串被人「看见」，于是任何按子串做的检查都会假绿。
    """
    import re

    src = (REPO_ROOT / "scripts" / "fleet_client.py").read_text(encoding="utf-8")
    calls = set(re.findall(r'_call\(\s*"(GET|POST)",\s*f"\{PREFIX\}/([^"]*)"', src))
    assert calls, "没从 fleet_client.py 抽出任何端点——抽取判据失效（别让它静默通过）"

    # 文档里 `GET  /api/...` 用的是对齐空格，所以先把连续空白压成一个再比。
    doc = re.sub(r"[ \t]+", " ", DOC.read_text(encoding="utf-8"))
    missing = []
    for method, suffix in sorted(calls):
        path = f"/api/v1/distribution/{suffix.replace('{domain}', '{domain_key}')}"
        if f"{method} {path}" not in doc:
            missing.append(f"{method} {path}")
    assert missing == [], f"参照客户端在打、契约档却没写：{missing}"


def test_refusals_still_exist_in_the_code():
    """The other direction: the doc must not promise messages nobody raises."""
    haystack = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            REPO_ROOT / "src" / "bench" / "proposals.py",
            REPO_ROOT / "src" / "web" / "routes" / "console.py",
            REPO_ROOT / "src" / "web" / "auth" / "deps.py",
            REPO_ROOT / "src" / "web" / "auth" / "domain_rbac.py",
            REPO_ROOT / "src" / "bench" / "submitters.py",
        )
    )
    stale = [doc for doc, probe in REFUSALS if probe not in haystack]
    assert stale == [], f"documented refusals nobody raises any more: {stale}"
