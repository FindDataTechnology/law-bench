"""Deterministic checkers for the KG lane acceptance criteria + market publish gate.

Registration happens at import time: importing this module installs the
checkers below into ``src.bench.data_checks.register_checker`` for the two
kinds this pack owns (``graph-snapshot``, ``publish-rule``). Every checker
is pure and deterministic — no LLM, no network, no live database.

True sources (read-only, cited per function):

A. KG 车道四条硬判据 — ``fd-text-core/scripts/kg_graph_checks.py`` (2026-11-03
   实核在 fd-text-core，不在 fd-legal-kg): 原脚本连 FalkorDB 分页拉全部节点名
   (``_all_names`` 每页 5000，防 resultset_size 静默截断) + 边计数，判据①④
   是纯名字规则，判据③是规模读数，判据②是同名组读数（打印，exit code 不参
   与）。本包把「吃什么」从 live 图改为**导入的图快照单元**（nodes/edges 名
   单化），判据算法逐行移植；live 分页枚举本身后置（README）。
   脏文号判据（④）的真源是 ``fd-text-core/scripts/kg_statute_repair_names.py``
   的 ``is_dirty_name``/``docno_of`` + ``fd_text_core/kg_lane/merge.py`` 的
   ``normalize_docno_issuer``（修复脚本需要 PG + FalkorDB + embedder，不可离线
   双跑；判读部分在此完整迁移）。
   判据②（同名不同文号可分，113/71 教训，语义真源 merge.py
   ``split_doc_number`` docstring：「113 号与 71 号都叫《行政单位财务规则》，
   但它们是两个不同版本…文号必须参与身份」）：原 live 脚本只打印组读数、不给
   布尔判定；这里按上述语义文档化为确定性判据——剥括号文号归一后的同名基若
   有 ≥2 节点，要求全名两两不同、文号两两非空且互异（坍缩/漏文号即不可分）。
   该解释在 README 中如实标注，不是原脚本 exit-code 的一部分。

B. 市场发布门 — ``paas/lib/publish-tool-gate.js``（``toolGateErrors`` 等四个
   纯函数，add-mcp-tool-scoping D5 + pack-publish-surface-closure 商业闭包）
   与 ``paas/registry-bridge.js``（``toolListNames`` / serverInfo 的
   metadata.surface 双字段映射：commercial_tools 名单优先；pre-enrichment
   计数形态 ``tools_commercial`` → ``"counts-only"`` 哨兵 → 闭包跳过并记
   observable note，不猜测）。名单推导的另一半是 finddata 根仓
   ``scripts/export_surface_commercial.py::commercial_tools``（tool-surface
   manifest → 商业名集，分组级与工具级 level  alike）。
   依赖 registry 运行时 ``/api/servers`` 拉取与 live MCP probe
   （``probeMcpToolNames``）的腿无法离线双跑：迁入版是**无 probe 分支的
   规则内核**（与真实门在 probe 缺席时的判定序列逐字一致，见 tests 的 node
   双跑门），registry fetch + live probe 腿 deferred（README）。

与 ``packs/gov`` 的关系：gov 包已把判据①③④降级迁移为「registry 元数据图」
逐单元对账（``packs/gov/checks.py`` 模块 docstring 有完整映射表），并明确略过
判据②。本包是 KG 判据车道语义的**完整版**：吃图快照单元、四条全部落地、
另立 eval-suite；两者 kind 不同、单元不同、聚合行不同，不存在重复计数。
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any, Callable, Optional

from src.bench.data_checks import CheckResult, register_checker

from .adapters import KIND_GRAPH, KIND_PUBLISH

# ═════════════════════════════ A. KG lane: ported from fd-text-core ═════════

# kg_graph_checks.py:26 —— 条级分裂形态（名字**以条号结尾**）
_ARTICLE = re.compile(r"第[0-9零一二三四五六七八九十百千]+条(?:之[一二三四五六七八九十]+)?$")
# kg_graph_checks.py:27 —— 「前缀是法规主体名」后缀判据
_SUFFIX = ("法", "法典", "条例", "规定", "办法", "细则", "解释", "决定", "通知", "批复")


def split_article_nodes(names: list[str]) -> list[str]:
    """判据①「法规名+条号」分裂节点清单（条级不入图 schema）。

    逐行移植 ``kg_graph_checks.check_graph`` 的 split 表达式：
    ``[n for n in names if (m := _ARTICLE.search(n)) and n[: m.start()].endswith(_SUFFIX)]``。
    """
    return [
        n for n in names
        if (m := _ARTICLE.search(n)) and n[: m.start()].endswith(_SUFFIX)
    ]


# kg_statute_repair_names.py:44-48 —— 括号文号形态（全角/半角）
_PAREN = ("（", "(")
_CLOSE = ("）", ")")
# 文号形态（括号内容必须命中，否则是附注不是文号）
_DOCNO_LIKE = re.compile(r"第\s*[0-9〇零一二三四五六七八九十百]+\s*号")


def docno_of(name: str) -> Optional[str]:
    """取名字末尾括号里的文号；无括号返回 None。（kg_statute_repair_names.py 移植）"""
    s = (name or "").rstrip()
    if not s or s[-1] not in _CLOSE:
        return None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        ch = s[i]
        if ch in _CLOSE:
            depth += 1
        elif ch in _PAREN:
            depth -= 1
            if depth == 0:
                return s[i + 1: -1]
    return None


def normalize_docno_issuer(docno: Optional[str]) -> Optional[str]:
    """文号机关名去重复前缀。逐行移植 ``fd_text_core.kg_lane.merge``（幂等）。

    实测源数据存在「财政部中华人民共和国财政部令第71号」这类重复机关名拼写；
    「中华人民共和国」是机关规范名的起始词，取**最后一次**出现起的后缀；
    另容忍缺字形态「华人民共和国」。
    """
    if not docno:
        return docno
    idx = docno.rfind("中华人民共和国")
    if idx > 0:
        return docno[idx:]
    if idx == 0:
        return docno
    idx = docno.rfind("华人民共和国")
    return docno[idx:] if idx > 0 else docno


def is_dirty_name(name: str) -> bool:
    """判据④污点判据：括号内容是**文号**（含「第N号」）且归一后与原文不同。

    移植 ``kg_statute_repair_names.is_dirty_name``——必须先过 ``_DOCNO_LIKE``
    形态：「X(附:…)」类合法括号附注不是文号（实测误判 1 例的教训）。
    """
    dn = docno_of(name)
    if not dn or not _DOCNO_LIKE.search(dn):
        return False
    return normalize_docno_issuer(dn) != dn


# merge.py:32-42 —— 同名归并用的名字规范化与括号文号形态
_WS = re.compile(r"[\s　]+")
_BOOK_TITLE = re.compile(r"[《〈]([^》〉]+)[》〉]")
_ISSUER_HEAD = r"[一-龥]{1,20}(?:部|委|局|署|府|厅|会|院|行|司|关)"
_SEQ_NO = r"第[0-9零一二三四五六七八九十百]+号"
_DOC_NUM_CORE = (
    rf"(?:{_ISSUER_HEAD}令{_SEQ_NO}|\d{{4}}年{_SEQ_NO}|[〔\[]\d{{4}}[〕\]]\s*\d+号|{_SEQ_NO})"
)
_DOC_NUM_WRAPPED = re.compile(rf"[（(]\s*({_DOC_NUM_CORE})\s*[)）]")


def normalize(text: str) -> str:
    """统一宽度与空白（merge.normalize 移植）：「刑法 」与「刑法」同一实体。"""
    return _WS.sub("", unicodedata.normalize("NFKC", text or ""))


def base_name(name: str) -> str:
    """剥书名号 + 去括号文号后的「同名基」——判据②的分组键。"""
    n = _BOOK_TITLE.sub(r"\1", normalize(name))
    return _DOC_NUM_WRAPPED.sub("", n)


def separability_failures(names: list[str]) -> list[str]:
    """判据②「同名不同文号可分（113/71 口径）」的确定性判定。

    live 原脚本只打印「行政单位财务规则*」组读数；布尔语义按 merge.py
    ``split_doc_number`` docstring 的版本身份规则文档化（见模块 docstring）：
    同名基 ≥2 节点的组，全名必须两两不同、每个成员必须带自己的文号、文号
    两两互异——违反即「同名实体被当成同一个」（试点把 113 号施行日挂到
    71 号上的根因形态）或重复名坍缩。
    """
    groups: "dict[str, list[str]]" = {}
    for n in names:
        groups.setdefault(base_name(n), []).append(n)
    problems: list[str] = []
    for base, members in groups.items():
        if len(members) < 2:
            continue
        if len(set(members)) != len(members):
            problems.append(f"同名重复（坍缩不可分）: {sorted(set(m for m in members if members.count(m) > 1))}")
            continue
        docnos = [docno_of(m) for m in members]
        missing = [m for m, d in zip(members, docnos) if not d]
        if missing:
            problems.append(f"同名组缺文号身份（版本号不参与身份）: {missing}")
            continue
        if len(set(docnos)) != len(docnos):
            problems.append(f"同名组文号重复不可分: {base} -> {docnos}")
    return problems


def scale_stats(attrs: dict) -> dict:
    """判据③规模读数（kg_graph_checks.check_graph 输出的同源字段）。

    nodes=len(names)、edges=len(边表)、statute_layer=带 law_id 的节点数、
    条级属性覆盖=其中带 article_no 属性者。live 版靠图查询，迁入版对快照
    枚举重算，声明值只作被核对的一方。
    """
    nodes = attrs.get("nodes") or []
    edges = attrs.get("edges") or []
    statute = [n for n in nodes if n.get("law_id") is not None]
    covered = [n for n in statute if n.get("article_no")]
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "statute_layer_nodes": len(statute),
        "article_attr_covered": len(covered),
    }


# --- graph-snapshot checkers -------------------------------------------------


def _names(unit: dict) -> list[str]:
    return [n.get("name") or "" for n in (unit.get("attrs") or {}).get("nodes") or []]


def check_split_article_zero(unit: dict) -> CheckResult:
    """判据① 条级分裂节点清零（连 live 版 exit code 同源：split 非空即 FAIL）。"""
    names = _names(unit)
    split = split_article_nodes(names)
    graph = (unit.get("attrs") or {}).get("graph")
    detail = f"[{graph}] 判据① 条级分裂节点: {len(split)} -> {'PASS' if not split else 'FAIL'}"
    for n in split[:5]:
        detail += f" | SPLIT: {n}"
    return CheckResult(name="split-article-zero", passed=not split, detail=detail)


def check_same_name_separable(unit: dict) -> CheckResult:
    """判据② 同名不同文号可分（113/71 口径；live 组的打印读数保留在 detail）。"""
    names = _names(unit)
    problems = separability_failures(names)
    rules = sorted(n for n in names if "行政单位财务规则" in n)
    graph = (unit.get("attrs") or {}).get("graph")
    detail = (
        f"[{graph}] 判据② 行政单位财务规则*: {rules or '(none)'}; "
        f"不可分同名组: {problems or '(none)'} -> {'PASS' if not problems else 'FAIL'}"
    )
    return CheckResult(name="same-name-diff-docno-separable", passed=not problems, detail=detail)


def check_scale_stats(unit: dict) -> CheckResult:
    """判据③ 规模统计对账：快照声明数与枚举重算逐一相符。"""
    attrs = unit.get("attrs") or {}
    declared = attrs.get("summary") or {}
    got = scale_stats(attrs)
    ok = (
        declared.get("nodes") == got["nodes"]
        and declared.get("edges") == got["edges"]
        and declared.get("statute_layer_nodes") == got["statute_layer_nodes"]
    )
    detail = (
        f"[{attrs.get('graph')}] 判据③ nodes={got['nodes']} edges={got['edges']} "
        f"statute_layer={got['statute_layer_nodes']} 条级属性覆盖="
        f"{got['article_attr_covered']}/{got['statute_layer_nodes']} "
        f"(declared {declared!r}) -> {'PASS' if ok else 'FAIL'}"
    )
    return CheckResult(name="scale-stats-consistent", passed=ok, detail=detail)


def check_dirty_docno_zero(unit: dict) -> CheckResult:
    """判据④ 脏文号（重复机关名）清零（连 live 版 exit code 同源）。"""
    names = _names(unit)
    dirt = [n for n in names if is_dirty_name(n)]
    graph = (unit.get("attrs") or {}).get("graph")
    detail = f"[{graph}] 判据④ 脏文号节点: {len(dirt)} -> {'PASS' if not dirt else 'FAIL'}"
    for n in dirt[:5]:
        detail += f" | DIRT: {n}"
    return CheckResult(name="dirty-docno-zero", passed=not dirt, detail=detail)


# ═══════════════════ B. Market publish gate: ported from paas ═══════════════
#
# paas/lib/publish-tool-gate.js 的确定性判定内核移植（错误/便签文案与其
# 逐字一致，tests/test_kg_gate.py 用 node 双跑真实 JS 门证明零漂移）。
# 依赖网络的两腿后置（deferred，见 README）：registryServerIndex 的
# /api/servers fetch、probeMcpToolNames 的 live MCP 探活。本内核等价于
# 真实门在 probe 缺席（`toolGateErrors(manifest, serverInfo, {})`）时的
# 完整判定序列——存在性腿给出的是真实门的「unresolved rather than
# absent」可操作拒文，不是「工具不存在」的断言。

_MCP_TOOL_REF_RE = re.compile(r"mcp__([A-Za-z0-9._-]+?)__([A-Za-z0-9._-]+)")


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _pack_label(manifest: Any) -> str:
    name = manifest.get("name") if isinstance(manifest, dict) else None
    return name if isinstance(name, str) and name else "(unnamed pack)"


def commercial_tools(manifest: dict) -> list[str]:
    """tool-surface manifest → 商业名集。移植 finddata 根仓
    ``scripts/export_surface_commercial.py::commercial_tools``（单一推导定义）：
    分组级 ``level`` 与工具级 override alike；非法 level、无名条目、跨组
    冲突级别都如实抛错；无任何商业工具的 manifest 是契约违例（错误而非
    空集——发布门据此会把一切声明拒掉）。写入端 PATCH registry 的部分
    deferred（需网络）。
    """
    tools: dict[str, str] = {}
    for group in _as_list(manifest.get("tool_groups")):
        level = group.get("level")
        if level not in ("commercial", "internal"):
            raise ValueError(f"tool_groups.{group.get('group')}: illegal level {level!r}")
        for entry in _as_list(group.get("tools")):
            if isinstance(entry, dict):
                name, lvl = entry.get("name"), entry.get("level", level)
            else:
                name, lvl = entry, level
            if not name:
                raise ValueError(f"tool_groups.{group.get('group')}: tool entry without a name")
            if lvl not in ("commercial", "internal"):
                raise ValueError(f"tool {name}: illegal level {lvl!r}")
            if name in tools and tools[name] != lvl:
                raise ValueError(f"tool {name}: conflicting levels across groups")
            tools[name] = lvl
    return sorted(n for n, lvl in tools.items() if lvl == "commercial")


def tool_list_names(tool_list: Any) -> Optional[list]:
    """registry 条目 ``tool_list`` → 名字表。移植 paas
    ``registry-bridge.js::toolListNames``：条目可能是名字字符串或工具对象
    （生产条目是对象形）；非数组返回 None（= 无快照），空名表也归 None。
    """
    if not isinstance(tool_list, list):
        return None
    names: list = []
    for t in tool_list:
        if isinstance(t, str):
            names.append(t)
        elif isinstance(t, dict) and isinstance(t.get("name"), str):
            names.append(t["name"])
    return names or None


def _js_number(value: Any) -> float:
    """JS ``Number()`` 的忠实镜像（registry-bridge 的计数判据用到）：
    null→0、bool→0/1、数字→自身、字符串→parseFloat（空串 0、非法 NaN）、
    其余→NaN。"""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError:
            return math.nan
    return math.nan


def server_info_from_entry(entry: Any) -> Optional[dict]:
    """registry 条目 → 发布门 serverInfo。合成 ``registry-bridge.js`` 的
    metadata.surface 映射（commercial_tools 名单优先；否则 ``tools_commercial``
    计数有限 → "counts-only" 哨兵）与 ``publish-tool-gate.js`` 对哨兵的消费。
    """
    if not isinstance(entry, dict):
        return None
    meta = entry.get("metadata")
    surface = meta.get("surface") if isinstance(meta, dict) else None
    commercial: Any = None
    if isinstance(surface, dict) and isinstance(surface.get("commercial_tools"), list):
        commercial = [str(t) for t in surface["commercial_tools"]]
    elif isinstance(surface, dict) and "tools_commercial" in surface \
            and math.isfinite(_js_number(surface["tools_commercial"])):
        commercial = "counts-only"
    return {
        "toolList": tool_list_names(entry.get("tool_list")),
        "commercialTools": commercial,
        "endpoint": None,  # live 探活后置：迁入版永远走 probe 缺席分支
    }


def declared_tools_by_server(manifest: Any) -> "dict[str, list]":
    """发布门声明收集器。移植 ``publish-tool-gate.js::declaredToolsByServer``：
    pack 级 allowTools ∪ 各角色 resources.mcpTools[server]；容忍畸形
    manifest（绝不抛错）；首次出现序（JS Set 插序）；server 无任何声明时
    不建条目（JS add 只在有数组时调用）。"""
    by_server: "dict[str, list]" = {}

    def add(server: str, names: list) -> None:
        bucket = by_server.setdefault(server, [])
        for t in names:
            if t not in bucket:
                bucket.append(t)

    servers = _as_list(manifest.get("mcpServers") if isinstance(manifest, dict) else None)
    agents = _as_list(manifest.get("agents") if isinstance(manifest, dict) else None)
    for ref in servers:
        if not isinstance(ref, dict) or not isinstance(ref.get("registryName"), str):
            continue
        server = ref["registryName"]
        if isinstance(ref.get("allowTools"), list):
            add(server, ref["allowTools"])
        for agent in agents:
            if not isinstance(agent, dict):
                continue
            resources = agent.get("resources")
            if not isinstance(resources, dict):
                continue
            mcp_tools = resources.get("mcpTools")
            if not isinstance(mcp_tools, dict):
                continue
            role_list = mcp_tools.get(server)
            if isinstance(role_list, list):
                add(server, role_list)
    return by_server


def named_mcp_tools(manifest: Any) -> "dict[str, dict[str, set]]":
    """技能正文点名的 ``mcp__<server>__<tool>``。移植 ``namedMcpTools``
    （dsh-mcp-client 命名约定正则，server 段非贪婪）。"""
    by_server: "dict[str, dict[str, set]]" = {}
    for skill in _as_list(manifest.get("skills") if isinstance(manifest, dict) else None):
        if not isinstance(skill, dict) or not isinstance(skill.get("content"), str):
            continue
        skill_name = skill["name"] if isinstance(skill.get("name"), str) else "(unnamed skill)"
        for m in _MCP_TOOL_REF_RE.finditer(skill["content"]):
            server, tool = m.group(1), m.group(2)
            tools = by_server.setdefault(server, {})
            tools.setdefault(tool, set()).add(skill_name)
    return by_server


def tool_face_errors(manifest: Any) -> list[dict]:
    """每个 mcpServers 引用必须显式选择工具面（非空 allowTools 或
    fullSurface）。移植 ``toolFaceErrors``，文案逐字一致。"""
    errors: list[dict] = []
    pack = _pack_label(manifest)
    for i, ref in enumerate(_as_list(manifest.get("mcpServers") if isinstance(manifest, dict) else None)):
        if not isinstance(ref, dict):
            continue  # structural gate reports the entry
        name = ref["registryName"] if isinstance(ref.get("registryName"), str) else f"mcpServers[{i}]"
        has_list = isinstance(ref.get("allowTools"), list) and len(ref["allowTools"]) > 0
        if has_list or ref.get("fullSurface") is True:
            continue
        errors.append({
            "error": (
                f"pack '{pack}' MCP reference '{name}' declares no tool face: "
                "declare its tool names in allowTools, or mark the reference "
                "fullSurface with a non-empty reason"
            ),
            "entry": f"mcpServers:{name}",
        })
    return errors


def tool_closure_errors(manifest: Any) -> list[dict]:
    """技能正文点名的每个工具必须落在该引用的 allowTools 内
    （fullSurface 与未声明者除外，各归他门）。移植 ``toolClosureErrors``。"""
    errors: list[dict] = []
    pack = _pack_label(manifest)
    refs = {
        r["registryName"]: r
        for r in _as_list(manifest.get("mcpServers") if isinstance(manifest, dict) else None)
        if isinstance(r, dict) and isinstance(r.get("registryName"), str)
    }
    for server, tools in named_mcp_tools(manifest).items():
        ref = refs.get(server)
        if ref is None or ref.get("fullSurface") is True:
            continue
        if not isinstance(ref.get("allowTools"), list) or len(ref["allowTools"]) == 0:
            continue
        allow = set(ref["allowTools"])
        for tool, skill_names in tools.items():
            if tool in allow:
                continue
            names = ", ".join(sorted(skill_names))
            errors.append({
                "error": (
                    f"pack '{pack}' skill(s) [{names}] name '{tool}' on MCP server "
                    f"'{server}', outside that reference's allowTools (add it to the "
                    "declaration, or mark the reference fullSurface)"
                ),
                "entry": f"mcpServers:{server}",
            })
    return errors


def tool_gate_errors(
    manifest: Any,
    server_info: "Callable[[str], Optional[dict]]",
) -> "tuple[list[dict], list[str]]":
    """发布门主判定（无 probe 分支）。移植 ``publish-tool-gate.js::toolGateErrors``
    在 ``probe`` 缺席时的完整序列：先商业闭包（与探活结果无关，越界即
    error+continue），counts-only 记 note 跳过闭包；再存在性对账 tool_list
    快照，缺名走真实门的「unresolved rather than absent」可操作拒文
    （live probe 腿 deferred，绝不伪造探活结论）。非 registry 条目豁免
    （local-binding 契约）。返回 (errors, notes)。"""
    errors: list[dict] = []
    notes: list[str] = []
    for server, names in declared_tools_by_server(manifest).items():
        entry = f"mcpServers:{server}"
        info = server_info(server)
        if info is None:
            notes.append(
                f"'{server}' is not a registry entry; its declarations ride "
                "as the local binding contract"
            )
            continue
        declared = list(names)
        # Commercial closure first: probe results are irrelevant to it.
        commercial = info.get("commercialTools")
        if isinstance(commercial, list):
            out = [t for t in declared if t not in commercial]
            if out:
                errors.append({
                    "error": (
                        f"MCP server '{server}' is surface-registered; tools outside "
                        f"its commercial set may not enter a pack: "
                        f"{', '.join(str(t) for t in out)}"
                    ),
                    "entry": entry,
                })
                continue
        elif commercial == "counts-only":
            notes.append(
                f"'{server}' carries surface counts but no commercial name list; "
                "closure skipped (enrich metadata.surface.commercial_tools)"
            )
        known = info.get("toolList") if isinstance(info.get("toolList"), list) else []
        missing = [t for t in declared if t not in known]
        if not missing:
            continue
        # Existence: registry tool_list snapshot; live probe deferred —— 等价于
        # 真实门 probe=null 的 else 分支（names UNCONFIRMED，never absent）。
        errors.append({
            "error": (
                f"MCP server '{server}' has no registry snapshot entry for declared "
                f"tool(s): {', '.join(str(t) for t in missing)}; the live probe could "
                "not confirm them, so this is unresolved rather than absent — if the "
                "entry is self-reported (surface_source=self_report), restart the "
                "service so it re-reports its surface (check its "
                "/health last_surface_report); otherwise refresh the registry entry's "
                "tool_list snapshot (see docs/registry-maintenance.md §6) and publish "
                "again, or drop the names"
            ),
            "entry": entry,
        })
    return errors, notes


def commercial_closure_errors(
    manifest: Any,
    server_info: "Callable[[str], Optional[dict]]",
) -> "tuple[list[dict], list[str]]":
    """只跑商业闭包腿（「allowTools ⊆ 商业集」判读本身），不碰存在性。
    语义为 ``tool_gate_errors`` 闭包分支的独立投影，文案同源。"""
    errors: list[dict] = []
    notes: list[str] = []
    for server, names in declared_tools_by_server(manifest).items():
        info = server_info(server)
        if info is None:
            continue
        commercial = info.get("commercialTools")
        if isinstance(commercial, list):
            out = [t for t in names if t not in commercial]
            if out:
                errors.append({
                    "error": (
                        f"MCP server '{server}' is surface-registered; tools outside "
                        f"its commercial set may not enter a pack: "
                        f"{', '.join(str(t) for t in out)}"
                    ),
                    "entry": f"mcpServers:{server}",
                })
        elif commercial == "counts-only":
            notes.append(
                f"'{server}' carries surface counts but no commercial name list; "
                "closure skipped (enrich metadata.surface.commercial_tools)"
            )
    return errors, notes


# --- publish-rule checkers ----------------------------------------------------


def _publish_inputs(unit: dict) -> tuple[Any, "Callable[[str], Optional[dict]]"]:
    attrs = unit.get("attrs") or {}
    manifest = attrs.get("pack_manifest")
    index = attrs.get("registry_index") or {}

    def server_info(name: str) -> Optional[dict]:
        entry = index.get(name) if isinstance(index, dict) else None
        return server_info_from_entry(entry) if entry is not None else None

    return manifest, server_info


def check_commercial_closure(unit: dict) -> CheckResult:
    """发布门·商业闭包：声明的每个工具叶名 ⊆ 所引用 server 的
    metadata.surface.commercial_tools 名单（越界即如真实门般点名拒绝；
    counts-only 条目跳过闭包并带 note，未上牌/local 引用豁免）。"""
    manifest, server_info = _publish_inputs(unit)
    errors, notes = commercial_closure_errors(manifest, server_info)
    case = (unit.get("attrs") or {}).get("case")
    detail = f"[{case}] 发布门·商业闭包: "
    detail += "; ".join(e["error"] for e in errors) if errors else "no violations"
    if notes:
        detail += " | notes: " + "; ".join(notes)
    return CheckResult(name="commercial-closure", passed=not errors, detail=detail)


def check_tool_declaration_gate(unit: dict) -> CheckResult:
    """发布门·完整离线判定：工具面显式（toolFace）∪ 技能点名闭包
    （toolClosure）∪ 商业闭包 ∪ tool_list 快照存在性（probe 腿后置，走
    真实门 probe 缺席分支的可操作拒文）。"""
    manifest, server_info = _publish_inputs(unit)
    errors = tool_face_errors(manifest) + tool_closure_errors(manifest)
    gate_errors, notes = tool_gate_errors(manifest, server_info)
    errors = errors + gate_errors
    case = (unit.get("attrs") or {}).get("case")
    detail = f"[{case}] 发布门·完整判定: "
    detail += "; ".join(e["error"] for e in errors) if errors else "clean"
    if notes:
        detail += " | notes: " + "; ".join(notes)
    return CheckResult(name="tool-declaration-gate", passed=not errors, detail=detail)


# Registration happens at import time (kernel contract: 模块 import 即注册).
register_checker(KIND_GRAPH, "split-article-zero", check_split_article_zero)
register_checker(KIND_GRAPH, "same-name-diff-docno-separable", check_same_name_separable)
register_checker(KIND_GRAPH, "scale-stats-consistent", check_scale_stats)
register_checker(KIND_GRAPH, "dirty-docno-zero", check_dirty_docno_zero)
register_checker(KIND_PUBLISH, "commercial-closure", check_commercial_closure)
register_checker(KIND_PUBLISH, "tool-declaration-gate", check_tool_declaration_gate)
