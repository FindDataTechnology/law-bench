"""对合同草稿跑一轮真实评测：判官逐条判分，落 eval_runs 并归因到域。

    python3 scripts/eval_contract_samples.py --dry-run
    python3 scripts/eval_contract_samples.py --type sale --rubric contract_sale_v2

为什么要有这一步：合同尺子（`scripts/seed_contract_rubrics.py`）此前只"落库"，
从没真的量过任何一份合同——域矩阵里 legal 的 `last_run` 一直是空的。登记不等于
测量；只有判官真判过一轮，这把尺子才从声明变成证据。

**样本来源如实说明**：这里评的不是真实签署合同，而是仓内模板
（`src/contracts/data/contracts.json`）填槽后的草稿。所以本脚本一次评两份：

- ``complete``：全部槽位填实；
- ``deficient``：同一份文本删掉风险转移、检验期间、违约责任、争议解决与适用法律
  ——用来证明尺子**会判不过**。一份永远满分的尺子等于没有尺子：`packs/gov/doc_checks.py`
  的测试同样要求每条判据都有坏样本。

两份的差值才是这把尺子的分辨力证据，单看 complete 的分数只说明判官通了。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "contracts" / "data" / "contracts.json"

#: 买卖合同 11 个槽位的填值（角色是买卖双方的真实公司名，金额与期限自洽）。
SALE_SLOTS: dict[str, str] = {
    "甲方名称": "宁波精工机械制造有限公司",
    "乙方名称": "杭州云和智能装备有限公司",
    "标的物名称": "数控立式加工中心 VMC-850（含随机附件与操作手册）",
    "标的物数量": "2 台",
    "标的物价款": "人民币壹佰贰拾万元整（¥1,200,000.00）",
    "付款方式": "分期付款：合同生效后 5 个工作日内支付 30% 预付款，验收合格后 10 个工作日内支付 70% 尾款",
    "付款期限": "验收合格后 10 个工作日内付清尾款",
    "交付方式": "甲方送货至乙方指定厂区并完成安装调试",
    "交付时间": "2026-12-31 前",
    "质量标准": "符合国家标准 GB/T 9061-2006 及本合同附件《技术规格书》约定",
    "验收标准": "按《技术规格书》逐项验收，空运转 8 小时无故障，验收期 15 个工作日",
}

#: 删掉这些行（按子串匹配）得到"缺条款"样本：风险转移、检验期间、违约责任、争议解决。
DEFICIENT_MARKERS: tuple[str, ...] = (
    "标的物毁损、灭失的风险",
    "应在检验期间内通知甲方",
    "## 违约责任",
    "## 争议解决",
    "依照《中华人民共和国民法典》及相关司法解释的规定执行",
)


def load_template(type_key: str) -> dict:
    data = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    for item in data:
        if item.get("key") == type_key:
            return item
    raise KeyError(f"模板里没有 key={type_key!r}；可用：{[x.get('key') for x in data]}")


def fill(body: str, slots: dict[str, str]) -> str:
    """填槽：模板里没给值的槽位原样留着——那份草稿就该被判为不完整。"""
    out = body
    for name, value in slots.items():
        out = out.replace("{{" + name + "}}", value)
    return out


def make_deficient(text: str) -> str:
    """逐行删除缺陷标记所在行（章节标题与其内容分开处理，标题行删掉后内容仍在）。"""
    kept: list[str] = []
    skipping_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            skipping_section = any(stripped == m for m in DEFICIENT_MARKERS if m.startswith("## "))
            if skipping_section:
                continue
        if skipping_section:
            continue
        if any(m in line for m in DEFICIENT_MARKERS if not m.startswith("## ")):
            continue
        kept.append(line)
    return "\n".join(kept)


def _evaluate(conn, *, text: str, rubric: str, label: str, task_desc: str,
              dry_run: bool) -> dict:
    from src.bench import domain_rubrics
    from src.eval.scoring import evaluate_contract
    from src.eval.store import store_result

    if dry_run:
        return {"label": label, "chars": len(text), "rubric": rubric, "dry_run": True}

    result = evaluate_contract(text, rubric, task_desc=task_desc)
    run_id = store_result(
        result,
        contract_path=None,
        task_desc=task_desc,
        channel="text",
        unit_kind="contract",
    )
    rid = conn.execute("SELECT id FROM rubrics WHERE name = %s", (rubric,)).fetchone()
    domain_rubrics.attribute_run(conn, run_id=run_id, rubric_id=rid["id"] if rid else None)
    return {
        "label": label, "run_id": run_id, "rubric": rubric,
        "score": result["score"], "n_passed": result["n_passed"],
        "n_criteria": result["n_criteria"], "all_pass": result["all_pass"],
        "n_invalid": result.get("n_invalid", 0),
        "failed": [c["id"] for c in result["criteria_results"] if c["verdict"] != "pass"],
        "judge_model": result.get("judge_model"),
    }


def run(conn, *, type_key: str, rubric: str, domain: str = "legal",
        dry_run: bool = True) -> list[dict]:
    tpl = load_template(type_key)
    complete = fill(tpl["body"], SALE_SLOTS if type_key == "sale" else {})
    deficient = make_deficient(complete)
    task_desc = f"{tpl.get('zh') or type_key}（{rubric}）"
    out = []
    for label, text in (("complete", complete), ("deficient", deficient)):
        out.append(_evaluate(conn, text=text, rubric=rubric, label=label,
                             task_desc=task_desc, dry_run=dry_run))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", default="sale", help="模板 key（默认 sale）")
    ap.add_argument("--rubric", default="contract_sale_v2", help="尺子名（默认 contract_sale_v2）")
    ap.add_argument("--domain", default="legal")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    from src.eval.db import connect

    conn = connect()
    try:
        results = run(conn, type_key=args.type, rubric=args.rubric,
                      domain=args.domain, dry_run=args.dry_run)
        for r in results:
            if r.get("dry_run"):
                print(f"[dry-run] {r['label']}: {r['chars']} 字 → {r['rubric']}")
                continue
            print(f"{r['label']:>10}: score={r['score']} 通过 {r['n_passed']}/{r['n_criteria']}"
                  f" invalid={r['n_invalid']} run_id={r['run_id']}")
            if r["failed"]:
                print(f"            未通过：{', '.join(r['failed'])}")
        if not args.dry_run:
            scores = {r["label"]: r["score"] for r in results}
            print(f"\n分辨力：complete={scores.get('complete')} vs deficient={scores.get('deficient')}")
            if scores.get("deficient") == 1.0:
                print("  ⚠️ 缺陷样本也满分——尺子没判出缺条款，这一轮的分数不能当证据。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
