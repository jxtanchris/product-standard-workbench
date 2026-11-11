# -*- coding: utf-8 -*-
"""生成 GB/T 3103.3-2000 可检查项与检查方法分析报告（DOCX）。"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BODY_FONT = "宋体"
HEAD_FONT = "黑体"


def set_run_font(run, name=BODY_FONT, size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def style_setup(doc):
    for sname, size, bold in (("Normal", 10.5, False), ("Heading 1", 15, True), ("Heading 2", 12, True)):
        st = doc.styles[sname]
        st.font.name = HEAD_FONT if bold else BODY_FONT
        st.font.size = Pt(size)
        st.font.bold = bold
        st.font.color.rgb = RGBColor(0, 0, 0)
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        rfonts.set(qn("w:ascii"), HEAD_FONT if bold else BODY_FONT)
        rfonts.set(qn("w:hAnsi"), HEAD_FONT if bold else BODY_FONT)
        rfonts.set(qn("w:eastAsia"), HEAD_FONT if bold else BODY_FONT)
    pf = doc.styles["Normal"].paragraph_format
    pf.line_spacing = 1.25
    pf.space_after = Pt(4)


def para(doc, text="", size=10.5, bold=False, align=None, indent=True,
         font=BODY_FONT, space_before=0, space_after=4, line=1.25):
    p = doc.add_paragraph()
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif align == "right":
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    if indent:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line
    if text:
        r = p.add_run(text)
        set_run_font(r, font, size, bold)
    return p


def heading(doc, text, level=1):
    h = doc.add_heading(level=level)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    r = h.add_run(text)
    set_run_font(r, HEAD_FONT, 15 if level == 1 else 12, True)
    h.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    h.paragraph_format.space_after = Pt(6)
    return h


def shade(cell, hexcolor="D9E2F3"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def cell_text(cell, text, size=9, bold=False, align="left", color=None):
    cell.text = ""
    lines = text.split("\n") if text else [""]
    for i, line in enumerate(lines):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT,
                       "center": WD_ALIGN_PARAGRAPH.CENTER}[align]
        r = p.add_run(line)
        set_run_font(r, BODY_FONT, size, bold, color)


def set_tbl_width(t, widths):
    total = sum(widths)
    tblPr = t._tbl.tblPr
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW")
        tblPr.append(tblW)
    tblW.set(qn("w:type"), "dxa")
    tblW.set(qn("w:w"), str(int(total / 2.54 * 1440)))
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)


def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:cantSplit")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def vcenter(cell):
    tcPr = cell._tc.get_or_add_tcPr()
    va = OxmlElement("w:vAlign")
    va.set(qn("w:val"), "center")
    tcPr.append(va)


def make_table(doc, headers, rows, widths, size=9, head_size=9, all_center=False):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    set_tbl_width(t, widths)
    for i, w in enumerate(widths):
        t.columns[i].width = Cm(w)
    hdr = t.rows[0]
    for i, h in enumerate(headers):
        cell_text(hdr.cells[i], h, head_size, True, "center")
        shade(hdr.cells[i])
        vcenter(hdr.cells[i])
    repeat_header(hdr)
    no_split(hdr)
    for row in rows:
        r = t.add_row()
        no_split(r)
        cells = r.cells
        for i, v in enumerate(row):
            if all_center:
                al = "center"
            else:
                al = "left" if (i == 0 and len(str(v)) > 8) else ("center" if (i == 0 or len(str(v)) <= 6) else "left")
            cell_text(cells[i], str(v), size, False, al)
            vcenter(cells[i])
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    return t


doc = Document()
style_setup(doc)

sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.2)
sec.bottom_margin = Cm(2.0)

# ---------------- 标题 ----------------
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(10)
r = p.add_run("GB/T 3103.3—2000《紧固件公差  平垫圈》")
set_run_font(r, HEAD_FONT, 18, True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(2)
r = p.add_run("可检查项识别与检查方法分析")
set_run_font(r, HEAD_FONT, 15, True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(10)
r = p.add_run("（依据 GB/T 3103.3—2000 / idt ISO 4759-3:2000 正文、表 1 及附录 A 全文整理）")
set_run_font(r, BODY_FONT, 9.5)

# ---------------- 1 标准概览 ----------------
heading(doc, "1  标准概览")

para(doc, "GB/T 3103.3—2000 是《紧固件公差》系列标准的第 3 部分，等同采用 ISO 4759-3:2000，"
          "代替 GB/T 3103.3—1982，2000-09-26 发布、2001-02-01 实施。该标准只规定“公差”，"
          "不规定材料、机械性能、表面缺陷、镀层厚度和标记，因此可检查项全部集中在尺寸与形位公差上。")

rows = [
    ["标准号 / 名称", "GB/T 3103.3—2000《紧固件公差  平垫圈》（Tolerances for fasteners—Plain washers）"],
    ["采标关系", "idt ISO 4759-3:2000《紧固件公差  第 3 部分：螺栓、螺钉和螺母用平垫圈  产品等级 A 和 C 级》"],
    ["代替标准", "GB/T 3103.3—1982（主要修改：C 级不规定 h₁ 公差；以“厚度不均匀度 Δh”代替“平行度”，C 级不要求；C 级不要求平面度；增加附录 A）"],
    ["适用范围", "螺纹公称直径 1 mm～150 mm 的螺栓、螺钉和螺母用、产品等级为 A 级和 C 级的冲压平垫圈；推荐非标准垫圈也采用"],
    ["适用对象", "冲压（冲裁）平垫圈；产品等级由产品质量和公差大小确定"],
    ["公差基准", "除另有规定外，本标准规定的公差适用于垫圈镀前尺寸（GB/T 5267）"],
    ["优先规则", "不符合本标准规定且有正当技术原因者应在产品标准中规定；本标准与产品标准规定不同时，以产品标准为准"],
    ["引用的形位基础标准", "GB/T 1182—1996、GB/T 16671—1996（形位公差的规定与表示方法）；GB/T 1800.2、GB/T 1800.4（极限与配合、IT 值）"],
]
make_table(doc, ["项目", "内容"], rows, [3.4, 13.2], size=9)

# ---------------- 2 判定前提 ----------------
heading(doc, "2  判定前提（检查前必须确认）")

for txt in [
    "（1）确认被检件在标准适用范围内：螺纹公称直径为 1 mm～150 mm 的螺栓、螺钉和螺母用平垫圈；"
    "超出范围的垫圈，本标准仅“推荐”采用，不具备强制判定效力。",
    "（2）确认产品等级为 A 级或 C 级。等级直接决定检查项目数量：C 级不要求 h₁、倒角 e/α、"
    "厚度不均匀度 Δh、平面度 t₂ 四项，只考核 d₁、d₂、h 和同轴度 t₁。",
    "（3）确认测量状态为镀前。若为镀后件，应先按 GB/T 5267 与镀层厚度换算出镀前尺寸，"
    "或直接以镀前工序件判定。",
    "（4）确认产品标准是否有更严格或不同的规定。如有，以产品标准为准（第 3 章末段）。",
]:
    para(doc, txt, indent=False)

# ---------------- 3 可检查项总表（横向） ----------------
land = doc.add_section(WD_SECTION.NEW_PAGE)
land.orientation = WD_ORIENT.LANDSCAPE
land.page_width, land.page_height = Cm(29.7), Cm(21.0)
land.left_margin = land.right_margin = Cm(1.6)
land.top_margin = Cm(1.6)
land.bottom_margin = Cm(1.4)

heading(doc, "3  可检查项总表")
para(doc, "表中共 9 项需判定的检查项（序号 1～9）与 2 项“标准未规定、不作判定”的图示项（序号 10～11）。"
          "“检查方法”一栏中，凡标注“〔建议〕”者为标准未规定、依据 GB/T 1182、GB/T 1958 及常规计量实践给出的推荐方法。",
     size=9, indent=False, space_after=6)

headers = ["序号", "检查项目\n（符号）", "条款", "A 级要求", "C 级要求", "检查方法与测量部位", "量具／设备", "判定准则"]
rows = [
    ["1", "适用性及状态确认\n（前置项）", "第1章\n第3章",
     "d＝1～150 mm；A 级；\n公差适用镀前尺寸",
     "d＝1～150 mm；C 级；\n公差适用镀前尺寸",
     "核对产品标准、图样与等级标识；\n确认待检件处于镀前状态；\n确认产品标准无更严规定",
     "产品图样、\n产品标准", "不满足范围或状态者\n不按本标准判定"],

    ["2", "通孔直径\nd₁", "3.1",
     "h≤4：H13\nh＞4：H14",
     "h≤4：H14\nh＞4：H15",
     "〔建议〕① 批量：用 H13/H14/H15 光滑极限塞规通、止检验；\n"
     "② 计量：内径千分尺或游标卡尺在互相垂直的两个方向测量；\n"
     "③ 测量截面应位于孔壁圆柱直段（h₁ 段）内，避开塌边与撕裂带",
     "光滑极限塞规、\n内径千分尺(0.01)、\n游标卡尺(0.02)",
     "实际 d₁ 在表 A3\nES～EI 之间"],

    ["3", "孔部高度\nh₁", "3.1",
     "h≤4：h₁min＝0.5h\nh＞4：h₁min＝0.3h\n（h₁ 为 d₁ 公差范围内\n孔的部分）",
     "未规定\n（标准注明\n“尚待提出”，\n不要求）",
     "〔建议〕投影仪或工具显微镜按 5∶1 放大，测量孔壁未塌边的直段高度；\n"
     "沿圆周均布 3 处测量，取最小值；\n不得把塌边、撕裂带计入 h₁",
     "投影仪、\n工具显微镜、\n深度尺",
     "h₁ 实测 ≥ h₁min"],

    ["4", "外径\nd₂", "3.2",
     "h≤4：h14\nh＞4：h15",
     "h16",
     "〔建议〕外径千分尺在互相垂直两个方向测量，取最大、最小值；\n"
     "批量可用卡规或影像测量仪；\n测量位置应避开外缘塌边",
     "外径千分尺(0.01)、\n卡规、\n影像测量仪",
     "实际 d₂ 在表 A2\nes～ei 之间"],

    ["5", "厚度\nh", "3.3",
     "h≤0.5：±0.05\n0.5＜h≤1：±0.1\n1＜h≤2.5：±0.2\n2.5＜h≤4：±0.3\n4＜h≤6：±0.6\n6＜h≤10：±1\n10＜h≤20：±1.2",
     "h≤0.5：±0.1\n0.5＜h≤1：±0.2\n1＜h≤2.5：±0.3\n2.5＜h≤4：±0.6\n4＜h≤6：±1\n6＜h≤10：±1.2\n10＜h≤20：±1.6",
     "〔建议〕外径千分尺（平测头）测量；\n测点位于孔边与外缘之间的带宽中部，避开倒角区与塌边；\n沿圆周均布 3 点，逐点判定；\n镀前状态下测量",
     "外径千分尺(0.01)\n或厚度千分尺",
     "各测点 |h－h公称|\n≤ 对应公差"],

    ["6", "倒角\ne、α", "3.4",
     "α＝30°～45°\ne_min＝0.25h\ne_max＝0.5h",
     "不要求\n（表中为“—”）",
     "〔建议〕投影仪或影像测量仪放大后，测量倒角斜面轴向宽度 e 与倒角角 α；\n"
     "可用倒角样板比对；\n沿圆周抽测 2～3 处",
     "投影仪、\n影像测量仪、\n角度尺",
     "0.25h ≤ e ≤ 0.5h\n且 30° ≤ α ≤ 45°"],

    ["7", "同一部位厚度\n不均匀度 Δh", "3.5.1",
     "h≤0.5：0.025\n0.5＜h≤1：0.05\n1＜h≤2.5：0.1\n2.5＜h≤4：0.15\n4＜h≤6：0.2\n6＜h≤10：0.3\n10＜h≤20：0.4\n（单位 mm）",
     "不要求",
     "〔建议〕测量带：自孔内棱边至外棱边、距两边各 x＝0.1(d₂－d₁) 的中间区域"
     "（标准原文注为“圆周宽度的 60%”）；\n在该带内沿圆周均布 ≥3 个径向位置测厚；\n"
     "取同一部位（同一圆周位置）最大厚度与最小厚度之差",
     "外径/厚度千分尺\n(0.001 或 0.01)、\n测厚夹具",
     "Δh 实测值\n＝h_max－h_min\n≤ 表值"],

    ["8", "同轴度\nt₁", "3.5.2",
     "d₂≤50：2IT12\nd₂＞50：2IT13\n（基准 A 为 φd₂\n外圆轴线）",
     "d₂≤50：2IT15\nd₂＞50：2IT16",
     "〔建议〕① 仲裁：三坐标测量机测内孔与外圆两圆柱面，按 GB/T 1182 评定同轴度；\n"
     "② 专用检具：心轴穿入内孔、百分表触外圆，旋转一周读最大差值（近似径向圆跳动）；\n"
     "③ 快速筛查：壁厚千分尺沿圆周测 4 点壁厚，最大壁厚差≈同轴度误差",
     "三坐标测量机、\n同轴度检具、\n壁厚千分尺",
     "t₁ 实测 ≤ 2ITn\n（IT 值查表 A1）"],

    ["9", "平面度\nt₂", "3.5.3",
     "按 h 分档（mm）：\n非不锈钢：\n≤0.5→0.1；≤1→0.15；≤2.5→0.2；\n≤4→0.3；≤6→0.4；≤10→0.6；≤20→1\n不锈钢：\n≤0.5→0.15；≤1→0.22；≤2.5→0.3；\n≤4→0.45；≤6→0.6；≤10→0.9；≤20→1.5",
     "不要求",
     "〔建议〕先去除毛刺（标准注 1）；\n将垫圈自由放置在 0 级平板上，用塞尺测最大间隙；\n"
     "或用百分表沿圆周均布 ≥6 点测量，取最大读数差；\n或三坐标扫描拟合平面；\n"
     "t₂ 与 h 的公差互为独立公差（标准注）",
     "0 级平板、塞尺、\n百分表/千分表\n及表架",
     "t₂ 实测 ≤ 表值"],

    ["10", "外缘高度\nh₂", "3.2",
     "未规定（标准注：\nh₂、塌边和撕裂带\n尚未规定，但将要提出）",
     "未规定",
     "仅图 3.2 中标注示意，用于说明 d₂ 公差覆盖的外缘部分；\n如需控制，应由产品标准另行规定",
     "—", "不作合格判定\n（仅记录）"],

    ["11", "塌边、\n撕裂带", "3.1 / 3.2",
     "未规定\n（“尚待提出”）",
     "未规定",
     "目视或放大镜、投影仪观察并记录形态与范围；\n目前无公差值，不得据本标准判废",
     "放大镜、\n投影仪", "不作合格判定\n（仅记录）"],
]
make_table(doc, headers, rows, [1.1, 2.7, 1.4, 4.7, 3.2, 7.3, 3.2, 2.9], size=8, head_size=8.5)

# ---------------- 4 逐项要点（纵向） ----------------
port = doc.add_section(WD_SECTION.NEW_PAGE)
port.orientation = WD_ORIENT.PORTRAIT
port.page_width, port.page_height = Cm(21.0), Cm(29.7)
port.left_margin = port.right_margin = Cm(2.2)
port.top_margin = Cm(2.2)
port.bottom_margin = Cm(2.0)

heading(doc, "4  逐项检查方法要点")

para(doc, "标准正文只给出公差数值，未规定测量方法、测量部位、测点数量和量具精度。以下要点中，"
          "“标准规定”为原文内容，“实施建议”为根据公差等级、结构特点与通行的计量规范补充的操作要求，"
          "建议纳入企业检验规范后固化执行。", indent=True)

items = [
    ("4.1  通孔直径 d₁（3.1）",
     ["标准规定：A 级按厚度分档取 H13（h≤4）或 H14（h＞4）；C 级取 H14（h≤4）或 H15（h＞4）。"
      "极限偏差查附录 A 表 A3。",
      "实施建议：d₁ 为冲裁孔，孔壁存在塌边与撕裂带，只有在 h₁ 段（d₁ 规定公差范围内的孔壁）测得的尺寸才有效。"
      "内径千分尺测量时应沿轴向取孔的中部截面，并在互相垂直的两个方向读数。",
      "量具选择：塞规适用于大批量通止判定，但无法给出实测值；需记录数据或做过程能力分析时应使用内径千分尺（分度值 0.01 mm）。"]),
    ("4.2  孔部高度 h₁（3.1）",
     ["标准规定：仅 A 级有要求，h₁min 为 0.5h（h≤4）或 0.3h（h＞4）；C 级未规定。",
      "实施建议：h₁ 是判别冲孔质量的指标，与螺栓支承面接触的有效孔壁有关。测量应在 5∶1 放大的投影影像上进行，"
      "以孔壁直线段（不含塌边、撕裂带）的轴向长度为准，圆周均布 3 处取最小值。"]),
    ("4.3  外径 d₂（3.2）",
     ["标准规定：A 级取 h14（h≤4）或 h15（h＞4），C 级一律 h16；极限偏差查表 A2。",
      "实施建议：外缘同样存在塌边，千分尺应卡在 d₂ 圆柱面上而非塌边过渡区；冲裁件常有 0.05～0.2 mm 的椭圆度，"
      "必须测两个互相垂直方向并取最大、最小值分别判定，不能只测一处。"]),
    ("4.4  厚度 h（3.3）",
     ["标准规定：A 级 ±0.05～±1.2，C 级 ±0.1～±1.6，按 h 分七档；公差适用于镀前尺寸。",
      "实施建议：测点应位于孔边与外缘之间的带宽中部，避开倒角区（e＝0.25h～0.5h）与塌边；"
      "沿圆周均布 3 点，逐点与公差比较。厚度是后续 Δh、t₂ 计算与判定的基数，应优先测量。",
      "注意：h 分档关系到 d₁、d₂、Δh、t₂ 的取值，必须先测准 h 再查对应档位，避免用错公差带。"]),
    ("4.5  倒角 e、α（3.4）",
     ["标准规定：α＝30°～45°，e_min＝0.25h，e_max＝0.5h，仅 A 级要求，C 级不要求。",
      "实施建议：倒角尺寸小（h＝2 时 e 仅 0.5～1.0 mm），宜用投影仪或影像测量仪放大测量；"
      "e 为倒角斜面的轴向投影宽度，不是斜面长度。冲裁件的自然塌角不等于倒角，需按图样区分。"]),
    ("4.6  同一部位厚度不均匀度 Δh（3.5.1）",
     ["标准规定：仅 A 级要求，按 h 分档取 0.025～0.4 mm，C 级不要求。该指标在 2000 版中替代了 1982 版的“平行度”。",
      "测量带：标准原文注“Δh 的要求适用于从孔的内棱边间与外棱边间的距离。x＝0.1(d₂－d₁)，即圆周宽度的 60%”。"
      "即自孔内棱边与外棱边各向内让出宽度 x 后，在剩余中间带内测量。",
      "实施建议：在中间带内沿圆周均布 ≥3 个径向位置，每一位置测同一圆周上若干点的厚度，"
      "取该部位 h_max 与 h_min 之差作为 Δh 实测值。因公差很小（最小 0.025 mm），千分尺分度值应不大于 0.001 mm 或 0.002 mm，"
      "并注意测力一致、避免弹性变形。",
      "提示：原文“x＝0.1(d₂－d₁)”与“圆周宽度的 60%”在几何上并不严格自洽（两侧各让 0.1 时剩余 80%），"
      "宜按 x 值控制测量带，并在检验规范中写明测点位置，避免争议。"]),
    ("4.7  同轴度 t₁（3.5.2）",
     ["标准规定：A 级 d₂≤50 取 2IT12、d₂＞50 取 2IT13；C 级取 2IT15、2IT16。基准 A 为 φd₂ 外圆轴线，"
      "被测要素为 φd₁ 内孔轴线。d₂ 是选取公差 t₁ 的依据。",
      "实施建议：以三坐标测量机测内外两圆柱并按 GB/T 1182 评定为仲裁方法；批量可用心轴＋百分表的专用检具，"
      "旋转一周读最大差值作近似判定；壁厚差法（同轴度误差≈最大壁厚差）仅作快速筛查，不作最终判定依据。",
      "计算：t₁ 需先用附录 A 表 A1 查 IT 值。例如 d₂＝24 mm 落在 18～30 档，IT12＝0.21 mm，故 t₁＝2×0.21＝0.42 mm。"]),
    ("4.8  平面度 t₂（3.5.3）",
     ["标准规定：仅 A 级要求，C 级不要求；并按材料分为“非不锈钢”与“不锈钢”两套数值，不锈钢约为非不锈钢的 1.5 倍。"
      "标准注 1 明确“去除毛刺后测量平面度”，另一注明确 t₂ 与厚度 h 的公差互为独立公差。",
      "实施建议：垫圈自由状态置于 0 级平板上，用塞尺测最大间隙；或用百分表沿圆周均布 ≥6 点测量取最大读数差；"
      "薄件（h≤1）应避免测量力与自重引起的弹性变形，读数以刚接触为准。",
      "注意：去除毛刺会改变厚度与平面状态，平面度应在去毛刺后、镀前测量；不得与厚度公差混判。"]),
]

for title, bullets in items:
    heading(doc, title, level=2)
    for b in bullets:
        para(doc, b, indent=True)

# ---------------- 5 不判定项 ----------------
heading(doc, "5  标准未规定、不作合格判定的内容")
para(doc, "以下内容在标准中以图示出现或明确“尚未规定”，不能作为判废依据，只能记录或由产品标准另行规定：", indent=True)
rows = [
    ["外缘高度 h₂（3.2）", "表 1 中注“h₂、塌边和撕裂带尚未规定，但将要提出”，无公差值"],
    ["塌边、撕裂带（3.1、3.2）", "同上，仅在图示中示意，无公差值"],
    ["C 级的 h₁、倒角、Δh、t₂", "标准对 C 级明确“不要求”，不得对 C 级件判这些项目不合格"],
    ["材料、机械性能、表面缺陷、镀层厚度、标记与包装", "不属于本标准的范围，应执行相应的产品标准与 GB/T 5267 等"],
]
make_table(doc, ["内容", "说明"], rows, [6.0, 10.6], size=9)

# ---------------- 6 附录 A 数值表 ----------------
h6 = heading(doc, "6  附录 A 公差数值表（用于换算上述公差代号）")
h6.paragraph_format.page_break_before = True
para(doc, "表 A1 标准公差等级的 IT 值（mm）", size=9.5, bold=True, indent=False, space_before=6)
rows = [
    ["＞3～6", "0.12", "0.18", "0.48", "0.75"], ["＞6～10", "0.15", "0.22", "0.58", "0.9"],
    ["＞10～18", "0.18", "0.27", "0.7", "1.1"], ["＞18～30", "0.21", "0.33", "0.84", "1.3"],
    ["＞30～50", "0.25", "0.39", "1", "1.6"], ["＞50～80", "0.3", "0.46", "1.2", "1.9"],
    ["＞80～120", "0.35", "0.54", "1.4", "2.2"], ["＞120～180", "0.4", "0.63", "1.6", "2.5"],
    ["＞180～250", "0.46", "0.72", "1.85", "2.9"],
]
rows.insert(0, ["≤3", "0.1", "0.14", "0.4", "0.6"])
make_table(doc, ["公称直径 / mm", "IT12", "IT13", "IT15", "IT16"], rows, [3.6, 3.25, 3.25, 3.25, 3.25], size=9, all_center=True)

para(doc, "表 A2 轴的极限偏差（mm）——用于 d₂（h14、h15、h16）", size=9.5, bold=True, indent=False, space_before=8)
rows = [
    ["≤3", "0／－0.25", "0／－0.4", "0／－0.6"], ["＞3～6", "0／－0.3", "0／－0.48", "0／－0.75"],
    ["＞6～10", "0／－0.36", "0／－0.58", "0／－0.9"], ["＞10～18", "0／－0.43", "0／－0.7", "0／－1.1"],
    ["＞18～30", "0／－0.52", "0／－0.84", "0／－1.3"], ["＞30～50", "0／－0.62", "0／－1", "0／－1.6"],
    ["＞50～80", "0／－0.74", "0／－1.2", "0／－1.9"], ["＞80～120", "0／－0.87", "0／－1.4", "0／－2.2"],
    ["＞120～180", "0／－1", "0／－1.6", "0／－2.5"], ["＞180～250", "0／－1.15", "0／－1.85", "0／－2.9"],
]
make_table(doc, ["公称直径 / mm", "h14", "h15", "h16"], rows, [4.0, 4.2, 4.2, 4.2], size=9, all_center=True)

para(doc, "表 A3 孔的极限偏差（mm）——用于 d₁（H13、H14、H15）", size=9.5, bold=True, indent=False, space_before=8)
rows = [
    ["≤3", "＋0.14／0", "＋0.25／0", "＋0.4／0"], ["＞3～6", "＋0.18／0", "＋0.3／0", "＋0.48／0"],
    ["＞6～10", "＋0.22／0", "＋0.36／0", "＋0.58／0"], ["＞10～18", "＋0.27／0", "＋0.43／0", "＋0.7／0"],
    ["＞18～30", "＋0.33／0", "＋0.52／0", "＋0.84／0"], ["＞30～50", "＋0.39／0", "＋0.62／0", "＋1／0"],
    ["＞50～80", "＋0.46／0", "＋0.74／0", "＋1.2／0"], ["＞80～120", "＋0.54／0", "＋0.87／0", "＋1.4／0"],
    ["＞120～180", "＋0.63／0", "＋1／0", "＋1.6／0"], ["＞180～250", "＋0.72／0", "＋1.15／0", "＋1.85／0"],
]
make_table(doc, ["公称直径 / mm", "H13", "H14", "H15"], rows, [4.0, 4.2, 4.2, 4.2], size=9, all_center=True)

# ---------------- 7 示例 ----------------
h7 = heading(doc, "7  换算与判定示例")
h7.paragraph_format.page_break_before = True
para(doc, "以 A 级平垫圈、公称厚度 h＝2 mm、d₁＝13 mm、d₂＝24 mm、材料为非不锈钢为例：", indent=True)
rows = [
    ["d₁", "h＝2≤4 → H13；d₁＝13 落在 10～18 档", "＋0.27／0", "13.00～13.27"],
    ["h₁", "h＝2≤4 → h₁min＝0.5h", "≥1.0", "≥1.0"],
    ["d₂", "h＝2≤4 → h14；d₂＝24 落在 18～30 档", "0／－0.52", "23.48～24.00"],
    ["h", "1＜h≤2.5 档", "±0.2", "1.8～2.2"],
    ["e、α", "e＝0.25h～0.5h", "0.5～1.0；30°～45°", "0.5～1.0"],
    ["Δh", "1＜h≤2.5 档", "0.1", "≤0.1"],
    ["t₁", "d₂＝24≤50 → 2IT12；IT12(18～30)＝0.21", "0.42", "≤0.42"],
    ["t₂", "非不锈钢，1＜h≤2.5 档", "0.2", "≤0.2"],
]
make_table(doc, ["项目", "取值依据", "公差 / 极限偏差（mm）", "合格区间（mm）"],
           rows, [2.2, 7.2, 3.8, 3.4], size=9)
para(doc, "注：示例仅演示“查档—查表—换算”的过程，d₁、d₂、h 的公称值应取自相应产品标准（如 GB/T 97.1、GB/T 97.2、GB/T 848 等）。",
     size=9, indent=False, space_before=4)

# ---------------- 8 局限 ----------------
heading(doc, "8  使用说明与局限")
for txt in [
    "（1）本标准是公差标准，不是检验标准。全文没有一条规定测量方法、量具、测点数量、抽样方案或合格质量水平。"
    "本文档中除“标准规定”外的操作内容均为推荐做法，落地时应写入企业检验规范并经技术、质量部门确认。",
    "（2）判定次序建议为：确认等级与镀前状态 → 测 h（确定分档）→ 测 d₁、d₂、e/α → 测 Δh、t₂ → 测 t₁。"
    "先定 h 档位可避免用错公差带，这是本标准最容易出错的地方。",
    "（3）C 级件的项目显著少于 A 级件，检验规范应分等级编制，避免对 C 级件提出标准未要求的项目。",
    "（4）抽样方案、批量与样本量、AQL 均不在本标准范围内，应在检验规范中按 GB/T 2828.1 或产品标准规定。",
    "（5）形位公差（t₁、t₂）的数值由 IT 等级换算而来，测量不确定度应明显小于公差值；"
    "对 0.025 mm 级的 Δh 与薄件 t₂，应评估量具与测量力带来的不确定度并记录。",
]:
    para(doc, txt, indent=False)

doc.save("GB-T 3103.3-2000 平垫圈 可检查项与检查方法分析.docx")
print("saved docx")
