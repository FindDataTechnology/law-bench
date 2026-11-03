"""把 paper/初稿.md 构建为投稿用 .docx（学术场景排版，含嵌入图件）。

排版依据 documents 技能的 scenes/academic.md：
  正文 宋体小四(12pt)、1.5 倍行距、首行缩进 2 字符、两端对齐、纯黑
  标题 黑体；图题/表题 宋体五号居中；页边距 上下 2.54cm / 左 3.00cm / 右 2.50cm
"""

import pathlib
import re
import sys

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = pathlib.Path(__file__).resolve().parent

LANG = sys.argv[1] if len(sys.argv) > 1 else "cn"
if LANG == "en":
    SRC = ROOT / "初稿_en.md"
    OUT = ROOT / "law-bench论文初稿_en.docx"
    TABLE_CAP = re.compile(r"^Table\s*\d")
else:
    SRC = ROOT / "初稿.md"
    OUT = ROOT / "law-bench论文初稿.docx"
    TABLE_CAP = re.compile(r"^表\s*\d")

BODY_CN, BODY_EN = "SimSun", "Times New Roman"
HEAD_CN = "SimHei"
BLACK = RGBColor(0, 0, 0)

# 图件：在首次出现图号引用的段落之后插入
FIGURES = {
    "图 1": (
        ROOT / "figures" / "02_system_design" / "fig1_architecture.png",
        "图 1  law-bench 总体架构与数据流",
    ),
    "图 2": (
        ROOT / "figures" / "04_experiments" / "fig2_pass_distribution.png",
        "图 2  43 类中文合同的全通过结果分布",
    ),
    "图 3": (
        ROOT / "figures" / "04_experiments" / "fig3_threshold_unlock.png",
        "图 3  阈值下调后解锁的 8 个类型及其通过评审项比例",
    ),
    "Figure 1": (
        ROOT / "figures" / "02_system_design" / "fig1_architecture.png",
        "Figure 1  Overall architecture and data flow of law-bench",
    ),
    "Figure 2": (
        ROOT / "figures" / "04_experiments" / "fig2_pass_distribution.png",
        "Figure 2  All-pass distribution over the 43 Chinese contract types",
    ),
    "Figure 3": (
        ROOT / "figures" / "04_experiments" / "fig3_threshold_unlock.png",
        "Figure 3  The 8 types unlocked by the threshold change and their per-criterion pass shares",
    ),
}
IMG_WIDTH = Cm(14.6)


def style_run(run, cn=BODY_CN, en=BODY_EN, size=12, bold=False):
    run.font.name = en
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = BLACK
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), cn)
    rfonts.set(qn("w:ascii"), en)
    rfonts.set(qn("w:hAnsi"), en)


def add_par(doc, text, *, cn=BODY_CN, size=12, bold=False, align=None,
            indent_chars=2, line=1.5, space_before=0, space_after=0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    if align is not None:
        p.alignment = align
    if indent_chars:
        pf.first_line_indent = Pt(size * indent_chars)
    pf.line_spacing = line
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    for seg, is_bold in parse_bold(text):
        style_run(p.add_run(seg), cn=cn, size=size, bold=(bold or is_bold))
    return p


def parse_bold(text):
    """把 **x** 解析为 (片段, 是否加粗) 序列。"""
    parts, pos = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*", text):
        if m.start() > pos:
            parts.append((text[pos:m.start()], False))
        parts.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        parts.append((text[pos:], False))
    return parts or [(text, False)]


def add_figure(doc, path, caption):
    if not path.exists():
        add_par(doc, f"[图件缺失：{path.name}]", align=WD_ALIGN_PARAGRAPH.CENTER)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=IMG_WIDTH)
    cap = add_par(doc, caption, size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER,
                  indent_chars=0, line=1.0, space_after=8)


