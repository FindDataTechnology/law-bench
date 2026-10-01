"""Deterministic (zero-LLM) content checks over clause rows.

Shared rule set for the offline detector (``scripts/content_check_offline.py``)
and the remediation driver (``scripts/content_remediation.py``). Operates on
plain clause dicts (``clauses`` table rows) — no DB access here.

Defect classes:
- region_leak      : province/city + local regulation citations (``region_lint``)
- artifact_*       : signature shells, underscore blanks, table fragments
- dup_*            : exact body / body_hash duplicate groups
- literal_*        : hardcoded commercial values (candidates for missing_slot)
- tiny/empty body  : placeholder stubs and blank bodies
"""

from __future__ import annotations

import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.clauses.audit import region_lint

MONEY_RE = re.compile(
    r"(?:人民币|RMB)?\s*[¥￥]?\s*[0-9０-９][0-9０-９,，.．]{0,15}\s*(?:万元|亿元|万元整|元|万)"
)
DATE_RE = re.compile(r"[0-9０-９]{4}\s*年\s*[0-9０-９]{1,2}\s*月\s*[0-9０-９]{1,2}\s*日")
COMPANY_RE = re.compile(r"[一-鿿A-Za-z0-9]{2,20}(?:有限公司|有限责任公司|股份有限公司|集团)")
UNDERSCORE_RE = re.compile(r"[_＿]{3,}")
HEADER_RE = re.compile(r"合同编号|签订地点|签订日期|签署地点|签署日期|甲方[（(]?(?:盖章|签[章字字])|邮编")
NUM_START_RE = re.compile(r"\A\s*(?:\d{1,3}[\.、．]|[（(]\d{1,3}[)）]|[一二三四五六七八九十]{1,3}[、\.．])\s*")
PIPE_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
LEGAL_NUM_RE = re.compile(
    r"(?:日内|日内完成|个工作日|个工作日内|工作日内|自然日|个月|个月内向?|日内向|年以内|[0-9０-９]+日|[0-9０-９]+天|不低于|不超过|不得超过|高于|低于|百分之|‰|%|％)"
)

BAD_END_RE = re.compile(r"[。；；！？：）》\)\.\"”]$")
TINY_BODY = 20


def parse_dump(path: Path) -> list[dict]:
    """Parse a psql COPY dump (one JSON object per CSV field, QUOTE=\\x01)."""
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict] = []
    with opener(path, "rt", encoding="utf-8", newline="") as f:  # type: ignore[operator]
        reader = csv.reader(f, quotechar="\x01", escapechar="\x02")
        for rec in reader:
            if not rec or not rec[0].strip():
                continue
            try:
                rows.append(json.loads(rec[0]))
            except json.JSONDecodeError as e:
                rows.append({"_parse_error": str(e), "_raw": rec[0][:200]})
    return rows


def assembly_ready(clause: dict) -> bool:
    tr = clause.get("tag_review") or {}
    return bool(tr) and all(v == "approved" for v in tr.values())


def any_rejected(clause: dict) -> bool:
    tr = clause.get("tag_review") or {}
    return any(v == "rejected" for v in tr.values())


def check(clauses: list[dict]) -> dict:
    """Run all rule-based checks. Returns ``{"census": …, "findings": …}``."""
    findings: dict[str, list] = defaultdict(list)

    for c in clauses:
        cid = c.get("id")
        body = c.get("body") or ""
        ct = c.get("contract_type")
        src = (c.get("tags") or {}).get("source")
        snippet = re.sub(r"\s+", " ", body)[:80]

        if not body.strip():
            findings["empty"].append({"id": cid, "type": ct, "source": src})
            continue

        hits = region_lint(body)
        if hits:
            findings["region_leak"].append({
                "id": cid, "type": ct, "source": src, "section": c.get("section"),
                "matches": hits[:6], "snippet": snippet,
            })

        if HEADER_RE.search(body):
            m = HEADER_RE.search(body)
            findings["artifact_header"].append({
                "id": cid, "type": ct, "source": src,
                "match": m.group(0), "snippet": snippet,
            })
        if UNDERSCORE_RE.search(body):
            findings["artifact_underscore"].append({
                "id": cid, "type": ct, "source": src, "snippet": snippet,
            })
        if PIPE_RE.search(body):
            findings["artifact_table"].append({
                "id": cid, "type": ct, "source": src, "snippet": snippet,
            })
        if len(body.strip()) < TINY_BODY:
            findings["tiny_body"].append({
                "id": cid, "type": ct, "source": src, "len": len(body.strip()),
                "body": body.strip(),
            })
        elif not BAD_END_RE.search(body.strip()[-2:]):
            findings["mid_sentence_end"].append({
                "id": cid, "type": ct, "source": src,
                "tail": body.strip()[-30:],
            })

        if "{{" not in body:
            for m in MONEY_RE.finditer(body):
                ctx = body[max(0, m.start() - 12): m.end() + 12]
                if LEGAL_NUM_RE.search(ctx):
                    continue  # statutory ratio/limit context
                findings["literal_money"].append({
                    "id": cid, "type": ct, "source": src, "section": c.get("section"),
                    "match": m.group(0), "context": re.sub(r"\s+", " ", ctx),
                })
                break
            m = DATE_RE.search(body)
            if m:
                findings["literal_date"].append({
                    "id": cid, "type": ct, "source": src,
                    "match": m.group(0), "snippet": snippet,
                })
        m = COMPANY_RE.search(body)
        if m and "{{" not in body:
            findings["literal_company"].append({
                "id": cid, "type": ct, "source": src, "section": c.get("section"),
                "match": m.group(0), "snippet": snippet,
            })

    by_hash = defaultdict(list)
    by_body = defaultdict(list)
    for c in clauses:
        body = (c.get("body") or "").strip()
        if not body:
            continue
        key_t = c.get("contract_type")
        if c.get("body_hash"):
            by_hash[(key_t, c["body_hash"])].append(c["id"])
        else:
            by_body[(key_t, body)].append(c["id"])
    for (ct, h), ids in by_hash.items():
        if len(ids) > 1:
            findings["dup_body_hash"].append({"type": ct, "ids": ids})
    for (ct, b), ids in by_body.items():
        if len(ids) > 1:
            findings["dup_exact_body"].append({
                "type": ct, "ids": ids, "snippet": re.sub(r"\s+", " ", b)[:60],
            })

    census = {
        "total": len(clauses),
        "by_source": Counter((c.get("tags") or {}).get("source") for c in clauses),
        "by_type": Counter(c.get("contract_type") for c in clauses),
        "tag_review_status": Counter(),
        "assembly_ready_custom": sum(
            1 for c in clauses
            if (c.get("tags") or {}).get("source") == "custom" and assembly_ready(c)
        ),
        "parse_errors": sum(1 for c in clauses if "_parse_error" in c),
        "with_scenario_tag": sum(
            1 for c in clauses if (c.get("tags") or {}).get("scenario")
        ),
        "with_stance_tag": sum(
            1 for c in clauses if (c.get("tags") or {}).get("stance")
        ),
    }
    for c in clauses:
        for dim, v in (c.get("tag_review") or {}).items():
            census["tag_review_status"][f"{dim}:{v}"] += 1

    return {"census": census, "findings": findings}
