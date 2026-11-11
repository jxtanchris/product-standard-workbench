# -*- coding: utf-8 -*-
"""从 OCR 结果里还原表格网格。

思路：先按 y 聚行，再在行内按 x 找"贯穿的空白列"作为列分隔，
最后把每个词落到 (row, col) 格子里拼成文本。
不做语义判断——只给网格，列是什么含义由人来指定。
"""
from __future__ import annotations

import statistics
from typing import Any

MIN_COL_GAP = 26.0      # 列间空白最小宽度（px @300dpi）
MIN_ROWS = 3
MIN_WORDS = 8


def _rows_of(words: list[dict]) -> list[list[dict]]:
    if not words:
        return []
    h = statistics.median([w["h"] for w in words]) or 20
    tol = max(6.0, h * 0.55)
    ws = sorted(words, key=lambda w: w["y"] + w["h"] / 2)
    rows, cur, last = [], [], None
    for w in ws:
        cy = w["y"] + w["h"] / 2
        if last is None or abs(cy - last) <= tol:
            cur.append(w)
            last = cy if last is None else (last + cy) / 2
        else:
            rows.append(sorted(cur, key=lambda x: x["x"]))
            cur, last = [w], cy
    if cur:
        rows.append(sorted(cur, key=lambda x: x["x"]))
    return rows


def _columns(rows: list[list[dict]], lo: float, hi: float) -> list[tuple[float, float]]:
    """把 [lo,hi] 按"整列空白"切开。"""
    width = int(hi - lo) + 1
    cover = [0] * max(width, 1)
    for row in rows:
        for w in row:
            a = int(max(0, w["x"] - lo))
            b = int(min(width - 1, w["x"] + w["w"] - lo))
            for i in range(a, b + 1):
                cover[i] += 1
    cuts, run = [], 0
    for i, c in enumerate(cover):
        if c == 0:
            run += 1
        else:
            if run >= MIN_COL_GAP:
                cuts.append((i - run, i))
            run = 0
    bounds = [lo] + [lo + (a + b) / 2 for a, b in cuts] + [hi]
    cols = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a > 4:
            cols.append((a, b))
    return cols


def _cell(row: list[dict], a: float, b: float) -> str:
    got = [w for w in row if a <= (w["x"] + w["w"] / 2) < b]
    return " ".join(w["t"] for w in sorted(got, key=lambda w: w["x"])).strip()


def detect_page(page: dict) -> list[dict]:
    """返回该页检测到的表格：[{rows, cols, cells, bbox, text_hint}]"""
    words = page.get("words") or []
    if len(words) < MIN_WORDS:
        return []
    rows = _rows_of(words)
    out = []
    # 按"行块"滑窗：连续、且每行词数相近的算同一张表
    i = 0
    while i < len(rows):
        if len(rows[i]) < 2:
            i += 1
            continue
        j = i
        while j + 1 < len(rows) and len(rows[j + 1]) >= 2:
            j += 1
        block = rows[i:j + 1]
        i = j + 1
        if len(block) < MIN_ROWS:
            continue
        lo = min(w["x"] for r in block for w in r)
        hi = max(w["x"] + w["w"] for r in block for w in r)
        cols = _columns(block, lo, hi)
        if len(cols) < 2:
            continue
        cells = [[_cell(r, a, b) for a, b in cols] for r in block]
        filled = sum(1 for row in cells for c in row if c)
        if filled < len(block) * 2:
            continue
        out.append({
            "page": page.get("page"),
            "rows": len(block),
            "cols": len(cols),
            "grid": cells,
            "bbox": {"x": round(lo, 1), "y": round(block[0][0]["y"], 1),
                     "w": round(hi - lo, 1), "h": round(block[-1][-1]["y"] + block[-1][-1]["h"]
                                                       - block[0][0]["y"], 1)},
        })
    return out


def detect(pages: list[dict]) -> list[dict]:
    out = []
    for p in pages:
        out.extend(detect_page(p))
    return out
