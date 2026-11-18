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


def test_a_backticked_internal_path_is_detected():
    """markdown 行内代码里的内部路径必须被抓到。

    2026-11-14 实测漏过一次：判据的前缀集不含反引号，而
    `` `law-bench-internal/src/web/auth/scopes.py` `` 正好是文档里写路径的常见形态
    ⇒ 一条真实泄漏从闸底下走过去，闸报 OK。文档是最容易写进内部路径的地方。
    """

    def hits(line: str) -> list[str]:
        return [n for n, p in hyg.CONTENT_RULES if p.search(line)]

    for line in (
        "| 共享身份 | Logto | `law-bench-internal/src/web/auth/scopes.py` |",
        "*`law-bench-internal/x.py`*",
        "见( law-bench-internal/y.py )",
        "law-bench-internal/z.py 开头即命中",
    ):
        assert "internal repo import/path reference" in hits(line), line

    # 反例：散文里提仓名、或粘在别的标识符后面，都不该红。
    for line in (
        "真源在 law-bench-internal 仓里（散文提仓名允许）",
        "my-law-bench-internal/x.py 不是本仓",
    ):
        assert "internal repo import/path reference" not in hits(line), line


def test_scan_reports_internal_path_reference_not_just_matches_it():
    """判据必须在 **scan_text() 层**成立，而不只是 `pattern.search()` 命中。

    2026-11-14 实历：`internal repo import/path reference` 这条规则**从来没有生效过**。
    正则是对的、上面两条测试也一直是绿的，但 `scan()` 里那段占位值过滤
    （`pattern.groups >= 1 and not _looks_real_secret(...)`，本意是给凭据类规则用的）
    对所有带捕获组的规则都生效，而 `law-bench-internal/` 永远「不像秘密」
    ⇒ 每一个命中都在报告之前被扔掉，闸对着一个真实泄漏报 OK。

    所以这条测试断言的是**报告**（scan_text 的返回值），不是匹配。
    """

    for name, text in (
        ("docs/x.md", "| 共享身份 | Logto | `law-bench-internal/src/web/auth/scopes.py` |"),
        ("docs/x.md", "python 侧见 law-bench-internal/wire-connector/selfcheck.py"),
        ("src/x.py", "from law_bench_internal import wire_connector"),
    ):
        violations = hyg.scan_text(name, text)
        assert any("internal repo import/path reference" in v for v in violations), (
            f"scan_text 没报出内部路径引用（判据死了而正则没错）：{name}: {text}"
        )

    # 散文提仓名仍然不报——这条豁免在报告层也必须成立，不是只在匹配层。
    assert hyg.scan_text("docs/x.md", "真源在 law-bench-internal 仓里") == []


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
