"""LLM extraction of structured clauses from a parsed 示范文本.

:func:`extract_document` calls the DRAFTER LLM (via ``litellm``, mirroring
``scripts/generate_contract_templates_llm.py``) once per document, returning the
document's contract type / province / level plus a list of reusable clauses -
each with a ``section``, a ``body`` containing ``{{slot}}`` placeholders, and a
slot-instruction manifest. Law references (``《...》`` provisions) are derived
deterministically from each clause body via :mod:`src.eval.legal_refs` (not
trusted to the LLM). Province/level are document-level (the whole 示范文本 is
from one province); clauses inherit them.

Idempotency: the raw extracted JSON is cached under
``src/clauses/data/_extracted/<stem>.json`` so re-runs can skip LLM cost; the
store layer deduplicates on ``(source_path, section, body_hash)``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# Avoid litellm's remote model-cost-map fetch (network-dependent); local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.generator import SLOT_PATTERN
from src.eval.legal_refs import CATEGORY_ZH, categorize

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_CONTRACT_TYPES_PATH = _REPO_ROOT / "src" / "eval" / "seed" / "law_info" / "contract_types.json"
_CACHE_DIR = _HERE / "data" / "_extracted"

# Canonical section order (zh) for assembly. The LLM is asked to map each clause
# to one of these; unrecognized sections sort last. Aligned to the skeleton's
# section headings in src/contracts/data/contracts.json.
SECTION_ORDER = (
    "当事人",
    "鉴于",
    "合同标的",
    "价款及支付",
    "履行期限",
    "权利义务",
    "违约责任",
    "争议解决",
    "附则",
    "签署信息",
)

# Cap input text so prompts stay bounded for long 示范文本.
_MAX_INPUT_CHARS = 12000

_LAW_NAME_RE = re.compile(r"《([^》\n]+)》")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _contract_type_catalog() -> list[dict]:
    return json.loads(_CONTRACT_TYPES_PATH.read_text(encoding="utf-8"))


def _valid_type_keys() -> set[str]:
    return {t["key"] for t in _contract_type_catalog()}


def section_rank(section: str) -> int:
    """Sort rank for a section (canonical order first, unknown last)."""
    if section in SECTION_ORDER:
        return SECTION_ORDER.index(section)
    return len(SECTION_ORDER)


def _build_prompt(text: str) -> str:
    types = _contract_type_catalog()
    type_lines = "\n".join(f'- "{t["key"]}": {t["zh"]}' for t in types)
    sections = "、".join(SECTION_ORDER)
    return (
        "你是中国法律合同结构化抽取助手。下面是一份合同示范文本（可能含使用说明、表格、空白下划线等），"
        "请从中抽取可复用的合同条款，输出严格的 JSON。\n\n"
        "输出格式（仅 JSON，不要任何解释）：\n"
        "{\n"
        '  "contract_type": "<必须从下方类型清单选一个 key，无法判断用 unknown>",\n'
        '  "source_doc_title": "<合同标题，如：吉林省前期物业服务合同（示范文本）>",\n'
        '  "province": "<省份简称，如 吉林/云南/北京；全国级合同填 null>",\n'
        '  "level": "<national 或 local；无地方制定机关且仅援引国家法规=national，否则 local>",\n'
        '  "clauses": [\n'
        '    {\n'
        '      "section": "<归入下列章节之一：' + sections + '>",\n'
        '      "body": "<条款正文，保留原意但简洁；把可填写的甲方/乙方/标的/金额/日期等关键值改为 {{slot}} 占位符，'
        "尽量复用 party_a, party_b, subject, amount, term_start, term_end, party_a_duty, party_b_duty, "
        'penalty, jurisdiction, sign_date, sign_location；类型特有字段可新增 {{slot}}>",\n'
        '      "slot_instructions": [\n'
        '        {"name": "<slot名，不含花括号>", "label": "<中文标签>", "description": "<说明>", '
        '"example": "<示例值>", "required": true}\n'
        "      ],\n"
        '      "tags": {"scenario": "<业务场景/交易子类型，如 农产品买卖/消费品零售/驾校培训/养老服务/住宅租赁/建设工程 等；用简短中文标签，无法判断填 null>", "stance": "<pro_a偏甲方/pro_b偏乙方/balanced中立>", "strength": "<strong强/standard标准/mild弱>", "risk": "<high高/medium中/low低>", "mandatory": "<mandatory强制/default任意/recommended示范>"}\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"合同类型清单（contract_type 只能取其中 key 或 unknown）：\n{type_lines}\n\n"
        "要求：\n"
        "1. 只抽取实质条款（当事人、标的、价款、期限、权利义务、违约、争议解决、附则、签署等），"
        "跳过使用说明、目录、附件清单、填表说明等非条款内容。\n"
        "2. 每个 {{slot}} 必须在 slot_instructions 里有且仅有一条对应说明。\n"
        "3. body 里的法条名保留原样《...》，不要改成占位符。\n"
        "4. province 取省份简称（去掉省/市字）；全国级合同 province=null 且 level=national。\n"
        "5. tags：scenario 判断该条款所属的业务场景/交易子类型（如 农产品买卖、消费品零售、驾校培训、养老服务、住宅租赁、建设工程、快递 等，用简短中文标签；同一示范文本的多条条款通常属于同一场景）；"
        "再判断利益倾向（pro_a偏甲方/pro_b偏乙方/balanced中立）、保护强度（strong/standard/mild）、"
        "风险等级（high/medium/low）、法律性质（mandatory强制/default任意/recommended示范）。不确定的填 null。\n\n"
        f"合同示范文本：\n\n{text}"
    )


def _call_llm(prompt: str) -> str:
    import litellm

    model = os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(os.environ.get("DRAFTER_TEMPERATURE", "0.2")),
        max_tokens=int(os.environ.get("EXTRACT_MAX_TOKENS", "8192")),
    )
    return resp.choices[0].message.content or ""


def _extract_json(raw: str) -> dict:
    """Parse the LLM's JSON output, tolerating a surrounding code fence."""
    text = raw.strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    # fall back to the outermost { ... } if the model added prose
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _law_refs_from_body(body: str) -> list[dict]:
    """Derive ``{name, category, category_zh}`` for each 《...》 provision in body."""
    out: list[dict] = []
    seen: set[str] = set()
    for raw in _LAW_NAME_RE.findall(body):
        name = raw.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cat = categorize(name)
        out.append({"name": name, "category": cat, "category_zh": CATEGORY_ZH[cat]})
    return out


