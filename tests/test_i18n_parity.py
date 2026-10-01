"""Locale tree parity for the chrome catalog (change finish-web-i18n-parity).

``LOCALES["zh"]`` and ``LOCALES["en"]`` must expose the same key paths: the
language switcher renders on every destination, so a key that exists in only
one locale renders the other locale's fallback mid-page. This walks both trees
and reports the exact divergent paths, mirroring what
``label_catalog_parity`` already enforces for the data-label catalogs.
"""

from __future__ import annotations

from src.web.i18n import LOCALES


def _key_paths(tree: dict, prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            paths |= _key_paths(value, f"{path}.")
        else:
            paths.add(path)
    return paths


def test_chrome_catalog_key_parity() -> None:
    zh = _key_paths(LOCALES["zh"])
    en = _key_paths(LOCALES["en"])
    missing_in_en = sorted(zh - en)
    missing_in_zh = sorted(en - zh)
    assert not missing_in_en, f"keys missing from en catalog: {missing_in_en}"
    assert not missing_in_zh, f"keys missing from zh catalog: {missing_in_zh}"


def test_every_leaf_is_str_in_both_locales() -> None:
    for lang, tree in LOCALES.items():
        for path in sorted(_key_paths(tree)):
            node = tree
            for part in path.split("."):
                node = node[part]
            assert isinstance(node, str), f"{lang}:{path} is {type(node).__name__}, expected str"
