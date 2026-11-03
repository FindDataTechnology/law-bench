#!/usr/bin/env python3
"""Standalone CLI twin of tests/test_kernel_domain_free.py.

Enforces the same domain-freedom criteria for the ``src/bench`` kernel as the
pytest gate — the banned-domain-term scan and the no-pack-import audit —
without needing pytest, so it can run in CI hooks or pre-commit. The criteria
(word list, AST import audit) live only in tests/test_kernel_domain_free.py
and are imported from there, so the two implementations cannot drift apart.

Usage (from the repository root):

    python3 scripts/check_kernel_domain_free.py

Exit codes: 0 = kernel is domain-free, 1 = violations found (details printed).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The criteria live in the test module (single source of truth); tests/ is not
# a package, so put it on sys.path and import the module directly.
_TESTS_DIR = REPO_ROOT / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from test_kernel_domain_free import (  # noqa: E402
    collect_kernel_files,
    find_domain_term_violations,
    find_pack_import_violations,
    missing_core_kernel_files,
)


def main() -> int:
    files = collect_kernel_files()
    violations: list[str] = []
    violations.extend(missing_core_kernel_files(files))
    violations.extend(find_domain_term_violations(files))
    violations.extend(find_pack_import_violations(files))
    if violations:
        print(f"kernel domain-free: FAILED ({len(violations)} violation(s))")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print(f"kernel domain-free: OK ({len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
