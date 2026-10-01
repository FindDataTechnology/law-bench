#!/usr/bin/env python3
"""Generate type-specific contract template bodies via the doubao LLM, informed
by each contract type's Doubao+DeepSeek 法律法规 answers, and refresh
``src/contracts/data/contracts.json``.

For each contract class the script:
1. reads the bundled 法律法规 answers (``src/eval/seed/law_info/{deepseek,doubao}/<key>.md``);
2. resolves the per-type Chinese slot set from the masters manifest
   (``src/contracts/data/type_slots.json``) and prompts the DRAFTER LLM (doubao
   via Ark, OpenAI-compatible) to draft a contract body containing exactly those
   ``{{中文占位符}}`` tokens;
3. normalizes the output (strip unknown tokens, append any missing required
   slots) so slot/instruction consistency holds;
4. caches the body to ``src/contracts/data/_llm_bodies/<key>.md`` (re-run with
   ``--force`` to regenerate).

The registry's ``slot_instructions`` always matches the body's actual slot set
(per-type Chinese for a regenerated body, Latin default for a legacy/cached
body) so ``check_slot_consistency`` stays green across the Latin->Chinese
migration. On LLM failure the existing (skeleton) body is kept, so the run is
non-destructive.

Usage::

    uv run python scripts/generate_contract_templates_llm.py [--force] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# Avoid litellm's remote model-cost-map fetch (network-dependent); local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.contracts.slots import (  # noqa: E402
    REQUIRED_SLOTS,
    default_slot_instructions,
    required_slots_for_type,
    slot_instructions_for_type,
    tail_allowed_slots_for_type,
)
from src.contracts.templates import normalize_body  # noqa: E402
from src.contracts.audit import audit_body  # noqa: E402

LAW_INFO_DIR = REPO_ROOT / "src" / "eval" / "seed" / "law_info"
TYPES_PATH = LAW_INFO_DIR / "contract_types.json"
REGISTRY_PATH = REPO_ROOT / "src" / "contracts" / "data" / "contracts.json"
BODIES_DIR = REPO_ROOT / "src" / "contracts" / "data" / "_llm_bodies"
_SOURCES = ("doubao", "deepseek")


def _read_law_context(key: str) -> str:
    parts = []
    for source in _SOURCES:
        p = LAW_INFO_DIR / source / f"{key}.md"
        if p.is_file():
            parts.append(f"### 来源：{source}\n\n{p.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def _build_prompt(zh: str, law_context: str, contract_type: str) -> str:
    """Prompt the drafter with the per-type Chinese slot set.

    The ``{{中文占位符}}`` tokens come from :func:`required_slots_for_type`
    (the masters manifest) so the generated body carries Chinese slots. The
    signing slots (签署日期/签署地点) are called out for the 签署信息 block.
    """
    slots = required_slots_for_type(contract_type)
    slot_list = "、".join("{{" + s + "}}" for s in slots)
    tail = tail_allowed_slots_for_type(contract_type)
    signing = (
        "、".join("{{" + s + "}}" for s in tail)
        if tail
        else "（本类合同无签署占位符）"
    )
    return (
        f"你是资深中国法律合同起草人。请依据下方《{zh}》相关法律法规，起草一份具体、完整、"
        f"可实际使用的{zh}正文（简体中文，Markdown 格式）。\n\n"
        "要求：\n"
        "1. 必须包含且仅包含以下占位符（原样保留双花括号，不得改名、不得增删）：\n"
        f"   {slot_list}\n"
        "2. 结构：当事人、鉴于（引用相关法律法规）、合同标的、价款及支付、履行期限、"
        "双方权利义务（针对本类合同的具体义务，不要泛泛而谈）、违约责任、争议解决、附则、"
        f"签署信息（含 {signing}）。\n"
        "3. 章节使用二级标题（##），不要输出一级标题（#），不要输出任何解释、前言或代码块标记。\n"
        "4. 条款内容要结合所依据的法律法规，体现该类合同的特点。\n\n"
        f"相关法律法规：\n\n{law_context}"
    )


def _call_llm(prompt: str) -> str:
    import litellm

    model = os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(os.environ.get("DRAFTER_TEMPERATURE", "0.3")),
        max_tokens=int(os.environ.get("DRAFTER_MAX_TOKENS", "4096")),
    )
    return resp.choices[0].message.content or ""


def _instructions_for_body(key: str, zh: str, body: str) -> list[dict]:
    """Pick the slot-instruction manifest matching the body's actual slot language.

    A regenerated body carries per-type Chinese slots -> use the per-type
    manifest (:func:`slot_instructions_for_type`). A legacy/cached body still
    carrying Latin slots -> use the Latin :func:`default_slot_instructions`, so
    ``check_slot_consistency`` stays green during the Latin->Chinese migration.
    Detection mirrors :func:`src.contracts.audit.audit_template`: a per-type
    manifest exists AND the body actually carries one of its slot tokens.
    """
    per_type = required_slots_for_type(key)
    has_manifest = per_type != list(REQUIRED_SLOTS)
    body_has_per_type = has_manifest and any(
        f"{{{{{s}}}}}" in (body or "") for s in per_type
    )
    if body_has_per_type:
        return slot_instructions_for_type(key, zh)
    return default_slot_instructions(zh)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate type-specific contract template bodies via the doubao LLM.",
    )
    parser.add_argument("--force", action="store_true", help="re-generate even if a cached body exists")
    parser.add_argument("--limit", type=int, default=None, help="only generate the first N types (debug)")
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="only regenerate the given contract-type key (mode G web route); "
        "exits non-zero if the key is not in contract_types.json",
    )
    args = parser.parse_args()

    # ``all_types`` drives the registry write (always the full set so a single-type
    # ``--type`` regen never truncates contracts.json to one entry); ``targets``
    # is the subset we actually call the LLM for.
    all_types = json.loads(TYPES_PATH.read_text(encoding="utf-8"))
    if args.type:
        targets = [t for t in all_types if t["key"] == args.type]
        if not targets:
            print(f"[error] --type {args.type!r} not found in {TYPES_PATH}", file=sys.stderr)
            return 2
    elif args.limit:
        targets = all_types[: args.limit]
    else:
        targets = all_types

    BODIES_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if REGISTRY_PATH.is_file():
        for e in json.loads(REGISTRY_PATH.read_text(encoding="utf-8")):
            existing[e["key"]] = e

    bodies: dict[str, str] = {}
    ok = cached = failed = skipped = 0
    for t in targets:
        key, zh = t["key"], t["zh"]
        law_ctx = _read_law_context(key)
        if not law_ctx:
            # No law_info seed -> cannot ground a fresh draft. Still load any
            # cached body and re-normalize it so fixes to normalize_body (e.g.
            # separator-slot sanitization) propagate to already-generated bodies;
            # the registry write below then carries the cleaned body. Without
            # this a skipped type's cached body could never be repaired short of
            # regenerating it, which is impossible without a law_info seed.
            cache = BODIES_DIR / f"{key}.md"
            if cache.is_file():
                bodies[key] = normalize_body(
                    cache.read_text(encoding="utf-8"),
                    required_slots_for_type(key),
                )
            skipped += 1
            print(f"[skip] {key}: no law_info seed")
            continue
        cache = BODIES_DIR / f"{key}.md"
        if cache.is_file() and not args.force:
            bodies[key] = cache.read_text(encoding="utf-8")
            cached += 1
            print(f"[cached] {key}")
            continue
        try:
            raw = _call_llm(_build_prompt(zh, law_ctx, key))
        except Exception as exc:  # noqa: BLE001 - report and fall back
            print(f"[fail] {key}: {exc}", file=sys.stderr)
            failed += 1
            if key in existing:
                bodies[key] = existing[key]["body"]
            continue
        # Audit the raw draft BEFORE normalization so omissions the drafter made
        # are visible instead of being silently papered over by normalize_body
        # (which appends missing slots to the 签署信息 tail). Non-blocking: the
        # normalized body is still written exactly as before.
        per_type = required_slots_for_type(key)
        per_tail = tail_allowed_slots_for_type(key)
        per_proper = [s for s in per_type if s not in per_tail]
        raw_audit = audit_body(
            raw,
            _instructions_for_body(key, zh, raw),
            key=key,
            zh=zh,
            required=per_type,
            tail_allowed=per_tail,
        )
        omitted = [
            s for s in per_proper
            if s in raw_audit.missing or s in raw_audit.tail_only
        ]
        if omitted:
            print(f"[audit] {key}: draft omitted body-proper slots {omitted}")
        body = normalize_body(raw, per_type)
        cache.write_text(body, encoding="utf-8")
        bodies[key] = body
        ok += 1
        print(f"[ok] {key} ({len(body)} chars)")

    # Assemble the full registry, preserving order. Only types that actually
    # have a body (freshly generated or carried over from the existing registry)
    # are written, so a single-type ``--type`` regen never truncates the file
    # and types that were never templated stay out (surfaced as
    # ``missing_templates`` by ``audit_all``, not as empty-body failures).
    registry = []
    for t in all_types:
        key, zh = t["key"], t["zh"]
        raw = bodies.get(key) or existing.get(key, {}).get("body", "")
        if not raw:
            continue
        # Re-normalize every body at registry-write time so normalize_body fixes
        # (e.g. separator-slot sanitization {{交付/登记}} -> {{交付登记}}) propagate
        # to cached/skipped bodies even when the type wasn't freshly LLM-generated
        # this run. Idempotent for already-clean bodies; only rewrites bodies
        # carrying stale token forms, and persists the cleaned cache.
        per_type = required_slots_for_type(key)
        body = normalize_body(raw, per_type)
        if body != raw:
            (BODIES_DIR / f"{key}.md").write_text(body, encoding="utf-8")
            print(f"[renormalized] {key}")
        registry.append(
            {
                "key": key,
                "zh": zh,
                "body": body,
                "slot_instructions": _instructions_for_body(key, zh, body),
            }
        )
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nwrote {len(registry)} templates to {REGISTRY_PATH} "
        f"(ok={ok}, cached={cached}, failed={failed})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
