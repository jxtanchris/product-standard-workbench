# -*- coding: utf-8 -*-
"""把确认后的检项导出成检验卡（xlsx）。"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
SUB_FONT = Font(name="微软雅黑", size=9, color="404040")
BODY = Font(name="微软雅黑", size=9)
BOLD = Font(name="微软雅黑", size=9, bold=True)
NOTE = Font(name="微软雅黑", size=9, italic=True, color="7F0000")
THIN = Side(style="thin", color="A6A6A6")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_L = Alignment(wrap_text=True, vertical="center", horizontal="left")
WRAP_C = Alignment(wrap_text=True, vertical="center", horizontal="center")
BAND = PatternFill("solid", fgColor="EAF1F8")


def build(job, items: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "检验卡"
    ws.sheet_view.showGridLines = False

    headers = ["序号", "条款", "检查项目", "类别", "是否判定", "原文依据",
               "检查方法", "实测记录", "结论"]
    widths = [5, 9, 24, 8, 9, 46, 30, 12, 9]

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    c = ws.cell(row=1, column=1,
                value=f"{job.code or '（标准号待补）'}　{job.title or job.filename}　检验卡")
    c.font = TITLE_FONT
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    sub = (f"来源文件：{job.filename}　　页数：{job.pages}　　取文：{job.engine or '—'}"
           f"　　检项：{len(items)} 项　　生成：{__import__('time').strftime('%Y-%m-%d %H:%M')}")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(headers))
    c = ws.cell(row=2, column=1, value=sub)
    c.font = SUB_FONT
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[2].height = 18

    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=j, value=h)
        c.fill = HDR_FILL
        c.font = HDR_FONT
        c.alignment = WRAP_C
        c.border = BORDER
    ws.row_dimensions[3].height = 28

    r = 4
    for i, it in enumerate(items):
        vals = [i + 1, it.get("clause", ""), it.get("title", ""), it.get("category", ""),
                "是" if it.get("measurable") else "否（记录）",
                it.get("evidence", ""), it.get("method", ""), "", ""]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font = BOLD if j == 3 else BODY
            c.alignment = WRAP_C if j in (1, 2, 4, 5, 8, 9) else WRAP_L
            c.border = BORDER
            if i % 2 == 1:
                c.fill = BAND
        ws.row_dimensions[r].height = 44
        r += 1

    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(headers))
    c = ws.cell(row=r, column=1,
                value="说明：①检项与条款由系统从标准原文中识别，经人工确认后生成；"
                      "②“原文依据”为识别时所依据的条款文字，判定争议时以此回溯标准原文；"
                      "③“检查方法”栏需由检验规范补充，标准原文未规定的部分不得直接引用为标准条文。")
    c.font = NOTE
    c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="left")
    ws.row_dimensions[r].height = 40

    r += 2
    ws.cell(row=r, column=1, value="编制：____________").font = BODY
    ws.cell(row=r, column=4, value="审核：____________").font = BODY
    ws.cell(row=r, column=7, value="日期：____________").font = BODY

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
