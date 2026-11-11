# -*- coding: utf-8 -*-
"""把一个标准的完整数据导出成 Excel（一个标准一个工作簿，六张表）。

    .venv/bin/python g1/service/tools/export_standard.py gb3103-3 [out.xlsx]

导出的内容与库里一一对应：
  概况 / 参数 / 检项 / 限值表 / 维度 / 限值行
JSON 字段（param_json、item_json、key_json、values_json）都展开成人能读的表格。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

import db  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(name="微软雅黑", size=9.5, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
LABEL_FONT = Font(name="微软雅黑", size=9, bold=True, color="404040")
BODY = Font(name="微软雅黑", size=9)
MONO = Font(name="Consolas", size=9)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="top")
BAND = PatternFill("solid", fgColor="EAF1F8")


def sheet(wb, name, title, headers, widths, rows, center_cols=(), freeze="A4"):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    n = len(headers)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    c = ws.cell(row=1, column=1, value=title)
    c.font = TITLE_FONT
    c.alignment = Alignment(vertical="center", horizontal="left")
    ws.row_dimensions[1].height = 26

    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n)
    c = ws.cell(row=2, column=1, value=f"共 {len(rows)} 行　·　导出于 {time.strftime('%Y-%m-%d %H:%M')}")
    c.font = LABEL_FONT
    ws.row_dimensions[2].height = 18

    for j, h in enumerate(headers, start=1):
        c = ws.cell(row=3, column=j, value=h)
        c.fill, c.font, c.border = HEAD_FILL, HEAD_FONT, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[3].height = 36

    for i, row in enumerate(rows):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=4 + i, column=j, value=v)
            c.font, c.border = BODY, BORDER
            c.alignment = CENTER if j in center_cols else WRAP
            if i % 2 == 1:
                c.fill = BAND
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w

    for i, row in enumerate(rows):
        lines = 1
        for j, v in enumerate(row, start=1):
            if v in (None, ""):
                continue
            cap = max(6.0, widths[j - 1] * 1.05)
            units = sum(1.85 if ord(ch) > 127 else 1.0 for ch in str(v))
            lines = max(lines, int(units // cap) + 1)
        ws.row_dimensions[4 + i].height = max(18, min(120, lines * 13 + 5))

    ws.freeze_panes = freeze
    return ws


def fmt_range(v) -> str:
    if isinstance(v, list) and len(v) == 2:
        return f"({v[0]}, {v[1]}]"
    return str(v)


def main() -> int:
    std_id = sys.argv[1] if len(sys.argv) > 1 else "gb3103-3"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"{std_id}-full.xlsx")

    conn = db.connect()
    s = conn.execute("SELECT * FROM standard WHERE id=?", (std_id,)).fetchone()
    if not s:
        print(f"没有标准 {std_id}")
        return 1
    params = json.loads(s["param_json"] or "[]")
    items = json.loads(s["item_json"] or "[]")
    limits = json.loads(s["limits_json"] or "{}")
    source = json.loads(s["source_json"] or "{}")

    tables = list(conn.execute("SELECT * FROM limit_table WHERE std_id=? ORDER BY id", (std_id,)))
    dims, rows = {}, []
    for t in tables:
        dims[t["id"]] = list(conn.execute(
            "SELECT * FROM limit_dim WHERE table_id=? ORDER BY seq", (t["id"],)))
        rows.extend(list(conn.execute(
            "SELECT * FROM limit_row WHERE table_id=? ORDER BY id", (t["id"],))))

    wb = Workbook()
    wb.remove(wb.active)

    # ---------- 概况 ----------
    info = [
        ("标准标识 id", s["id"]),
        ("标准号 code", s["code"]),
        ("名称 title", s["title"]),
        ("分类 category", s["category"]),
        ("适用范围 scope", s["scope"]),
        ("备注 note", s["note"]),
        ("来源标记 custom", "上传分析发布" if s["custom"] else "灌库/内置"),
        ("入库时间", time.strftime("%Y-%m-%d %H:%M", time.localtime(s["created_at"] or 0))),
        ("规格参数", f"{len(params)} 个：" + "、".join(p["code"] for p in params)),
        ("检项", f"{len(items)} 项"),
        ("限值表", f"{len(tables)} 张 / {sum(len(v) for v in dims.values())} 个维度 / {len(rows)} 行"),
        ("规则式限值 limits_json", json.dumps(limits, ensure_ascii=False) if limits else "（未使用，全部走多维限值表）"),
        ("原件 job_id", source.get("job_id", "—")),
        ("原件文件", source.get("filename", "—")),
        ("原件大小", f"{source.get('size', 0):,} 字节" if source.get("size") else "—"),
        ("原件 sha256", source.get("sha256", "—")),
    ]
    ws = sheet(wb, "概况", f"{s['code']}　{s['title']}　数据导出", ["项目", "内容"], [22, 110],
               info, center_cols=(1,), freeze="A4")
    for r in range(4, 4 + len(info)):
        ws.cell(row=r, column=1).font = LABEL_FONT

    # ---------- 参数 ----------
    sheet(wb, "参数", "规格参数（决定检验卡的表单）",
          ["序号", "参数代码", "名称", "类型", "单位", "必填", "可选值", "默认值", "最小", "最大", "说明"],
          [5, 14, 22, 9, 7, 6, 26, 10, 7, 7, 40],
          [[i + 1, p["code"], p.get("name", ""), p.get("type", ""), p.get("unit", ""),
            "是" if p.get("required", True) else "否",
            "、".join(p.get("options") or []) or "—",
            p.get("default") if p.get("default") is not None else "—",
            p.get("min") if p.get("min") is not None else "—",
            p.get("max") if p.get("max") is not None else "—",
            p.get("help", "")]
           for i, p in enumerate(params)],
          center_cols=(1, 2, 4, 5, 6, 8, 9, 10))

    # ---------- 检项 ----------
    sheet(wb, "检项", "检项全文（标准里有哪 8 个检查项）",
          ["序号", "检项 id", "条款", "原件页码", "检查项目", "符号", "类别", "限值表",
           "实测键", "检查方法", "测量部位", "量具 / 设备", "测点分布", "实测说明", "依赖参数"],
          [5, 9, 8, 9, 18, 8, 7, 9, 11, 44, 34, 24, 16, 18, 14],
          [[i + 1, it["id"], it.get("clause", ""), it.get("page") or "—",
            it.get("name", ""), it.get("symbol", ""), it.get("kind", ""),
            it.get("table", ""), it.get("measured_key", ""),
            it.get("method") or "—", it.get("position") or "—", it.get("gauge") or "—",
            it.get("points") or "—", it.get("measured_hint") or "—",
            "、".join(it.get("requires") or []) or "—"]
           for i, it in enumerate(items)],
          center_cols=(1, 2, 3, 4, 6, 7, 8, 9))

    # ---------- 限值表 ----------
    trows = []
    for t in tables:
        d = dims[t["id"]]
        trows.append([
            t["local_id"], t["name"], t["item_code"],
            " × ".join(x["code"] for x in d) or "（无维度）",
            len(d), len(conn.execute("SELECT 1 FROM limit_row WHERE table_id=?", (t["id"],)).fetchall()),
            t["value_form"], t["nominal_param"] or "—", t["unit"],
        ])
    sheet(wb, "限值表", "限值表（多维查询表的表头）",
          ["表号 local_id", "表名", "服务检项", "维度", "维度数", "行数", "值类型", "叠加公称参数", "单位"],
          [12, 40, 10, 40, 7, 7, 11, 14, 7],
          trows, center_cols=(1, 3, 5, 6, 7, 8, 9))

    # ---------- 维度 ----------
    drows = []
    for t in tables:
        for d in dims[t["id"]]:
            vals = json.loads(d["values_json"] or "[]")
            if d["kind"] == "range":
                shown = "、".join(fmt_range(v) for v in vals) if vals else "（由行反推）"
            else:
                shown = "、".join(str(v) for v in vals) if vals else "（由行反推）"
            drows.append([t["local_id"], d["seq"], d["code"],
                          "枚举" if d["kind"] == "enum" else "区间（左开右闭）",
                          len(vals), shown])
    sheet(wb, "维度", "限值表的维度（每张表的自变量）",
          ["表号", "序号", "参数代码", "类型", "取值个数", "取值"],
          [12, 6, 14, 16, 9, 80],
          drows, center_cols=(1, 2, 3, 4, 5))

    # ---------- 限值行 ----------
    code_of = {t["id"]: t["local_id"] for t in tables}
    kinds = {t["id"]: {d["code"]: d["kind"] for d in dims[t["id"]]} for t in tables}
    lrows = []
    for r in rows:
        key = json.loads(r["key_json"] or "{}")
        kind = kinds.get(r["table_id"], {})
        desc = "；".join(
            f"{k}={fmt_range(val) if isinstance(val, list) else val}"
            for k, val in key.items())
        lrows.append([
            code_of.get(r["table_id"], ""), desc,
            r["lower"] if r["lower"] is not None else "",
            r["upper"] if r["upper"] is not None else "",
            r["lower_expr"] or "", r["upper_expr"] or "",
            "是" if r["na"] else "", r["note"] or "",
        ])
    ws = sheet(wb, "限值行", "限值行（维度组合 → 限值，共 143 行）",
               ["表号", "维度组合", "下限", "上限", "下限表达式", "上限表达式", "不要求", "说明"],
               [10, 56, 10, 10, 16, 16, 8, 22],
               lrows, center_cols=(1, 3, 4, 7))
    for r in range(4, 4 + len(lrows)):
        for col in (5, 6):
            ws.cell(row=r, column=col).font = MONO

    wb.save(out)
    total = 1 + len(params) + len(items) + len(tables) + len(drows) + len(lrows)
    print(f"已导出 {out}（6 个工作表，{total} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
