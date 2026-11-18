"""只读岗位：巡检员（warden）与质检员（verifier）。

这两个岗位是团队的**第一支**，选它们打头是因为它们不改本体：一个把缺口变成任务，
一个把噪声从人眼前拿掉。跑错了最坏的结果是"报告不准"，不是"写脏了库"。

三条纪律：

- **只读**：这里没有任何写库路径（除了台账与派单）。发现问题出结论，不动数据。
- **质检员不看起草思路**：它拿到的是产物 + 当前本体，回源核对；起草者的解释不在
  输入里。否则"独立检查"只是自我复述。
- **不确定就报不确定**：逐字核对需要语料原文，拿不到时报 ``unknown`` 而不是
  ``pass``。把"没法验"记成"验过了"，是这套东西最不能犯的错。
"""

from __future__ import annotations

from typing import Any, Optional

from . import (agent_ids, agent_runs, agent_team, authoring, corpus_catalog, dispatch,
               estate, libraries, proposals, workspaces)
from src.search import library_index

#: 缺口 → 该由哪个内核岗位处理；``None`` = 人（复核积压不是智能体能替的）。
#:
#: **派生自 ``dispatch.GAP_ROUTE``，不另写一份**：两张表各写一遍，早晚会漂移，
#: 而漂移的那一次会让一个岗位去干另一个岗位的活，事后只能靠人发现。
GAP_OWNER: dict[str, Optional[str]] = {
    gap: dispatch.kernel_role_for(gap) for gap in dispatch.GAP_TASKS
}

#: 质检员能机器判定的项。顺序即报告顺序（先便宜且确定的后贵的）。
MAX_BUILDER_DOCS = 50

VERIFIER_CHECKS = (
    "key_already_live",      # 键已在库里：连"要不要写"都不用判
    "missing_evidence",      # 没有可回源的依据
    "endpoint_open",         # 关系端点未闭合
    "near_duplicate",        # 同一实体的另一种写法已在本体
    "quote_mismatch",        # 引文不在所引块里（编造）
    "quote_unverifiable",    # 有引文但取不到原文，没法验
)


def _role(role: str, domain_key: str) -> str:
    return agent_ids.agent_identity(role, domain_key)


def _finish_failed(conn: Any, run_id: int, exc: BaseException) -> None:
    """记下失败，**先回滚**再写。

    失败的来源常常是一条 SQL 报错（表缺失、约束冲突），此时连接已处于中止事务
    状态：不回滚就去写台账，写台账本身会再失败——于是"失败一定留痕"这条承诺
    在最需要它的时刻失效，而且现场只剩一句 InFailedSqlTransaction。
    """
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001 - 回滚失败也不能掩盖原始错误
        pass
    try:
        agent_runs.finish(conn, run_id=run_id, outcome="failed",
                          detail=f"{type(exc).__name__}: {exc}"[:300])
    except Exception:  # noqa: BLE001 - 台账写不进去时，原始异常必须继续抛
        pass


