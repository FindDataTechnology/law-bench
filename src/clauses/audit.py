"""LLM-driven clause-library audit: classify -> rewrite -> verify.

A one-time quality pass over assembly-ready clauses (P0 base / P1 custom / P2
tagged-ready) that the rubric-only evaluation is blind to. Three defect classes:

- ``region_leak``  — provincial/city regulations hardcoded into a national base
- ``missing_slot`` — commercial blanks (amounts/parties/periods) written as
                     literals instead of ``{{slot}}`` (statutory defaults stay)
- ``extraction_artifact`` — 示范文本 boilerplate (合同编号 headers, signing-place
                     leftovers) that belong to the contract shell, not a clause

Pipeline (per clause)::

    3 models classify (kimi-k3 / glm-5.2 / deepseek-v3)  ── majority vote
        │  verdict ∈ {ok, region_leak, missing_slot, wrong_scenario,
        │              extraction_artifact, duplicate, uncertain}
        ▼  (needs_change only)
    single-model rewrite (kimi-k3)  ── region genericize / slot-ify / strip
        ▼
    verify (different model)  ── defect fixed? legal point preserved?
        ▼
    pass  -> update_clause(body=rewrite)   (manual=true, re-derives hash/slots/refs)
    fail  -> keep original, log to output/audit/*_failed.json

``wrong_scenario`` and ``duplicate`` are NOT rewritten here: wrong_scenario needs
a retag, duplicate needs the deterministic dedupe pass (see ``scripts/audit_clauses.py
--tier p3``). They are classified so the driver can route them.

Reuses (no new infra):
- litellm.completion + RateLimit/ServiceUnavailable retry  (self_iterate.py pattern)
- _extract_json fence-stripping                            (src/clauses/extract.py)
- ThreadPoolExecutor + majority vote                       (src/eval/scoring.py pattern)
- update_clause / bulk_review / is_assembly_ready          (src/clauses/{store,tag_review}.py)

NOTE: audit metadata is NOT persisted into the ``tags`` JSONB — ``validate_tags``
silently drops unknown keys (``tags.py`` line 175). Per-clause results go to
``output/audit/<type>_<id>.json``; batch-level goes to ``pipeline_runs``.
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

# --- province / city name list (hardcoded — no existing list in the codebase) --
# 34 province-level administrative regions + common sub-provincial cities that
# appear in local regulations. The ``region`` tag dimension was deliberately
# removed (province is provenance, not a legal axis — see clause-region-is-wrong-axis
# memory), so there is no vocab to reuse.
PROVINCES = [
    # municipalities
    "北京", "天津", "上海", "重庆",
    # provinces
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽",
    "福建", "江西", "山东", "河南", "湖北", "湖南", "广东", "海南",
    "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    # autonomous regions
    "内蒙古", "广西", "西藏", "宁夏", "新疆",
    # SARs
    "香港", "澳门",
]
# Sub-provincial / provincial-capital cities frequently cited in local 法规/办法.
_COMMON_CITIES = [
    "深圳", "广州", "杭州", "南京", "成都", "武汉", "西安", "苏州",
    "东莞", "佛山", "珠海", "中山", "惠州", "汕头", "厦门", "福州",
    "长沙", "郑州", "青岛", "济南", "大连", "沈阳", "哈尔滨", "长春",
    "昆明", "贵阳", "南昌", "合肥", "太原", "石家庄", "兰州", "西宁",
    "海口", "南宁", "银川", "乌鲁木齐", "拉萨", "呼和浩特",
]
_ALL_PLACE_NAMES = PROVINCES + _COMMON_CITIES

# Place name + optional 省/市 + local-regulation suffix. Matches:
#   《深圳市员工工资支付条例》  广东省工资支付条例  北京市建筑垃圾处置管理规定
#   按照深圳市现行规定  依据广东省有关规定
_REGULATION_SUFFIX = r"(?:条例|规定|办法|实施细则|实施办法|管理办法|管理规定|支付条例|工资支付条例|管理细则)"
_REGION_RE = re.compile(
    r"(?:" + "|".join(_ALL_PLACE_NAMES) + r")"
    r"(?:省|市|自治区|特别行政区)?"
    r"(?:[一-鿿]{0,10}?)"
    r"(?:" + _REGULATION_SUFFIX + r")"
)
# Bare place name followed by a locality-binding qualifier (现行规定/的有关规定/地区).
_REGION_BIND_RE = re.compile(
    r"(?:" + "|".join(_ALL_PLACE_NAMES) + r")(?:省|市)?"
    r"(?:现行(?:规定|法规)|的有关规定|地区(?:内|范围内)?|辖区内)"
)
# Local agency names: XX市工商局 / XX省住建厅 / XX市XX管理局 / XX市XX委员会.
_REGION_AGENCY_RE = re.compile(
    r"(?:" + "|".join(_ALL_PLACE_NAMES) + r")"
    r"(?:省|市)?"
    r"(?:[一-鿿]{0,8}?)"
    r"(?:局|厅|委员会|管理局|管理处|管理站|监督管理部门)"
)

# Same trio as V4/V5 self-iteration so audit verdicts are apples-to-apples with
# the re-eval gate. Relay rate-limits per uid (not per model) at 12 concurrent.
# NOTE: deepseek-v3 was retired from the relay (2026-08-12: "No available
# channel"); deepseek-v4-pro is its successor. self_iterate.py's DEFAULT_JUDGES
# still names v3 — the re-eval gate must pass --judges with v4-pro to match.
DEFAULT_AUDIT_MODELS = ["openai/kimi-k3", "openai/glm-5.2", "openai/deepseek-v4-pro"]
REWRITE_MODEL = "openai/kimi-k3"
# Verifier is deliberately a DIFFERENT model than the rewriter.
VERIFY_MODEL = "openai/glm-5.2"

VERDICTS = (
    "ok",
    "region_leak",
    "missing_slot",
    "wrong_scenario",
    "extraction_artifact",
    "duplicate",
    "uncertain",
)
# Verdicts that trigger a rewrite. wrong_scenario (needs retag) and duplicate
# (needs dedupe) are handled out-of-band by the driver, not rewritten here.
_REWRITABLE = {"region_leak", "missing_slot", "extraction_artifact"}

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


# --------------------------------------------------------------------------- #
# region_lint — deterministic, no LLM
# --------------------------------------------------------------------------- #
def region_lint(body: str) -> list[str]:
    """Return residual province/city regulation matches found in ``body``.

    Detects local-regulation citations (《深圳市员工工资支付条例》), bare
    locality-binding qualifiers (按照广东省现行规定), and local agency names
    (北京市住建委). Used both as a pre-filter (region_leak candidates) and as a
    post-rewrite quality metric (rewritten clauses should show 0 matches).

    National-level names (中华人民共和国/全国/国家) are NOT flagged.
    """
    if not body:
        return []
    found: list[str] = []
    for rx in (_REGION_RE, _REGION_BIND_RE, _REGION_AGENCY_RE):
        for m in rx.findall(body):
            if m and m not in found:
                found.append(m)
    return found


# --------------------------------------------------------------------------- #
# LLM call helpers (mirror scripts/self_iterate.py:generate_combined_clause)
# --------------------------------------------------------------------------- #
def _call_llm_with_retry(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> str | None:
    """Single litellm.completion call with RateLimit/ServiceUnavailable retry.

    Mirrors ``generate_combined_clause``: 3 attempts, backoff 15*(attempt+1)s,
    triggers on ``RateLimit`` or ``ServiceUnavailable`` in the exception string.
    """
    import litellm

    if max_tokens is None:
        max_tokens = int(os.environ.get("GEN_MAX_TOKENS", "800"))
    for attempt in range(3):
        try:
            resp = litellm.completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return text
        except Exception as e:
            s = str(e)
            # "No available channel" = the model has no backing channel on the
            # relay (quota exhausted / disabled). Not transient — retrying just
            # burns 45s of backoff per call. Fail fast; the 2-of-3 majority
            # vote still holds with the remaining models.
            if "No available channel" in s:
                return None
            if "RateLimit" in s or "ServiceUnavailable" in s or "429" in s or "503" in s:
                if attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
            print(f"  ⚠ LLM error ({model}): {e}")
            return None
    return None


def _extract_json(raw: str) -> dict:
    """Parse LLM JSON output, tolerating a surrounding code fence or prose.

    Mirrors ``src/clauses/extract.py:_extract_json``.
    """
    text = (raw or "").strip()
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Prompts
# --------------------------------------------------------------------------- #
_CLASSIFY_SYSTEM = """\
你是中国法律合同条款质量审核专家。判断一条合同条款是否存在以下缺陷之一。

