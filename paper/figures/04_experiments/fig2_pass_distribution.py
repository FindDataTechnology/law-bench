"""图 2：43 类中文合同全通过结果分布（具名/非具名分组）。

数据源：paper/figures/data/fig2_pass_distribution.csv
该数据文件由 src/contracts/classification.py 与提交 644576e 记录的失败类型集合生成，
与论文表 1 同源。真实数据，非 mock。
"""

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

NATURE = ["#2E86AB", "#C73E1D"]
PASS_COLOR, FAIL_COLOR = "#2E86AB", "#C73E1D"
ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "figures" / "data" / "fig2_pass_distribution.csv"
OUT = pathlib.Path(__file__).resolve().parent

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load():
    with DATA.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    rows = load()
    named = [r for r in rows if r["group"] == "named"]
    unnamed = [r for r in rows if r["group"] == "unnamed"]

    fig, axes = plt.subplots(
        1, 2, figsize=(7.0, 5.2), gridspec_kw={"width_ratios": [19, 24]}
    )

    for ax, group, title in (
        (axes[0], named, "具名合同（19 类）"),
        (axes[1], unnamed, "非具名合同（24 类）"),
    ):
        labels = [r["zh_name"] for r in group]
        colors = [PASS_COLOR if r["result"] == "pass" else FAIL_COLOR for r in group]
        y = range(len(group))
        ax.barh(list(y), [1] * len(group), color=colors, height=0.62)
        ax.set_yticks(list(y))
        ax.set_yticklabels(labels, fontsize=6.5)
        ax.set_xlim(0, 1.18)
        ax.set_xticks([])
        ax.set_title(title, fontsize=9, pad=6)
        ax.invert_yaxis()
        for spine in ("top", "right", "bottom"):
            ax.spines[spine].set_visible(False)
        # 在失败条目右侧标注分数
        for i, r in enumerate(group):
            if r["result"] == "fail":
                ax.text(1.02, i, r["score"], va="center", fontsize=6.5,
                        color=FAIL_COLOR)

    n_pass = sum(1 for r in rows if r["result"] == "pass")
    fig.suptitle(
        f"43 类中文合同的全通过结果（全通过 {n_pass}/43，"
        f"具名 {sum(1 for r in named if r['result']=='pass')}/{len(named)}，"
        f"非具名 {sum(1 for r in unnamed if r['result']=='pass')}/{len(unnamed)}）",
        fontsize=9.5,
        y=0.985,
    )
    fig.text(
        0.5, 0.012,
        "蓝色为全部评审项通过，红色为未通过（右侧标注通过评审项数/总数）；"
        "数据来源：提交 644576e 运行记录，每评审项 3 裁判、all-pass 二值聚合，单次运行。",
        ha="center", fontsize=6.5,
    )
    fig.tight_layout(rect=[0, 0.035, 1, 0.965])

    fig.savefig(OUT / "fig2_pass_distribution.png", dpi=450)
    fig.savefig(OUT / "fig2_pass_distribution.svg")
    print("wrote", OUT / "fig2_pass_distribution.png")
    print("wrote", OUT / "fig2_pass_distribution.svg")


if __name__ == "__main__":
    main()
