# -*- coding: utf-8 -*-
"""生成 GB/T 3103.3-2000 平垫圈检验项目清单（XLSX）。"""
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter

HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
SUB_FONT = Font(name="微软雅黑", size=9, color="404040")
BODY_FONT = Font(name="微软雅黑", size=9)
BOLD_FONT = Font(name="微软雅黑", size=9, bold=True)
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="center")
WRAP_LEFT = Alignment(wrap_text=True, vertical="center", horizontal="left")
CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")
BAND = PatternFill("solid", fgColor="EAF1F8")
GRAY = PatternFill("solid", fgColor="F2F2F2")


def disp_units(txt):
    return sum(1.85 if ord(ch) > 127 else 1.0 for ch in txt)


def est_lines(txt, col_width):
    cap = col_width * 1.15
    total = 0
    for seg in str(txt).split("\n"):
        total += max(1, -(-disp_units(seg) // cap))
    return int(total)


def auto_height(row_values, widths, minimum=34):
    lines = 1
    for v, w in zip(row_values, widths):
        if v:
            lines = max(lines, est_lines(v, w))
    return max(minimum, lines * 13.6 + 8)


wb = Workbook()

# ================= Sheet 1 检验项目清单 =================
ws = wb.active
ws.title = "检验项目清单"
ws.sheet_view.showGridLines = False

headers = ["序号", "检查项目", "符号", "条款", "A 级要求", "C 级要求",
           "检查方法与测量部位", "量具 / 设备", "判定准则",
           "实测记录", "结论", "备注"]
widths = [5, 14, 7, 7, 26, 20, 52, 20, 18, 12, 8, 16]

ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
c = ws.cell(row=1, column=1, value="GB/T 3103.3—2000《紧固件公差  平垫圈》检验项目清单")
c.font = TITLE_FONT
c.alignment = Alignment(horizontal="left", vertical="center")
ws.row_dimensions[1].height = 26

ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
c = ws.cell(row=2, column=1,
            value="产品名称：____________　规格 d＝____mm　产品等级：A / C　材料：__________　"
                  "状态：镀前 / 镀后　批量：______　检验日期：__________　检验员：__________")
c.font = SUB_FONT
c.alignment = Alignment(horizontal="left", vertical="center")
ws.row_dimensions[2].height = 20

for j, h in enumerate(headers, start=1):
    c = ws.cell(row=3, column=j, value=h)
    c.fill = HDR_FILL
    c.font = HDR_FONT
    c.alignment = CENTER
    c.border = BORDER
ws.row_dimensions[3].height = 32

rows = [
    ["1", "适用性及状态确认（前置）", "—", "第1章\n第3章",
     "d＝1～150 mm；A 级；公差适用镀前尺寸",
     "d＝1～150 mm；C 级；公差适用镀前尺寸",
     "核对产品标准、图样与等级标识；确认待检件处于镀前状态；确认产品标准无更严规定",
     "产品图样、产品标准", "不满足范围或状态者不按本标准判定", "", "", ""],

    ["2", "通孔直径", "d₁", "3.1", "h≤4：H13\nh＞4：H14", "h≤4：H14\nh＞4：H15",
     "① 批量：H13/H14/H15 光滑极限塞规通、止检验；② 计量：内径千分尺或游标卡尺在互相垂直两方向测量；"
     "③ 测量截面位于孔壁圆柱直段（h₁ 段）内，避开塌边与撕裂带",
     "光滑极限塞规、内径千分尺(0.01)、游标卡尺(0.02)", "实际 d₁ 在表 A3 的 ES～EI 之间", "", "", ""],

    ["3", "孔部高度", "h₁", "3.1", "h≤4：h₁min＝0.5h\nh＞4：h₁min＝0.3h\n（h₁ 为 d₁ 公差范围内孔的部分）",
     "未规定（标准注明“尚待提出”，不要求）",
     "投影仪或工具显微镜按 5∶1 放大，测量孔壁未塌边的直段高度；沿圆周均布 3 处，取最小值；不得计入塌边、撕裂带",
     "投影仪、工具显微镜、深度尺", "h₁ 实测 ≥ h₁min", "", "", ""],

    ["4", "外径", "d₂", "3.2", "h≤4：h14\nh＞4：h15", "h16",
     "外径千分尺在互相垂直两方向测量，取最大、最小值；批量可用卡规或影像测量仪；测量位置避开外缘塌边",
     "外径千分尺(0.01)、卡规、影像测量仪", "实际 d₂ 在表 A2 的 es～ei 之间", "", "", ""],

    ["5", "厚度", "h", "3.3",
     "h≤0.5：±0.05\n0.5＜h≤1：±0.1\n1＜h≤2.5：±0.2\n2.5＜h≤4：±0.3\n4＜h≤6：±0.6\n6＜h≤10：±1\n10＜h≤20：±1.2",
     "h≤0.5：±0.1\n0.5＜h≤1：±0.2\n1＜h≤2.5：±0.3\n2.5＜h≤4：±0.6\n4＜h≤6：±1\n6＜h≤10：±1.2\n10＜h≤20：±1.6",
     "外径千分尺（平测头）测量；测点位于孔边与外缘之间的带宽中部，避开倒角区与塌边；沿圆周均布 3 点，逐点判定；镀前状态下测量",
     "外径千分尺(0.01) 或厚度千分尺", "各测点 |h－h公称| ≤ 对应公差", "", "", "先测 h 以确定各表分档"],

    ["6", "倒角", "e、α", "3.4", "α＝30°～45°\ne_min＝0.25h\ne_max＝0.5h", "不要求（表中为“—”）",
     "投影仪或影像测量仪放大后，测量倒角斜面轴向宽度 e 与倒角角 α；可用倒角样板比对；沿圆周抽测 2～3 处",
     "投影仪、影像测量仪、角度尺", "0.25h ≤ e ≤ 0.5h 且 30° ≤ α ≤ 45°", "", "", ""],

    ["7", "同一部位厚度\n不均匀度", "Δh", "3.5.1",
     "h≤0.5：0.025\n0.5＜h≤1：0.05\n1＜h≤2.5：0.1\n2.5＜h≤4：0.15\n4＜h≤6：0.2\n6＜h≤10：0.3\n10＜h≤20：0.4",
     "不要求",
     "测量带：自孔内棱边至外棱边、距两边各 x＝0.1(d₂－d₁) 的中间区域（原文注为“圆周宽度的 60%”）；"
     "在该带内沿圆周均布 ≥3 个径向位置测厚；取同一部位最大厚度与最小厚度之差",
     "外径/厚度千分尺(0.001 或 0.01)、测厚夹具", "Δh 实测＝h_max－h_min ≤ 表值", "", "",
     "2000 版以本项替代 1982 版“平行度”"],

    ["8", "同轴度", "t₁", "3.5.2", "d₂≤50：2IT12\nd₂＞50：2IT13\n（基准 A 为 φd₂ 外圆轴线）",
     "d₂≤50：2IT15\nd₂＞50：2IT16",
     "① 仲裁：三坐标测量机测内孔与外圆两圆柱面，按 GB/T 1182 评定同轴度；"
     "② 专用检具：心轴穿入内孔、百分表触外圆，旋转一周读最大差值；"
     "③ 快速筛查：壁厚千分尺沿圆周测 4 点壁厚，最大壁厚差≈同轴度误差",
     "三坐标测量机、同轴度检具、壁厚千分尺", "t₁ 实测 ≤ 2ITn（IT 值查表 A1）", "", "", ""],

    ["9", "平面度", "t₂", "3.5.3",
     "按 h 分档（mm）：\n非不锈钢：≤0.5→0.1；≤1→0.15；≤2.5→0.2；≤4→0.3；≤6→0.4；≤10→0.6；≤20→1\n"
     "不锈钢：≤0.5→0.15；≤1→0.22；≤2.5→0.3；≤4→0.45；≤6→0.6；≤10→0.9；≤20→1.5",
     "不要求",
     "先去除毛刺（标准注 1）；将垫圈自由放置在 0 级平板上用塞尺测最大间隙；或用百分表沿圆周均布 ≥6 点测量取最大读数差；"
     "或三坐标扫描拟合平面；t₂ 与 h 的公差互为独立公差",
     "0 级平板、塞尺、百分表/千分表及表架", "t₂ 实测 ≤ 表值", "", "",
     "不锈钢数值约为非不锈钢的 1.5 倍"],

    ["10", "外缘高度（未规定）", "h₂", "3.2", "未规定（标准注：h₂、塌边和撕裂带尚未规定，但将要提出）", "未规定",
     "仅图 3.2 中标注示意，用于说明 d₂ 公差覆盖的外缘部分；如需控制，应由产品标准另行规定",
     "—", "不作合格判定（仅记录）", "", "", ""],

    ["11", "塌边、撕裂带（未规定）", "—", "3.1 / 3.2", "未规定（“尚待提出”）", "未规定",
     "目视或放大镜、投影仪观察并记录形态与范围；目前无公差值，不得据本标准判废",
     "放大镜、投影仪", "不作合格判定（仅记录）", "", "", ""],
]

r = 4
for i, row in enumerate(rows):
    for j, v in enumerate(row, start=1):
        c = ws.cell(row=r, column=j, value=v)
        c.font = BOLD_FONT if j == 2 else BODY_FONT
        c.alignment = CENTER if j in (1, 3, 4, 11) else WRAP_LEFT
        c.border = BORDER
        if i % 2 == 1:
            c.fill = BAND
    ws.row_dimensions[r].height = auto_height(row, widths)
    r += 1

for j, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(j)].width = w

ws.freeze_panes = "E4"

# 结论说明行
r += 1
ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
c = ws.cell(row=r, column=1,
            value="判定：全部应检项目符合 → 合格；任一应检项目不符合 → 不合格。"
                  "C 级件的 h₁、倒角 e/α、Δh、t₂ 不作要求，不得判为不合格。"
                  "产品标准与本标准规定不同时，以产品标准为准（第 3 章）。")
c.font = Font(name="微软雅黑", size=9, italic=True, color="7F0000")
c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
ws.row_dimensions[r].height = 30

ws.print_title_rows = "3:3"
ws.page_setup.orientation = "landscape"
ws.page_setup.paperSize = 8  # A3
ws.page_setup.fitToWidth = 1
ws.sheet_properties.pageSetUpPr.fitToPage = True

# ================= Sheet 2 公差数值表 =================
ws2 = wb.create_sheet("公差数值表")
ws2.sheet_view.showGridLines = False
ws2.merge_cells("A1:E1")
c = ws2.cell(row=1, column=1, value="附录 A 公差数值表（GB/T 3103.3—2000 附录 A，单位 mm）")
c.font = TITLE_FONT
c.alignment = Alignment(horizontal="left", vertical="center")
ws2.row_dimensions[1].height = 26

def block(ws, start_row, title, headers_, data, widths_):
    ws.merge_cells(start_row=start_row, start_column=1, end_row=start_row, end_column=len(headers_))
    c = ws.cell(row=start_row, column=1, value=title)
    c.font = Font(name="微软雅黑", size=10, bold=True)
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[start_row].height = 20
    hr = start_row + 1
    for j, h in enumerate(headers_, start=1):
        c = ws.cell(row=hr, column=j, value=h)
        c.fill = HDR_FILL
        c.font = HDR_FONT
        c.alignment = CENTER
        c.border = BORDER
    for i, row in enumerate(data):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=hr + 1 + i, column=j, value=v)
            c.font = BODY_FONT
            c.alignment = CENTER
            c.border = BORDER
            if i % 2 == 1:
                c.fill = GRAY
    return hr + len(data) + 2

