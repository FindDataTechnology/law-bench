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
        "internal repo import/path reference",
        re.compile(r"(^|[\s'\"(])(from\s+law_bench_internal|import\s+law_bench_internal|law-bench-internal/)"),
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
        for rule_name, pattern in CONTENT_RULES:
            if any(path.endswith(skip) and rule_name == rule for skip, rule in ALLOWLIST):
                continue
            for m in pattern.finditer(text):
                # Rules with capture groups expose the candidate secret in the
                # LAST group (the assigned-secret rule's first group is the key
                # name); placeholder-shaped values are skipped (fail-closed:
                # anything not matching the placeholder markers still trips).
                if pattern.groups >= 1 and not _looks_real_secret(
                    m.group(pattern.groups)
                ):
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                snippet = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
                violations.append(
                    f"{path}:{line_no}: {rule_name}: ...{snippet}..."
                )
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
