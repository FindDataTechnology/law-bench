#!/usr/bin/env python3
"""Run the ontology conformance gate against this repo's own adapter.

Standalone-checkout entry point (same shape as ``fd-open-data-protocol/scripts/
ontology_gate.py``). The workspace-root ``scripts/ontology_conformance_gate.py``
cannot be used from CI: each repo is checked out on its own, and the kernel has
**no git remote** to fetch (it is not a git repository). So this surface keeps a
one-entry registry next to itself (``ontology-adapter.json``) and this launcher
pins it.

Unlike the other surfaces this one needs a **live PostgreSQL**: the ports under
test are psycopg + PG dialect (JSONB, ``RETURNING``, ``now()``), so an in-memory
sandbox would only prove that the kernel's own memory ports work. The sandbox
creates one throwaway database per run and drops it at exit; business data is
never touched. ``database_url`` comes from the environment or the ``.env`` next
to this file.

Usage::

    python3 scripts/ontology_gate.py            # check this repo's adapter
    python3 scripts/ontology_gate.py --list     # what is registered here

Exit codes are the gate's: ``0`` passed, ``1`` violations (each printed with its
fix), ``2`` the gate could not run (including "no database reachable").
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "ontology-adapter.json"

# The registry's `paths: ["src", "."]` is resolved against the registry file, so
# this is belt-and-braces: it also makes the packages importable when the
# registry is passed explicitly from elsewhere.
for _root in (str(REPO_ROOT / "src"), str(REPO_ROOT)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

try:
    from fd_ontology_kernel.conformance.gate import main
except ModuleNotFoundError:  # pragma: no cover - CI installs the wheel first
    raise SystemExit(
        "闸门 · 前置 · 装不到 fd_ontology_kernel · "
        "修法：先装本仓 vendored 的内核 wheel（uv pip install vendor/*.whl），再跑这条命令"
    )


if __name__ == "__main__":
    argv = list(sys.argv[1:])
    if not any(arg.startswith("--registry") for arg in argv):
        argv = ["--registry", str(REGISTRY), *argv]
    if not any(
        arg in {"--list", "--all"} or arg.startswith("--adapter") for arg in argv
    ):
        argv.append("--all")
    raise SystemExit(main(argv))
