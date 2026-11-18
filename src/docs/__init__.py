"""Compatibility shim — ``src.docs`` has moved to :mod:`src.generator`.

This package is preserved *only* so out-of-tree callers that still write
``from src.docs import ...`` or ``from src.docs.slots import ...`` (notably
``contract-review-agent`` and ``fd-coding-law-bench-mcp``, which are outside
this project's refactor scope) keep resolving without a code change.

New code must import from :mod:`src.generator`. This shim emits no warning at
runtime (sibling subprojects import it on every run); the deprecation is
documented here and in the move commit. The aliasing is thin: every public
name and every submodule (``slots`` / ``generator`` / ``converter``) delegates
to the real :mod:`src.generator` package.
"""

from __future__ import annotations

import importlib
import sys

# Re-export the moved package's public surface so
# `from src.docs import SLOT_PATTERN, create_docx, ...` keeps working.
from src.generator import *  # noqa: F401,F403
from src.generator import __all__  # noqa: F401

# Alias the submodules both in ``sys.modules`` AND as attributes of this
# package, so all three access shapes resolve to the moved modules:
#   - `from src.docs.slots import X`          (sys.modules lookup)
#   - `import src.docs.slots`                 (sys.modules + attr bind)
#   - `import src.docs` then `src.docs.slots` (attribute lookup)
# Importing `src.docs` always runs this __init__ first, so the aliases are in
# place before any submodule name is resolved.
_docs = sys.modules[__name__]
for _sub in ("slots", "generator", "converter"):
    _mod = importlib.import_module(f"src.generator.{_sub}")
    sys.modules[f"src.docs.{_sub}"] = _mod
    setattr(_docs, _sub, _mod)

del _docs, _sub, _mod, importlib, sys