def fetch_chunk_text(
    conn: Any, *, library: str, source_key: str, chunk_id: str
) -> Optional[str]:
    """按证据里的坐标取回那段原文；取不到返回 ``None``（不是空串）。

    这是质检"逐字核对"的前提。两种库形状都要覆盖：向量库按点 id 取 payload，
    外接表按登记列名查一行。取不到就是**没法验**，绝不能退化成"验过了"。
    """
    from . import libraries

    lib = libraries.get_library(conn, library_key=library)
    if lib is None:
        return None
    src = next(
        (x for x in libraries.list_sources(conn, library_id=lib["id"])
         if x["source_key"] == source_key),
        None,
    )
    if src is None:
        return None
    backend = lib.get("backend") or ""
    loc = libraries.resolve_location(lib)
    if backend == "qdrant":
        data = library_index._qdrant_post(
            loc["url_env"], f"/collections/{loc['collection']}/points",
            {"ids": [_coerce_id(chunk_id)], "with_payload": True, "with_vector": False},
        )
        points = (data.get("result") or [])
        if not points:
            return None
        payload = points[0].get("payload") or {}
        rule = src.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        text_field = ((rule.get("document") or {}).get("text")) or "chunk_text"
        text = payload.get(text_field)
        return str(text) if text else None

    if backend == "pgvector-external":
        import psycopg

        rule = src.get("ingest_rule") or {}
        if isinstance(rule, str):
            import json as _json

            rule = _json.loads(rule or "{}")
        cols = {**(rule.get("columns") or {})}
        table = src["uri"]
        id_col = cols.get("id", "id")
        text_col = cols.get("text", "text")
        from psycopg.rows import dict_row

        with psycopg.connect(loc["dsn_env"], connect_timeout=10,
                             row_factory=dict_row) as ext:
            row = ext.execute(
                f"SELECT {text_col} AS t FROM {table} WHERE {id_col} = %s",
                (chunk_id,),
            ).fetchone()
        return str(row["t"]) if row and row.get("t") else None
    return None


def _coerce_id(chunk_id: str) -> Any:
    """Qdrant 的点 id 可能是整数；能转就转，不能就原样传。"""
    try:
        return int(chunk_id)
    except (TypeError, ValueError):
        return chunk_id


def run_warden(conn: Any, *, domain_key: str, limit: int = 50) -> dict:
    """巡检一轮：缺口 → 质量比 → 派单 → 台账。不写本体。"""
    role = _role("warden", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"warden-{domain_key}")
    try:
        domain = workspaces.get_domain(conn, domain_key=domain_key)
        if domain is None:
            raise ValueError(f"domain {domain_key!r} not found")
        rows = estate.matrix(conn, domains=[domain])
        row = rows[0]
        gaps = list(row["gaps"])

        created, already, skipped = 0, 0, []
        for gap in gaps:
            owner = GAP_OWNER.get(gap)
            if owner is None:
                skipped.append(gap)          # 复核积压归人，不派给智能体
                continue
            out = dispatch.dispatch(
                conn, rows=rows, gap=gap,
                assignee=_role(owner, domain_key), created_by=role,
            )
            created += len(out["created"])
            already += len(out["already_open"])

        # 计数键不能叫 "gaps"：返回体里已经有 gaps（列表），用 **counts 展开会把
        # 列表覆盖成整数，调用方拿到一个 len() 不了的数字。
        counts = {"gap_count": len(gaps), "tasks_created": created,
                  "already_open": already, "skipped": skipped}
        detail = None if gaps else "无缺口"
        finished = agent_runs.finish(conn, run_id=run["id"], outcome="ok",
                                     counts=counts, artifact_refs=[], detail=detail)
        return {"run": finished, "gaps": gaps, **counts}
    except Exception as exc:  # noqa: BLE001 - 台账必须记下失败本身的形状
        _finish_failed(conn, run["id"], exc)
        raise


