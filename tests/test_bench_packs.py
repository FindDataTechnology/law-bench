"""Tests for the domain pack registry (src/bench/packs.py).

Builds synthetic packs under ``tmp_path`` with ``PACKS_DIR`` monkeypatched —
no dependence on any real pack's existence or contents. Covers:

- ``list_packs``: reads every pack dir's manifest, sorted, skipping
  non-directory entries; missing manifest and malformed YAML raise as-is;
- ``load_pack``: exact manifest round-trip, unknown pack raises, path
  traversal in the name rejected;
- ``validate_pack``: the pass path plus each violation family (missing
  fields, empty kinds, illegal component type, nonexistent component path,
  repo-escaping component path, name/directory mismatch, non-mapping
  manifest).
"""

from __future__ import annotations

import yaml
import pytest

import src.bench.packs as packs_mod
from src.bench.packs import list_packs, load_pack, validate_pack

# A repo-relative path guaranteed to exist (kernel store module).
GOOD_COMPONENT = {"type": "module", "path": "src/bench/store.py"}

VALID_MANIFEST = {
    "name": "alpha",
    "version": "0.1.0",
    "description": "synthetic pack used by the registry tests",
    "kinds": ["qa-pair"],
    "components": [GOOD_COMPONENT],
    "eval_suites": ["suite-a"],
}


def _make_pack(root, name="alpha", manifest=None):
    pack_dir = root / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        VALID_MANIFEST if manifest is None else manifest, allow_unicode=True
    )
    (pack_dir / "pack.yaml").write_text(body, encoding="utf-8")
    return pack_dir


@pytest.fixture()
def packs_root(tmp_path, monkeypatch):
    monkeypatch.setattr(packs_mod, "PACKS_DIR", tmp_path)
    return tmp_path


class TestDefaultLayout:
    def test_packs_dir_defaults_to_the_repo_packs_directory(self):
        assert packs_mod.PACKS_DIR == packs_mod.REPO_ROOT / "packs"
        assert packs_mod.PACKS_DIR.name == "packs"
        assert packs_mod.PACKS_DIR.is_dir()


class TestListPacks:
    def test_reads_every_pack_manifest_sorted_by_directory(self, packs_root):
        _make_pack(packs_root, "beta", {**VALID_MANIFEST, "name": "beta"})
        _make_pack(packs_root, "alpha")
        (packs_root / "stray.txt").write_text("not a pack dir", encoding="utf-8")
        found = list_packs()
        assert [m["name"] for m in found] == ["alpha", "beta"]
        assert found[0] == VALID_MANIFEST

    def test_missing_manifest_raises(self, packs_root):
        (packs_root / "empty-pack").mkdir()
        with pytest.raises(FileNotFoundError):
            list_packs()

    def test_runtime_pycache_and_dot_dirs_are_skipped(self, packs_root):
        # The packs package is importable in the image, so Python materialises
        # packs/__pycache__ at runtime; that must never wedge the registry.
        _make_pack(packs_root, "alpha")
        (packs_root / "__pycache__").mkdir()
        (packs_root / ".staging").mkdir()
        found = list_packs()
        assert [m["name"] for m in found] == ["alpha"]

    def test_malformed_yaml_raises(self, packs_root):
        broken = packs_root / "broken"
        broken.mkdir()
        (broken / "pack.yaml").write_text("name: [unclosed", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            list_packs()


class TestLoadPack:
    def test_round_trips_the_manifest(self, packs_root):
        _make_pack(packs_root, "alpha")
        assert load_pack("alpha") == VALID_MANIFEST

    def test_unknown_pack_raises_file_not_found(self, packs_root):
        with pytest.raises(FileNotFoundError):
            load_pack("nope")

    @pytest.mark.parametrize("bad", ["../alpha", "a/b", "..", ".", ""])
    def test_non_plain_directory_names_rejected(self, packs_root, bad):
        with pytest.raises(ValueError):
            load_pack(bad)


class TestValidatePack:
    def test_valid_manifest_passes(self):
        assert validate_pack(VALID_MANIFEST) == []
        assert validate_pack(VALID_MANIFEST, directory="alpha") == []

    def test_missing_required_fields_reported(self):
        problems = validate_pack({"name": "x"})
        joined = "\n".join(problems)
        for field in ("version", "description", "kinds", "components", "eval_suites"):
            assert f"missing required field '{field}'" in joined

    def test_empty_kinds_rejected(self):
        problems = validate_pack({**VALID_MANIFEST, "kinds": []})
        assert any("'kinds' must not be empty" in p for p in problems)

    def test_non_string_kind_rejected(self):
        problems = validate_pack({**VALID_MANIFEST, "kinds": ["ok", 7]})
        assert any("'kinds' must contain only non-empty strings" in p for p in problems)

    def test_illegal_component_type_rejected(self):
        bad = {
            **VALID_MANIFEST,
            "components": [{"type": "macro", "path": "src/bench/store.py"}],
        }
        problems = validate_pack(bad)
        assert any("illegal component type 'macro'" in p for p in problems)

    def test_missing_component_path_rejected(self):
        bad = {**VALID_MANIFEST, "components": [{"type": "data"}]}
        problems = validate_pack(bad)
        assert any("'path' must be a non-empty" in p for p in problems)

    def test_nonexistent_component_path_rejected(self):
        bad = {
            **VALID_MANIFEST,
            "components": [{"type": "data", "path": "packs/no-such-dir/x.yaml"}],
        }
        problems = validate_pack(bad)
        assert any("does not exist in the repo" in p for p in problems)

    def test_repo_escaping_component_path_rejected(self):
        bad = {
            **VALID_MANIFEST,
            "components": [{"type": "data", "path": "../../outside-secrets"}],
        }
        problems = validate_pack(bad)
        assert any("escapes the repo root" in p for p in problems)

    def test_component_path_may_be_the_repo_root_itself(self):
        bad = {**VALID_MANIFEST, "components": [{"type": "data", "path": "."}]}
        assert validate_pack(bad) == []

    def test_empty_components_list_is_legal(self):
        ok = {**VALID_MANIFEST, "components": []}
        assert validate_pack(ok) == []

    def test_eval_suites_must_be_strings(self):
        problems = validate_pack({**VALID_MANIFEST, "eval_suites": [1]})
        assert any("'eval_suites' must be a list of strings" in p for p in problems)

    def test_name_directory_mismatch_reported(self):
        problems = validate_pack(VALID_MANIFEST, directory="beta")
        assert any(
            "'alpha'" in p and "'beta'" in p and "does not match" in p
            for p in problems
        )
        assert validate_pack({**VALID_MANIFEST, "name": "beta"}, directory="beta") == []

    def test_non_mapping_manifest_rejected(self):
        problems = validate_pack(["not", "a", "mapping"])
        assert problems == ["manifest must be a mapping, got list"]

    def test_multiple_violations_all_reported(self):
        problems = validate_pack({"kinds": [], "components": [{"type": "weird"}]})
        joined = "\n".join(problems)
        assert "missing required field 'name'" in joined
        assert "'kinds' must not be empty" in joined
        assert "illegal component type 'weird'" in joined


class TestListValidateIntegration:
    def test_synthetic_packs_validate_clean(self, packs_root):
        _make_pack(packs_root, "alpha")
        _make_pack(packs_root, "beta", {**VALID_MANIFEST, "name": "beta"})
        for manifest in list_packs():
            assert validate_pack(manifest, directory=manifest["name"]) == []
