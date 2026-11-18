#!/usr/bin/env python3
"""Public-repo leak gate (fail-closed).

Scans every git-tracked file for credentials and references to the internal
repo; any hit fails the build (CI runs this before packaging). Additive by
design: new rules append to the tables below.

Checks:
1. URL-embedded credentials        ``scheme://user:secret@host`` (the gitee
                                   token-in-URL accident is the namesake case)
2. Key/secret material             sk- keys, PEM blocks, generic api_key=...,
                                   ssh-config style host blocks
3. Internal repo references        import paths or file paths pointing into
                                   law-bench-internal (prose mentions of the
                                   repo's *name* in docs are allowed; only
                                   import/path forms are violations)
4. Credential-shaped tracked files .env, *.pem, *token*, ssh-config.json

Usage: ``python3 scripts/check_public_hygiene.py`` from the repo root.
Exit 0 = clean, exit 1 = violations (printed one per line).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# (rule name, compiled pattern applied to file content). Patterns with a
# group expose the candidate secret; _looks_real_secret() filters placeholder
# values so example docs and hermetic test fixtures don't fail the build while
# anything unrecognized still trips the gate (fail-closed).
CONTENT_RULES = [
    (
        "url-embedded credential",
        re.compile(r"[a-z][a-z0-9+.-]*://[^\s/@]*:([^\s/@]{6,})@[^\s]"),
    ),
    ("sk-style api key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    (
        "pem private key block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    (
        "assigned secret literal",
        # Left boundary: non-letter (not \b) so SNAKE_CASE env names like
        # GITEE_TOKEN match while 'mytoken=' stays prose.
        re.compile(
            r"""(?i)(?<![A-Za-z])(api[_-]?key|api[_-]?secret|password|passwd|token)\b['"]?\s*[:=]\s*['"]?([^'"\s(){}\[\];,.]{12,})['"]?"""
        ),
    ),
    (
        # 前缀用**负向后视**而不是字符类：2026-11-14 实测漏了一个真实泄漏——
        # `docs/fleet-loop-program.md` 里写着 `` `law-bench-internal/src/...` ``，
        # 而原来的 `(^|[\s'\"(])` 不含反引号，于是 markdown 最常用来写路径的那种
        # 形态（行内代码）整个绕过判据，闸报 OK。文档恰恰是最容易写进内部路径的
        # 地方，所以这里改成「前面不是单词字符或连字符」即可，反引号、括号、引号、
        # 行首都覆盖，且不会把 `my-law-bench-internal/` 误判成命中。
        "internal repo import/path reference",
        re.compile(
            r"(?<![\w-])(from\s+law_bench_internal|import\s+law_bench_internal|law-bench-internal/)"
        ),
    ),
]

# Substrings that mark a candidate secret as a documented placeholder or
# hermetic test fixture rather than real material.
PLACEHOLDER_MARKERS = (
    "changeme",
    "change-me",
    "your-",
    "<password>",
    "example",
    "placeholder",
    "hermetic",
    "not-a-real",
    "dummy",
    "fake",
    "sample",
    "todo",
    "xxxx",
    "secret-key",
    "secret_key",
)

# Repo conventions for synthetic keys (see src/web/auth/apikey.py test docs):
# keys minted for tests start with this prefix.
SYNTHETIC_PREFIXES = ("lbk_", "test_", "sk-test")


def _looks_real_secret(candidate: str) -> bool:
    low = candidate.lower()
    if any(marker in low for marker in PLACEHOLDER_MARKERS):
        return False
    if candidate.startswith(SYNTHETIC_PREFIXES):
        return False
    # Leading underscore = Python identifier (_mint_m2m_token), never real
    # secret material.
    if candidate.startswith("_"):
        return False
    if set(candidate) <= set("<>{}[]()-_"):
        return False
    # Real credentials carry both letters and digits; prose identifiers, JS
    # variable chains and placeholder words ("password") do not.
    if not (any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate)):
        return False
    return True

