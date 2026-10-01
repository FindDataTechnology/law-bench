#!/usr/bin/env python3
"""One-off fixup: strip spurious leading ``## <section>`` headers from clause
bodies that the audit rewriter added before the header-stripping fix landed.

The assembler (``src/clauses/assemble.py:_resolve_sections``) prepends
``## <section>`` itself, so a clause body that *also* starts with ``## <...>``
produces a doubled header in the assembled contract. The audit rewrite prompt
now forbids adding headers and ``rewrite_clause`` strips any that slip through,
but the employment pilot clauses (6971/6974/6976) were written before that fix.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(override=True)

from src.clauses.store import get_custom_clause, update_clause

# Clauses persisted in the employment pilot whose rewrites included a leading
# ## header. 6969 was fine (no header); these three were not.
AFFECTED = [6971, 6974, 6976]
_LEADING_HEADER_RE = re.compile(r"\A##\s+[^\n]*\n+")


def main() -> int:
    for cid in AFFECTED:
        c = get_custom_clause(cid)
        if not c:
            print(f"  id={cid}: NOT FOUND")
            continue
        body = c.get("body") or ""
        if not _LEADING_HEADER_RE.match(body):
            print(f"  id={cid}: no leading header, skipping")
            continue
        fixed = _LEADING_HEADER_RE.sub("", body)
        update_clause(cid, {"body": fixed})
        print(f"  ✅ id={cid}: stripped leading header ({len(body)}->{len(fixed)} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
