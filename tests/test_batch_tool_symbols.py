"""`contract_generate_batch` 的符号解析（lex-matter-spine 5.5 实采暴露的缺陷）。

2026-11-10 现网实测：本工具一调就 `ImportError: cannot import name 'tag_vocab_list'
from 'src.clauses.tags'`。同一天已经修过 `catalog.py`（`type_metadata`）里**一模一样**
的错——`tag_vocab_list` 是 **MCP 侧工具名**，`src.clauses.tags` 里的函数叫
`tag_vocab_for_type`。当时只修了那一处，漏了这里。

所以本文件测的不是"函数返回什么"，而是**这类错不会再被漏掉**：
仓里任何 `from src.clauses.tags import ...` 都必须能真的解析成功。
静态 import 检查比"跑一遍工具"便宜得多，且能在出片前拦住。
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PKG_SRC = REPO / "fd-coding-law-bench-mcp" / "src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

SRC_ROOTS = (PKG_SRC, REPO / "src")
# 只吃**单行**的 import：最初的正则允许跨行，把下一行代码也当成符号名，
# 于是"文件里一切都在"的自检变成一片假红。多行 import（带括号）另行合并。
_FROM_TAGS = re.compile(r"from\s+src\.clauses\.tags\s+import\s+(\([^)]*\)|[^\n(]+)")


def _imported_names() -> list[tuple[Path, int, str]]:
    """收集仓内所有 `from src.clauses.tags import ...` 的被导入名。"""
    found: list[tuple[Path, int, str]] = []
    for root in SRC_ROOTS:
        for path in root.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for match in _FROM_TAGS.finditer(text):
                clause = match.group(1).strip().lstrip("(").rstrip(")").replace("\\", " ")
                line = text[: match.start()].count("\n") + 1
                for name in clause.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if name and name.isidentifier():
                        found.append((path, line, name))
    return found


def test_every_tag_symbol_import_actually_resolves():
    """逐个名字去真模块里查：不存在就指名文件:行。

    这条是"只修一处、漏了另一处"的机器化检查。之前靠人记，记不住。
    """
    from src.clauses import tags as tags_module

    imps = _imported_names()
    assert imps, "没有扫到任何 from src.clauses.tags import——正则或路径失效，别当成通过"
    missing = [
        f"{path.relative_to(REPO)}:{line} 导入了不存在的符号 {name!r}"
        for path, line, name in imps
        if not hasattr(tags_module, name)
    ]
    assert not missing, "以下导入会 ImportError：\n" + "\n".join(missing)


def test_batch_tool_module_imports_clean():
    """batch 工具模块本身可导入——上一版就是在这里炸的。"""
    module = importlib.import_module("fd_coding_law_bench_mcp.tools.batch")
    assert hasattr(module, "contract_generate_batch")


@pytest.mark.asyncio
async def test_enumerate_all_actually_enumerates(monkeypatch):
    """`enumerate_all=True` 走的就是出错那条分支，必须真的产出组合。

    `tag_vocab_for_type` 在本模块是**函数内导入**（不在模块命名空间），所以替身要打在
    `src.clauses.tags` 上而不是模块属性上——打在模块上会 AttributeError，
    那种红是测试写错，不是代码坏。
    """
    import src.clauses.tags as tags_mod
    from fd_coding_law_bench_mcp.tools import batch as batch_mod

    monkeypatch.setattr(tags_mod, "tag_vocab_for_type", lambda key=None: {"stance": ["pro_a", "pro_b"]})

    # 每个组合实际调的是 content.contract_content（模块内 from ... import，故替身打在源模块）
    import fd_coding_law_bench_mcp.tools.content as content_mod

    async def fake_content(contract_type, tags=None, format="markdown", trace_id=None):  # noqa: ANN001
        return {"body_text": "BODY", "contract_type": contract_type, "format": format,
                "slots": [], "instructions": [], "law_refs": []}

    monkeypatch.setattr(content_mod, "contract_content", fake_content)

    result = await batch_mod.contract_generate_batch("bailment", enumerate_all=True, max_concurrent=2)
    assert not result.get("error"), f"枚举分支报错：{result.get('error')}"
    assert result.get("total_requested") == 2, f"应枚举出 2 个组合，实际 {result.get('total_requested')}"
    assert len(result.get("results") or []) == 2
    assert result.get("success_count") == 2, f"summary 计数不对：{result}"