def run_verifier(conn: Any, *, domain_key: str, limit: int = 200) -> dict:
    """质检一轮：把不值得人看的提案标出来。不改提案状态，不写本体。"""
    role = _role("verifier", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"verifier-{domain_key}")
    try:
        domain = workspaces.get_domain(conn, domain_key=domain_key)
        if domain is None:
            raise ValueError(f"domain {domain_key!r} not found")
        live = agent_ids_live_keys(conn, domain_key=domain_key)
        rel_kinds = _relationship_kinds(conn, domain)
        pending = proposals.list_proposals(conn, domain_key=domain_key,
                                           state="pending", limit=limit)
        cache: dict[tuple[str, str, str], Optional[str]] = {}

        def text_for(evidence: dict) -> Optional[str]:
            key = (str(evidence.get("library") or ""), str(evidence.get("source_key") or ""),
                   str(evidence.get("chunk_id") or ""))
            if not all(key):
                return None
            if key not in cache:
                try:
                    cache[key] = fetch_chunk_text(
                        conn, library=key[0], source_key=key[1], chunk_id=key[2])
                except Exception:  # noqa: BLE001 - 取不到 = 没法验，不是通过
                    cache[key] = None
            return cache[key]

        findings = _inspect(pending, live=live, rel_kinds=rel_kinds, text_for=text_for)

        by_check: dict[str, int] = {}
        for f in findings:
            by_check[f["check"]] = by_check.get(f["check"], 0) + 1
        clean = len(pending) - len({f["proposal_id"] for f in findings})
        counts = {"pending": len(pending), "flagged": len({f["proposal_id"] for f in findings}),
                  "clean": clean, "by_check": by_check}

        # 薄不薄看"有多少条其实不用人看"：一条都没标出来时，人不该以为质检白跑，
        # 那说明这批提案本来就干净，所以给 ok；只有当输入为空时才是 thin。
        outcome = "thin" if not pending else "ok"
        finished = agent_runs.finish(
            conn, run_id=run["id"], outcome=outcome, counts=counts,
            artifact_refs=[{"batch": p["batch"]} for p in _batches(pending)],
            detail=None if pending else "没有待确认提案",
        )
        return {"run": finished, "findings": findings, **counts}
    except Exception as exc:  # noqa: BLE001
        _finish_failed(conn, run["id"], exc)
        raise


def agent_ids_live_keys(conn: Any, *, domain_key: str) -> dict[str, str]:
    """``{key: kind}`` of live units — the set a proposal is checked against."""
    from . import authoring

    return authoring.authoring_live_key_kinds(conn, domain_key=domain_key)


def _relationship_kinds(conn: Any, domain: dict) -> set[str]:
    from . import templates

    tmpl = templates.get_template_by_id(conn, template_id=domain["template_id"])
    schema = (tmpl or {}).get("schema") or {}
    kinds = schema.get("relationship_kinds")
    return {str(k) for k in kinds} if isinstance(kinds, list) else set()


def _inspect(pending: list[dict], *, live: dict[str, str],
             rel_kinds: set[str], text_for: Optional[Any] = None) -> list[dict]:
    """四类机器判定 + 一类"没法验"。返回 findings，不改任何东西。"""
    findings: list[dict] = []
    seen_keys: dict[str, list[dict]] = {}
    for p in pending:
        key = (p.get("external_key") or "").strip()
        kind = p.get("kind") or ""
        seen_keys.setdefault(key, []).append(p)

        if key and key in live:
            findings.append(_finding(p, "key_already_live",
                                     f"键已存在于本体（kind={live[key]}）"))
            continue

        evidence = p.get("evidence") or {}
        if kind in rel_kinds:
            frm = evidence.get("from_key") or evidence.get("from")
            to = evidence.get("to_key") or evidence.get("to")
            if not frm or not to:
                findings.append(_finding(p, "missing_evidence",
                                         "关系提案缺少 from_key/to_key"))
                continue
            missing = [k for k in (frm, to) if k not in live]
            if missing:
                findings.append(_finding(p, "endpoint_open",
                                         f"端点不存在：{missing}"))
                continue
        else:
            if not evidence:
                findings.append(_finding(p, "missing_evidence", "没有依据"))
                continue
            if isinstance(evidence, dict) and "quote" in evidence:
                quote = str(evidence.get("quote") or "")
                text = None
                if text_for is not None:
                    text = text_for(evidence)
                if text is None:
                    # 拿不到原文就只能说"没法验"——不能报通过，那等于替人签字。
                    findings.append(_finding(p, "quote_unverifiable",
                                             "有引文但取不到原文，未核验"))
                elif not _quote_in(quote, text):
                    findings.append(_finding(p, "quote_mismatch",
                                             f"引文不在原文里：{quote[:40]}"))
                # 逐字命中 = 通过，不产生 finding（干净的就是干净的）

    # 同一实体的两种写法：同键多条（跨来源）在 pending 里就是重复主张
    for key, group in seen_keys.items():
        if len(group) > 1:
            for p in group[1:]:
                findings.append(_finding(p, "near_duplicate",
                                         f"与提案 {group[0]['id']} 同键"))
    return findings


