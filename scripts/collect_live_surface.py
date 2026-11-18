#!/usr/bin/env python3
"""在 pod 内采集已声明工具的 live 返回形状（change lex-matter-spine 5.6 的采集侧）。

为什么必须在 pod 内跑：MCP 面只监听 `127.0.0.1:8080`，且要 `MCP_HTTP_TOKEN`；
从集群外打它得先过网关（网关会剥客户端凭据，形状与直连不同）。

产出是**给比对器吃的数据**，不是结论：
    python3 scripts/collect_live_surface.py --out /tmp/live-surface.json
再由 `check_declared_vs_live.py` 与 `tool-surface.json` 的声明逐键比对。

设计上的三条约束：
1. 只采集 `output_structure.declared` 里的工具——未声明的没有可比的契约；
2. 每工具的参数显式登记在 `CALL_ARGS`，不猜默认值：无参调用会返回空集，
   空集无法验证"字段形状"（这正是 11-09 单样本误判的同类错误）；
3. 采集失败不静默：记 `error` 字段原样带回，由比对器判红。

退出码：0 采集完成（哪怕个别工具报错，错误也写进产物）/ 1 环境不成立。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "tool-surface.json"
BASE = os.environ.get("MCP_BASE_URL", "http://127.0.0.1:8080/mcp")

# 每工具的采集参数：要给"能产出非空结构"的入参，否则形状验不出来。
CALL_ARGS: dict[str, dict] = {
    "contract_generate": {"contract_type": "bailment"},
    "type_metadata": {"contract_type": "bailment"},
    "contract_type_catalog": {},
    "tag_vocab_list": {"contract_type": "bailment"},
    # 实测（2026-11-10）：这两个工具的 contract_type 是**必填**，无参调用返回
    # pydantic missing_argument 的 isError=true——不填参数就等于没采到形状。
    "validation_check": {"contract_type": "bailment"},
    "validation_list": {"contract_type": "bailment"},
    "law_references": {},
    "law_types": {},
    # 2026-11-11 起 law_info 有数据（种子 86 行），必须给入参才能采到正文形状
    "law_info": {"contract_type": "sale"},
    "clause_list": {},
    "search_clauses": {"query": "违约金"},
    # 5.5 批次二新增：每件都给足必填入参，否则采到的是"缺参数"错误而不是形状。
    "tag_validate": {"tags": {"stance": "pro_a"}},
    "tag_combinations_list": {"contract_type": "bailment"},
    "contract_content": {"contract_type": "bailment"},
    "task_status": {"handle": "nonexistent-handle"},
    "task_failed_items": {"handle": "nonexistent-handle"},
    "clause_get": {"clause_id": {"$first": ["clause_list", "result", "id"]}},
    "contract_download": {"artifact_id": 1},
    "contract_generate_batch": {"contract_type": "bailment", "tag_combinations": [{"stance": "pro_a"}]},
    # 2026-11-11：format=markdown 只存正文、**不经对象存储**，故本工具可在无 RustFS
    # 依赖的情况下采到真形状（此前把它整件归为「依赖 MinIO」是错判）。
    # 它按 contract_type+scenario+stance 复用，复调返回 new=0/reused=1，
    # 因此反复采集不会累积行；落库行 body_hash=md5(空串) 是已知探针产物。
    "contract_generate_stored": {"contract_type": "bailment", "format": "markdown"},
    # `clause_id` **不能写死**：重跑 `load_one` 是 DELETE+INSERT，id 会整体换号
    # （实测 1 → 6 就是这么飞的，写死会让下一次采集报 clause not found）。
    # `$first` 表示「先调 clause_list，取 result[0].id」；解析见 resolve_args。
    # status 用 pending：种子条款本来就是待审，这样反复采集不改任何评审状态，
    # 也不会伪造一次「人工已批准」。
    "clause_review": {"clause_id": {"$first": ["clause_list", "result", "id"]}, "status": "pending"},
}


def post(payload: dict, sid: str | None) -> tuple[dict, str | None]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    token = os.environ.get("MCP_HTTP_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    if sid:
        headers["mcp-session-id"] = sid
    request = urllib.request.Request(BASE, data=json.dumps(payload).encode(), headers=headers)
    response = urllib.request.urlopen(request, timeout=120)
    raw = response.read().decode("utf-8", "replace")
    # streamable HTTP 把 JSON-RPC 装在 SSE 的 data: 行里
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    return (json.loads(raw) if raw.strip() else {}), response.headers.get("mcp-session-id")


def call_tool(name: str, arguments: dict, sid: str | None, index: int = 1) -> dict:
    """调一次 tools/call，返回原始 reply。"""
    reply, _ = post(
        {
            "jsonrpc": "2.0",
            "id": index,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        sid,
    )
    return reply


def resolve_args(arguments: dict, sid: str | None) -> dict:
    """解析依赖参数：`{"$first": [tool, container, key]}` → 该工具返回的第一条元素字段。

    存在的理由：有些工具的入参必须是**已存在**的业务 id（`clause_id`），而 id 由
    装载/重建决定、会换号。写死 id 的采集器过几天就会变成 `clause not found`，
    而那种红是"采集器坏了"不是"声明错了"，会稀释比对器的信号。
    """
    out: dict = {}
    for key, value in arguments.items():
        if isinstance(value, dict) and "$first" in value:
            tool, container, elem = value["$first"]
            reply = call_tool(tool, CALL_ARGS.get(tool, {}), sid)
            structured = (reply.get("result") or {}).get("structuredContent") or {}
            items = structured.get(container) or []
            out[key] = items[0][elem] if items else None
            print(f"  [derived] {key}={out[key]} (from {tool}.{container}[0].{elem})", file=sys.stderr)
        else:
            out[key] = value
    return out


def shape(value: object) -> object:
    """把返回值压成"可比的形状"：只留类型与键名，不留内容。"""
    if isinstance(value, dict):
        return {k: shape(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        # 空集也要能表达：记成空列表，比对器会把它当"未观测到元素形状"
        return [shape(value[0])] if value else []
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if value is None:
        return "null"
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    # pod 里脚本会被 cp 到 /tmp（仓目录不在运行镜像里），所以允许显式给 manifest
    ap.add_argument("--manifest", default=str(MANIFEST))
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"manifest 缺失：{manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = manifest["output_structure"]["declared"]

    init, sid = post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "surface-collector", "version": "1"},
            },
        },
        None,
    )
    server = (init.get("result") or {}).get("serverInfo") or {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    print(f"connected: {server.get('name')} {server.get('version')}", file=sys.stderr)

    out: dict[str, object] = {
        "server": server,
        "base": BASE,
        "tools": {},
    }
    for index, name in enumerate(declared, start=10):
        call_args = resolve_args(CALL_ARGS.get(name, {}), sid)
        try:
            reply = call_tool(name, call_args, sid, index)
            result = reply.get("result") or {}
            structured = result.get("structuredContent")
            entry = {
                "args": call_args,
                "isError": result.get("isError"),
            }
            if structured is None:
                entry["error"] = (reply.get("error") or {}).get("message") or "no structuredContent"
            else:
                entry["shape"] = shape(structured)
            out["tools"][name] = entry
            print(f"  {name}: {'ERR' if 'error' in entry else 'ok'}", file=sys.stderr)
        except Exception as exc:  # 采集失败要留痕，不能静默跳过
            out["tools"][name] = {"args": call_args, "error": f"{type(exc).__name__}: {exc}"}
            print(f"  {name}: EXC {type(exc).__name__}", file=sys.stderr)

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {args.out}（{len(out['tools'])} 件）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
