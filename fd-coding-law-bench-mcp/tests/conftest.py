"""Pytest path bootstrap for the fd-coding-law-bench-mcp project.

Lets ``import fd_coding_law_bench_mcp`` work without an editable install by
putting the project's ``src/`` on ``sys.path``. The package's own ``__init__``
then puts the law-template repo root on ``sys.path`` so ``import src.*`` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PKG_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PKG_SRC) not in sys.path:
    sys.path.insert(0, str(_PKG_SRC))


# Configure pytest-asyncio to auto-run `async def test_*` functions. The
# pytest-asyncio plugin is already installed; we set the mode to "auto" so tests
# don't need @pytest.mark.asyncio on each one.
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as asyncio")
    # Set asyncio mode to auto if not already set
    if not config.getini("asyncio_mode"):
        config._inicfg = config._inicfg or {}
        config._inicfg["asyncio_mode"] = "auto"