def _quote_in(quote: str, text: str) -> bool:
    from .extraction import verify_quote

    return verify_quote(quote, text)


def _finding(proposal: dict, check: str, note: str) -> dict:
    return {"proposal_id": proposal["id"], "check": check, "note": note,
            "kind": proposal.get("kind"), "external_key": proposal.get("external_key"),
            "batch": proposal.get("batch") or _batch_of(proposal)}


def _batch_of(proposal: dict) -> Optional[str]:
    ev = proposal.get("evidence")
    return ev.get("batch") if isinstance(ev, dict) else None


def _batches(pending: list[dict]) -> list[dict]:
    return [{"batch": b} for b in {_batch_of(p) for p in pending} if b]


# ── 确定性写：取材员与结构员 ────────────────────────────────────────────────
#
# 这两个岗位拿到的是**写权限**，所以验收比只读岗硬：同一输入重跑两遍，第二遍必须
# 零新增；键未归名整批拒绝；一切写入只经内核（adopt_* → authoring_*）。
# 它们只读本域**已经订阅**的范围（effective_sources），不做任何放宽订阅的动作。


def _role_params(domain_key: str, role: str) -> dict:
    plan = agent_team.plan(domain_key)
    for entry in plan.get("runnable") or []:
        if entry["role"] == role:
            return entry.get("params") or {}
    return {}


def run_scout(conn: Any, *, domain_key: str, limit: Optional[int] = None) -> dict:
    """取材一轮：把目录里的文档取成本体里的文档单位。确定性、幂等。"""
    role = _role("scout", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"scout-{domain_key}")
    try:
        params = _role_params(domain_key, role)
        take = max(1, min(int(limit or params.get("limit") or 20), 50))
        wanted = {str(k) for k in (params.get("doc_types") or [])}
        only_sources = {str(k) for k in (params.get("sources") or [])}

        domain = workspaces.get_domain(conn, domain_key=domain_key)
        scope = libraries.effective_sources(conn, domain_path=domain.get("path") or domain_key)
        adopted, skipped_kind, considered, already = 0, 0, 0, 0
        unapplied: list[str] = []
        per_source: dict[str, int] = {}

        for lib_key, allowed in scope.items():
            for source_key in sorted(allowed):
                if only_sources and source_key not in only_sources:
                    continue
                try:
                    page = corpus_catalog.documents(
                        conn, library_key=lib_key, source_key=source_key,
                        limit=take, domain_key=domain_key,
                    )
                except (corpus_catalog.DocumentMappingError, corpus_catalog.StoreError) as exc:
                    per_source[f"{lib_key}/{source_key}"] = -1
                    unapplied.append(f"{source_key}: {type(exc).__name__}")
                    continue
                # 稳定排序：目录按块数降序，同分文档的顺序不稳定，两次调用可能返回
                # 不同的前 N 份——实测第二遍又取了 20 份新文档，"幂等"当场破产。
                # 按 id 排是确定性的，配合"跳过已取入"才能真收敛。
                rows = sorted(page["rows"], key=lambda r: str(r["id"]))
                kinds = {r.get("kind") for r in rows}
                # 文种筛选只在来源真的给出文种时才有意义；给不出就如实说"未筛"，
                # 不能假装筛过（否则上层会以为噪声已被过滤）。
                apply_kind = bool(wanted) and any(kinds)
                if wanted and not any(kinds):
                    unapplied.append(f"{source_key}: 来源未提供文种字段，未按文种筛选")
                for row in rows:
                    considered += 1
                    if apply_kind and (row.get("kind") or "") not in wanted:
                        skipped_kind += 1
                        continue
                    if adopted >= take:
                        break
                    if row.get("adopted_as"):
                        already += 1
                        continue
                    out = corpus_catalog.adopt_document(
                        conn, domain_key=domain_key, library_key=lib_key,
                        source_key=source_key, doc_id=row["id"], operator=role,
                    )
                    if out.get("created"):
                        adopted += 1
                    per_source[f"{lib_key}/{source_key}"] = per_source.get(
                        f"{lib_key}/{source_key}", 0) + 1

        counts = {"considered": considered, "adopted": adopted,
                  "already_adopted": already,
                  "skipped_kind": skipped_kind, "per_source": per_source}
        outcome = "ok"
        detail = None
        if wanted and unapplied:
            detail = "文种筛选未完全生效：" + "；".join(unapplied)[:200]
            outcome = "thin"          # 筛选没生效 = 结果比预期宽，要人看一眼
        finished = agent_runs.finish(conn, run_id=run["id"], outcome=outcome,
                                     counts=counts, detail=detail)
        return {"run": finished, **counts, "warnings": unapplied}
    except Exception as exc:  # noqa: BLE001
        _finish_failed(conn, run["id"], exc)
        raise


