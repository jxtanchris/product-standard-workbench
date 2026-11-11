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

# 章节性标题：整章讲的是"规矩"，不是"要量的东西"
SECTION_TITLES = (
    "范围", "规范性引用文件", "引用标准", "引用文件", "术语和定义", "术语", "定义",
    "符号", "代号", "代号与术语", "标记", "标记制度", "标记示例", "标记方法",
    "分类", "材料", "化学成分", "通则", "总则", "概述", "前言", "引言",
    "试验方法的适用性", "适用性", "适用范围", "订货", "包装", "运输", "贮存",
)
# 过程性小节：试验怎么做，不是检什么
PROCESS_TITLES = (
    "设备", "试验设备", "试验装置", "试验程序", "试验步骤", "试验方法", "方法",
    "试验结果", "结果", "结果判定", "判定规则", "供方的控制", "需方的控制",
    "交付", "试验报告", "仲裁", "复验", "标志", "仪器", "装置", "制备",
    "技术要求", "试样", "试件",
)
# 性能等级写法与条款号同形（4.6 / 8.8 / 10.9），要排除
GRADE_CLAUSES = {"3.6", "4.6", "4.8", "5.6", "5.8", "6.8", "8.8", "9.8", "10.9", "12.9"}
# 标题里必须有这些"可测量的东西"，或者是一个明确的检验动作
METRIC_WORDS = (
    "通孔", "外径", "内径", "孔径", "外圆", "圆角", "孔部", "杆部", "头部", "支承面",
    "直径", "长度", "厚度", "宽度", "高度", "间距", "螺纹", "螺距", "倒角",
    "角度", "公差", "尺寸", "同轴", "圆度", "平面度", "平行度", "垂直度", "位置度",
    "跳动", "直线度", "对称度", "强度", "硬度", "伸长率", "收缩率", "冲击", "载荷",
    "楔负载", "扭矩", "疲劳", "脱碳", "增碳", "回火", "氢脆", "镀层", "粗糙度",
    "保证应力", "应力", "性能", "缺陷", "裂纹", "毛刺", "间隙", "不均匀度",
)
ACTION_WORDS = ("试验", "检查", "检验", "测量", "测试", "判定")
# 上级标题像"一个检项"时，下级视为它的方法步骤
TESTISH_RE = re.compile(r"(试验|检查|检验|测定|性能|硬度|载荷|强度|扭矩|脱碳|增碳|回火|冲击|缺陷|镀层)")

CODE_STRIP = re.compile(r"(?:GB|ISO|DIN|EN|JIS|ASTM|ASME|SAE|BS|NF)(?:/[A-Z])?\s?"
                        r"\d+(?:\.\d+)*(?:\s*[-—:]\s*\d{4})?")
LIMIT_HINT = re.compile(r"[≤≥±]|\d\s*(?:mm|%|N|MPa|HRC|HV|HB)\b|～|~")


@dataclass
class Candidate:
    id: str
    clause: str
    title: str
    category: str = "其他"
    measurable: bool = True
    score: float = 0.0
    page: int = 0
    reason: str = ""
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


def _looks_table_ish(line: str) -> bool:
    """像表格/符号表的一行：短标记开头，或一多半是数字。"""
    toks = line.split()
    if len(toks) >= 4 and sum(1 for t in toks if re.fullmatch(r"[\d.,%±\-—]+", t)) >= 3:
        return True
    if re.match(r"^[A-Za-z]{1,3}\s", line) and len(line) < 40:
        return True
    return False


def _clean_body(flat: list[tuple[int, str]], idx: int, end: int, max_lines: int = 4) -> str:
    """条款后的正文，跳过紧邻的表格碎片（它们会把"有没有数值"判错）。"""
    out: list[str] = []
    for j in range(idx + 1, min(end, idx + 1 + max_lines * 3)):
        ln = flat[j][1]
        if _looks_table_ish(ln):
            continue
        out.append(ln)
        if len(out) >= max_lines:
            break
    return " ".join(out)


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
        clean_body = _clean_body(flat, idx, end)
        title = _clean_title(rest)
        if not title:
            continue
        if any(title.startswith(k) for k in SKIP_TITLES):
            continue
        if num in seen:
            continue
        seen.add(num)

        cat, hit = _categorize(title + " " + clean_body)
        # 去掉标准号再判"有没有数值"，否则 GB/T 5276 里的 5276 也算数值
        numeric = bool(LIMIT_HINT.search(CODE_STRIP.sub(" ", clean_body)))
        tbl = TABLE_HINT.search(clean_body)
        depth = len(num.split("."))

        score = 0.2 + 0.4 * hit + 0.2 * int(numeric) + 0.2 * int(depth >= 2) \
            + 0.1 * int(bool(tbl))
        if cat == "其他" and not numeric:
            score -= 0.15
        score = round(min(1.0, max(0.0, score)), 2)

        # −−− 最终判断：这条到底算不算"检查项目" −−−
        metric = [w for w in METRIC_WORDS if w in title]
        action = [w for w in ACTION_WORDS if w in title]
        reason = ""
        if num in GRADE_CLAUSES or title.startswith("级"):
            reason = "性能等级或断行碎片，不是条款"
        elif (title.endswith("/") or title.endswith("、")
              or re.search(r"[/=]", title) or "，" in title):
            reason = "表格单元格被当成条款"
        elif title in SECTION_TITLES or any(t in title for t in
                                            ("术语", "符号", "代号", "标记制度", "标记示例")):
            reason = "章节标题（讲规矩，不是要量的东西）"
        elif title in PROCESS_TITLES or any(t in title for t in
                                            ("试验结果", "交付", "供方的控制", "需方的控制",
                                             "技术要求", "仪器", "装置", "制备", "试件")):
            reason = "过程性小节（讲怎么做，不是检什么）"
        elif not (metric or action):
            reason = "标题里没有可测量的对象"
        selected = not reason

        out.append(Candidate(
            id=f"c{len(out) + 1:03d}", clause=num, title=title, category=cat,
            measurable=numeric or cat in ("尺寸", "形位", "性能"),
            score=score, page=page, evidence=evidence,
            table_ref=tbl.group(0) if tbl else "",
            selected=selected,
            reason=reason,
        ))

    # −−− 父子折叠：上级已经是检项时，下级是它的方法步骤，不再单列 −−−
    by_clause = {c.clause: c for c in out}

    def testish(title: str) -> bool:
        return bool(TESTISH_RE.search(title))

    def ancestor(cand: "Candidate") -> "Candidate | None":
        parts = cand.clause.split(".")
        while len(parts) > 1:
            parts = parts[:-1]
            p = by_clause.get(".".join(parts))
            if p and (p.selected or p.reason == ""):
                if testish(p.title):
                    return p
        return None

    for c in out:
        if not c.selected:
            continue
        a = ancestor(c)
        if a is not None:
            c.selected = False
            c.reason = f"属于 {a.clause}「{a.title}」的方法步骤"

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
