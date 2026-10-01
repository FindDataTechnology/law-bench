"""One-off: seed scenario-specific ``source='tagged'`` clauses for the 43 contract
types that have zero scenario coverage.

For each type, the LLM:
  1. Suggests 3-4 short Chinese scenario labels (e.g. 外资 / 上市公司 / 个人独资).
  2. For each (type, scenario) pair, rewrites ONE key section from the 母版 base
     to be scenario-specific (tweaking the language so the resulting body_hash
     differs from base + from sibling scenarios).

The seeded rows are tagged ``source='tagged'`` with ``tags.scenario`` and
``tag_review.scenario='pending'`` so they enter the assembly's scenario override
path the same way the retag_scenario.py-produced corpus does. They count as
''auto'' (not manual) and live under a synthetic source_path so the
``(source_path, section, body_hash)`` partial unique index routes any duplicate
LLM output to a no-op upsert.

Runbook:
  PYTHONPATH=. python3 scripts/seed_scenario_clauses.py [--limit 5]
  PYTHONPATH=. python3 scripts/seed_scenario_clauses.py              # full
  PYTHONPATH=. python3 scripts/seed_scenario_clauses.py --only training,partnership

After this, run ``python3 scripts/generate_all_types_stored.py`` to materialize
the new scenario x stance combinations in ``contract_artifacts``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import litellm
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

from src.clauses.store import upsert_clauses
from src.eval.db import connect, now_iso
from src.eval.store import ensure_schema

MODEL = os.environ.get("DRAFTER_MODEL") or "openai/glm-5.2"

# 43 types with no source='tagged' clauses (output of the diagnostic query).
TYPES_43: list[str] = [
    "housekeeping", "partnership", "divorce", "accident-settlement",
    "private_equity_fund", "estate-division", "marital-property", "factoring",
    "real_estate_development", "vam_agreement", "ppp_project", "insurance",
    "talent_agency", "ip_license", "training", "shareholders", "mortgage",
    "elderly-support", "adoption", "pledge", "film_production", "warehousing",
    "trust", "capital_increase", "software_development", "equity_holding_in_trust",
    "debt-transfer", "investment", "will", "nda", "internship", "gift",
    "debt-restructuring", "settlement", "merger_acquisition", "company_formation",
    "non-compete", "legacy-support", "employment", "labor-service", "prenup",
    "equity_incentive", "shop-transfer",
]

# Curated per-type scenario fallback (used when LLM JSON parsing fails).
# 3-4 short Chinese labels per type, matching common business sub-types.
FALLBACK_SCENARIOS: dict[str, list[str]] = {
    "housekeeping": ["日常保洁", "深度清洁", "钟点工", "其他"],
    "partnership": ["普通合伙", "有限合伙", "项目合伙", "其他"],
    "divorce": ["协议离婚", "诉讼离婚", "其他"],
    "accident-settlement": ["交通事故", "工伤事故", "医疗事故", "其他"],
    "private_equity_fund": ["基金募集", "基金投资", "基金退出", "其他"],
    "estate-division": ["法定继承", "遗嘱继承", "其他"],
    "marital-property": ["婚前财产", "婚后共同财产", "其他"],
    "factoring": ["明保理", "暗保理", "其他"],
    "real_estate_development": ["住宅开发", "商业开发", "工业地产", "其他"],
    "vam_agreement": ["股权转让对赌", "业绩对赌", "上市对赌", "其他"],
    "ppp_project": ["BOT", "TOT", "ROT", "其他"],
    "insurance": ["财产保险", "人寿保险", "意外保险", "其他"],
    "talent_agency": ["艺人经纪", "运动员经纪", "高管猎头", "其他"],
    "ip_license": ["专利许可", "商标许可", "著作权许可", "其他"],
    "training": ["职业培训", "语言培训", "企业内训", "其他"],
    "shareholders": ["有限公司股东", "股份公司股东", "其他"],
    "mortgage": ["房产抵押", "动产抵押", "股权质押", "其他"],
    "elderly-support": ["居家养老", "机构养老", "社区养老", "其他"],
    "adoption": ["收养子女", "继父母收养", "其他"],
    "pledge": ["动产质押", "权利质押", "其他"],
    "film_production": ["电影制作", "电视剧制作", "网络短剧", "其他"],
    "warehousing": ["普通仓储", "保税仓储", "危险品仓储", "其他"],
    "trust": ["资金信托", "财产信托", "家族信托", "其他"],
    "capital_increase": ["有限公司增资", "股份公司增资", "外资增资", "其他"],
    "software_development": ["定制开发", "SaaS订阅", "外包开发", "其他"],
    "equity_holding_in_trust": ["代持协议", "隐名股东", "其他"],
    "debt-transfer": ["债权转让", "债务转移", "其他"],
    "investment": ["股权投资", "项目投资", "其他"],
    "will": ["自书遗嘱", "代书遗嘱", "公证遗嘱", "其他"],
    "nda": ["单方披露", "双向披露", "员工保密", "其他"],
    "internship": ["高校实习", "社会实践", "其他"],
    "gift": ["动产赠与", "不动产赠与", "其他"],
    "debt-restructuring": ["债务豁免", "债转股", "展期重组", "其他"],
    "settlement": ["诉讼和解", "仲裁和解", "其他"],
    "merger_acquisition": ["股权收购", "资产收购", "换股并购", "其他"],
    "company_formation": ["有限公司设立", "股份公司设立", "外资公司设立", "其他"],
    "non-compete": ["离职竞业", "在职竞业", "其他"],
    "legacy-support": ["隔代抚养", "遗赠扶养", "其他"],
    "employment": ["全日制用工", "非全日制用工", "劳务派遣", "其他"],
    "labor-service": ["劳务派遣", "劳务分包", "其他"],
    "prenup": ["婚前财产协议", "婚后财产协议", "其他"],
    "equity_incentive": ["股票期权", "限制性股票", "虚拟股权", "其他"],
    "shop-transfer": ["商铺转让", "摊位转让", "其他"],
}


def _llm(prompt: str, *, max_tokens: int = 1024) -> str:
    resp = litellm.completion(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _extract_json(text: str) -> Any:
    """Tolerate ```json fences / leading prose; return the first JSON value."""
    import re
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Find first { or [
    for i, ch in enumerate(text):
        if ch in "[{":
            text = text[i:]
            break
    # Trim trailing non-JSON
    depth = 0
    for j, ch in enumerate(text):
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                text = text[: j + 1]
                break
    return json.loads(text)


def _suggest_scenarios(contract_type: str) -> list[str]:
    """Return 3-4 short Chinese scenario labels for a type.

    First tries the LLM (returns 0-4). Then falls back to the curated
    FALLBACK_SCENARIOS dict (always 3-4). Result is union, deduped, capped at 4.
    """
    out: list[str] = []
    llm_err: str | None = None
    try:
        prompt = (
            "你是中国合同业务场景分类助手。给下面这个合同类型列出 3-4 个常见"
            "业务子场景，每个用 2-6 个汉字的简短中文标签回答（不要解释、不要编号、"
            "不要标点，例如 有限公司增资、股份公司增资、外资增资）。\n\n"
            f"合同类型：{contract_type}\n\n"
            "只输出一个 JSON 数组。"
        )
        raw = _llm(prompt, max_tokens=128)
        try:
            val = _extract_json(raw)
        except Exception as exc:
            val = None
            llm_err = f"json-parse: {exc}"
        if isinstance(val, list):
            out.extend(str(x).strip() for x in val if str(x).strip())
    except Exception as exc:
        llm_err = f"llm-call: {exc}"
    # Fall back to curated list
    fb = FALLBACK_SCENARIOS.get(contract_type, [])
    for s in fb:
        if s and s not in out:
            out.append(s)
        if len(out) >= 4:
            break
    return out[:4]


def _rewrite_section(contract_type: str, scenario: str, section: str, base_body: str) -> str | None:
    """Ask the LLM to rewrite one base section to be scenario-specific.

    The rewrite must keep slot tokens ``{{中文slot}}`` intact (we'll re-derive
    slot_instructions from the body on insert) and must NOT change the section
    header (e.g. ``第一条 增资方案``) so the assembly section lookup still hits.
    """
    prompt = (
        "你是中国合同条款改写助手。改写下面这条合同条款，让它专门针对"
        f"「{scenario}」业务场景做微调（增补该场景特有的交易细节）。要求：\n"
        "1. 保留 ``{{中文slot}}`` 占位符原样不动；\n"
        "2. 保留条款编号与开头的章节标题（如「第一条 XXX」）原样不动；\n"
        "3. 改写篇幅 ≤ 400 字，输出纯中文正文，不要解释。\n\n"
        f"合同类型：{contract_type}\n"
        f"场景：{scenario}\n"
        f"条款：\n{base_body}\n"
    )
    raw = _llm(prompt, max_tokens=600)
    body = raw.strip().strip("`").strip()
    if not body:
        return None
    # Sanity: must keep the section header line if the base had one
    first_line = base_body.splitlines()[0].strip() if base_body else ""
    if first_line and first_line not in body:
        return None
    return body