缺陷类型定义（按严重度排序）：
1. region_leak — 条款正文硬编码了特定省市的地方性法规（如《深圳市员工工资支付条例》、《广东省工资支付条例》），或将地方性规定作为通用义务。全国通用条款不应绑定特定地域。
2. missing_slot — 条款存在应当用 {{slot}} 占位符表示的商业空白（具体金额、当事人名称、期限日期、标的描述等），但被写死为具体值或缺失。注意：法定时限（"15日内"、"30日"）、法定比例（"不超过20%"）等法定默认值不应改为占位符。
3. extraction_artifact — 条款含抽取伪影：残留编号、格式符号、表格碎片、合同编号/签订地点等示范文本表头、不完整句子、无意义重复。
4. wrong_scenario — 条款业务场景与所在章节/类型不匹配（如建筑垃圾清运出现在通用权利义务章节）。
5. duplicate — 条款与同类型下其他条款内容完全重复。
6. ok — 无缺陷。

判断规则：
- 只判定最严重的一个缺陷；多缺陷时按 region_leak > missing_slot > extraction_artifact > wrong_scenario > duplicate > ok。
- region_leak：正文出现 省/市名 + 地方性法规名（条例/规定/办法），且条款为全国通用级别。
- missing_slot：出现具体金额（"人民币10万元"）、具体当事人名称（非甲方/乙方通称）、具体日期（非法定时限）等应填空值。
- 切勿把法定时限/法定比例误判为 missing_slot——它们必须保持硬编码。
- 仅输出严格 JSON，不要解释。"""

_CLASSIFY_USER = """\
合同类型：{contract_type}
章节：{section}
条款正文：
---
{body}
---

