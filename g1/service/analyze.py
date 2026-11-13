# -*- coding: utf-8 -*-
"""标准 → 检项候选：条款切分 + 检项识别（规则）。

产出的是“候选”，供人工在界面上勾选、改名、调类别；
不追求一步到位，追求每条都能回溯到页码与原文。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

CJK = r"[\u4e00-\u9fa5]"

RULES_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "rules_config.json"

# 系统出厂默认规则（覆盖标准分析 4 步向导全部识别规则）
DEFAULT_RULES: dict = {
    # ---------------- 第 1 步：检查项识别规则 ----------------
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
    ],
    "collapse_subclauses": True,

    # ---------------- 第 2 步：规格参数识别规则 ----------------
    "param_rules": [
        {"pattern": "螺纹公称直径|公称直径", "code": "d_nom", "name": "公称直径 d", "type": "number", "unit": "mm", "options": [], "required": True},
        {"pattern": "公称厚度|厚度", "code": "h_nom", "name": "公称厚度 h", "type": "number", "unit": "mm", "options": [], "required": True},
        {"pattern": "公称长度|长度范围", "code": "l_nom", "name": "公称长度 L", "type": "number", "unit": "mm", "options": [], "required": True},
        {"pattern": "螺距", "code": "pitch", "name": "螺距 P", "type": "number", "unit": "mm", "options": [], "required": False},
        {"pattern": "产品等级|等级", "code": "grade", "name": "产品等级", "type": "enum", "unit": "", "options": ["A", "B", "C"], "required": True},
        {"pattern": "不锈钢", "code": "material", "name": "材料类型", "type": "enum", "unit": "", "options": ["非不锈钢", "不锈钢"], "required": False},
        {"pattern": "性能等级", "code": "property_class", "name": "性能等级", "type": "enum", "unit": "", "options": ["4.8", "8.8", "10.9"], "required": True},
        {"pattern": "表面处理|镀层", "code": "coating", "name": "表面处理", "type": "enum", "unit": "", "options": ["无", "镀锌", "其他"], "required": False},
    ],
    "auto_import_class_params": True,

    # ---------------- 第 3 步：限值与表格拆解识别规则 ----------------
    "stat_qualifiers": [
        {"code": "Min", "name": "最小值 / 下限", "words": ["min", "minimum", "最小", "最小值", "下限", "最低", "下偏差"]},
        {"code": "Max", "name": "最大值 / 上限", "words": ["max", "maximum", "最大", "最大值", "上限", "最高", "上偏差"]},
        {"code": "Avg", "name": "平均值 / 均值", "words": ["avg", "average", "mean", "平均", "平均值", "均值", "算术平均", "算术平均值"]},
        {"code": "Nom", "name": "公称值 / 基准值", "words": ["nom", "nominal", "公称", "公称值", "标称", "标称值", "基准", "基准值"]},
        {"code": "Typ", "name": "典型值", "words": ["typ", "typical", "典型", "典型值"]},
        {"code": "Ref", "name": "参考值", "words": ["ref", "reference", "参考", "参考值"]},
        {"code": "Std", "name": "标准值", "words": ["std", "standard", "标准", "标准值"]},
        {"code": "Med", "name": "中位数", "words": ["med", "median", "中位", "中位数", "中值"]},
        {"code": "Dev", "name": "偏差 / 公差", "words": ["dev", "tol", "deviation", "tolerance", "偏差", "允差", "公差"]},
    ],
    "dim_hints": [
        {"pattern": "性能等级|强度等级|等级|grade", "code": "property_class", "name": "性能等级"},
        {"pattern": "螺纹规格|螺纹公称|公称直径|规格|直径|d\\b", "code": "d_nom", "name": "公称直径 d"},
        {"pattern": "厚度|板厚|h\\b", "code": "h_nom", "name": "公称厚度 h"},
        {"pattern": "长度|L\\b", "code": "l_nom", "name": "公称长度 L"},
        {"pattern": "螺距|pitch", "code": "pitch", "name": "螺距 P"},
        {"pattern": "材料|material|钢", "code": "material", "name": "材料类型"},
        {"pattern": "表面处理|镀层|涂层|coating", "code": "coating", "name": "表面处理"},
    ],
    "skip_table_keywords": [
        "引用标准", "规范性引用", "符号", "代号", "术语", "标记示例", "目次", "目录", "采样", "抽样"
    ],
    "composite_no_keywords": [
        "No.", "序号", "项目代号", "试验项目"
    ],
    "cross_matrix_keywords": [
        "机械性能", "化学成分", "性能等级", "强度等级"
    ],

    # ---------------- 第 4 步：检项与限值关联规则 ----------------
    "auto_bind_by_name": True,
    "auto_bind_by_table_ref": True,
    "auto_create_missing_item": True,
    "synonym_rules": [
        {"item_keyword": "抗拉强度", "table_aliases": ["Rm", "σb", "抗拉", "抗拉强度"]},
        {"item_keyword": "下屈服强度", "table_aliases": ["Rel", "ReL", "屈服", "下屈服强度", "规定非比例延伸强度"]},
        {"item_keyword": "维氏硬度", "table_aliases": ["HV", "维氏", "维氏硬度"]},
        {"item_keyword": "洛氏硬度", "table_aliases": ["HRC", "HRB", "洛氏", "洛氏硬度"]},
        {"item_keyword": "布氏硬度", "table_aliases": ["HB", "HBW", "布氏", "布氏硬度"]},
        {"item_keyword": "断后伸长率", "table_aliases": ["A", "δ", "伸长率", "延伸率", "断后伸长率"]},
        {"item_keyword": "断面收缩率", "table_aliases": ["Z", "ψ", "收缩率", "断面收缩率"]},
        {"item_keyword": "冲击吸收功", "table_aliases": ["KV", "KV2", "AKV", "冲击功", "冲击", "冲击吸收功"]},
        {"item_keyword": "保证载荷", "table_aliases": ["Sp", "保证应力", "保证载荷"]},
        {"item_keyword": "楔负载", "table_aliases": ["楔负载", "楔负载强度"]},
        {"item_keyword": "表面渗碳", "table_aliases": ["渗碳层", "表面渗碳层深度", "有效硬化层"]},
        {"item_keyword": "破坏扭矩", "table_aliases": ["破坏扭矩", "最小破坏扭矩", "拧断扭矩"]},
        {"item_keyword": "拧入扭矩", "table_aliases": ["拧入扭矩", "自攻扭矩"]},
    ],
}

STEP_RULE_KEYS: dict[str, list[str]] = {
    "step1_items": [
        "metric_words", "action_words", "section_titles", "process_titles",
        "skip_titles", "grade_clauses", "categories", "collapse_subclauses",
    ],
    "step2_params": [
        "param_rules", "auto_import_class_params",
    ],
    "step3_limits": [
        "stat_qualifiers", "dim_hints", "skip_table_keywords",
        "composite_no_keywords", "cross_matrix_keywords",
    ],
    "step4_links": [
        "auto_bind_by_name", "auto_bind_by_table_ref",
        "auto_create_missing_item", "synonym_rules",
    ],
}


def _sanitize_rules_dict(rules: dict, base: dict | None = None) -> dict:
    """清洗并补齐 4 步识别规则字典。"""
    fallback = copy.deepcopy(base if base is not None else DEFAULT_RULES)
    clean = copy.deepcopy(fallback)
    if not isinstance(rules, dict):
        return clean

    for str_list_key in (
        "metric_words", "action_words", "section_titles", "process_titles",
        "skip_titles", "grade_clauses", "skip_table_keywords",
        "composite_no_keywords", "cross_matrix_keywords",
    ):
        if str_list_key in rules and isinstance(rules[str_list_key], list):
            clean[str_list_key] = [str(w).strip() for w in rules[str_list_key] if str(w).strip()]

    for bool_key in (
        "collapse_subclauses", "auto_import_class_params",
        "auto_bind_by_name", "auto_bind_by_table_ref", "auto_create_missing_item",
    ):
        if bool_key in rules:
            clean[bool_key] = bool(rules[bool_key])

    if "categories" in rules and isinstance(rules["categories"], list):
        cats = []
        for c in rules["categories"]:
            if isinstance(c, dict) and str(c.get("name", "")).strip():
                words = [str(w).strip() for w in c.get("words", []) if str(w).strip()]
                cats.append({"name": str(c["name"]).strip(), "words": words})
        if cats:
            clean["categories"] = cats

    if "param_rules" in rules and isinstance(rules["param_rules"], list):
        pr_list = []
        for pr in rules["param_rules"]:
            if not isinstance(pr, dict):
                continue
            pat = str(pr.get("pattern") or pr.get("正则") or "").strip()
            code = str(pr.get("code") or "").strip()
            if not pat or not code:
                continue
            opts = pr.get("options") if "options" in pr else pr.get("可选值", [])
            if isinstance(opts, str):
                opts = [x.strip() for x in re.split(r"[,，、\s]+", opts) if x.strip()]
            elif isinstance(opts, list):
                opts = [str(x).strip() for x in opts if str(x).strip()]
            else:
                opts = []
            typ = str(pr.get("type") or pr.get("类型") or "number").strip()
            if typ not in ("number", "enum"):
                typ = "enum" if opts else "number"
            pr_list.append({
                "pattern": pat,
                "code": code,
                "name": str(pr.get("name") or pr.get("名称") or code).strip(),
                "type": typ,
                "unit": str(pr.get("unit") or pr.get("单位") or "").strip(),
                "options": opts,
                "required": bool(pr.get("required", typ == "number")),
            })
        clean["param_rules"] = pr_list

    if "stat_qualifiers" in rules and isinstance(rules["stat_qualifiers"], list):
        sq_list = []
        for sq in rules["stat_qualifiers"]:
            if not isinstance(sq, dict):
                continue
            code = str(sq.get("code") or "").strip()
            if not code:
                continue
            words = sq.get("words", [])
            if isinstance(words, str):
                words = [x.strip() for x in re.split(r"[,，、\s]+", words) if x.strip()]
            elif isinstance(words, list):
                words = [str(x).strip() for x in words if str(x).strip()]
            else:
                words = []
            sq_list.append({
                "code": code,
                "name": str(sq.get("name") or code).strip(),
                "words": words,
            })
        if sq_list:
            clean["stat_qualifiers"] = sq_list

    if "dim_hints" in rules and isinstance(rules["dim_hints"], list):
        dh_list = []
        for dh in rules["dim_hints"]:
            if not isinstance(dh, dict):
                continue
            pat = str(dh.get("pattern") or "").strip()
            code = str(dh.get("code") or "").strip()
            if not pat or not code:
                continue
            dh_list.append({
                "pattern": pat,
                "code": code,
                "name": str(dh.get("name") or code).strip(),
            })
        if dh_list:
            clean["dim_hints"] = dh_list

    if "synonym_rules" in rules and isinstance(rules["synonym_rules"], list):
        sr_list = []
        for sr in rules["synonym_rules"]:
            if not isinstance(sr, dict):
                continue
            kw = str(sr.get("item_keyword") or "").strip()
            if not kw:
                continue
            aliases = sr.get("table_aliases", [])
            if isinstance(aliases, str):
                aliases = [x.strip() for x in re.split(r"[,，、\s]+", aliases) if x.strip()]
            elif isinstance(aliases, list):
                aliases = [str(x).strip() for x in aliases if str(x).strip()]
            else:
                aliases = []
            sr_list.append({
                "item_keyword": kw,
                "table_aliases": aliases,
            })
        clean["synonym_rules"] = sr_list

    return clean


def get_rules(override: dict | None = None) -> dict:
    """读取当前生效的识别规则；优先从 data/rules_config.json 读取，并可叠加单作业 override。"""
    base = copy.deepcopy(DEFAULT_RULES)
    if RULES_FILE.exists():
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _sanitize_rules_dict(data, DEFAULT_RULES)
        except Exception:
            pass
    if override and isinstance(override, dict):
        return _sanitize_rules_dict(override, base)
    return base


def save_rules(rules: dict) -> dict:
    """持久化保存用户手工调整后的识别规则，即刻热生效。"""
    current = get_rules()
    clean = _sanitize_rules_dict(rules, current)
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return clean


def reset_rules(step_key: str | None = None) -> dict:
    """恢复系统出厂默认规则；若指定 step_key（如 step1_items），则仅恢复该步骤规则。"""
    if step_key and step_key in STEP_RULE_KEYS:
        cur = get_rules()
        for k in STEP_RULE_KEYS[step_key]:
            cur[k] = copy.deepcopy(DEFAULT_RULES[k])
        return save_rules(cur)
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


def parse(pages: list[dict], min_score: float = 0.35, rules_override: dict | None = None) -> list[Candidate]:
    """条款切分 + 检项识别。pages 为 [{"page":1,"lines":[...]}]"""
    rules = get_rules(rules_override)
    metric_words = tuple(rules.get("metric_words", []))
    action_words = tuple(rules.get("action_words", []))
    section_titles = tuple(rules.get("section_titles", []))
    process_titles = tuple(rules.get("process_titles", []))
    skip_titles = tuple(rules.get("skip_titles", []))
    grade_clauses = set(rules.get("grade_clauses", []))
    categories = rules.get("categories", [])
    collapse_subclauses = bool(rules.get("collapse_subclauses", True))

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
    if collapse_subclauses:
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
    (r["pattern"], r["code"], r["name"], r["type"], r["unit"], r["options"] or None)
    for r in DEFAULT_RULES["param_rules"]
]


def suggest_params(pages: list[dict], limit: int = 12, rules_override: dict | None = None) -> list[dict]:
    """从正文猜规格参数，并记录是"哪一行、命中哪个词"猜出来的。"""
    rules = get_rules(rules_override)
    param_rules = rules.get("param_rules") or DEFAULT_RULES["param_rules"]
    lines = [(int(p.get("page", 0)), ln.strip()) for p in pages for ln in p.get("lines", []) if ln.strip()]
    out, seen = [], set()
    for pr in param_rules:
        pat = pr.get("pattern") or pr.get("正则") or ""
        code = pr.get("code") or ""
        name = pr.get("name") or pr.get("名称") or code
        typ = pr.get("type") or pr.get("类型") or "number"
        unit = pr.get("unit") or pr.get("单位") or ""
        options = pr.get("options") if "options" in pr else (pr.get("可选值") or [])
        required = bool(pr.get("required", typ == "number" or code in ("grade",)))
        if not pat or not code or code in seen:
            continue
        hit = None
        for page, ln in lines:
            try:
                m = re.search(pat, ln)
            except re.error:
                m = (pat in ln) and type("_M", (), {"group": lambda self, _: pat})()
            if m:
                hit = (page, ln, m.group(0))
                break
        if not hit:
            continue
        seen.add(code)
        page, ln, word = hit
        out.append({"code": code, "name": name, "type": typ, "unit": unit,
                    "required": required,
                    "options": options or [], "default": (options or [None])[0],
                    "min": None, "max": None, "help": "",
                    "trace": [f"正文第 {page} 页命中「{word}」",
                              f"原文：{ln[:60]}",
                              f"规则：/{pat}/ → {code}"]})
        if len(out) >= limit:
            break
    return out


def auto_link_items_and_tables(
    items: list[dict],
    table_drafts: list[dict],
    existing_links: dict | None = None,
    rules_override: dict | None = None,
) -> dict:
    """按第 4 步识别规则（名称匹配、表号引用、同义词字典）自动建立 检项 -> 限值表 的关联映射。"""
    rules = get_rules(rules_override)
    by_name = bool(rules.get("auto_bind_by_name", True))
    by_tref = bool(rules.get("auto_bind_by_table_ref", True))
    synonyms = rules.get("synonym_rules") or []

    links = dict(existing_links or {})
    if not items or not table_drafts:
        return links

    def _strip_stat(nm: str) -> str:
        return re.sub(r"(?:Min|Max|Avg|Nom|Typ|Ref|Std|Med|Dev)$", "", (nm or "").strip(), flags=re.IGNORECASE).strip()

    for it in items:
        if not it.get("selected", True):
            continue
        iid = it.get("id") or ""
        if not iid:
            continue
        it_title = (it.get("title") or "").strip()
        it_base = _strip_stat(it_title)
        tref = (it.get("table_ref") or "").strip()

        # 0) 若已有绑定且表存在，保留
        if links.get(iid) and links[iid] != "rule" and any(d.get("id") == links[iid] for d in table_drafts):
            continue

        matched_tid = ""
        # 1) 直接通过 item_code 匹配
        for d in table_drafts:
            if d.get("item_code") == iid:
                matched_tid = d.get("id") or ""
                break

        # 2) 按名称匹配
        if not matched_tid and by_name and it_title:
            for d in table_drafts:
                d_name = (d.get("name") or "").strip()
                d_short = d_name.split(" - ")[-1].strip() if " - " in d_name else d_name
                if d_short == it_title or _strip_stat(d_short) == it_base:
                    matched_tid = d.get("id") or ""
                    break
                if it_base and len(it_base) >= 2 and (it_base in d_short or _strip_stat(d_short) in it_base):
                    matched_tid = d.get("id") or ""
                    break

        # 3) 按同义词字典匹配
        if not matched_tid and synonyms and it_title:
            for sr in synonyms:
                kw = (sr.get("item_keyword") or "").strip()
                aliases = [str(a).strip() for a in (sr.get("table_aliases") or []) if str(a).strip()]
                if kw and (kw in it_title or it_base in kw):
                    for d in table_drafts:
                        d_name = (d.get("name") or "").strip()
                        d_short = _strip_stat(d_name.split(" - ")[-1].strip() if " - " in d_name else d_name)
                        if any(al.lower() == d_short.lower() or al in d_short for al in aliases):
                            matched_tid = d.get("id") or ""
                            break
                if matched_tid:
                    break

        # 4) 按正文引用的表号匹配（当该原表只有 1 张限值表或尚未匹配时）
        if not matched_tid and by_tref and tref:
            m_no = re.search(r"\d+", tref)
            if m_no:
                t_prefix = f"T{m_no.group(0)}"
                cands = [d for d in table_drafts if str(d.get("id") or "").startswith(t_prefix)]
                if len(cands) == 1:
                    matched_tid = cands[0].get("id") or ""

        if matched_tid:
            links[iid] = matched_tid

    return links


def rules_catalog(override: dict | None = None) -> dict:
    """把 4 步向导判定规则原样吐出来，界面上照着调，并带上可配置结构。"""
    rules = get_rules(override)
    return {
        "configurable": rules,
        "steps_meta": [
            {
                "step": 1,
                "key": "step1_items",
                "title": "第 1 步：检查项识别规则",
                "summary": "控制 PDF 条款切分、可测量检项命中词、排除章节/过程小节及分类词典",
                "keys": STEP_RULE_KEYS["step1_items"],
            },
            {
                "step": 2,
                "key": "step2_params",
                "title": "第 2 步：规格参数识别规则",
                "summary": "控制从标准正文中自动识别规格参数（正则匹配词 → 参数代码、类型、单位、可选值）",
                "keys": STEP_RULE_KEYS["step2_params"],
            },
            {
                "step": 3,
                "key": "step3_limits",
                "title": "第 3 步：限值与表格拆解规则",
                "summary": "控制表格特征值列（Min/Max/Avg/Nom 等）识别、表头维度映射及 5 种拆分模式判别词",
                "keys": STEP_RULE_KEYS["step3_limits"],
            },
            {
                "step": 4,
                "key": "step4_links",
                "title": "第 4 步：检项与限值关联规则",
                "summary": "控制检查项目与拆分后的限值表自动关联策略及同义词映射字典",
                "keys": STEP_RULE_KEYS["step4_links"],
            },
        ],
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
            {"正则": pr["pattern"], "code": pr["code"], "名称": pr["name"], "类型": pr["type"],
             "单位": pr.get("unit", ""), "可选值": pr.get("options", []), "说明": "正文任一页命中即建议"}
            for pr in (rules.get("param_rules") or [])
        ],
        "tables": {
            "一句话": "OCR 还原网格后，按拆分模式与特征值词典（Min/Max/Avg/Nom 等）自动拆解。",
            "步骤": [
                "① 盘点标准全文原表并按表头/标题关键词推荐 5 种拆分模式之一",
                "② 按特征值词典识别 Min / Max / Avg / Nom / Typ / Ref 等列或子表头",
                "③ 按表头维度映射规则匹配公称直径 d_nom、性能等级 property_class 等维度参数",
                "④ 拆分为『表格标题/指标名 + 特征值』的独立单指标限值表",
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
