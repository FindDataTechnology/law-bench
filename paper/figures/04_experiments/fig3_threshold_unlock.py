"""图 3：阈值下调（0.99→0.67）后解锁的 8 个类型的通过评审项比例。

数据源：paper/figures/data/fig3_threshold_unlock.csv
与论文表 2 同源。真实数据，非 mock。
"""

import csv
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BEFORE_COLOR, AFTER_COLOR = "#95C623", "#2E86AB"
ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "figures" / "data" / "fig3_threshold_unlock.csv"
OUT = pathlib.Path(__file__).resolve().parent

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def ratio(score: str) -> float:
    passed, total = score.split("/")
    return int(passed) / int(total)


def main():
    with DATA.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    labels = [f"{r['zh_name']}（{r['contract_type']}）" for r in rows]
    before = [ratio(r["score_before"]) for r in rows]
    after = [ratio(r["score_after"]) for r in rows]

    y = np.arange(len(rows))
    height = 0.36

    fig, ax = plt.subplots(figsize=(7.0, 4.1))
    ax.barh(y - height / 2, before, height, label="阈值 0.99（仅全票失败触发改进）",
            color=BEFORE_COLOR)
    ax.barh(y + height / 2, after, height, label="阈值 0.67（多数失败触发改进）",
            color=AFTER_COLOR)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.24)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_xticklabels(["0", "20%", "40%", "60%", "80%", "100%"], fontsize=7.5)
    ax.set_xlabel("通过评审项比例", fontsize=8)
    ax.axvline(1.0, color="#888888", linestyle="--", linewidth=0.8)

    for i, r in enumerate(rows):
        ax.text(ratio(r["score_before"]) + 0.015, i - height / 2, r["score_before"],
                va="center", fontsize=6.5, color="#4A4A4A")
        ax.text(ratio(r["score_after"]) + 0.015, i + height / 2, r["score_after"],
                va="center", fontsize=6.5, color="#4A4A4A")

    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.16),
              ncol=2, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title("阈值下调后解锁的 8 个类型及其通过评审项比例", fontsize=9.5, pad=8)
    fig.text(
        0.5, 0.005,
        "虚线为全部评审项通过（100%）；数据来源：提交 644576e 阈值变更前后逐类记录，"
        "每评审项 3 裁判、all-pass 二值聚合，单次运行。",
        ha="center", fontsize=6.5,
    )
    fig.tight_layout(rect=[0, 0.145, 1, 1])

    fig.savefig(OUT / "fig3_threshold_unlock.png", dpi=450)
    fig.savefig(OUT / "fig3_threshold_unlock.svg")
    print("wrote", OUT / "fig3_threshold_unlock.png")
    print("wrote", OUT / "fig3_threshold_unlock.svg")


if __name__ == "__main__":
    main()
