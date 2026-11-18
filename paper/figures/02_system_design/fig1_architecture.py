"""图 1：law-bench 总体架构与数据流（示意类图件，非数据图）。

依据 docs/pipeline-architecture.md 的三条流水线与论文 2.1 节的数据流描述绘制。
图中不出现主机名、域名、集群名（按 AGENTS.md 对退役基础设施的处理要求）。
"""

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BLUE, MAGENTA, ORANGE = "#2E86AB", "#A23B72", "#F18F01"
FILL, TEXT = "#F4F7FA", "#333333"
OUT = pathlib.Path(__file__).resolve().parent

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

LAYERS = [
    ("条款语料层", "条款记录：正文 · 分节 · 来源类别 · 法律主题标签 · 填充说明 · 法条引用", BLUE),
    ("组装层", "标签检索 → 分节覆盖（立场 ＞ 场景 ＞ 母版）→ 渲染前一致性校验", BLUE),
    ("槽位填充层", "起草模型按填充说明返回结构化取值；回填正文，按输入摘要缓存（温度 0）", BLUE),
    ("评估层", "每条评审项 3 裁判独立判定 → 全通过式二值聚合（全通过 1.0，否则 0.0）", MAGENTA),
    ("自愈层", "失败项按法律主题标签归因到分节；条款级改进，合并而非替换", ORANGE),
    ("运行记录层", "运行级 + 迭代级记录：装配参数 · 逐条判定 · 动作痕迹", BLUE),
]

BOX_H = 0.108
GAP = 0.028
TOP = 0.945
X0, W = 0.06, 0.80
CX = X0 + W / 2


def main():
    fig, ax = plt.subplots(figsize=(7.0, 5.4))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    tops = []
    for i, (name, desc, color) in enumerate(LAYERS):
        top = TOP - i * (BOX_H + GAP)
        y = top - BOX_H
        tops.append((y, top))
        ax.add_patch(
            FancyBboxPatch(
                (X0, y), W, BOX_H,
                boxstyle="round,pad=0.004,rounding_size=0.012",
                linewidth=1.3, edgecolor=color, facecolor=FILL, zorder=2,
            )
        )
        ax.text(X0 + 0.018, top - BOX_H * 0.32, name, fontsize=9, color=TEXT,
                va="center", ha="left", fontweight="bold", zorder=3)
        ax.text(X0 + 0.018, top - BOX_H * 0.70, desc, fontsize=6.8, color=TEXT,
                va="center", ha="left", zorder=3)

    def arrow(y_from, y_to, x=CX, color="#555555", lw=1.3, ls="-", style="-|>"):
        ax.add_patch(
            FancyArrowPatch((x, y_from), (x, y_to), arrowstyle=style,
                            mutation_scale=11, linewidth=lw, linestyle=ls,
                            color=color, zorder=4,
                            shrinkA=0, shrinkB=0)
        )

    # 主链：1→2→3→4，以及 4→6（全通过或达轮次上限）
    for i in (0, 1, 2):
        arrow(tops[i][0], tops[i + 1][1])
    arrow(tops[3][0], tops[5][1], x=X0 + W * 0.78)

    # 反馈边一：4→5（未全部通过且未达轮次上限）
    arrow(tops[3][0], tops[4][1], x=X0 + W * 0.22, color=ORANGE, lw=1.8)
    ax.text(X0 + W * 0.22 - 0.012, (tops[3][0] + tops[4][1]) / 2,
            "未全通过", fontsize=6.5, color=ORANGE, ha="right", va="center", zorder=5)

    # 反馈边二：5→2（自愈回到组装，构成闭环）——走左侧绕行
    x_left = X0 - 0.038
    y5 = (tops[4][0] + tops[4][1]) / 2
    y2 = (tops[1][0] + tops[1][1]) / 2
    ax.add_patch(FancyArrowPatch(
        (X0, y5), (X0, y2), connectionstyle="bar,fraction=-0.16",
        arrowstyle="-|>", mutation_scale=11, linewidth=1.8, color=ORANGE, zorder=1,
    ))
    ax.text(x_left - 0.028, (y2 + y5) / 2, "自愈闭环", fontsize=6.8, color=ORANGE,
            rotation=90, ha="center", va="center", zorder=5)

    # 反馈边三：6→2（评估信号回流，虚线）
    x_right = X0 + W + 0.030
    y6 = (tops[5][0] + tops[5][1]) / 2
    ax.add_patch(FancyArrowPatch(
        (X0 + W, y6), (X0 + W, y2), connectionstyle="bar,fraction=0.14",
        arrowstyle="-|>", mutation_scale=11, linewidth=1.2, color=BLUE,
        linestyle=(0, (4, 3)), zorder=1,
    ))
    ax.text(x_right + 0.030, (y2 + y6) / 2, "评估信号回流", fontsize=6.8, color=BLUE,
            rotation=90, ha="center", va="center", zorder=5)

    fig.text(0.5, 0.012,
             "评估信号经自愈层回流至组装层，构成起草—评估—改进闭环；"
             "运行记录层留存逐条判定与动作痕迹，供回归比较与追溯。",
             ha="center", fontsize=6.5)
    fig.tight_layout(rect=[0.02, 0.035, 0.98, 1.0])

    fig.savefig(OUT / "fig1_architecture.png", dpi=450)
    fig.savefig(OUT / "fig1_architecture.svg")
    print("wrote", OUT / "fig1_architecture.png")
    print("wrote", OUT / "fig1_architecture.svg")


if __name__ == "__main__":
    main()
