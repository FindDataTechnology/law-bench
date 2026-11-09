"""Public-repo leak gate (add-knowledge-bench-platform, task 3.2).

Green path runs the real scan against the repo (must be clean at HEAD).
Red path unit-tests each content rule against synthetic strings so rule
regressions surface without planting material in tracked files.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_public_hygiene as hyg  # noqa: E402


def test_repo_is_clean_at_head():
    violations = hyg.scan()
    assert violations == [], f"public-repo leak gate tripped:\n" + "\n".join(violations)


def test_url_embedded_credential_detected():
    # 用明显的合成值：2026-11-09 发现原字面量疑似真实 gitee token，已换成 FAKE-*。
    # 规则只要求密码段 >=6 字符，换成假值不影响这条测试要验的行为。
    line = 'origin = "https://FindDataTechnology:FAKE-TOKEN-ONLY-FOR-TEST@gitee.com/x.git"'
    hits = [n for n, p in hyg.CONTENT_RULES if p.search(line)]
    assert "url-embedded credential" in hits


def test_internal_repo_path_reference_detected():
    line = "from law_bench_internal import wire_connector  # internal only"
    assert any(p.search(line) for _, p in hyg.CONTENT_RULES)
    line2 = "cfg = load('law-bench-internal/configs/x.yaml')"
    assert any(p.search(line2) for _, p in hyg.CONTENT_RULES)


def test_sk_key_and_pem_detected():
    assert any(p.search("key = 'sk-abcdefghijklmnop123456'") for _, p in hyg.CONTENT_RULES)
    assert any(p.search("-----BEGIN RSA PRIVATE KEY-----") for _, p in hyg.CONTENT_RULES)


def test_assigned_secret_detected_but_example_placeholder_not_flagged():
    secret_line = 'API_KEY = "9f8e7d6c5b4a3210fedcba"'
    assert any(p.search(secret_line) for _, p in hyg.CONTENT_RULES)
    # .env.example placeholder style must not produce a violation: the rule
    # may match lexically, but the real-secret filter rejects the value.
    placeholder = 'OPENAI_API_KEY=your-key-here'
    rule = dict(hyg.CONTENT_RULES)["assigned secret literal"]
    m = rule.search(placeholder)
    assert m is not None and not hyg._looks_real_secret(m.group(rule.groups))


def test_banned_tracked_filenames():
    assert any(p.search(".env") and n == "dotenv secrets file"
               for p, n in [(a, b) for a, b in hyg.BANNED_FILE_PATTERNS] for _ in [0])
    for fname, want in [(".env", True), ("ssh-config.json", True), ("server.pem", True),
                        ("my_token_cache.json", True), ("src/store.py", False),
                        ("README.md", False), ("tokens.md", True)]:
        hits = [n for pat, n in hyg.BANNED_FILE_PATTERNS if pat.search(fname)]
        assert bool(hits) == want, f"{fname}: expected banned={want}, got {hits}"
