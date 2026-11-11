# -*- coding: utf-8 -*-
"""生成数据逻辑视图（SVG → PNG）。

    python3 docs/gen_erd.py
产物：docs/schema.png
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_HTML = ROOT / "docs" / ".erd.html"
OUT_PNG = ROOT / "docs" / "schema.png"

W = 1360
CARD_BG = "#ffffff"
CARD_BORDER = "#d5dee8"
HEAD_BG = "#1f4e79"
HEAD_FG = "#ffffff"
TXT = "#26313d"
MUTED = "#7b8794"
PK = "#b7791f"
FK = "#2f6fb0"
LINE = "#9fb0c2"

ENTITIES = {
    "standard": dict(
        x=30, y=70, w=330,
        title="standard", sub="标准", rows=[
            ("id", "TEXT", "PK", "标准标识（如 gb3103-3）"),
            ("code", "TEXT", "", "标准号，如 GB/T 3103.3—2000"),
            ("title", "TEXT", "", "标准名称"),
            ("category", "TEXT", "", "分类，如 紧固件/垫圈"),
            ("custom", "INT", "", "1 = 上传分析后发布"),
            ("param_json", "JSON", "", "规格参数数组（第二步表单）"),
            ("item_json", "JSON", "", "检项数组（含 table 引用）"),
            ("limits_json", "JSON", "", "规则式限值（上传发布用）"),
        ]),
    "limit_table": dict(
        x=470, y=70, w=340,
        title="limit_table", sub="限值表（多维查询表）", rows=[
            ("id", "INT", "PK", "代理键"),
            ("std_id", "TEXT", "FK", "→ standard.id（级联删）"),
            ("local_id", "TEXT", "UQ", "标准内的表 id，如 T-D1"),
            ("name", "TEXT", "", "表名"),
            ("value_form", "TEXT", "", "absolute / deviation"),
            ("nominal_param", "TEXT", "", "偏差型叠加哪个参数"),
            ("item_code", "TEXT", "FK", "服务的检项 id"),
            ("unit", "TEXT", "", "单位，默认 mm"),
        ]),
    "limit_dim": dict(
        x=930, y=70, w=390,
        title="limit_dim", sub="维度（表有几个自变量）", rows=[
            ("id", "INT", "PK", "代理键"),
            ("table_id", "INT", "FK", "→ limit_table.id（级联删）"),
            ("seq", "INT", "", "维度顺序"),
            ("code", "TEXT", "", "参数 code，如 h_nom"),
            ("kind", "TEXT", "", "enum 枚举 / range 区间"),
            ("values_json", "JSON", "", "取值：[\"A\",\"C\"] 或 [[0,4],[4,20]]"),
        ]),
    "standard_document": dict(
        x=30, y=0, w=330, title="standard_document", sub="标准 ↔ 原件（多对多）", rows=[
            ("std_id", "TEXT", "PK", "→ standard.id"),
            ("doc_id", "TEXT", "PK", "→ document.id"),
            ("created_at", "REAL", "", "挂载时间"),
        ]),
    "document": dict(
        x=30, y=470, w=330, title="document", sub="标准原件（PDF 存档）", rows=[
            ("id", "TEXT", "PK", "sha256，内容寻址"),
            ("job_id", "TEXT", "", "来自哪次上传"),
            ("filename", "TEXT", "", "原始文件名"),
            ("size", "INT", "", "字节数"),
            ("storage", "TEXT", "", "db：内容进库 / file：只存路径"),
            ("path", "TEXT", "", "storage=file 时用"),
            ("content", "BLOB", "", "≤20MB 的 PDF 原文"),
        ]),
    "limit_row": dict(
        x=930, w=390,
        title="limit_row", sub="限值行（维度组合 → 限值）", rows=[
            ("id", "INT", "PK", "代理键"),
            ("table_id", "INT", "FK", "→ limit_table.id（级联删）"),
            ("key_json", "JSON", "", "{\"grade\":\"A\",\"h_nom\":[0,4]}"),
            ("lower / upper", "REAL", "", "数值型限值"),
            ("lower_expr / upper_expr", "TEXT", "", "表达式型，优先于数值"),
            ("na", "INT", "", "1 = 标准明确不要求"),
            ("note", "TEXT", "", "备注，如 H13 @ (10,18]"),
        ]),
}

ROW_H = 26
HEAD_H = 46


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def card_h(e: dict) -> int:
    return HEAD_H + len(e["rows"]) * ROW_H + 14


def card(e: dict) -> str:
    x, y, w = e["x"], e["y"], e["w"]
    h = card_h(e)
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{CARD_BG}" '
        f'stroke="{CARD_BORDER}" stroke-width="1.5"/>',
        f'<path d="M{x} {y+10} a10 10 0 0 1 10 -10 h{w-20} a10 10 0 0 1 10 10 v{HEAD_H-10} h-{w} z" '
        f'fill="{HEAD_BG}"/>',
        f'<text x="{x+14}" y="{y+21}" fill="{HEAD_FG}" font-size="14" font-weight="600" '
        f'font-family="Menlo,monospace">{esc(e["title"])}</text>',
        f'<text x="{x+14}" y="{y+37}" fill="#cfe0f0" font-size="11.5">{esc(e["sub"])}</text>',
    ]
    ty = y + HEAD_H + 18
    for name, typ, mark, desc in e["rows"]:
        color = PK if mark == "PK" else (FK if mark in ("FK", "UQ") else TXT)
        parts.append(f'<text x="{x+14}" y="{ty}" fill="{color}" font-size="12" '
                     f'font-family="Menlo,monospace" font-weight="{"600" if mark else "400"}">'
                     f'{esc(name)}</text>')
        parts.append(f'<text x="{x+205}" y="{ty}" fill="{MUTED}" font-size="11">{esc(typ)}</text>')
        if mark:
            parts.append(f'<rect x="{x+14+len(name)*7.2+6}" y="{ty-11}" width="20" height="14" rx="3" '
                         f'fill="{color}" opacity="0.12"/>')
            parts.append(f'<text x="{x+18+len(name)*7.2+6}" y="{ty-1}" fill="{color}" '
                         f'font-size="9.5" font-weight="700">{mark}</text>')
        ty += ROW_H
    return "\n".join(parts)


def arrow(x1, y1, x2, y2, label, sub=""):
    mid = (x1 + x2) / 2
    return f'''
    <path d="M{x1} {y1} L{x2-9} {y2}" stroke="{LINE}" stroke-width="1.6" fill="none"/>
    <path d="M{x2-10} {y2-5} L{x2} {y2} L{x2-10} {y2+5} z" fill="{LINE}"/>
    <text x="{mid}" y="{y1-9}" text-anchor="middle" fill="{TXT}" font-size="11.5"
          font-weight="600">{esc(label)}</text>
    <text x="{mid}" y="{y1+16}" text-anchor="middle" fill="{MUTED}" font-size="10.5">{esc(sub)}</text>'''


def layout() -> int:
    """统一算一遍各卡的 y，返回画布高度。"""
    std, dim, row = ENTITIES["standard"], ENTITIES["limit_dim"], ENTITIES["limit_row"]
    row["y"] = dim["y"] + card_h(dim) + 40
    link, doc = ENTITIES["standard_document"], ENTITIES["document"]
    link["y"] = std["y"] + card_h(std) + 46
    doc["y"] = link["y"] + card_h(link) + 46
    return max(std["y"] + card_h(std), ENTITIES["limit_table"]["y"] + card_h(ENTITIES["limit_table"]),
               row["y"] + card_h(row), doc["y"] + card_h(doc)) + 110


def _up_arrow(lower: dict, upper: dict, label: str, sub: str, dx: int = 64) -> str:
    """下方卡片 → 上方卡片的竖直箭头（自带标注，避免压到标题）。"""
    x = lower["x"] + dx
    y_top = lower["y"] - 4
    y_bottom = upper["y"] + card_h(upper) + 4
    mid = (y_top + y_bottom) / 2
    return f'''
    <path d="M{x} {y_top} L{x} {y_bottom+9}" stroke="{LINE}" stroke-width="1.6" fill="none"/>
    <path d="M{x-5} {y_bottom+10} L{x} {y_bottom} L{x+5} {y_bottom+10} z" fill="{LINE}"/>
    <text x="{x+12}" y="{mid-4}" fill="{TXT}" font-size="11.5" font-weight="600">{label}</text>
    <text x="{x+12}" y="{mid+12}" fill="{MUTED}" font-size="10.5">{sub}</text>'''


def build() -> str:
    std = ENTITIES["standard"]
    lt = ENTITIES["limit_table"]
    dim = ENTITIES["limit_dim"]
    row = ENTITIES["limit_row"]
    H = layout()

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="-apple-system,PingFang SC,system-ui,sans-serif">',
        f'<rect width="{W}" height="{H}" fill="#f6f8fb"/>',
        f'<text x="30" y="34" fill="{TXT}" font-size="16" font-weight="700">'
        f'数据逻辑视图 · 产品标准分析工作台</text>',
        f'<text x="30" y="52" fill="{MUTED}" font-size="11.5">'
        f'6 张表；标准持有参数与检项（JSON），限值表按 标准 → 表 → 维度/行 三级展开，原件按 sha256 存档、可挂多个标准</text>',
        card(std), card(lt), card(dim), card(row),
        card(ENTITIES["standard_document"]), card(ENTITIES["document"]),
        arrow(std["x"] + std["w"], 190, lt["x"], 190, "1 : N", "limit_table.std_id"),
        arrow(lt["x"] + lt["w"], 140, dim["x"], 140, "1 : N", "limit_dim.table_id"),
        arrow(lt["x"] + lt["w"], 230, row["x"], row["y"] + 90, "1 : N", "limit_row.table_id"),
        _up_arrow(ENTITIES["standard_document"], std, "N : 1", "sd.std_id"),
        _up_arrow(ENTITIES["document"], ENTITIES["standard_document"], "1 : N", "sd.doc_id"),
        # 说明
        f'<text x="30" y="{H-72}" fill="{MUTED}" font-size="11.5">'
        f'· 级联：删 standard 删其 limit_table（连带维度/行）与 standard_document 关联，原件本身保留</text>',
        f'<text x="30" y="{H-52}" fill="{MUTED}" font-size="11.5">'
        f'· 唯一：UNIQUE(std_id, local_id)；standard_document 主键 (std_id, doc_id)</text>',
        f'<text x="30" y="{H-32}" fill="{MUTED}" font-size="11.5">'
        f'· 求值：按维度命中一行 → 取 lower/upper 或表达式 → deviation 时叠加 nominal_param</text>',
        "</svg>",
    ]
    return "\n".join(parts)


def main() -> int:
    svg = build()
    OUT_HTML.write_text(
        f"<html><meta charset='utf-8'><body style='margin:0'>{svg}</body></html>",
        encoding="utf-8")
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    profile = ROOT / ".build-cache" / "chrome-erd"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
                    "--disable-crash-reporter", "--disable-breakpad",
                    "--hide-scrollbars", "--force-device-scale-factor=2",
                    f"--user-data-dir={profile}",
                    f"--window-size={W},{layout()}",
                    f"--screenshot={OUT_PNG}", OUT_HTML.as_uri()],
                   check=True, capture_output=True, timeout=120)
    OUT_HTML.unlink(missing_ok=True)
    print("wrote", OUT_PNG, OUT_PNG.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