输出 JSON：
{{"verdict":"ok|region_leak|missing_slot|wrong_scenario|extraction_artifact|duplicate","suggested_fix":"非ok时简述修复方向（如'将《深圳市员工工资支付条例》改为国家法律法规通用表述'、'将金额改为{{amount}}占位符'）；ok时填空字符串","confidence":0.0到1.0,"reason":"简要依据"}}"""

_REWRITE_SYSTEM = """\
你是中国法律合同条款修订专家。根据审核结论修订一条合同条款，遵循三条规则：

规则1（region_leak 修复）：将硬编码的地方性法规和省市名泛化为全国通用表述。
- 保留原有法律义务和保护标准，只替换地域绑定，绝不删除义务本身。
- 《XX省/市XX条例》→ 替换为国家法律法规（《中华人民共和国劳动合同法》《中华人民共和国劳动法》《民法典》等）；无对应国家法律的，替换为"按照国家及当地有关规定执行"。
- "广东省、深圳市现行规定" → "国家现行法律法规"。
- XX市工商局/XX省住建厅等地方机构 → "当地相关主管部门"。
- 裸省市名（"深圳市"）在义务语境中 → "当地"。
- 保留对《民法典》《劳动合同法》等国家法律的引用。

规则2（missing_slot 修复）：将商业空白值替换为 {{slot}} 占位符。
- 应改为占位符的：具体金额（→{{amount}}）、具体当事人名称（→{{party_a}}/{{party_b}}）、具体日期（→{{term_start}}/{{term_end}}）、具体标的描述（→{{subject}}）、具体违约金数额（→{{penalty}}）。
- 必须保持硬编码的：法定时限（"15日内"、"30日"、"一年内"）、法定比例（"不超过20%"）、法定程序步骤、法律条文编号。
- 尽量复用已有规范 slot 名：party_a, party_b, subject, amount, term_start, term_end, party_a_duty, party_b_duty, penalty, jurisdiction, sign_date, sign_location。

规则3（extraction_artifact 修复）：删除抽取伪影。
- 移除残留编号（"1."、"（1）"等，除非是条款结构本身）、格式碎片、表头（合同编号/签订地点/签订日期行）、不完整句子。
- 保持条款语义完整。

输出要求：
- 只输出修订后的条款正文，不要解释、不要加引号、不要加代码块标记。
- 不要添加章节标题（如 ## 价款及支付）；章节标题由系统在组装时自动添加，条款正文只需包含条款内容本身。
- 保留 {{slot}} 占位符格式。"""

_REWRITE_USER = """\
合同类型：{contract_type}
章节：{section}
审核结论：{verdict}
修复方向：{suggested_fix}
原条款正文：
---
{body}
---