# Tracked filenames that must never exist in the public repo
BANNED_FILE_PATTERNS = [
    (re.compile(r"(^|/)\.env$"), "dotenv secrets file"),
    (re.compile(r"\.pem$"), "key material"),
    (re.compile(r"(^|/)ssh-config\.json$"), "ssh host config"),
    (re.compile(r"(^|/)[^/]*token[^/]*$", re.IGNORECASE), "token-named file"),
]

# False-positive allowances: (path substring, rule name) pairs to skip.
ALLOWLIST = [
    # impeccable live.js dev token (localhost-only heatmap tooling, committed
    # upstream; not a credential for any hosted surface)
    ("src/web/templates/base.html", "assigned secret literal"),
    (".env.example", "assigned secret literal"),  # placeholders by design
    ("check_public_hygiene.py", "assigned secret literal"),
    ("check_public_hygiene.py", "url-embedded credential"),
    ("check_public_hygiene.py", "internal repo import/path reference"),
    ("test_public_hygiene.py", "assigned secret literal"),
    ("test_public_hygiene.py", "url-embedded credential"),
    ("test_public_hygiene.py", "internal repo import/path reference"),
    # the gate's own self-test carries synthetic sk-/PEM samples by design
    ("test_public_hygiene.py", "sk-style api key"),
    ("test_public_hygiene.py", "pem private key block"),
]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


#: 哪些规则的「最后一个捕获组」是**候选秘密**，因此要过 `_looks_real_secret` 的
#: 占位值过滤。只登记凭据类规则。
#:
#: 2026-11-14 实历：这个过滤原来对**所有**带捕获组的规则生效，于是
#: `internal repo import/path reference` 这条**从来没生效过**——它捕获到的
#: `law-bench-internal/`（或 `from law_bench_internal`）永远不像秘密
#: （`looks_real=False`），每一个命中都在报告之前被扔掉。闸因此一直是绿的，
#: 而它头注宣称的能力（抓内部路径引用）其实不存在。判据要按规则声明它是否
#: 携带秘密，而不是用「有没有捕获组」去猜。
SECRET_GROUP_RULES = frozenset({"url-embedded credential", "assigned secret literal"})


def scan_text(path: str, text: str) -> list[str]:
    """Apply the content rules to one file's bytes (``path`` drives allowlist + messages).

    Split out from :func:`scan` so the scanner itself is testable: a test that only
    asserts ``pattern.search(line)`` is truthy cannot tell whether a violation is
    ever *reported*, which is how the internal-path rule stayed dead.
    """
    out: list[str] = []
    for rule_name, pattern in CONTENT_RULES:
        if any(path.endswith(skip) and rule_name == rule for skip, rule in ALLOWLIST):
            continue
        for m in pattern.finditer(text):
            # Only credential-shaped rules carry a placeholder filter. Applying it
            # to every rule with a group silently disables the non-secret ones.
            if (
                rule_name in SECRET_GROUP_RULES
                and pattern.groups >= 1
                and not _looks_real_secret(m.group(pattern.groups))
            ):
                continue
            line_no = text.count("\n", 0, m.start()) + 1
            snippet = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
            out.append(f"{path}:{line_no}: {rule_name}: ...{snippet}...")
    return out


def scan() -> list[str]:
    violations: list[str] = []
    for path in tracked_files():
        for pattern, reason in BANNED_FILE_PATTERNS:
            if pattern.search(path):
                violations.append(f"{path}: banned file ({reason})")
        fpath = REPO_ROOT / path
        try:
            text = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError):
            continue  # binary or special: filename rules above still applied
        violations.extend(scan_text(path, text))
    return violations


def main() -> int:
    violations = scan()
    if violations:
        print(f"public-repo hygiene: FAILED ({len(violations)} violation(s))")
        for v in violations:
            print(f"  {v}")
        print("fix: remove the material or move it to the internal repo;")
        print("     allowlist entries live in scripts/check_public_hygiene.py")
        return 1
    files = len(tracked_files())
    print(f"public-repo hygiene: OK ({files} tracked files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
