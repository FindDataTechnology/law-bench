"""线自描述端点 ``/.well-known/line-manifest.json``（change converge-line-identity-and-keys 1.4）。

家族实现：公开、免鉴权、零网络。**原样回吐**仓根 ``line-manifest.json``——那份是
唯一真源，端点只是它的投影；这里一旦加工（解析后再 dump、补字段、重排键），就会
出现第二个真源，两处投影必然漂移。

为什么路径是「候选链」而不是一条固定的：同一个包在两种布局下运行。

* **源码树**：``<repo>/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/wellknown.py``
  ——``parents[3]`` 是仓根 ``<repo>``（本仓的真源就在这里）。
* **镜像**：``uv pip install ./deps/lawbench-mcp`` 把包装进
  ``/app/.venv/lib/python3.12/site-packages/fd_coding_law_bench_mcp/``，
  ``parents[3]`` 落在 ``/app/.venv/lib``——那里没有清单。镜像里真正的那份是
  ``WORKDIR /app`` 下的 ``line-manifest.json``（Dockerfile ``COPY line-manifest.json ./``），
  所以 ``Path.cwd()`` 必须排在源码树之后、包同级之前。

``LINE_MANIFEST_PATH`` 一项即封顶：部署方显式指路时不再往下猜。

两个状态码分得很清：**缺失=404**（该线未发布清单，属配置事实）；**存在但不可解析
=500**（属缺陷，不能伪装成 404 让调用方以为"本来就没有"）。

门（``server._TokenGuard``）的豁免集合 ``server.EXEMPT_PATHS`` 引用本模块的
``WELL_KNOWN_PATH``——路由与豁免是两个落点，但路径字面量只在这里出现一次。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

#: 与 ``fd-info`` / ``wire-ops-mcp`` / ``facet-ops-mcp`` 逐字相同的路径常量。
WELL_KNOWN_PATH = "/.well-known/line-manifest.json"
ENV_MANIFEST_PATH = "LINE_MANIFEST_PATH"
#: 清单是运行期契约：改一次要生效，但不能让边缘缓存长期撒谎。
CACHE_CONTROL = "public, max-age=300"

CONTENT_TYPE = "application/json; charset=utf-8"


def manifest_candidates() -> list[Path]:
    """按优先级列出可能放清单的位置（``LINE_MANIFEST_PATH`` 一项即封顶）。

    ``parents[3]`` 只有在布局够深时才存在；site-packages 也好、源码树也好都够深，
    但仍按 ``__init__`` 的做法做长度守卫，避免浅装布局在导入期抛 IndexError。
    """
    override = os.environ.get(ENV_MANIFEST_PATH)
    if override:
        return [Path(override)]
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    if len(here.parents) > 3:  # 源码树：<repo>/fd-coding-law-bench-mcp/src/<pkg>/wellknown.py
        candidates.append(here.parents[3] / "line-manifest.json")
    candidates.append(Path.cwd() / "line-manifest.json")  # 镜像 WORKDIR /app
    candidates.append(here.parent / "line-manifest.json")  # 清单与包同级（兜底）
    return candidates


def manifest_path() -> Path:
    """实际取用的清单路径；都不存在时返回首选位置（让 404 能点名期望路径）。"""
    candidates = manifest_candidates()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def manifest_response() -> tuple[int, bytes, dict[str, str]]:
    """(status, body, headers) —— 不读网络、不建会话。

    成功时附 ``Cache-Control``，失败时不附：让缓存别把一个"暂时没发布"的 404 记成
    长期事实。``content-type`` 由路由层统一给（失败体也是 JSON），本函数只管字节。
    """
    path = manifest_path()
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return 404, b'{"detail":"line-manifest not published"}', {}
    except OSError as exc:
        detail = f"line-manifest unreadable: {type(exc).__name__}"
        return 500, json.dumps({"detail": detail}).encode(), {}
    try:
        json.loads(raw)
    except ValueError:
        return 500, b'{"detail":"line-manifest is not valid JSON"}', {}
    return 200, raw, {"cache-control": CACHE_CONTROL}


def register(mcp) -> None:
    """把端点挂到 ``FastMCP`` 实例上（stdio 形态下无 HTTP 面，不挂）。

    用 ``custom_route`` 而不是自己包一层 ASGI：路由属于应用本身，于是**两个分支都在**
    ——stdio 不挂、http 挂；HTTP 形态下 ``create_streamable_http_app`` 把自定义路由
    追加在 ``/mcp`` 之后，但两者路径精确、互不遮挡（本应用没有 SPA 兜底）。
    鉴权门的豁免在 ``server.EXEMPT_PATHS``，两处必须同时改，否则配了令牌的线仍然
    对匿名发现请求回 401。
    """
    if not hasattr(mcp, "custom_route"):  # pragma: no cover - 依赖缺失时宁可起不来
        raise RuntimeError(
            "fastmcp 缺 custom_route：无法挂 " + WELL_KNOWN_PATH + "（升级依赖，别静默跳过）"
        )
    from starlette.responses import Response

    @mcp.custom_route(WELL_KNOWN_PATH, methods=["GET"])
    async def line_manifest(_request):  # noqa: ANN001 - ASGI 边界，不需要类型
        status, body, headers = manifest_response()
        return Response(
            content=body, status_code=status, media_type=CONTENT_TYPE, headers=headers
        )
