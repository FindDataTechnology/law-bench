"""Per-contract-class 法律法规 extraction from the Doubao+DeepSeek answers.

Reuses :func:`src.eval.legal_refs.extract_references` (which pulls
``《...》``-wrapped law names out of the markdown and categorizes them). Reads
the bundled answers under ``output/law_info/{deepseek,doubao}/<type>.md`` so the
tool is standalone (no database).
"""

from __future__ import annotations

from pathlib import Path

from src.eval.errors import NotFoundError
from src.eval.legal_refs import extract_references

from .templates import _LAW_INFO_DIR

_SOURCES = ("doubao", "deepseek")


def extract_laws_for_type(
    contract_type: str, law_info_dir: str | Path | None = None
) -> list[dict]:
    """Return the 法律法规 referenced in ``contract_type``'s answers.

    Each entry is ``{name, category, category_zh, sources}`` where ``sources``
    lists which of ``doubao``/``deepseek`` cited the law. Sorted by category
    order then name. Raises :class:`NotFoundError` when no answers exist for the
    type.
    """
    base = Path(law_info_dir) if law_info_dir else _LAW_INFO_DIR
    items: list[dict] = []
    for source in _SOURCES:
        path = base / source / f"{contract_type}.md"
        if path.is_file():
            items.append(
                {
                    "contract_type": contract_type,
                    "source": source,
                    "content": path.read_text(encoding="utf-8"),
                }
            )
    if not items:
        raise NotFoundError(f"no law_info answers for contract type: {contract_type!r}")
    refs = extract_references(items)
    return [
        {
            "name": r["name"],
            "category": r["category"],
            "category_zh": r["category_zh"],
            "sources": r["sources"],
        }
        for r in refs
    ]
