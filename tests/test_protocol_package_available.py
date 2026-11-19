"""The observation-layer importer works from the installed package.

``scripts/import_protocol_ontology.py`` reads the outside-world vocabulary from
``fd-open-data-protocol``. That package must be importable **in the image**, not
just from a sibling checkout on a developer's machine — otherwise the import
step works locally and fails in production, which is exactly the gap this test
pins (found 2026-11-19: the script shipped, the dependency did not).

The sibling-checkout path stays supported for local work against an unreleased
protocol change; that branch is covered by the CLI being run with an explicit
``--protocol-dir``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_protocol_package_is_importable():
    """It must be installed, not merely present as a sibling checkout."""
    assert importlib.util.find_spec("fd_open_data_protocol") is not None, (
        "fd-open-data-protocol is not installed — the importer would work on a "
        "developer machine (sibling checkout) and fail in the image. It ships as "
        "vendor/fd_open_data_protocol-*.whl (see pyproject [tool.uv.sources])."
    )


def test_wheel_is_vendored():
    """The wheel must be in the build context, or CI/Docker cannot install it."""
    wheels = list((REPO_ROOT / "vendor").glob("fd_open_data_protocol-*.whl"))
    assert len(wheels) == 1, (
        f"expected exactly one vendored protocol wheel, found {wheels}"
    )


def test_declared_as_a_dependency():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"fd-open-data-protocol"' in text, "not in [project.dependencies]"
    assert "vendor/fd_open_data_protocol-" in text, "no [tool.uv.sources] path"


def test_vocabulary_loads_and_has_the_expected_shape():
    from fd_open_data_protocol.vocabulary import load_vocabulary

    registry = load_vocabulary()
    assert len(registry.entity_type_ids()) == 30
    assert len([e for e in registry.entries.get("relation-type", [])]) == 14


def test_importer_builds_a_valid_template_from_the_installed_package():
    """End-to-end through the real builder, without touching a database."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "import_protocol_ontology.py"),
         "--dry-run"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "installed package" in out.stdout, (
        "the importer fell back to a checkout — in the image there is none"
    )
    assert "30 entity types" in out.stdout


def test_alignment_declaration_ships_in_the_wheel():
    """`vocabulary/alignment/*.yaml` is one level deeper than the six pinned files.

    package-data's `vocabulary/*.yaml` does not match it. When that line was
    missing the wheel simply had no alignment file, and `load_alignment()`
    returns empty for a missing file (deliberately — an older checkout is
    valid), so the failure was completely silent: declaration written, logic
    working, tests green on the working tree, alignment empty in the image.
    """
    from fd_open_data_protocol.vocabulary import load_alignment

    declared = load_alignment()
    assert declared["alignments"], "alignment declaration is missing from the wheel"
    assert declared["target"]["layer"] == "foundation"
    assert declared["alignments"]["company"]["to"] == "organization"


def test_importer_reads_alignment_from_the_declaration_not_a_local_copy():
    """One place to add an alignment: the protocol's own file.

    Hardcoding the map in the importer was a second copy, and the two drifted
    immediately — the copy listed 7 entries while the declaration had 8.
    """
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "import_protocol_ontology.py"),
         "--dry-run"],
        capture_output=True, text=True, cwd=REPO_ROOT, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "8 alignments" in out.stdout, (
        "the importer must report the number the declaration holds"
    )
