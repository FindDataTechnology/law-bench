#!/usr/bin/env python3
"""Build b2 region-generalization drafts from the live bodies.

Strategy: minimal-edit surgical replacements on the exact live bodies (never
hand-retyped), one (old, new) pair per defect. Verifies every pair matched and
region_lint(new) == 0 before emitting output/remediation/b2_drafts.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.clauses.audit import region_lint  # noqa: E402

targets = json.loads(Path("output/remediation/b2_targets.json").read_text(encoding="utf-8"))
by_id = {t["id"]: t for t in targets}

REPLACEMENTS: dict[int, list[tuple[str, str]]] = {
    4507: [
        ("向上海{{exchange_name}}产权交易所", "向{{exchange_name}}产权交易所"),
        ("提交上海仲裁委员会仲裁", "提交{{arbitration_commission}}仲裁"),
    ],
    4709: [
        ("《商品房屋租赁管理办法》《济南市人民政府办公厅关于培育和发展住房租赁市场试点工作的实施意见》等法律法规和指导意见",
         "《商品房屋租赁管理办法》等法律法规和相关政策文件"),
    ],
    1326: [
        ("《商品房屋租赁管理办法》《北京市房屋租赁管理若干规定》及其他有关法律法规",
         "《商品房屋租赁管理办法》及其他有关法律法规"),
    ],
    2242: [
        ("根据有关法律法规及《青海省公共租赁住房管理办法》、《青海省保障性住房准入分配退出和运营管理实施细则》等规定",
         "根据有关法律法规及《公共租赁住房管理办法》等规定"),
    ],
    7956: [
        ("、《租赁房屋治安管理规定》、《江苏省特种行业管理条例》等法律",
         "、《租赁房屋治安管理规定》等法律"),
    ],
    2755: [
        ("1、由杭州仲裁委员会仲裁", "1、由{{arbitration_commission}}仲裁"),
    ],
    1784: [
        ("《房地产经纪管理办法》《南京市房屋租赁管理办法》等法律",
         "《房地产经纪管理办法》等法律"),
    ],
    5379: [
        ("续签的合同租金按《深圳市保障性租赁住房管理办法》有关规定执行",
         "续签的合同租金按照国家和当地有关住房保障政策规定执行"),
    ],
    4662: [
        ("也可提请上海仲裁委员会仲裁", "也可提请{{arbitration_commission}}仲裁"),
    ],
    2060: [
        ("《商品房屋租赁管理办法》《河北省租赁房屋治安管理条例》等",
         "《商品房屋租赁管理办法》等"),
    ],
    2252: [
        ("《中华人民共和国民法典》《深圳市保障性住房条例》《深圳市公共租赁住房管理办法》等有关",
         "《中华人民共和国民法典》《公共租赁住房管理办法》等有关"),
    ],
    2327: [
        ("《中华人民共和国民法典》《深圳市保障性住房条例》《深圳市公共租赁住房管理办法》（深圳市人民政府令第 352 号）等有关",
         "《中华人民共和国民法典》《公共租赁住房管理办法》等有关"),
    ],
    3406: [
        ("1.提交中国广州仲裁委员会裁决", "1.提交{{arbitration_commission}}裁决"),
    ],
    2709: [
        ("《中华人民共和国城市房地产管理法》《南京市房屋租赁管理办法》等法律",
         "《中华人民共和国城市房地产管理法》等法律"),
    ],
    2930: [
        ("《中华人民共和国城市房地产管理法》《北京市住房租赁条例》《商品房屋租赁管理办法》",
         "《中华人民共和国城市房地产管理法》《商品房屋租赁管理办法》"),
    ],
    3711: [
        ("1、提交中国广州仲裁委员会仲裁", "1、提交{{arbitration_commission}}仲裁"),
    ],
    3810: [
        ("《中华人民共和国合同法》《中华人民共和国食品安全法》《上海市食品安全条例》《上海市房屋租赁条例》等",
         "《中华人民共和国合同法》《中华人民共和国食品安全法》等"),
    ],
}

drafts: dict[str, str] = {}
problems: list[str] = []

for cid, pairs in REPLACEMENTS.items():
    t = by_id.get(cid)
    if t is None:
        problems.append(f"#{cid}: not in targets")
        continue
    body = t["body"]
    for old, new in pairs:
        if old not in body:
            problems.append(f"#{cid}: pattern not found: {old[:40]}...")
            continue
        body = body.replace(old, new)
    hits = region_lint(body)
    if hits:
        problems.append(f"#{cid}: region_lint residual {hits[:4]}")
        continue
    if body == t["body"]:
        problems.append(f"#{cid}: no change")
        continue
    drafts[str(cid)] = body

if problems:
    print("PROBLEMS:")
    for p in problems:
        print(" -", p)
    raise SystemExit(1)

out = Path("output/remediation/b2_drafts.json")
out.write_text(json.dumps(drafts, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"b2 drafts OK: {len(drafts)} clauses -> {out}")