def _fetch_base_clauses(conn, contract_type: str) -> list[dict]:
    """Return base clauses for the type, ordered by id (so we pick stable sections)."""
    rows = conn.execute(
        "SELECT id, section, body FROM clauses "
        "WHERE contract_type = %s AND tags->>'source' = 'base' "
        "ORDER BY id",
        (contract_type,),
    ).fetchall()
    return [dict(r) for r in rows]


def _seed_one(conn, contract_type: str, *, dry: bool = False) -> dict:
    """Generate + insert scenario-specific tagged clauses for one type.

    Idempotent: skips scenarios that already have a seeded row.
    """
    base_clauses = _fetch_base_clauses(conn, contract_type)
    if not base_clauses:
        return {"type": contract_type, "skipped": "no base", "scenarios": 0, "inserted": 0}
    scenarios = _suggest_scenarios(contract_type)
    if not scenarios:
        return {"type": contract_type, "skipped": "no scenarios", "scenarios": 0, "inserted": 0}

    # Skip scenarios that already have a seeded row (identified by source_path prefix).
    # NOTE: psycopg treats '%' as a placeholder char; escape as '%%'.
    existing = {
        r["scenario"]
        for r in conn.execute(
            "SELECT DISTINCT tags->>'scenario' AS scenario FROM clauses "
            "WHERE contract_type = %s AND source_path LIKE 'scripts/seed_scenario_clauses.py/%%'",
            (contract_type,),
        ).fetchall()
        if r["scenario"]
    }
    new_scenarios = [s for s in scenarios if s not in existing][:3]
    if not new_scenarios:
        return {"type": contract_type, "scenarios": len(scenarios), "inserted": 0, "skipped_existing": len(existing)}

    # Rewrite only the 1 longest base section per scenario (cheaper than 2).
    target = max(base_clauses, key=lambda c: len(c["body"]))

    now = now_iso()
    new_clauses: list[dict] = []
    for scen in new_scenarios:
        body = _rewrite_section(contract_type, scen, target["section"], target["body"])
        if not body:
            continue
        source_path = f"scripts/seed_scenario_clauses.py/{contract_type}/{scen}/{target['section']}.md"
        new_clauses.append({
            "contract_type": contract_type,
            "section": target["section"],
            "body": body,
            "slot_instructions": [],
            "law_refs": [],
            "source_path": source_path,
            "source_doc_title": f"{contract_type} {scen} 示范",
            "manual": False,
            "tags": {"source": "tagged", "scenario": scen},
            "tag_review": {"scenario": "pending"},
        })

    if dry or not new_clauses:
        return {
            "type": contract_type,
            "scenarios": len(scenarios),
            "new_scenarios": len(new_scenarios),
            "would_insert": len(new_clauses),
            "inserted": 0,
        }
    n = upsert_clauses(new_clauses, db=None)
    return {
        "type": contract_type,
        "scenarios": len(scenarios),
        "new_scenarios": len(new_scenarios),
        "inserted": n,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only first N types (smoke)")
    ap.add_argument("--only", type=str, default="", help="comma-separated type subset")
    ap.add_argument("--dry", action="store_true", help="plan only, no DB writes")
    args = ap.parse_args()

    if args.only:
        types = [t.strip() for t in args.only.split(",") if t.strip()]
    else:
        types = list(TYPES_43)
    if args.limit:
        types = types[: args.limit]

    ensure_schema()
    conn = connect()
    t0 = time.time()
    print(f"seeding scenarios for {len(types)} types via {MODEL}", flush=True)
    results: list[dict] = []
    for i, t in enumerate(types, 1):
        try:
            r = _seed_one(conn, t, dry=args.dry)
        except Exception as exc:  # noqa: BLE001
            r = {"type": t, "error": str(exc)[:120]}
        results.append(r)
        elapsed = time.time() - t0
        print(
            f"  [{i:>2}/{len(types)}] {t:<28} scen={r.get('scenarios', 0):>2} "
            f"inserted={r.get('inserted', 0):>3} ({elapsed:.0f}s)",
            flush=True,
        )
    conn.close()
    inserted = sum(r.get("inserted", 0) for r in results)
    print(f"\nDONE in {time.time()-t0:.0f}s: types={len(types)} new_clauses={inserted}")


if __name__ == "__main__":
    sys.exit(main())