def _set_row_props(row, *, header=False, cant_split=True):
    """跨页控制：表头行重复（tblHeader）、行内不断裂（cantSplit）。"""
    from docx.oxml import OxmlElement

    tr_pr = row._tr.get_or_add_trPr()
    if header:
        el = OxmlElement("w:tblHeader")
        el.set(qn("w:val"), "true")
        tr_pr.append(el)
    if cant_split:
        tr_pr.append(OxmlElement("w:cantSplit"))


def add_table(doc, rows):
    header, body = rows[0], rows[1:]
    t = doc.add_table(rows=len(rows), cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, cell_text in enumerate(header):
        cell = t.cell(0, j)
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing = 1.0
        style_run(p.add_run(cell_text), cn=HEAD_CN, size=10.5, bold=True)
    _set_row_props(t.rows[0], header=True)
    for i, row in enumerate(body, start=1):
        for j, cell_text in enumerate(row):
            if j >= len(header):
                continue
            cell = t.cell(i, j)
            cell.text = ""
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.line_spacing = 1.0
            style_run(p.add_run(cell_text), size=10.5)
        _set_row_props(t.rows[i])
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def build():
    lines = SRC.read_text(encoding="utf-8").splitlines()
    doc = Document()

    sec = doc.sections[0]
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(3.00)
    sec.right_margin = Cm(2.50)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_EN
    normal.font.size = Pt(12)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_CN)

    inserted = set()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        # 表格
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not re.fullmatch(r"[-: ]+", "".join(cells)):
                    rows.append(cells)
                i += 1
            if rows:
                add_table(doc, rows)
            continue

        # 引用块（表注/图注/待补说明）
        if line.startswith(">"):
            add_par(doc, line.lstrip("> ").strip(), size=10.5, indent_chars=0,
                    line=1.25, space_after=4)
            i += 1
            continue

        # 标题
        if line.startswith("# "):
            add_par(doc, line[2:].strip(), cn=HEAD_CN, size=18, bold=True,
                    align=WD_ALIGN_PARAGRAPH.CENTER, indent_chars=0,
                    line=1.5, space_before=0, space_after=12)
            i += 1
            continue
        if line.startswith("## "):
            add_par(doc, line[3:].strip(), cn=HEAD_CN, size=16, bold=True,
                    align=WD_ALIGN_PARAGRAPH.CENTER, indent_chars=0,
                    line=1.5, space_before=18, space_after=10)
            i += 1
            continue
        if line.startswith("### "):
            add_par(doc, line[4:].strip(), cn=HEAD_CN, size=14, bold=True,
                    align=WD_ALIGN_PARAGRAPH.LEFT, indent_chars=0,
                    line=1.5, space_before=12, space_after=6)
            i += 1
            continue

        # 参考文献条目：悬挂缩进、不首行缩进
        if re.match(r"^\[\d+\]\s", line):
            p = doc.add_paragraph()
            pf = p.paragraph_format
            pf.line_spacing = 1.25
            pf.space_after = Pt(3)
            pf.left_indent = Pt(24)
            pf.first_line_indent = Pt(-24)
            style_run(p.add_run(line), size=10.5)
            i += 1
            continue

        # 表题：居中、不缩进、与表格保持同页
        if TABLE_CAP.match(line):
            p = add_par(doc, line, size=10.5, align=WD_ALIGN_PARAGRAPH.CENTER,
                        indent_chars=0, line=1.25, space_before=8, space_after=3)
            p.paragraph_format.keep_with_next = True
            i += 1
            continue

        # 正文段落
        p = add_par(doc, line, align=WD_ALIGN_PARAGRAPH.JUSTIFY, space_after=6)
        for key, (path, caption) in FIGURES.items():
            if key in inserted:
                continue
            if key in line:
                inserted.add(key)
                add_figure(doc, path, caption)
                break
        i += 1

    doc.save(OUT)
    print("wrote", OUT)
    print("插入图件:", sorted(inserted) or "无")


if __name__ == "__main__":
    build()
