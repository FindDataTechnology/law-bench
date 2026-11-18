"""KG 图快照 + 市场发布规则 → knowledge units（kind graph-snapshot / publish-rule）.

读入两类「尺子」的可离线单元：

A. **图快照单元**（``tests/fixtures/kg/*-synthetic.json``）—— 一条知识单元 =
   一张图的名字化快照（nodes/edges 名单 + summary 声明数）。真源
   ``fd-text-core/scripts/kg_graph_checks.py`` 连 FalkorDB 分页拉节点名/边数
   （网络依赖，不可离线跑）；本包把它「吃什么」换成快照，判据算法本身逐行
   移植进 ``checks.py``。

   **诚实注记**：本仓与兄弟仓都没有可直接只读导出的真实图统计 JSON
   （2026-11-03 grep 全仓 ``split_article_nodes``/``*checks*.json``/
   ``*snapshot*.json`` 均无产出文件）——所以这些快照是**合成的最小反例/正例**
   （节点名、文号、law_id 全为构造值，非任何生产图的抽样），每个文件自带
   ``"source": "synthetic"`` 与说明。它们用来证明判据算法可离线跑并对真/假
   形态给出正确裁决；不代表任何真实图的健康度。

B. **发布规则单元**（``tests/fixtures/kg/publish-rule-*.json``）—— 一条知识
   单元 = 一次「pack 声明工具面 vs registry 条目商业集/tool_list」的判定
   输入（pack_manifest + registry_index 两份合成数据）。真源
   ``paas/lib/publish-tool-gate.js``（发布端消费侧闭合门）读
   ``registry-bridge.js::registryServerIndex`` 的活栈快照；本包把它「吃什么」
   换成喂给门的 (manifest, index) 输入对，判定逻辑移植在 ``checks.py``。
   registry fetch 与 live probe 两腿后置（deferred，见 README），故发布规则
   单元走的是真实门 probe 缺席分支——存在性缺名给出的是「unresolved rather
   than absent」的可操作拒文，不是「工具不存在」的断言。

载入是幂等的：单元按 ``(kind, namespace, external_key)`` upsert，
重跑原位更新、计数不变。结构损坏（快照边指向未知 uuid、节点缺 name、
发布单元缺 pack_manifest/registry_index）如实抛错，不留半行；语义违例
（判据不过）保持可载入，由 ``checks.py`` 的确定性判据诚实 FAIL。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from src.bench.store import upsert_knowledge_unit

KIND_GRAPH = "graph-snapshot"
KIND_PUBLISH = "publish-rule"
NAMESPACE = "kg-gate"

# 图快照 / 发布规则的真源脚本（README 有完整叙述）；只读引用，绝不写。
KG_CHECKS_SRC = "fd-text-core/scripts/kg_graph_checks.py"
DIRTY_NAME_SRC = "fd-text-core/scripts/kg_statute_repair_names.py"
MERGE_SRC = "fd-text-core/fd_text_core/kg_lane/merge.py"
PUBLISH_GATE_SRC = "paas/lib/publish-tool-gate.js"
REGISTRY_BRIDGE_SRC = "paas/registry-bridge.js"
EXPORT_SURFACE_SRC = "scripts/export_surface_commercial.py"

# Fixtures 根（本仓内，非兄弟仓；env 覆盖便于测试指向 tmp）。
_DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "kg"


def fixtures_dir() -> Path:
    """快照/规则 fixture 目录（env KG_GATE_FIXTURES 每次调用重读，可 monkeypatch）。"""
    env = os.environ.get("KG_GATE_FIXTURES")
    return Path(env) if env else _DEFAULT_FIXTURES


# ── graph snapshots ──────────────────────────────────────────────────────────

_SNAPSHOT_FILES = (
    "legal-v2-synthetic.json",
    "lane-drift-synthetic.json",
    "collapsed-samename-synthetic.json",
)
_PUBLISH_FILES = (
    "publish-rule-law-bench-clean.json",
    "publish-rule-internal-violation.json",
    "publish-rule-counts-only.json",
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot_to_unit(snapshot: dict, *, source_file: Optional[str] = None) -> dict:
    """一张名字化图快照 → ``upsert_knowledge_unit`` kwargs（结构校验在此）。"""
    graph = snapshot.get("graph")
    if not isinstance(graph, str) or not graph.strip():
        raise ValueError(f"{source_file or graph}: snapshot missing 'graph' name")

    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    summary = snapshot.get("summary")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError(f"{graph}: snapshot 'nodes' must be a non-empty list")
    if not isinstance(edges, list):
        raise ValueError(f"{graph}: snapshot 'edges' must be a list")
    if not isinstance(summary, dict):
        raise ValueError(f"{graph}: snapshot 'summary' must be a mapping")

    uuids: set = set()
    for n in nodes:
        if not isinstance(n, dict):
            raise ValueError(f"{graph}: node must be a mapping, got {n!r}")
        if not isinstance(n.get("name"), str) or not n["name"]:
            raise ValueError(f"{graph}: node missing non-empty 'name': {n!r}")
        uuid = n.get("uuid")
        if uuid in uuids:
            raise ValueError(f"{graph}: duplicate node uuid {uuid!r}")
        uuids.add(uuid)
    for e in edges:
        if not isinstance(e, dict):
            raise ValueError(f"{graph}: edge must be a mapping, got {e!r}")
        for side in ("src", "dst"):
            if e.get(side) not in uuids:
                raise ValueError(
                    f"{graph}: edge references unknown node {e.get(side)!r} "
                    f"(structural corruption, not a unit-level fact)"
                )

    n_statute = sum(1 for n in nodes if n.get("law_id") is not None)
    n_covered = sum(
        1 for n in nodes if n.get("law_id") is not None and n.get("article_no")
    )
    body = (
        f"KG 图快照 {graph}（source={snapshot.get('source', 'unknown')}）："
        f"声明 nodes={summary.get('nodes')} edges={summary.get('edges')} "
        f"statute_layer={summary.get('statute_layer_nodes')}；实际枚举 "
        f"nodes={len(nodes)} edges={len(edges)} statute_layer={n_statute} "
        f"条级属性覆盖={n_covered}/{n_statute}。四条硬判据（分裂/同名可分/"
        f"规模/脏文号）由 packs/kg-gate/checks.py 对 nodes.name 逐一核验。"
    )
    return {
        "kind": KIND_GRAPH,
        "namespace": NAMESPACE,
        "external_key": graph,
        "body": body,
        "tags": {"record_type": "graph-snapshot", "source": snapshot.get("source")},
        "attrs": snapshot,
        "tier": "bronze",
        "source_path": source_file,
        "provenance": {
            "true_source": KG_CHECKS_SRC,
            "dirty_name_source": DIRTY_NAME_SRC,
            "merge_source": MERGE_SRC,
            "adapter": "packs/kg-gate/adapters.py",
            "fixture": source_file,
            "note": "synthetic offline snapshot; live version needs FalkorDB",
        },
    }


def publish_rule_to_unit(rule: dict, *, source_file: Optional[str] = None) -> dict:
    """一份发布门判定输入 → kwargs（结构校验在此）。"""
    case = rule.get("case")
    if not isinstance(case, str) or not case.strip():
        raise ValueError(f"{source_file or case}: publish rule missing 'case'")
    manifest = rule.get("pack_manifest")
    index = rule.get("registry_index")
    if not isinstance(manifest, dict):
        raise ValueError(f"{case}: publish rule needs a 'pack_manifest' mapping")
    if not isinstance(index, dict):
        raise ValueError(f"{case}: publish rule needs a 'registry_index' mapping")

    servers = manifest.get("mcpServers") or []
    declared = ", ".join(
        f"{s.get('registryName')}[{','.join(s.get('allowTools') or [])}]"
        for s in servers
        if isinstance(s, dict)
    )
    body = (
        f"市场发布门判定输入 {case}（source={rule.get('source', 'unknown')}）："
        f"pack {manifest.get('name')!r} 声明 {declared or '(no servers)'}；"
        f"registry_index 含 {list(index)}。commercial-closure 与 "
        f"tool-declaration-gate 两条判据对这份输入离线复核。"
    )
    return {
        "kind": KIND_PUBLISH,
        "namespace": NAMESPACE,
        "external_key": case,
        "body": body,
        "tags": {"record_type": "publish-rule", "source": rule.get("source")},
        "attrs": rule,
        "tier": "bronze",
        "source_path": source_file,
        "provenance": {
            "true_source": PUBLISH_GATE_SRC,
            "bridge_source": REGISTRY_BRIDGE_SRC,
            "export_surface_source": EXPORT_SURFACE_SRC,
            "adapter": "packs/kg-gate/adapters.py",
            "fixture": source_file,
            "note": (
                "offline rule kernel; real gate reads registryServerIndex + "
                "live probe (deferred). probe-absent branch of the real gate."
            ),
        },
    }


def load_kg_gate(conn: Any) -> int:
    """载入全部图快照 + 发布规则单元；返回条数。幂等（按 identity upsert）。"""
    root = fixtures_dir()
    count = 0
    for fname in _SNAPSHOT_FILES:
        path = root / fname
        snapshot = _read_json(path)
        upsert_knowledge_unit(conn, **snapshot_to_unit(snapshot, source_file=str(path)))
        count += 1
    for fname in _PUBLISH_FILES:
        path = root / fname
        rule = _read_json(path)
        upsert_knowledge_unit(conn, **publish_rule_to_unit(rule, source_file=str(path)))
        count += 1
    return count
