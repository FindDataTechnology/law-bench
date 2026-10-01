"""Entry point: ``python -m fd_coding_law_bench_mcp``.

Loads ``.env`` (law-bench reads DB / RAG / LLM config from it) then serves the
MCP server — stdio by default, or streamable HTTP when ``MCP_HTTP_TRANSPORT``
is ``http`` (which additionally requires ``MCP_HTTP_TOKEN``; see
``fd_coding_law_bench_mcp.server.main``).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from .server import main

# law-template repo root (this package lives at
# <repo>/fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/). Used to locate
# .env regardless of the launch cwd, so the server works when an MCP client
# starts it from a working directory that is not the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _entry() -> int:
    # law-bench reads DB / RAG / LLM config from .env; load it from the repo
    # root before serving.
    load_dotenv(_REPO_ROOT / ".env")
    main()  # blocks: serves stdio or HTTP depending on MCP_HTTP_TRANSPORT
    return 0


if __name__ == "__main__":
    raise SystemExit(_entry())
