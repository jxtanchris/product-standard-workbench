# -*- coding: utf-8 -*-
"""检验卡导出（xlsx），按当前规格把解析后的限值固化下来。"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
SUB_FONT = Font(name="微软雅黑", size=9, color="404040")
BODY_FONT = Font(name="微软雅黑", size=9)
BOLD_FONT = Font(name="微软雅黑", size=9, bold=True)
WARN_FONT = Font(name="微软雅黑", size=9, italic=True, color="7F0000")
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_L = Alignment(wrap_text=True, vertical="center", horizontal="left")
WRAP_C = Alignment(wrap_text=True, vertical="center", horizontal="center")
BAND = PatternFill("solid", fgColor="EAF1F8")


def build_card(std, ctx: dict, rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "检验卡"
    ws.sheet_view.showGridLines = False

    headers = ["序号", "检查项目", "符号", "条款", "要求（按当前规格解析）", "状态",
               "检查方法与测量部位", "量具 / 设备", "实测记录", "结论"]
    widths = [5, 15, 7, 7, 24, 10, 46, 22, 12, 9]

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    c = ws.cell(row=1, column=1, value=f"{std.code}《{std.title}》检验卡")
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    parts = []
    for p in std.params:
        v = ctx.get(p.code)
        if v is None:
            continue
        unit = f" {p.unit}" if p.unit else ""
        parts.append(f"{p.name}：{v}{unit}")
    spec_text = "　　".join(parts) + f"　　（{std.note}）"
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    c = ws.cell(row=2, column=1, value=spec_text)
    c.font = SUB_FONT
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 20

    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=j, value=h)
        c.fill = HDR_FILL
        c.font = HDR_FONT
        c.alignment = WRAP_C
        c.border = BORDER
    ws.row_dimensions[3].height = 30

    r = 4
    for i, row in enumerate(rows):
        vals = [i + 1, row["name"], row["symbol"], row["clause"], row["limit_text"],
                row["status_text"], f"{row['method']}\n部位：{row['position']}\n测点：{row['points']}",
                row["gauge"], "", ""]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = BOLD_FONT if j == 2 else BODY_FONT
            c.alignment = WRAP_C if j in (1, 3, 4, 6, 9, 10) else WRAP_L
            c.border = BORDER
            if i % 2 == 1:
                c.fill = BAND
        ws.row_dimensions[r].height = 62
        r += 1

    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
    c = ws.cell(row=r, column=1,
                value="说明：①“要求”栏由系统按当前规格查表解析得出，代号（H13、h14、2IT12 等）已展开为极限尺寸；"
                      "②标“不要求”者按标准不判定，不得判为不合格；③公差适用于镀前尺寸（GB/T 5267）；"
                      "④检查方法为标准未规定项，由企业检验规范确认后执行。")
    c.font = WARN_FONT
    c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
    ws.row_dimensions[r].height = 42

    r += 2
    ws.cell(row=r, column=1, value="检验员：____________").font = BODY_FONT
    ws.cell(row=r, column=5, value="审核：____________").font = BODY_FONT
    ws.cell(row=r, column=8, value="日期：____________").font = BODY_FONT

    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = 8
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "3:3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