titles = ["≤3", "＞3～6", "＞6～10", "＞10～18", "＞18～30", "＞30～50",
          "＞50～80", "＞80～120", "＞120～180", "＞180～250"]

a1 = [[titles[0], 0.1, 0.14, 0.4, 0.6], [titles[1], 0.12, 0.18, 0.48, 0.75],
      [titles[2], 0.15, 0.22, 0.58, 0.9], [titles[3], 0.18, 0.27, 0.7, 1.1],
      [titles[4], 0.21, 0.33, 0.84, 1.3], [titles[5], 0.25, 0.39, 1, 1.6],
      [titles[6], 0.3, 0.46, 1.2, 1.9], [titles[7], 0.35, 0.54, 1.4, 2.2],
      [titles[8], 0.4, 0.63, 1.6, 2.5], [titles[9], 0.46, 0.72, 1.85, 2.9]]
a2 = [[titles[0], "0／－0.25", "0／－0.4", "0／－0.6"], [titles[1], "0／－0.3", "0／－0.48", "0／－0.75"],
      [titles[2], "0／－0.36", "0／－0.58", "0／－0.9"], [titles[3], "0／－0.43", "0／－0.7", "0／－1.1"],
      [titles[4], "0／－0.52", "0／－0.84", "0／－1.3"], [titles[5], "0／－0.62", "0／－1", "0／－1.6"],
      [titles[6], "0／－0.74", "0／－1.2", "0／－1.9"], [titles[7], "0／－0.87", "0／－1.4", "0／－2.2"],
      [titles[8], "0／－1", "0／－1.6", "0／－2.5"], [titles[9], "0／－1.15", "0／－1.85", "0／－2.9"]]