def _normalize_slot_instructions(body: str, instructions: list[dict]) -> list[dict]:
    """Ensure exactly one instruction per ``{{slot}}`` in body.

    Drops instructions for absent slots and synthesizes a stub for any slot the
    LLM missed, so the manifest always covers the body's slots.
    """
    body_slots = list(dict.fromkeys(SLOT_PATTERN.findall(body)))
    by_name = {}
    for ins in instructions or []:
        name = ins.get("name")
        if name and name not in by_name:
            entry = {
                "name": name,
                "label": str(ins.get("label") or name),
                "description": str(ins.get("description") or ""),
                # YAML parses unquoted numbers/dates as int/date; coerce to str
                # so Jsonb serialization never chokes on a slot example.
                "example": "" if ins.get("example") is None else str(ins.get("example")),
                "required": bool(ins.get("required", False)),
            }
            # Round-trip generator metadata: prompt / type / enum_values.
            # Additive only — copy when present, never add when absent, so
            # entries without these keys stay exactly as before.
            for _k in ("prompt", "type", "enum_values"):
                if _k in ins:
                    entry[_k] = ins[_k]
            by_name[name] = entry
    out = []
    for s in body_slots:
        out.append(
            by_name.get(
                s,
                {"name": s, "label": s, "description": "", "example": "", "required": False},
            )
        )
    return out


def _post_process(raw: dict, source_path: str) -> dict:
    """Validate + normalize the LLM output into a document-with-clauses record."""
    valid = _valid_type_keys()
    contract_type = raw.get("contract_type") or "unknown"
    if contract_type not in valid:
        contract_type = "unknown"
    province = raw.get("province")
    if isinstance(province, str):
        province = province.strip() or None
    else:
        province = None
    level = raw.get("level")
    if level not in ("national", "local"):
        # default by province presence: provincial doc -> local, else national
        level = "local" if province else "national"
    # conservative: national must have no province
    if level == "national":
        province = None

    clauses: list[dict] = []
    source = "tagged" if level == "local" else "base"
    for c in raw.get("clauses") or []:
        body = (c.get("body") or "").strip()
        if not body:
            continue
        section = (c.get("section") or "附则").strip() or "附则"
        instructions = _normalize_slot_instructions(body, c.get("slot_instructions") or [])
        # build tags: source + scenario + LLM-suggested universal dims
        clause_tags: dict = {"source": source}
        scenario = (c.get("tags") or {}).get("scenario")
        if scenario and scenario != "null":
            clause_tags["scenario"] = scenario
        for k in ("stance", "strength", "risk", "mandatory"):
            v = (c.get("tags") or {}).get(k)
            if v and v != "null":
                clause_tags[k] = v
        # all auto-set tags enter review as pending
        tag_review = {k: "pending" for k in clause_tags}
        clauses.append(
            {
                "contract_type": contract_type,
                "section": section,
                "body": body,
                "slot_instructions": instructions,
                "law_refs": _law_refs_from_body(body),
                "level": level,
                "source_path": source_path,
                "source_doc_title": (raw.get("source_doc_title") or "").strip() or None,
                "body_hash": hashlib.md5(body.encode("utf-8")).hexdigest(),
                "category": source,
                "tags": clause_tags,
                "tag_review": tag_review,
            }
        )
    return {
        "contract_type": contract_type,
        "province": province,
        "level": level,
        "source_doc_title": raw.get("source_doc_title") or None,
        "source_path": source_path,
        "clauses": clauses,
    }


def _cache_path(source_path: str) -> Path:
    stem = Path(source_path).stem
    return _CACHE_DIR / f"{stem}.json"


def load_cached(source_path: str) -> dict | None:
    """Return the cached extraction for ``source_path`` if present, else None."""
    p = _cache_path(source_path)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - corrupt cache -> re-extract
            return None
    return None


def save_cache(source_path: str, record: dict) -> None:
    p = _cache_path(source_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_document(document: dict, *, use_cache: bool = True) -> dict:
    """Extract structured clauses from one parsed document.

    ``document`` is ``{source_path, ext, text}`` (from :mod:`src.clauses.corpus`).
    Returns ``{contract_type, province, level, source_doc_title, source_path,
    clauses}`` where each clause is a ready-to-store row (incl. ``category``,
    ``body_hash``, ``slot_instructions``, ``law_refs``). Reuses the cached
    extraction under ``src/clauses/data/_extracted/`` unless ``use_cache=False``.
    """
    source_path = document["source_path"]
    if use_cache:
        cached = load_cached(source_path)
        if cached is not None:
            return cached
    text = (document.get("text") or "")[:_MAX_INPUT_CHARS]
    if not text.strip():
        return {
            "contract_type": "unknown",
            "province": None,
            "level": "national",
            "source_doc_title": None,
            "source_path": source_path,
            "clauses": [],
        }
    record = _post_process(_extract_json(_call_llm(_build_prompt(text))), source_path)
    save_cache(source_path, record)
    return record
