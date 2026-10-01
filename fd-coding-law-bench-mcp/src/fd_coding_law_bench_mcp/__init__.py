"""FastMCP server exposing law-bench contract generation, evaluation, and RAG
search as MCP tools. Wraps the existing ``src.*`` modules in place - nothing is
relocated.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the law-template repo root importable so ``import src.*`` works when this
# package runs from an editable install / source checkout. No-op for non-source
# layouts (the shared venv must otherwise expose ``src`` on sys.path) - including
# shallow site-packages targets where the fourth parent does not exist.
_PARENTS = Path(__file__).resolve().parents
if len(_PARENTS) > 3:
    _REPO_ROOT = _PARENTS[3]
    if (_REPO_ROOT / "src").is_dir() and str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

__version__ = "0.1.0"