a3 = [[titles[0], "＋0.14／0", "＋0.25／0", "＋0.4／0"], [titles[1], "＋0.18／0", "＋0.3／0", "＋0.48／0"],
      [titles[2], "＋0.22／0", "＋0.36／0", "＋0.58／0"], [titles[3], "＋0.27／0", "＋0.43／0", "＋0.7／0"],
      [titles[4], "＋0.33／0", "＋0.52／0", "＋0.84／0"], [titles[5], "＋0.39／0", "＋0.62／0", "＋1／0"],
      [titles[6], "＋0.46／0", "＋0.74／0", "＋1.2／0"], [titles[7], "＋0.54／0", "＋0.87／0", "＋1.4／0"],
      [titles[8], "＋0.63／0", "＋1／0", "＋1.6／0"], [titles[9], "＋0.72／0", "＋1.15／0", "＋1.85／0"]]

nxt = block(ws2, 3, "表 A1  标准公差等级的 IT 值", ["公称直径 / mm", "IT12", "IT13", "IT15", "IT16"], a1, None)
nxt = block(ws2, nxt, "表 A2  轴的极限偏差（用于 d₂：h14、h15、h16）", ["公称直径 / mm", "h14", "h15", "h16"], a2, None)
nxt = block(ws2, nxt, "表 A3  孔的极限偏差（用于 d₁：H13、H14、H15）", ["公称直径 / mm", "H13", "H14", "H15"], a3, None)