def run_builder(conn: Any, *, domain_key: str, limit: int = MAX_BUILDER_DOCS) -> dict:
    """结构一轮：给已取入的文档补条款。只补「还一条都没有」的文档，避免每轮重扫。"""
    role = _role("builder", domain_key)
    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=f"builder-{domain_key}")
    try:
        live = authoring.authoring_live_keys(conn, domain_key=domain_key)
        # 只认"文档"：条款单位同样带 attrs.corpus（它们也是从语料取来的），
        # 用 clause_no 把它们排除，否则结构员会把条款当文档再切一遍。
        docs = [
            u for u in authoring.authoring_live_entities(conn, domain_key=domain_key, limit=100000)
            if (u.get("attrs") or {}).get("corpus")
            and "clause_no" not in (u.get("attrs") or {})
        ]
        built, already, skipped = 0, 0, []
        for unit in docs[:limit]:
            corpus = (unit.get("attrs") or {}).get("corpus") or {}
            lib_key = corpus.get("library")
            src_key = corpus.get("source_key")
            doc_id = corpus.get("doc_id")
            if not (lib_key and src_key and doc_id):
                skipped.append({"key": unit["external_key"], "reason": "缺少语料坐标"})
                continue
            # 已有条款则跳过：本岗位只负责"从无到有"，不负责反复重扫。
            # 必须要求键里真的有 "#"：文档键自己 split("#")[0] 也等于自己，
            # 少了这个条件，每份文档都会被判成"已有条款"，结构员永远不干活。
            if any("#" in k and k.split("#", 1)[0] == unit["external_key"] for k in live):
                already += 1
                continue
            try:
                out = corpus_catalog.adopt_clauses(
                    conn, domain_key=domain_key, library_key=lib_key,
                    source_key=src_key, doc_id=doc_id, operator=role,
                    law_key=unit["external_key"],
                )
            except corpus_catalog.DocumentMappingError as exc:
                skipped.append({"key": unit["external_key"], "reason": str(exc)[:80]})
                continue
            if out.get("adopted"):
                built += 1
            elif out.get("reason"):
                skipped.append({"key": unit["external_key"], "reason": out["reason"]})

        counts = {"documents": len(docs[:limit]), "built": built,
                  "already_had_clauses": already, "skipped": len(skipped)}
        finished = agent_runs.finish(conn, run_id=run["id"], outcome="ok" if docs else "thin",
                                     counts=counts,
                                     detail=None if docs else "本域没有已取入的文档")
        return {"run": finished, **counts, "skips": skipped[:10]}
    except Exception as exc:  # noqa: BLE001
        _finish_failed(conn, run["id"], exc)
        raise


