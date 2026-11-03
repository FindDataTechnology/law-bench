"""Domain-freedom regression gate for the ``src/bench`` kernel.

The knowledge-bench kernel under ``src/bench/`` must stay domain-neutral: all
legal (or any other vertical) knowledge and vocabulary lives in domain packs
under ``packs/``. These tests pin that invariant as a hard regression gate:

- ``test_kernel_source_has_no_domain_terms`` scans every kernel source file
  for domain-specific terms (identifiers or Chinese legal vocabulary). Zero
  hits are allowed; there are no exceptions.
- ``test_kernel_imports_no_pack`` parses every kernel source file and asserts
  that nothing is imported from a domain pack (any module whose top-level name
  is or starts with ``packs``) and that no relative import escapes the kernel
  package. The kernel may import stdlib and third-party packages only.

``scripts/check_kernel_domain_free.py`` is a standalone CLI that enforces the
exact same criteria by importing the functions below — the word list lives
only here so the two implementations cannot drift apart.

This module must stay importable without pytest (the CLI runs it under a bare
``python3``): use stdlib imports only, and express checks as plain asserts.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KERNEL_DIR = REPO_ROOT / "src" / "bench"

# Domain terms that must never appear in kernel source (case-insensitive).
# ``clause`` is a generic kind name owned by the kernel and is deliberately
# NOT on this list.
BANNED_TERMS: tuple[str, ...] = (
    "law_catalog",
    "contract_type",
    "law_ref",
    "民法典",
    "法条",
    "法规",
    "合同",
)

# Files whose presence proves we are really looking at the kernel; without
# them the gates below could pass vacuously on an empty directory.
_REQUIRED_KERNEL_FILES: tuple[str, ...] = ("__init__.py", "store.py")


def collect_kernel_files() -> list[Path]:
    """All Python files under src/bench (sorted; __pycache__ excluded)."""
    if not KERNEL_DIR.is_dir():
        return []
    return sorted(
        p for p in KERNEL_DIR.rglob("*.py") if "__pycache__" not in p.parts
    )


def _rel_to_repo(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def missing_core_kernel_files(files: list[Path] | None = None) -> list[str]:
    """Sanity guard so the gates cannot pass vacuously: if the kernel skeleton
    itself is missing (src/bench moved or emptied), report it instead of
    letting an empty file list look "clean"."""
    if files is None:
        files = collect_kernel_files()
    found = sorted(p.name for p in files)
    problems: list[str] = []
    for required in _REQUIRED_KERNEL_FILES:
        if required not in found:
            problems.append(
                f"src/bench/{required} not found: kernel gate would be "
                f"vacuous (python files under src/bench: {found or 'none'})"
            )
    return problems


def find_domain_term_violations(files: list[Path]) -> list[str]:
    """Scan each file line-by-line for banned domain terms (case-insensitive).

    Returns one formatted line per (file, term, line) hit; empty means clean.
    A line containing two different terms is reported once per term.
    """
    violations: list[str] = []
    for path in files:
        rel = _rel_to_repo(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{rel}: unreadable as UTF-8 text: {exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for term in BANNED_TERMS:
                if term in lowered:
                    violations.append(
                        f"{rel}:{lineno}: banned domain term {term!r} "
                        f"in: {line.strip()}"
                    )
    return violations


def _is_pack_module(top_level_name: str) -> bool:
    """True for any module whose top-level import name is or starts with
    ``packs`` (covers ``packs``, ``packs.legal`` and ``packs*`` siblings).
    The kernel may import stdlib and third parties only."""
    return top_level_name.startswith("packs")


def _relative_import_escapes_kernel(path: Path, level: int) -> bool:
    """True if a relative import of the given level from ``path`` would leave
    the kernel package (src/bench). A file directly in src/bench may use
    level 1 (still inside the kernel); each extra directory level under
    src/bench allows one more dot before the import escapes the kernel."""
    depth_under_kernel = len(path.parent.relative_to(KERNEL_DIR).parts)
    return level > depth_under_kernel + 1


def find_pack_import_violations(files: list[Path]) -> list[str]:
    """AST-audit every file's imports for domain-pack reachability.

    Returns one formatted violation line per offense; empty means clean.
    - ``import packs`` / ``import packs.legal`` / ``from packs.x import y``:
      top-level import name is or starts with ``packs`` -> violation.
    - Relative imports (level > 0) cannot be resolved to an absolute pack
      name, so they are skipped for the name check — but one that escapes the
      kernel package is itself a violation (that is how a pack could be
      reached without ever naming ``packs``).
    """
    violations: list[str] = []
    for path in files:
        rel = _rel_to_repo(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{rel}: syntax error, cannot audit imports: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_pack_module(alias.name.split(".", 1)[0]):
                        violations.append(
                            f"{rel}:{node.lineno}: import of domain pack "
                            f"module {alias.name!r} (kernel must not import packs)"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.level > 0:
                    if _relative_import_escapes_kernel(path, node.level):
                        target = "." * node.level + (node.module or "")
                        violations.append(
                            f"{rel}:{node.lineno}: relative import {target!r} "
                            f"(level={node.level}) escapes the kernel package"
                        )
                    continue
                module = node.module or ""
                if _is_pack_module(module.split(".", 1)[0]):
                    violations.append(
                        f"{rel}:{node.lineno}: import of domain pack "
                        f"module {module!r} (kernel must not import packs)"
                    )
    return violations


def test_kernel_source_has_no_domain_terms() -> None:
    files = collect_kernel_files()
    missing = missing_core_kernel_files(files)
    assert not missing, "kernel source gate cannot run:\n" + "\n".join(missing)
    violations = find_domain_term_violations(files)
    assert not violations, (
        f"src/bench kernel is not domain-free: {len(violations)} banned-term "
        "hit(s). Domain logic and vocabulary belong in domain packs (packs/), "
        "never in the kernel:\n" + "\n".join(violations)
    )


def test_kernel_imports_no_pack() -> None:
    files = collect_kernel_files()
    missing = missing_core_kernel_files(files)
    assert not missing, "kernel import gate cannot run:\n" + "\n".join(missing)
    violations = find_pack_import_violations(files)
    assert not violations, (
        f"src/bench kernel reaches a domain pack: {len(violations)} "
        "violation(s). The kernel may import stdlib/third-party modules only "
        "(never 'packs*'; relative imports must stay inside the kernel):\n"
        + "\n".join(violations)
    )
