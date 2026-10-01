#!/usr/bin/env python3
"""Generate ``docs/legal_references.md`` from the bundled law_info markdown.

Reads the canonical bundled markdown under ``src/eval/seed/law_info/`` (41
contract types × {doubao, deepseek}), runs the pure ``extract_references``
extractor, and writes a committed, deterministic reference doc listing every
referenced 法律法规, deduplicated and categorized.

Re-run whenever the bundled markdown changes; the output is sorted so repeated
runs produce an identical file.

Run:
    uv run python scripts/extract_legal_references.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from extract_harbor_rules import project_root

from src.eval.legal_refs import CATEGORY_ORDER, CATEGORY_ZH, extract_references

DOC_REL = "docs/legal_references.md"


def _load_items() -> list[dict]:
    """Read the bundled markdown into ``[{contract_type, source, content}]``."""
    import json

    seed = project_root() / "src/eval/seed/law_info"
    with (seed / "contract_types.json").open(encoding="utf-8") as fh:
        contract_types = json.load(fh)
    items: list[dict] = []
    for ct in contract_types:
        key = ct["key"]
        for source in ("doubao", "deepseek"):
            path = seed / source / f"{key}.md"
            if path.is_file():
                items.append(
                    {"contract_type": key, "source": source, "content": path.read_text(encoding="utf-8")}
                )
    return items


def _render(refs: list[dict]) -> str:
    lines: list[str] = [
        "# 法律法规索引 (Legal References Index)",
        "",
        "> 自动生成自 `src/eval/seed/law_info/` 下豆包与 DeepSeek 的法律法规回答。",
        "> 生成脚本：`scripts/extract_legal_references.py`。请勿手动编辑；修改数据后重新运行脚本。",
        "",
        f"总计 **{len(refs)}** 条法律法规（去重后）。",
        "",
    ]
    for cat in CATEGORY_ORDER:
        group = [r for r in refs if r["category"] == cat]
        if not group:
            continue
        lines.append(f"## {CATEGORY_ZH[cat]} ({cat})")
        lines.append("")
        lines.append("| 名称 (Name) | 出现合同类型数 | 来源 |")
        lines.append("|---|---:|---|")
        for r in group:
            types_n = len(r["contract_types"])
            sources = ", ".join(r["sources"])
            lines.append(f"| {r['name']} | {types_n} | {sources} |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=project_root() / DOC_REL)
    args = ap.parse_args()

    refs = extract_references(_load_items())
    text = _render(refs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({len(refs)} laws)")


if __name__ == "__main__":
    main()
