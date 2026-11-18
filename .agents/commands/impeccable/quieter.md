---
name: "Impeccable: Quieter"
description: "Tone down visually aggressive or overstimulating designs"
category: "Design"
tags: ["design", "ui", "impeccable"]
---

Impeccable design command: **quieter** — Tone down visually aggressive or overstimulating designs.

**Input**: optionally name a target (file, route, feature, or element) after the command, e.g. /impeccable:quieter <target>. If omitted, the reference decides how to choose the target; ask the user when it is ambiguous.

**Steps**

1. Follow the impeccable skill at .agents/skills/impeccable/SKILL.md, starting with its Setup section: with cwd at the project root, run node .agents/skills/impeccable/scripts/context.mjs once per session (append --target <path> when the input names a source file or route). Skip it if it already ran this session; follow its directives.
2. Load reference/quieter.md relative to the skill base directory and follow it exactly for this command, passing the user's input.
3. Load reference/craft-floor.md immediately before editing any UI, and honor the skill's core principles throughout. Do not deviate from the reference playbook.
