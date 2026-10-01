"""Strengthen sale contract base clauses: add missing legal sections.

Adds 3 sections to the sale base clause set so the assembled contract satisfies
the `contract_sale_v3` rubric criteria that currently fail:
- ownership_transfer  -> 标的物所有权转移与风险负担
- inspection_period   -> 检验期间与质量异议
- ownership_retention -> 所有权保留

Runs against the shared law-bench PostgreSQL via `src.clauses.store.upsert_clause`.
Idempotent: upsert keyed on (source_path, section, body_hash); each run writes
the same rows.

Usage:
    PYTHONPATH=. python contract-review-agent/db/strengthen_sale_clauses.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# A stable per-section source_path so upserts are idempotent and identifiable.
_SRC_PATH = "law-bench/manual/strengthen-sale-base"

NEW_BASE_CLAUSES = [
    {
        "contract_type": "sale",
        "section": "所有权转移与风险负担",
        "category": "base",
        "source_path": f"{_SRC_PATH}/ownership-transfer",
        "source_doc_title": "买卖合同母版-所有权转移与风险负担",
        "manual": True,
        "body": (
            "1. 所有权转移时点：标的物所有权自交付时起由甲方转移至乙方；"
            "依照法律、行政法规规定应当办理登记手续的标的物（如机动车、船舶、航空器、不动产等），"
            "自登记完成之日起所有权转移至乙方。\n"
            "2. 风险负担：标的物毁损、灭失的风险，交付前由甲方承担，交付后由乙方承担；"
            "因乙方原因致使标的物未按约定期限交付的，自约定交付期限届满之日起风险由乙方承担；"
            "因甲方原因致使标的物未按约定期限交付的，风险由甲方承担。\n"
            "3. 单证交付：甲方应当同时交付提取标的物的单证和与标的物有关的资料，"
            "乙方受领标的物后应当及时办理相关过户、登记或备案手续，甲方应予协助。"
        ),
    },
    {
        "contract_type": "sale",
        "section": "检验期间与质量异议",
        "category": "base",
        "source_path": f"{_SRC_PATH}/inspection-period",
        "source_doc_title": "买卖合同母版-检验期间与质量异议",
        "manual": True,
        "body": (
            "1. 检验期间：乙方应当在收到标的物之日起{{inspection_days}}日内，"
            "对标的物的数量、外观、型号及质量进行检验。\n"
            "2. 异议通知：乙方发现标的物数量或质量不符合约定的，"
            "应当在上述检验期间内以书面形式（包括电子邮件、书面函件等）向甲方提出异议，"
            "并载明具体不符事项；乙方怠于通知的，视为标的物数量、质量符合约定。\n"
            "3. 隐蔽瑕疵：标的物存在不易发现的隐蔽瑕疵的，"
            "乙方自发现或者应当发现之日起{{inspection_days}}日内提出异议；"
            "甲方知道或者应当知道标的物不符合约定的，不受前述检验期间的限制。"
        ),
    },
    {
        "contract_type": "sale",
        "section": "所有权保留",
        "category": "base",
        "source_path": f"{_SRC_PATH}/ownership-retention",
        "source_doc_title": "买卖合同母版-所有权保留",
        "manual": True,
        "body": (
            "1. 所有权保留约定：在乙方付清全部价款之前，标的物所有权仍归甲方所有，"
            "甲方保留标的物所有权。\n"
            "2. 登记对抗：双方同意依照《中华人民共和国民法典》第六百四十一条的规定"
            "就所有权保留办理登记，以对抗善意第三人。\n"
            "3. 权利行使：乙方逾期未付清价款的，甲方有权依法主张取回标的物，"
            "但不得损害乙方已经支付价款的相应权利及法定权益；"
            "标的物交付后，乙方在付清价款前不得擅自处分标的物。"
        ),
    },
]


def main() -> int:
    from src.clauses.store import upsert_clause

    written = 0
    for clause in NEW_BASE_CLAUSES:
        cid = upsert_clause(clause)
        print(f"[ok] sale/{clause['section']} -> id={cid}")
        written += 1
    print(f"\nDone: {written} clauses upserted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
