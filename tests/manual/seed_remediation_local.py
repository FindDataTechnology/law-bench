#!/usr/bin/env python3
"""Seed synthetic defect clauses into the LOCAL test DB and verify the
content_remediation driver end-to-end (apply + rollback + idempotency).

Local only — targets database_url (localhost test postgres), never prod.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# fresh remediation state each run (stale before-snapshots would be picked up
# by rollback and restore garbage onto unrelated rows)
shutil.rmtree("output/remediation", ignore_errors=True)

from src.eval.db import connect

conn = connect()
conn.execute("DELETE FROM clauses")
conn.execute("ALTER SEQUENCE clauses_id_seq RESTART WITH 9001")
conn.commit()

DUP = "乙方应按照约定交付货物，逾期每日按合同价款的千分之一支付违约金。"
seed = [
    # b0-data: metadata keys in tag_review
    {"contract_type": "sale", "category": "custom", "section": "附则",
     "body": "本合同自双方签字盖章之日起生效。",
     "tags": {"source": "custom", "stance": "pro_a"},
     "tag_review": {"_note": "auto-approved-pilot", "source": "approved", "stance": "approved"}},
    {"contract_type": "sale", "category": "custom", "section": "价款",
     "body": "价款为{{amount}}元。",
     "tags": {"source": "custom", "stance": "pro_b"},
     "tag_review": {"_imported_at": "2026-08-17T10:00:28", "_source_hash": "dab6eb83"}},
    # b1: body_hash dup group (tagged) + one distinct
    {"contract_type": "sale", "category": "tagged", "section": "违约责任",
     "body": DUP, "tags": {"source": "tagged", "scenario": "车辆买卖"},
     "tag_review": {"source": "pending"}},
    {"contract_type": "sale", "category": "tagged", "section": "违约责任",
     "body": DUP, "tags": {"source": "tagged", "scenario": "车辆买卖"},
     "tag_review": {"source": "pending"}},
    {"contract_type": "sale", "category": "tagged", "section": "验收",
     "body": "买受人应当在检验期限内验收。", "tags": {"source": "tagged", "scenario": "车辆买卖"}},
    # b3: artifacts
    {"contract_type": "work", "category": "tagged", "section": "签署",
     "body": "设计费为{{amount}}元。\n甲方（签字）：__________ 乙方（盖章）：__________\n签订日期：____年__月__日",
     "tags": {"source": "tagged", "scenario": "住宅租赁"}},
    {"contract_type": "service", "category": "tagged", "section": "交付",
     "body": "乙方应当于____年__月__日前完成交付。",
     "tags": {"source": "tagged", "scenario": "家政服务"}},
    {"contract_type": "sale", "category": "tagged", "section": "标的",
     "body": "所购建材基本情况：\n| 建材名称 | 产地 | 品牌 |\n|----|----|----|\n| 示例 | 示例 | 示例 |\n质量应符合国家标准。",
     "tags": {"source": "tagged", "scenario": "建材买卖"}},
    {"contract_type": "service", "category": "tagged", "section": "附则",
     "body": "本合同一式___份，双方各执一份。（以下无正文，为签署页）",
     "tags": {"source": "tagged", "scenario": "家政服务"}},
    # b4: spot fix (hardcoded money) + thin stub keep
    {"contract_type": "employment", "category": "custom", "section": "保密与竞业限制",
     "body": "乙方违反的，应支付违约金100000元。",
     "tags": {"source": "custom", "stance": "pro_a"}},
    {"contract_type": "sale", "category": "tagged", "section": "违约责任",
     "body": "违约责任：{{penalty}}。", "tags": {"source": "tagged", "scenario": "车辆买卖"}},
]
from src.clauses.store import upsert_clauses
n = upsert_clauses(seed)
conn.close()
print("seeded:", n)

# ids assigned sequentially from the restarted sequence; read them back by
# matching (body, tags, tag_review) against unclaimed rows — the dup pair
# shares body AND tags, only tag_review differs
conn = connect()
rows = conn.execute(
    "SELECT id, body, tags, tag_review FROM clauses ORDER BY id"
).fetchall()
conn.close()
rows = [dict(r) for r in rows]
ids = []
used = set()
for s in seed:
    for r in rows:
        if r["id"] in used:
            continue
        if (r["body"] == s["body"]
                and json.dumps(r["tags"], sort_keys=True) == json.dumps(s.get("tags"), sort_keys=True)
                and json.dumps(r["tag_review"] or {}, sort_keys=True) == json.dumps(s.get("tag_review") or {}, sort_keys=True)):
            ids.append(r["id"])
            used.add(r["id"])
            break
    else:
        raise SystemExit(f"seed row not found in DB: {s['body'][:30]}")
print("ids:", ids)
IDS_MONEY, IDS_STUB = ids[9], ids[10]

DRIVER = ["./.venv/Scripts/python.exe", "scripts/content_remediation.py"]
b4_drafts = Path("output/remediation/test_b4_drafts.json")
b4_drafts.parent.mkdir(parents=True, exist_ok=True)
b4_drafts.write_text(json.dumps({
    str(IDS_MONEY): {"action": "rewrite", "body": "乙方违反的，应支付违约金{{penalty}}。"},
    str(IDS_STUB): {"action": "keep"},
}, ensure_ascii=False), encoding="utf-8")


def run(*extra):
    r = subprocess.run(DRIVER + list(extra), capture_output=True, text=True)
    print(r.stdout[-1200:])
    if r.returncode != 0:
        print("STDERR:", r.stderr[-800:])
        raise SystemExit(f"command failed: {extra}")
    return r.stdout


def db_state():
    c = connect()
    rows = c.execute("SELECT id, body, tag_review FROM clauses ORDER BY id").fetchall()
    c.close()
    return {r["id"]: (r["body"], dict(r["tag_review"] or {})) for r in rows}


failures = []

# --- --list
out = run("--list")
for needle in ("b0-data: 2 clauses", "b1:      1 duplicate", "b3:      4 clauses"):
    if needle not in out:
        failures.append(f"--list missing {needle!r}")

# --- b0-data dry-run then apply
run("--batch", "b0-data", "--dry-run")
run("--batch", "b0-data")
st = db_state()
if "_note" in st[ids[0]][1] or "_imported_at" in st[ids[1]][1]:
    failures.append("b0-data did not strip metadata keys")
if st[ids[0]][1].get("stance") != "approved":
    failures.append("b0-data dropped genuine dim")

# --- b1 apply
run("--batch", "b1")
st = db_state()
if st[ids[3]][1].get("source") != "rejected":
    failures.append("b1 did not reject duplicate victim")
if st[ids[2]][1].get("source") == "rejected":
    failures.append("b1 rejected the canonical clause")

# --- b3 apply
run("--batch", "b3")
st = db_state()
b6 = st[ids[5]][0]
if "签字" in b6 or "盖章" in b6 or "签订日期" in b6:
    failures.append(f"b3 left shell line: {b6!r}")
b65 = st[ids[6]][0]
if "{{sign_date}}" not in b65:
    failures.append(f"b3 did not slotify inline date blank: {b65!r}")
b7 = st[ids[7]][0]
if "|" in b7:
    failures.append(f"b3 left table fragment: {b7!r}")
b8 = st[ids[8]][0]
if "{{contract_copies}}" not in b8:
    failures.append(f"b3 did not slotify copies: {b8!r}")

# --- b4 drafts
run("--batch", "b4", "--drafts", str(b4_drafts))
st = db_state()
if "100000" in st[IDS_MONEY][0]:
    failures.append("b4 did not apply penalty rewrite")
if st[IDS_STUB][0] != "违约责任：{{penalty}}。":
    failures.append("b4 touched a keep-action clause")

# --- rollback every batch (twice for idempotency)
for batch in ("b0-data", "b1", "b3", "b4"):
    run("--rollback", batch)
run("--rollback", "b1")
st_after = db_state()
st_ref = db_state()
if st_after != st_ref:
    failures.append("rollback not idempotent")

st = db_state()
if st[ids[0]][1].get("_note") != "auto-approved-pilot":
    failures.append("rollback did not restore _note")
if st[ids[3]][1].get("source") != "pending":
    failures.append("rollback did not revive duplicate victim")
if "签字" not in st[ids[5]][0]:
    failures.append("rollback did not restore artifact body")
if "100000" not in st[IDS_MONEY][0]:
    failures.append("rollback did not restore money body")

# --- leave a clean slate
c = connect()
c.execute("DELETE FROM clauses")
c.commit()
c.close()

if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)
    raise SystemExit(1)
print("ALL LOCAL DRIVER CHECKS PASSED")