for col, w in zip("ABCDE", [18, 14, 14, 14, 14]):
    ws2.column_dimensions[col].width = w
ws2.freeze_panes = "A3"
ws2.page_setup.orientation = "landscape"
ws2.page_setup.paperSize = 9  # A4
ws2.page_setup.fitToWidth = 1
ws2.page_setup.fitToHeight = 0
ws2.sheet_properties.pageSetUpPr.fitToPage = True

# ================= Sheet 3 使用说明 =================
ws3 = wb.create_sheet("使用说明")
ws3.sheet_view.showGridLines = False
ws3.column_dimensions["A"].width = 4
ws3.column_dimensions["B"].width = 80

ws3.merge_cells("A1:B1")
c = ws3.cell(row=1, column=1, value="使用说明")
c.font = TITLE_FONT
c.alignment = Alignment(horizontal="left", vertical="center")
ws3.row_dimensions[1].height = 28

notes = [
    ("1", "本清单依据 GB/T 3103.3—2000（idt ISO 4759-3:2000）正文、表 1 与附录 A 整理。该标准只规定公差，"
          "未规定测量方法、量具、测点数量与抽样方案；“检查方法与测量部位”栏为依据 GB/T 1182、GB/T 1958 及常规计量实践给出的推荐做法，"
          "应经技术、质量部门确认后写入企业检验规范。"),
    ("2", "判定前提：① 螺纹公称直径 1～150 mm 的螺栓、螺钉和螺母用平垫圈；② 产品等级为 A 级或 C 级；"
          "③ 公差适用于镀前尺寸（GB/T 5267）；④ 产品标准有不同规定时，以产品标准为准。"),
    ("3", "C 级不要求 h₁、倒角 e/α、厚度不均匀度 Δh、平面度 t₂ 四项，只考核 d₁、d₂、h 与同轴度 t₁，"
          "检验规范应分等级编制，避免对 C 级件提出标准未要求的项目。"),
    ("4", "建议判定次序：确认等级与镀前状态 → 测 h（确定各表分档）→ 测 d₁、d₂、e/α → 测 Δh、t₂ → 测 t₁。"
          "先定 h 档位可避免用错公差带，这是本标准最容易出错之处。"),
    ("5", "外缘高度 h₂、塌边、撕裂带在标准中“尚未规定”，h₂ 仅作图示说明；这些内容不得作为判废依据，只能记录。"),
    ("6", "材料、机械性能、表面缺陷、镀层厚度、标记与包装不属于本标准范围，应执行相应的产品标准（如 GB/T 97.1、GB/T 97.2、GB/T 848）与 GB/T 5267。"),
    ("7", "抽样方案、批量与样本量、AQL 不在本标准范围内，建议按 GB/T 2828.1 或产品标准在检验规范中规定。"),
    ("8", "计算示例：A 级、h＝2 mm、d₁＝13 mm、d₂＝24 mm、非不锈钢 → d₁：H13（＋0.27/0，10～18 档）；"
          "d₂：h14（0/－0.52，18～30 档）；h：±0.2；e：0.5～1.0；Δh：0.1；t₁：2IT12＝2×0.21＝0.42；t₂：0.2。"),
    ("9", "表中“实测记录”“结论”栏供现场填写，可按抽样方案逐件分栏或另附记录表。"),
]
r = 3
for no, txt in notes:
    c = ws3.cell(row=r, column=1, value=no)
    c.font = BODY_FONT
    c.alignment = Alignment(horizontal="center", vertical="top")
    c = ws3.cell(row=r, column=2, value=txt)
    c.font = BODY_FONT
    c.alignment = Alignment(wrap_text=True, vertical="top", horizontal="left")
    ws3.row_dimensions[r].height = auto_height([txt], [80], minimum=30)
    r += 1

ws3.page_setup.orientation = "landscape"
ws3.page_setup.paperSize = 9  # A4
ws3.page_setup.fitToWidth = 1
ws3.page_setup.fitToHeight = 0
ws3.sheet_properties.pageSetUpPr.fitToPage = True

wb.save("GB-T 3103.3-2000 平垫圈 检验项目清单.xlsx")
print("saved xlsx")