修订后条款正文："""

_VERIFY_SYSTEM = """\
你是中国法律合同条款审核专家。验证一条条款的修订是否正确，检查两个维度：

1. fixed（缺陷是否已修复）：原条款被判定为"{verdict}"缺陷，修订后该缺陷是否已消除？
   - region_leak：修订后是否还残留省市名或地方性法规？
   - missing_slot：商业空白是否已改为 {{slot}}？法定时限是否保留？
   - extraction_artifact：伪影是否已清除？
2. legal_preserved（法律义务是否保留）：修订后是否保留了原条款所有实质法律义务、权利、保护标准？是否没有丢失任何法律要点？

仅输出严格 JSON：
{{"fixed":true或false,"legal_preserved":true或false,"reason":"简要验证结论"}}"""

_VERIFY_USER = """\
合同类型：{contract_type}
原条款：
---
{original}
---
修订后条款：
---
{rewritten}
---

输出 JSON："""


# --------------------------------------------------------------------------- #
# classify
# --------------------------------------------------------------------------- #
def _classify_one(
    body: str, contract_type: str, section: str, model: str
) -> dict:
    """Single-model classify. Returns a normalized verdict dict (never raises)."""
    user = _CLASSIFY_USER.format(
        contract_type=contract_type, section=section or "（未指定）", body=body
    )
    raw = _call_llm_with_retry(
        model,
        [{"role": "system", "content": _CLASSIFY_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=400,
    )
    if not raw:
        return {"verdict": "uncertain", "suggested_fix": "", "confidence": 0.0, "reason": f"{model}: no response"}
    try:
        d = _extract_json(raw)
    except Exception as e:
        return {"verdict": "uncertain", "suggested_fix": "", "confidence": 0.0, "reason": f"{model}: json parse error {e}"}
    v = str(d.get("verdict", "")).strip()
    if v not in VERDICTS:
        v = "uncertain"
    return {
        "verdict": v,
        "suggested_fix": str(d.get("suggested_fix", "") or ""),
        "confidence": float(d.get("confidence", 0.5) or 0),
        "reason": str(d.get("reason", "") or ""),
        "model": model,
    }


def classify_clause_multi(
    body: str,
    contract_type: str,
    section: str,
    models: list[str] | None = None,
) -> dict:
    """3-model classify with majority vote.

    Returns ``{verdict, suggested_fix, confidence, model_verdicts}``. Tie /
    all-differ / no majority → ``uncertain`` (keep as-is, log for manual review),
    per the spec's low-confidence-defers-to-keep scenario.
    """
    models = models or DEFAULT_AUDIT_MODELS
    with ThreadPoolExecutor(max_workers=len(models)) as pool:
        results = list(
            pool.map(
                lambda m: _classify_one(body, contract_type, section, m), models
            )
        )

    model_verdicts = {r["model"]: r for r in results if r.get("model")}
    # Tally verdicts (exclude uncertain from winning unless it's the only one)
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    # Majority = any verdict with > n/2 votes. With 3 models that's >=2.
    n = len(results)
    winner = None
    winner_count = 0
    for v, c in counts.items():
        if c > winner_count:
            winner = v
            winner_count = c

    confidence = winner_count / n if n else 0.0
    if winner is None or winner == "uncertain" or winner_count <= n / 2 or confidence < 0.6:
        return {
            "verdict": "uncertain",
            "suggested_fix": "",
            "confidence": confidence,
            "model_verdicts": model_verdicts,
        }
    # Take suggested_fix from the first model that agreed with the winner.
    suggested = ""
    for r in results:
        if r["verdict"] == winner and r.get("suggested_fix"):
            suggested = r["suggested_fix"]
            break
    return {
        "verdict": winner,
        "suggested_fix": suggested,
        "confidence": confidence,
        "model_verdicts": model_verdicts,
    }


# --------------------------------------------------------------------------- #
# rewrite
# --------------------------------------------------------------------------- #
def rewrite_clause(
    body: str,
    contract_type: str,
    section: str,
    verdict: str,
    suggested_fix: str,
    *,
    model: str = REWRITE_MODEL,
) -> str | None:
    """Single-model rewrite applying the region/slot/artifact rules.

    Returns the rewritten body (slot names canonicalized via the slot ontology),
    or None on LLM failure.
    """
    from src.contracts.slot_ontology import normalize_body_slots

    user = _REWRITE_USER.format(
        contract_type=contract_type,
        section=section or "（未指定）",
        verdict=verdict,
        suggested_fix=suggested_fix or "（无）",
        body=body,
    )
    raw = _call_llm_with_retry(
        model,
        [{"role": "system", "content": _REWRITE_SYSTEM}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=int(os.environ.get("GEN_MAX_TOKENS", "1200")),
    )
    if not raw:
        return None
    body = raw.strip()
    # Defensive: strip a spurious leading section header the model may have
    # added despite the prompt instructing otherwise. The assembler prepends
    # "## <section>" itself, so a clause body must never start with "## ".
    body = re.sub(r"\A##\s+[^\n]*\n+", "", body)
    # Canonicalize any new {{slot}} names to the ontology (seller_name -> party_a).
    return normalize_body_slots(body, contract_type)


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def verify_rewrite(
    original: str,
    rewritten: str,
    contract_type: str,
    verdict: str,
    *,
    model: str = VERIFY_MODEL,
) -> dict:
    """Verify the rewrite fixed the defect AND preserved legal obligations.

    Uses a different model than the rewriter. Returns
    ``{fixed, legal_preserved, reason}``. Verify-fail → driver keeps the original.
    """
    user = _VERIFY_USER.format(
        contract_type=contract_type, original=original, rewritten=rewritten
    )
    sys_msg = _VERIFY_SYSTEM.format(verdict=verdict)
    raw = _call_llm_with_retry(
        model,
        [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}],
        temperature=0.1,
        max_tokens=400,
    )
    if not raw:
        return {"fixed": False, "legal_preserved": False, "reason": f"{model}: no response"}
    try:
        d = _extract_json(raw)
    except Exception as e:
        return {"fixed": False, "legal_preserved": False, "reason": f"json parse error {e}"}
    return {
        "fixed": bool(d.get("fixed", False)),
        "legal_preserved": bool(d.get("legal_preserved", False)),
        "reason": str(d.get("reason", "") or ""),
    }


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #
def audit_one_clause(clause: dict, models: list[str] | None = None) -> dict:
    """Run classify -> rewrite -> verify for one clause.

    Returns a result dict the driver persists to ``output/audit/<type>_<id>.json``::

        {clause_id, contract_type, section, verdict, confidence, original,
         rewritten, applied, verify, model_verdicts, region_lint_before,
         region_lint_after}

    ``applied`` is True only when verify confirms fixed AND legal_preserved.
    ``wrong_scenario``/``duplicate`` are classified but NOT rewritten.
    """
    body = (clause.get("body") or "").strip()
    ct = clause.get("contract_type") or ""
    section = clause.get("section") or ""
    cid = clause.get("id")

    result = {
        "clause_id": cid,
        "contract_type": ct,
        "section": section,
        "verdict": "ok",
        "confidence": 0.0,
        "original": body,
        "rewritten": None,
        "applied": False,
        "verify": None,
        "model_verdicts": {},
        "region_lint_before": region_lint(body),
        "region_lint_after": [],
    }

    if not body:
        result["verdict"] = "extraction_artifact"
        return result

    classified = classify_clause_multi(body, ct, section, models)
    result["verdict"] = classified["verdict"]
    result["confidence"] = classified["confidence"]
    result["model_verdicts"] = classified.get("model_verdicts", {})

    verdict = classified["verdict"]
    if verdict not in _REWRITABLE:
        # ok / uncertain / wrong_scenario / duplicate — no rewrite here.
        return result

    rewritten = rewrite_clause(
        body, ct, section, verdict, classified.get("suggested_fix", "")
    )
    if not rewritten or rewritten.strip() == body.strip():
        # No change produced — nothing to apply.
        result["rewritten"] = rewritten
        return result
    result["rewritten"] = rewritten

    verify = verify_rewrite(body, rewritten, ct, verdict)
    result["verify"] = verify
    result["region_lint_after"] = region_lint(rewritten)

    if verify.get("fixed") and verify.get("legal_preserved"):
        result["applied"] = True
    return result


__all__ = [
    "region_lint",
    "classify_clause_multi",
    "rewrite_clause",
    "verify_rewrite",
    "audit_one_clause",
    "DEFAULT_AUDIT_MODELS",
    "REWRITE_MODEL",
    "VERIFY_MODEL",
    "VERDICTS",
    "PROVINCES",
]
