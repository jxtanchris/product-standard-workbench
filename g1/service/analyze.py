# -*- coding: utf-8 -*-
"""标准 → 检项候选：条款切分 + 检项识别（规则）。

产出的是“候选”，供人工在界面上勾选、改名、调类别；
不追求一步到位，追求每条都能回溯到页码与原文。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CJK = r"[\u4e00-\u9fa5]"

RULES_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "rules_config.json"

# 系统出厂默认规则
DEFAULT_RULES: dict = {
    "metric_words": [
        "通孔", "外径", "内径", "孔径", "外圆", "圆角", "孔部", "杆部", "头部", "支承面",
        "直径", "长度", "厚度", "宽度", "高度", "间距", "螺纹", "螺距", "倒角",
        "角度", "公差", "尺寸", "同轴", "圆度", "平面度", "平行度", "垂直度", "位置度",
        "跳动", "直线度", "对称度", "强度", "硬度", "伸长率", "收缩率", "冲击", "载荷",
        "楔负载", "扭矩", "疲劳", "脱碳", "增碳", "回火", "氢脆", "镀层", "粗糙度",
        "保证应力", "应力", "性能", "缺陷", "裂纹", "毛刺", "间隙", "不均匀度",
    ],
    "action_words": [
        "试验", "检查", "检验", "测量", "测试", "判定"
    ],
    "section_titles": [
        "范围", "规范性引用文件", "引用标准", "引用文件", "术语和定义", "术语", "定义",
        "符号", "代号", "代号与术语", "标记", "标记制度", "标记示例", "标记方法",
        "分类", "材料", "化学成分", "通则", "总则", "概述", "前言", "引言",
        "试验方法的适用性", "适用性", "适用范围", "订货", "包装", "运输", "贮存",
    ],
    "process_titles": [
        "设备", "试验设备", "试验装置", "试验程序", "试验步骤", "试验方法", "方法",
        "试验结果", "结果", "结果判定", "判定规则", "供方的控制", "需方的控制",
        "交付", "试验报告", "仲裁", "复验", "标志", "仪器", "装置", "制备",
        "技术要求", "试样", "试件",
    ],
    "skip_titles": [
        "范围", "引用标准", "规范性引用文件", "术语", "定义", "符号", "前言",
        "附录", "总则", "概述", "引用文件"
    ],
    "grade_clauses": [
        "3.6", "4.6", "4.8", "5.6", "5.8", "6.8", "8.8", "9.8", "10.9", "12.9"
    ],
    "categories": [
        {"name": "形位", "words": ["形位", "平面度", "同轴度", "平行度", "垂直度", "圆度", "圆柱度", "位置度", "跳动", "轮廓度", "对称度", "不均匀度", "圆跳动", "全跳动"]},
        {"name": "性能", "words": ["性能", "强度", "硬度", "抗拉", "屈服", "扭矩", "盐雾", "疲劳", "冲击", "延伸", "保证载荷", "脱碳", "再回火"]},
        {"name": "表面", "words": ["表面", "外观", "镀层", "涂层", "缺陷", "锈", "毛刺", "色泽", "粗糙度"]},
        {"name": "标记", "words": ["标记", "标志", "包装", "标识", "标签", "随附"]},
        {"name": "尺寸", "words": ["公差", "偏差", "尺寸", "直径", "厚度", "高度", "宽度", "长度", "外径", "内径", "倒角", "通孔", "螺纹", "螺距", "圆角"]},
    ]
}


def get_rules() -> dict:
    """读取当前生效的识别规则；优先从 data/rules_config.json 读取，不存在时采用默认规则。"""
    if RULES_FILE.exists():
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in DEFAULT_RULES.items():
                    data.setdefault(k, v)
                return data
        except Exception:
            pass
    return {
        k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_RULES.items()
    }


def save_rules(rules: dict) -> dict:
    """持久化保存用户手工调整后的识别规则，即刻热生效。"""
    clean = {}
    clean["metric_words"] = [str(w).strip() for w in rules.get("metric_words", []) if str(w).strip()]
    clean["action_words"] = [str(w).strip() for w in rules.get("action_words", []) if str(w).strip()]
    clean["section_titles"] = [str(w).strip() for w in rules.get("section_titles", []) if str(w).strip()]
    clean["process_titles"] = [str(w).strip() for w in rules.get("process_titles", []) if str(w).strip()]
    clean["skip_titles"] = [str(w).strip() for w in rules.get("skip_titles", []) if str(w).strip()]
    clean["grade_clauses"] = [str(w).strip() for w in rules.get("grade_clauses", []) if str(w).strip()]
    clean["categories"] = []
    for c in rules.get("categories", []):
        if isinstance(c, dict) and c.get("name"):
            words = [str(w).strip() for w in c.get("words", []) if str(w).strip()]
            clean["categories"].append({"name": str(c["name"]).strip(), "words": words})
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def reset_rules() -> dict:
    """一键恢复为系统出厂默认规则。"""
    return save_rules(DEFAULT_RULES)


# 兼容引用
CATEGORIES = [(c["name"], c["words"]) for c in DEFAULT_RULES["categories"]]
SKIP_TITLES = tuple(DEFAULT_RULES["skip_titles"])
SECTION_TITLES = tuple(DEFAULT_RULES["section_titles"])
PROCESS_TITLES = tuple(DEFAULT_RULES["process_titles"])
GRADE_CLAUSES = set(DEFAULT_RULES["grade_clauses"])
METRIC_WORDS = tuple(DEFAULT_RULES["metric_words"])
ACTION_WORDS = tuple(DEFAULT_RULES["action_words"])

CLAUSE_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})[\s　]*(.+)$")
TRAIL_NOISE = re.compile(r"[A-Za-z0-9\.\s]{1,}$")
NUMERIC_HINT = re.compile(r"[0-9０-９]|≤|≥|＜|＞|<|>|±|～|~|IT\d|H\d{1,2}|h\d{1,2}")
TABLE_HINT = re.compile(r"表\s?[A-Z]?\.?\d+")
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
    trace: list = field(default_factory=list)      # 判定过程，逐条给人看
    words: list = field(default_factory=list)      # 命中的关键词
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


def _categorize(text: str, categories: list[dict] | None = None) -> tuple[str, int]:
    cats = categories if categories is not None else get_rules().get("categories", [])
    for c in cats:
        cat_name = c["name"]
        for w in c.get("words", []):
            if w in text:
                return cat_name, 1
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
    rules = get_rules()
    metric_words = tuple(rules.get("metric_words", []))
    action_words = tuple(rules.get("action_words", []))
    section_titles = tuple(rules.get("section_titles", []))
    process_titles = tuple(rules.get("process_titles", []))
    skip_titles = tuple(rules.get("skip_titles", []))
    grade_clauses = set(rules.get("grade_clauses", []))
    categories = rules.get("categories", [])

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
        if any(title.startswith(k) for k in skip_titles):
            continue
        if num in seen:
            continue
        seen.add(num)

        cat, hit = _categorize(title + " " + clean_body, categories=categories)
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
        metric = [w for w in metric_words if w in title]
        action = [w for w in action_words if w in title]
        trace = [
            f"① 行首匹配条款号：{num}（后面紧跟汉字「{title[:6]}」）",
            f"② 标题：{title}",
            f"③ 类别：{cat}" + (f"（正文命中「{cat}」关键词）" if hit else "（没命中任何类别关键词）"),
            f"④ 正文含限值/符号：{'是' if numeric else '否'}（先剥掉 GB/T 5276 这类标准号再判断）",
            f"⑤ 提到表格：{tbl.group(0) if tbl else '没有'}　层级：{depth} 级　分数：{score}",
        ]
        if metric or action:
            trace.append(f"⑥ 标题含可测对象/检验动作：{'、'.join(metric + action)}")
        else:
            trace.append("⑥ 标题里没有可测对象，也没有检验动作")
        reason = ""
        if num in grade_clauses or title.startswith("级"):
            trace.append(f"⑦ 判为排除：{num} 是性能等级写法或断行碎片")
            reason = "性能等级或断行碎片，不是条款"
        elif (title.endswith("/") or title.endswith("、")
              or re.search(r"[/=]", title) or "，" in title):
            reason = "表格单元格被当成条款"
            trace.append("⑦ 判为排除：标题像表格单元格（带 / = ，或结尾是斜杠）")
        elif title in section_titles or any(t in title for t in
                                            ("术语", "符号", "代号", "标记制度", "标记示例")):
            reason = "章节标题（讲规矩，不是要量的东西）"
            trace.append("⑦ 判为排除：章节标题（范围/术语/标记/材料这类整章）")
        elif title in process_titles or any(t in title for t in
                                            ("试验结果", "交付", "供方的控制", "需方的控制",
                                             "技术要求", "仪器", "装置", "制备", "试件")):
            reason = "过程性小节（讲怎么做，不是检什么）"
            trace.append("⑦ 判为排除：过程性小节（设备/程序/试验结果/技术要求）")
        elif not (metric or action):
            reason = "标题里没有可测量的对象"
            trace.append("⑦ 判为排除：标题里没有可测量的对象")
        selected = not reason
        trace.append("⑧ 结论：" + ("算检查项目" if selected else "不算，" + reason))

        out.append(Candidate(
            id=f"c{len(out) + 1:03d}", clause=num, title=title, category=cat,
            measurable=numeric or cat in ("尺寸", "形位", "性能"),
            score=score, page=page, evidence=evidence,
            table_ref=tbl.group(0) if tbl else "",
            selected=selected,
            reason=reason,
            trace=trace,
            words=sorted(set(metric + action + [cat] if hit else metric + action)),
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
            c.trace.append(f"⑨ 上级 {a.clause}「{a.title}」已经是检项 → 本条折叠为它的方法步骤")

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
    """从正文猜规格参数，并记录是"哪一行、命中哪个词"猜出来的。"""
    lines = [(int(p.get("page", 0)), ln.strip()) for p in pages for ln in p.get("lines", []) if ln.strip()]
    out, seen = [], set()
    for pat, code, name, typ, unit, options in PARAM_RULES:
        if code in seen:
            continue
        hit = None
        for page, ln in lines:
            m = re.search(pat, ln)
            if m:
                hit = (page, ln, m.group(0))
                break
        if not hit:
            continue
        seen.add(code)
        page, ln, word = hit
        out.append({"code": code, "name": name, "type": typ, "unit": unit,
                    "required": typ == "number" or code in ("grade",),
                    "options": options or [], "default": (options or [None])[0],
                    "min": None, "max": None, "help": "",
                    "trace": [f"正文第 {page} 页命中「{word}」",
                              f"原文：{ln[:60]}",
                              f"规则：/{pat}/ → {code}"]})
        if len(out) >= limit:
            break
    return out


def rules_catalog() -> dict:
    """把判定规则原样吐出来，界面上照着调，并带上可配置结构。"""
    rules = get_rules()
    return {
        "configurable": rules,
        "items": {
            "一句话": "先按行首切条款，再用五条硬规则排除，最后看标题有没有可测对象。",
            "步骤": [
                "① 行首匹配 数字(.)数字，且后面紧跟汉字 → 当成一个条款",
                "② 取条款后面的正文当证据（跳过表格碎片行）",
                "③ 按关键词判类别（尺寸/形位/性能/表面/标记/其他）",
                "④ 计算分数：0.2 + 0.4*命中类别 + 0.2*有数值 + 0.2*层级≥2 + 0.1*提到表",
                "⑤ 五条硬规则排除：性能等级写法 / 表格单元格 / 章节标题 / 过程性小节 / 标题无可测对象",
                "⑥ 上级已经是检项时，下级折叠为它的方法步骤",
            ],
            "条款号正则": CLAUSE_RE.pattern,
            "章节标题": list(rules.get("section_titles", [])),
            "过程性小节": list(rules.get("process_titles", [])),
            "性能等级（与条款号同形）": sorted(rules.get("grade_clauses", [])),
            "可测对象词": list(rules.get("metric_words", [])),
            "检验动作词": list(rules.get("action_words", [])),
            "类别规则": rules.get("categories", []),
            "上级算检项的标题特征": TESTISH_RE.pattern,
            "数值判定": "先剥掉标准号，再看 " + LIMIT_HINT.pattern,
        },
        "params": [
            {"正则": pat, "code": code, "名称": name, "类型": typ,
             "可选值": options or [], "说明": "正文任一页命中即建议"}
            for pat, code, name, typ, unit, options in PARAM_RULES
        ],
        "tables": {
            "一句话": "OCR 只还原网格，谁当维度、谁当上下限，先按表头猜，再给人改。",
            "步骤": [
                "① 在前 3 行里找表头（命中关键词最多且 ≥2 个表头词的那行）",
                "② 表头含 上限/最大/max/公差 → 上限；含 下限/最小/min → 下限",
                "③ 表头含 性能等级/螺纹规格/公称直径/厚度/螺距/材料 → 对应维度参数",
                "④ 没表头线索时保守猜：数字列→上限，短文本且取值≤8 的最多 2 列→维度",
                "⑤ 表内分段：整列空白 / 表头混排(max 直径d) / 维度表头重复 → 拆成多张表",
                "⑥ 生成后先预览，逐行标问题（维度值可疑 / 缺下限 / 缺上限 / 下限>上限）",
            ],
        },
    }


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
