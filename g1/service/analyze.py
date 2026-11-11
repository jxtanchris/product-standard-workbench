# -*- coding: utf-8 -*-
"""标准 → 检项候选：条款切分 + 检项识别（规则）。

产出的是“候选”，供人工在界面上勾选、改名、调类别；
不追求一步到位，追求每条都能回溯到页码与原文。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

CJK = r"[\u4e00-\u9fa5]"

# 类别关键词，顺序即优先级
CATEGORIES: list[tuple[str, list[str]]] = [
    ("形位", ["形位", "平面度", "同轴度", "平行度", "垂直度", "圆度", "圆柱度",
              "位置度", "跳动", "轮廓度", "对称度", "不均匀度", "圆跳动", "全跳动"]),
    ("性能", ["性能", "强度", "硬度", "抗拉", "屈服", "扭矩", "盐雾", "疲劳", "冲击",
              "延伸", "保证载荷", "脱碳", "再回火"]),
    ("表面", ["表面", "外观", "镀层", "涂层", "缺陷", "锈", "毛刺", "色泽", "粗糙度"]),
    ("标记", ["标记", "标志", "包装", "标识", "标签", "随附"]),
    ("尺寸", ["公差", "偏差", "尺寸", "直径", "厚度", "高度", "宽度", "长度",
              "外径", "内径", "倒角", "通孔", "螺纹", "螺距", "圆角"]),
]

CLAUSE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[\s　]*(.+)$")
TRAIL_NOISE = re.compile(r"[A-Za-z0-9\.\s]{1,}$")
NUMERIC_HINT = re.compile(r"[0-9０-９]|≤|≥|＜|＞|<|>|±|～|~|IT\d|H\d{1,2}|h\d{1,2}")
TABLE_HINT = re.compile(r"表\s?[A-Z]?\.?\d+")
# 这些章节不是检项，直接跳过
SKIP_TITLES = ("范围", "引用标准", "规范性引用文件", "术语", "定义", "符号", "前言",
               "附录", "总则", "概述", "引用文件")


@dataclass
class Candidate:
    id: str
    clause: str
    title: str
    category: str = "其他"
    measurable: bool = True
    score: float = 0.0
    page: int = 0
    evidence: str = ""
    table_ref: str = ""
    selected: bool = True
    method: str = ""          # 由人补充
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _clause_of(line: str) -> tuple[str, str] | None:
    m = CLAUSE_RE.match(line.strip())
    if not m:
        return None
    num, rest = m.group(1), m.group(2).strip()
    if not re.search(CJK, rest):
        return None
    if re.match(r"^[\d\s~～\-—±\.]", rest):      # 1.5mm、2 个 之类的数值行
        return None
    if not re.match(CJK, rest):                     # 条款号后必须紧跟汉字
        return None
    if int(num.split(".")[0]) > 30:
        return None
    return num, rest


def _clean_title(rest: str, limit: int = 30) -> str:
    t = re.sub(r"\s+", "", rest)
    t = TRAIL_NOISE.sub("", t)
    if len(re.findall(CJK, t)) < 2:
        return ""
    return t[:limit]


def _categorize(text: str) -> tuple[str, int]:
    for cat, words in CATEGORIES:
        for w in words:
            if w in text:
                return cat, 1
    return "其他", 0


def _looks_clause_number(num: str) -> bool:
    parts = [int(p) for p in num.split(".")]
    if len(parts) == 1:
        return parts[0] <= 20
    return True


def parse(pages: list[dict], min_score: float = 0.35) -> list[Candidate]:
    """条款切分 + 检项识别。pages 为 [{"page":1,"lines":[...]}]"""
    # 1) 先压平成 (page, line)
    flat: list[tuple[int, str]] = []
    for p in pages:
        for ln in p.get("lines", []):
            ln = ln.strip()
            if ln:
                flat.append((int(p.get("page", 0)), ln))

    # 2) 切条款
    heads: list[tuple[int, int, str, str]] = []   # (index, page, clause, rest)
    for i, (page, ln) in enumerate(flat):
        got = _clause_of(ln)
        if got and _looks_clause_number(got[0]):
            heads.append((i, page, got[0], got[1]))

    out: list[Candidate] = []
    seen: set[str] = set()
    for k, (idx, page, num, rest) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(flat)
        body = [flat[j][1] for j in range(idx, min(end, idx + 5))]
        evidence = " ".join(body)[:160]
        title = _clean_title(rest)
        if not title:
            continue
        if any(title.startswith(k) for k in SKIP_TITLES):
            continue
        if num in seen:
            continue
        seen.add(num)

        cat, hit = _categorize(title + " " + evidence)
        numeric = bool(NUMERIC_HINT.search(evidence))
        tbl = TABLE_HINT.search(evidence)
        depth = len(num.split("."))

        score = 0.2 + 0.4 * hit + 0.2 * int(numeric) + 0.2 * int(depth >= 2) \
            + 0.1 * int(bool(tbl))
        if cat == "其他" and not numeric:
            score -= 0.15
        score = round(min(1.0, max(0.0, score)), 2)

        out.append(Candidate(
            id=f"c{len(out) + 1:03d}", clause=num, title=title, category=cat,
            measurable=numeric or cat in ("尺寸", "形位", "性能"),
            score=score, page=page, evidence=evidence,
            table_ref=tbl.group(0) if tbl else "",
            selected=score >= min_score,
        ))

    out.sort(key=lambda c: [int(x) for x in c.clause.split(".")])
    return out


# 规格参数候选：命中关键词才建议，代码统一 *_nom / 枚举
PARAM_RULES: list[tuple[str, str, str, str, str, list[str] | None]] = [
    (r"螺纹公称直径|公称直径", "d_nom", "公称直径 d", "number", "mm", None),
    (r"公称厚度|厚度", "h_nom", "公称厚度 h", "number", "mm", None),
    (r"公称长度|长度范围", "l_nom", "公称长度 L", "number", "mm", None),
    (r"螺距", "pitch", "螺距 P", "number", "mm", None),
    (r"产品等级|等级", "grade", "产品等级", "enum", "", ["A", "B", "C"]),
    (r"不锈钢", "material", "材料类型", "enum", "", ["非不锈钢", "不锈钢"]),
    (r"性能等级", "property_class", "性能等级", "enum", "", ["4.8", "8.8", "10.9"]),
    (r"表面处理|镀层", "coating", "表面处理", "enum", "", ["无", "镀锌", "其他"]),
]


def suggest_params(pages: list[dict], limit: int = 6) -> list[dict]:
    text = " ".join(ln for p in pages for ln in p.get("lines", []))
    out, seen = [], set()
    for pat, code, name, typ, unit, options in PARAM_RULES:
        if re.search(pat, text) and code not in seen:
            seen.add(code)
            out.append({"code": code, "name": name, "type": typ, "unit": unit,
                        "required": typ == "number" or code in ("grade",),
                        "options": options or [], "default": (options or [None])[0],
                        "min": None, "max": None, "help": ""})
        if len(out) >= limit:
            break
    return out


def summarize(cands: list[Candidate]) -> dict:
    by_cat: dict[str, int] = {}
    for c in cands:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1
    return {
        "total": len(cands),
        "selected": sum(1 for c in cands if c.selected),
        "measurable": sum(1 for c in cands if c.measurable),
        "by_category": by_cat,
    }