# ── 只提案：概念员 ──────────────────────────────────────────────────────────
#
# 团队里唯一需要模型判断的岗位，所以它的纪律最紧：**产出只有 pending 提案，
# 一个单位都不直接写**。加速的办法不在"让它多写"，而在批摘要与批量抽取。

def run_concept(
    conn: Any, *,
    domain_key: str,
    max_chunks: Optional[int] = None,
    batch: Optional[str] = None,
    complete_fn: Optional[Any] = None,
) -> dict:
    """概念一轮：从语料抽候选 → 落 pending 提案 → 记台账与批摘要。"""
    from . import extraction

    role = _role("concept", domain_key)
    params = _role_params(domain_key, role)
    chunks = int(max_chunks or params.get("batch_chunks") or 10)
    floor = float(params.get("min_usable_rate") or 0.5)
    cap = int(params.get("max_total") or 100)
    # 语料面由该线声明：概念只从长于说理的那类语料里来，声明在哪由 pack 决定。
    # 没声明就不指定（保持原有"整个订阅范围"的语义）。
    sources = [str(x) for x in (params.get("sources") or [])] or None
    batch_name = batch or f"concept-{domain_key}-{_stamp()}"

    run = agent_runs.start(conn, role=role, domain_key=domain_key,
                           run_key=batch_name, input_digest=batch_name)
    try:
        report = extraction.run(
            conn, domain_key=domain_key,
            sources=sources, max_chunks=chunks, max_total=cap,
            batch=batch_name, complete_fn=complete_fn, submitted_by=role,
        )
        summary = _batch_summary(report, batch_name=batch_name)
        rate = float(report.get("usable_rate") or 0.0)
        thin = report.get("submitted", 0) == 0 or rate < floor
        counts = {
            "sampled": report.get("sampled", 0),
            "produced": report.get("produced", 0),
            "submitted": report.get("submitted", 0),
            "duplicate": report.get("duplicate", 0),
            "usable_rate": round(rate, 3),
            "by_kind": report.get("by_kind") or {},
            "skipped": report.get("skipped") or {},
        }
        finished = agent_runs.finish(
            conn, run_id=run["id"],
            outcome="thin" if thin else "ok",
            counts={**counts, "batch": batch_name},
            artifact_refs=[{"batch": batch_name}],
            detail=summary,
        )
        return {"run": finished, "batch": batch_name, "summary": summary, **counts}
    except Exception as exc:  # noqa: BLE001
        _finish_failed(conn, run["id"], exc)
        raise


def _batch_summary(report: dict, *, batch_name: str) -> str:
    """批摘要：一批提案的共同主张、被丢掉的原因、以及它自己没把握的部分。

    没有摘要的批次不受理（复核按批决策的前提）。摘要只陈述**可核对的事实**：
    抽了多少块、各类候选多少、哪些被证据/端点/词表闸拒掉——不写"这批很有价值"
    这类无法核对的话。
    """
    by_kind = report.get("by_kind") or {}
    skipped = {k: v for k, v in (report.get("skipped") or {}).items() if v}
    parts = [
        f"批 {batch_name}：采样 {report.get('sampled', 0)} 块，"
        f"产出 {report.get('produced', 0)} 条，入箱 {report.get('submitted', 0)} 条，"
        f"可用率 {round(float(report.get('usable_rate') or 0), 3)}"
    ]
    if by_kind:
        parts.append("类型分布：" + "、".join(f"{k}×{v}" for k, v in sorted(by_kind.items())))
    if skipped:
        parts.append("被闸门拒掉：" + "、".join(f"{k}×{v}" for k, v in sorted(skipped.items())))
    if report.get("stopped"):
        parts.append(f"提前停止：{report['stopped']}")
    if not by_kind and not skipped:
        parts.append("本轮没有产生任何候选（语料可能不含可抽内容）")
    return "；".join(parts)


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
