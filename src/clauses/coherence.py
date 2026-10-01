"""Pre-release coherence gate for assembled contracts.

Validates the resolved contract before rendering:
- (a) every section the 母版 (base) defines is present in the resolved set
      (override replaces a section's body, it must never drop the section);
- (b) no duplicate section in the resolved set (engine invariant);
- (c) every ``{{slot}}`` in the assembled body has a matching instruction.

A failure raises :class:`CoherenceError` with a diagnostic naming the failing
check(s). The gate is strict: an incoherent contract is not rendered.
"""

from __future__ import annotations

import re


class CoherenceError(ValueError):
    """Raised when an assembled contract fails the coherence gate."""


def validate_coherence(
    resolved: list[dict],
    body: str,
    instructions: list[dict],
    base_sections: set[str] | None = None,
) -> None:
    """Validate the resolved contract; raise :class:`CoherenceError` on failure.

    ``resolved`` is the one-clause-per-section list from the override resolver.
    ``body`` is the assembled Markdown body. ``instructions`` is the union of
    slot instructions. ``base_sections`` is the set of sections the 母版 defines
    (passed in so the gate can assert none were dropped).
    """
    errors: list[str] = []

    resolved_sections = [c["section"] for c in resolved]

    # (a) every base section is present (override replaces, never drops).
    if base_sections is not None:
        missing = sorted(base_sections - set(resolved_sections))
        if missing:
            errors.append(f"missing canonical sections: {missing}")

    # (b) no duplicate section.
    seen: set[str] = set()
    dups: set[str] = set()
    for s in resolved_sections:
        if s in seen:
            dups.add(s)
        seen.add(s)
    if dups:
        errors.append(f"duplicate sections: {sorted(dups)}")

    # (c) every slot in the body has a matching instruction.
    instr_names = {i["name"] for i in instructions}
    body_slots = set(re.findall(r"\{\{(\w+)\}\}", body))
    uninstr = sorted(body_slots - instr_names)
    if uninstr:
        errors.append(f"un-instructed slots: {uninstr}")

    if errors:
        raise CoherenceError("; ".join(errors))


__all__ = ["CoherenceError", "validate_coherence"]
