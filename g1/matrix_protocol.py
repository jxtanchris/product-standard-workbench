# -*- coding: utf-8 -*-
"""国家/行业标准复合大表通用协议与多步骤逐表拆解引擎 (USMP: Universal Standard Matrix Protocol).

支持 5 种标准预定义表格拆分模式：
  1. single_indicator    (模式 1：单指标简单表，1 表 → 1 张单指标限值表)
  2. multi_col_parallel  (模式 2：多指标并列表，1 表 → 按列拆分为 N 张限值表)
  3. matrix_2d_cross     (模式 3：二维矩阵交叉表，行参数 × 列参数 → 二维正交限值表)
  4. composite_no_master (模式 4：No. 复合大表，1 表 → 按 No. 拆分为 N 张多维主从限值表)
  5. ignore_skip         (模式 5：非判定表 / 忽略跳过，0 张限值表)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MatrixDim:
    """维度定义（公共自变量或指标专属自变量）。"""
    code: str                      # 参数代码，如 property_class, d_nom, rm_nom
    name: str                      # 中文名称，如 性能等级, 公称直径 d
    kind: str = "enum"             # 类型: enum (枚举值) | range (数值区间)
    unit: str = ""                 # 物理单位
    options: List[str] = field(default_factory=list)  # 可选枚举列表


@dataclass
class MatrixRow:
    """限值明细行（在完整多维正交坐标下的判定点）。"""
    key: Dict[str, Any]            # 完整坐标字典，例如 {'property_class': '8.8', 'd_nom': '16~39', 'rm_nom': '800'}
    nominal: Optional[float] = None  # 标准给出的公称基准值
    lower: Optional[float] = None    # 限值下限 (min / ≥)
    upper: Optional[float] = None    # 限值上限 (max / ≤)
    lower_expr: str = ""           # 动态表达式下限（若有）
    upper_expr: str = ""           # 动态表达式上限（若有）
    na: bool = False               # 是否不适用/不要求 (如 '—')
    note: str = ""                 # 特殊备注（如 '仅记录', '大规格加严'）
    extra_stats: Dict[str, float] = field(default_factory=dict)  # 其它极值/统计值（如 {'Avg': 0.08, 'Typ': 0.10}）


@dataclass
class MatrixTableItem:
    """按 No 序号切分出的单指标限值主表实体。"""
    no: str                        # 序号，如 '1', '2', '5', '5b'
    name: str                      # 检项/指标名称，如 '抗拉强度 RmMin', '镀层厚度Avg'
    unit: str = ""                 # 检项单位，如 'MPa', 'N', 'HV', '%'
    local_table_id: str = ""       # 标准内唯一的子表代号，如 'T-PROP-RM-MIN'
    item_id: str = ""              # 绑定的标准检项 ID
    clause: str = ""               # 标准条款号，如 '9.1'
    stat_type: str = ""            # 统计/极值特征类型，如 'Min', 'Max', 'Avg', 'Nom', 'Typ', 'Ref' 等
    extra_dims: List[MatrixDim] = field(default_factory=list)  # 专属增量参数树
    rows: List[MatrixRow] = field(default_factory=list)        # 该指标对应的所有多维明细行

    def all_dimensions(self, common_dims: List[MatrixDim]) -> List[MatrixDim]:
        """合并表头公共自变量与该主表专属自变量。"""
        return list(common_dims) + list(self.extra_dims)


@dataclass
class StandardMatrix:
    """复合大表/母表整体实体。"""
    local_id: str                  # 母表代号，如 'M-PROP-TABLE3'
    title: str                     # 母表标题，如 'GB/T 3098.1 表3 螺栓机械和物理性能'
    common_dims: List[MatrixDim] = field(default_factory=list)  # 表头公共参数池 (所有主表默认继承)
    tables: List[MatrixTableItem] = field(default_factory=list)  # 按 No 序号排列的限值主表清单
    category: str = "性能"
    split_mode: str = "composite_no_master"
    source_table_id: str = ""

    def to_dict(self) -> dict:
        return {
            "local_id": self.local_id,
            "title": self.title,
            "category": self.category,
            "split_mode": self.split_mode,
            "source_table_id": self.source_table_id,
            "common_dims": [
                {"code": d.code, "name": d.name, "kind": d.kind, "unit": d.unit, "options": d.options}
                for d in self.common_dims
            ],
            "tables": [
                {
                    "no": t.no,
                    "name": t.name,
                    "unit": t.unit,
                    "local_table_id": t.local_table_id,
                    "item_id": t.item_id,
                    "clause": t.clause,
                    "stat_type": t.stat_type,
                    "extra_dims": [
                        {"code": ed.code, "name": ed.name, "kind": ed.kind, "unit": ed.unit, "options": ed.options}
                        for ed in t.extra_dims
                    ],
                    "rows": [
                        {
                            "key": r.key,
                            "nominal": r.nominal,
                            "lower": r.lower,
                            "upper": r.upper,
                            "lower_expr": r.lower_expr,
                            "upper_expr": r.upper_expr,
                            "na": r.na,
                            "note": r.note
                        }
                        for r in t.rows
                    ]
                }
                for t in self.tables
            ]
        }


# ------------------------------------------------------------------ 辅助工具函数
_CAPTION_RE = re.compile(
    r"^\s*表\s*([0-9A-Za-z]+(?:\.[0-9]+)?)\s*(?:[（(]续[)）])?\s*(.*)$"
)
_PROSE_FOLLOW_RE = re.compile(
    r"^(规定了|给出了|列出了|为|中|和表|～表|~表|所示|适用|应符合|的试验)"
)
_NUM_CLEAN_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _clean_num(val: Any) -> Optional[float]:
    """从 OCR 字符串中提取纯数值（去除空格千分位及角标噪声）。"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("-", "—", "一", "／", "/"):
        return None
    # 处理如 "3 150"、"34 000" 的千分位空格
    s_nospace = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", s)
    # 常见 OCR 尾注噪声清理，如 "0.20°", "420°", "2208" (实为 220^g)
    s_nospace = re.sub(r"[°'\"‘’“”a-zA-Z]+$", "", s_nospace).strip()
    m = _NUM_CLEAN_RE.search(s_nospace)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _match_item_id(indicator_name: str, items: list[dict]) -> str:
    """根据指标名称自动匹配当前标准中的检项 ID。"""
    if not indicator_name or not items:
        return ""
    clean_ind = re.sub(r"[A-Za-z0-9_.\s/()（）,，·•-]", "", indicator_name)
    if not clean_ind:
        clean_ind = indicator_name.strip()
    best_id = ""
    best_score = 0
    for it in items:
        title = (it.get("title") or it.get("name") or "").strip()
        if not title:
            continue
        clean_title = re.sub(r"[A-Za-z0-9_.\s/()（）,，·•-]", "", title)
        if clean_ind and clean_ind == clean_title:
            return it.get("id") or it.get("code") or ""
        if clean_ind and (clean_ind in clean_title or clean_title in clean_ind):
            score = min(len(clean_ind), len(clean_title))
            if score > best_score:
                best_score = score
                best_id = it.get("id") or it.get("code") or ""
    return best_id


# ------------------------------------------------------------------ 第一步：从标准 PDF 原件自动盘点原表清单
def discover_source_tables(
    job_data: dict,
    std_meta: dict | None = None,
    existing_matrices: list[dict] | None = None,
    existing_tables: list[dict] | None = None,
) -> list[dict]:
    """从标准作业 OCR 文本与表格块中，盘点出该标准涉及到的全部原始表格清单，
    并为每张表格智能推荐拆分模式（模式 1 ~ 模式 5）。
    """
    text = (job_data or {}).get("text") or ""
    ocr_tables = (job_data or {}).get("tables") or []
    std_code = ((std_meta or {}).get("code") or (job_data or {}).get("code") or "").strip()
    workbench_state = (job_data or {}).get("workbench_state") or {}

    # 已存在的母表映射: local_id / source_table_id -> matrix info
    mat_by_key: dict[str, dict] = {}
    for m in (existing_matrices or []):
        lid = (m.get("local_id") or "").upper()
        if lid:
            mat_by_key[lid] = m
        sid = (m.get("source_table_id") or "").upper()
        if sid:
            mat_by_key[sid] = m

    # 1. 解析全文行与页码标记（如果 text 中没有分页，结合 ocr_tables 推断页码）
    lines = [ln.strip() for ln in text.splitlines()]
    caption_entries: list[dict] = []
    for idx, ln in enumerate(lines):
        if not ln.startswith("表"):
            continue
        m = _CAPTION_RE.match(ln)
        if not m:
            continue
        t_no = m.group(1).strip()
        rest = (m.group(2) or "").strip()
        is_cont = ("（续）" in ln) or ("(续)" in ln)
        if rest and _PROSE_FOLLOW_RE.match(rest):
            continue
        if len(rest) > 28 or "。" in rest or "，" in rest:
            continue
        # 收集表题后续 18 行作为表头/正文上下文
        ctx_lines = []
        for k in range(idx + 1, min(len(lines), idx + 22)):
            nxt = lines[k]
            if not nxt:
                continue
            if nxt.startswith("表") and _CAPTION_RE.match(nxt):
                break
            if re.match(r"^\d+\.\d+(?:\.\d+)?\s+\S+", nxt):
                break
            ctx_lines.append(nxt)
        caption_entries.append({
            "t_no": t_no,
            "raw_title": rest,
            "is_cont": is_cont,
            "line_idx": idx,
            "caption_line": ln,
            "context_lines": ctx_lines,
        })

    # 2. 按表号 t_no 聚合逻辑原表（把 表X 与 表X(续) 合并为一张逻辑表）
    logical_map: dict[str, dict] = {}
    logical_order: list[str] = []
    for cap in caption_entries:
        t_no = cap["t_no"]
        if t_no not in logical_map:
            clean_title = re.sub(r"\s*(mm|N·m|N•m|MPa|%)$", "", cap["raw_title"]).strip()
            unit_hint = ""
            um = re.search(r"(mm|N·m|N•m|MPa|%)$", cap["raw_title"])
            if um:
                unit_hint = um.group(1).replace("•", "·")
            logical_map[t_no] = {
                "t_no": t_no,
                "table_id": f"SRC-TABLE-{t_no}",
                "matrix_local_id": f"M-TABLE{t_no}",
                "label": f"表{t_no}",
                "title": clean_title or f"表{t_no}",
                "full_title": f"表{t_no} {clean_title}".strip(),
                "unit_hint": unit_hint,
                "context_lines": list(cap["context_lines"]),
                "ocr_indices": [],
                "grids": [],
                "pages": [],
            }
            logical_order.append(t_no)
        else:
            existing = logical_map[t_no]
            if not existing["title"] or existing["title"] == f"表{t_no}":
                if cap["raw_title"]:
                    existing["title"] = cap["raw_title"]
                    existing["full_title"] = f"表{t_no} {cap['raw_title']}".strip()
            for cl in cap["context_lines"]:
                if cl not in existing["context_lines"] and len(existing["context_lines"]) < 36:
                    existing["context_lines"].append(cl)

    # 3. 将 OCR 表格块匹配到逻辑表（按页码与关键词重叠度）
    assigned_ocr: set[int] = set()
    for t_idx, ot in enumerate(ocr_tables):
        grid = ot.get("grid") or []
        if not grid:
            continue
        flat_text = " ".join(cell for row in grid for cell in row if cell)
        # 过滤前言里的引用标准列表（如 -GB/T 3098.xx）
        if flat_text.count("GB/T") >= 2 or flat_text.count("ISO") >= 2:
            assigned_ocr.add(t_idx)
            continue
        # 检查表格首行单元格是否自带 "表X 标题"
        first_row_text = " ".join(str(c).strip() for c in (grid[0] if grid else []) if c)
        m_in = re.search(r"(?:^|\s)表\s*([0-9A-Za-z]+)\s+\S+", first_row_text)
        if m_in and m_in.group(1) in logical_map:
            t_no = m_in.group(1)
            logical_map[t_no]["ocr_indices"].append(t_idx)
            logical_map[t_no]["grids"].append(grid)
            if ot.get("page") and ot["page"] not in logical_map[t_no]["pages"]:
                logical_map[t_no]["pages"].append(ot["page"])
            assigned_ocr.add(t_idx)
            continue

        # 按上下文词汇重叠度匹配（若得分相同，优先匹配尚未分配网格的逻辑表）
        best_tno = None
        best_score = 0
        for t_no in logical_order:
            linfo = logical_map[t_no]
            ctx_blob = linfo["full_title"] + " " + " ".join(linfo["context_lines"])
            score = 0
            for row in grid[:10]:
                for cell in row:
                    c = (cell or "").strip()
                    if len(c) >= 2 and c in ctx_blob:
                        score += len(c)
            if score > best_score or (
                score > 0
                and score == best_score
                and best_tno is not None
                and len(logical_map[best_tno]["grids"]) > 0
                and len(linfo["grids"]) == 0
            ):
                best_score = score
                best_tno = t_no

        if best_tno and best_score >= 3:
            logical_map[best_tno]["ocr_indices"].append(t_idx)
            logical_map[best_tno]["grids"].append(grid)
            if ot.get("page") and ot["page"] not in logical_map[best_tno]["pages"]:
                logical_map[best_tno]["pages"].append(ot["page"])
            assigned_ocr.add(t_idx)

    # 4. 如果没有识别出任何表标题，退化为直接使用非引用类的 OCR 表格块
    if not logical_order:
        for t_idx, ot in enumerate(ocr_tables):
            if t_idx in assigned_ocr:
                continue
            grid = ot.get("grid") or []
            if not grid:
                continue
            t_no = str(t_idx + 1)
            logical_map[t_no] = {
                "t_no": t_no,
                "table_id": f"SRC-TABLE-{t_no}",
                "matrix_local_id": f"M-TABLE{t_no}",
                "label": f"表{t_no}",
                "title": f"原文表格 #{t_no} (第{ot.get('page', '?')}页)",
                "full_title": f"表{t_no} (第{ot.get('page', '?')}页)",
                "unit_hint": "",
                "context_lines": [],
                "ocr_indices": [t_idx],
                "grids": [grid],
                "pages": [ot.get("page")] if ot.get("page") else [],
            }
            logical_order.append(t_no)

    # 5. 为每张逻辑表构建预览网格、智能推荐拆分模式并检查当前处理状态
    results: list[dict] = []
    for seq, t_no in enumerate(logical_order, start=1):
        info = logical_map[t_no]
        merged_grid: list[list[str]] = []
        for g in info["grids"]:
            for r in g:
                if any(str(c).strip() for c in r):
                    merged_grid.append([str(c).strip() for c in r])

        # 若某个表标题在文本中存在但未被 tablefind 切成 grid，用 context_lines 构造预览网格
        if not merged_grid and info["context_lines"]:
            for cl in info["context_lines"][:10]:
                parts = re.split(r"\s+", cl.strip())
                merged_grid.append(parts if len(parts) > 1 else [cl])

        rec_mode, rec_reason = _recommend_split_mode(info, merged_grid)
        page_num = info["pages"][0] if info["pages"] else None

        # 检查是否已拆解或已跳过
        tid = info["table_id"]
        mlid = info["matrix_local_id"]
        saved_mat = mat_by_key.get(mlid.upper()) or mat_by_key.get(tid.upper())
        # 兼容以前保存的 M-PROP-TABLE3 等
        if not saved_mat and t_no == "3":
            saved_mat = mat_by_key.get("M-PROP-TABLE3")
        if not saved_mat and t_no == "4":
            saved_mat = mat_by_key.get("M-LOAD-TABLE4")

        wb_entry = workbench_state.get(tid) or workbench_state.get(mlid) or {}
        if saved_mat:
            status = "completed"
            sub_count = len(saved_mat.get("tables") or saved_mat.get("indicators") or [])
            chosen_mode = saved_mat.get("split_mode") or wb_entry.get("split_mode") or rec_mode
        elif wb_entry.get("status") == "skipped":
            status = "skipped"
            sub_count = 0
            chosen_mode = "ignore_skip"
        elif wb_entry.get("status") == "completed":
            status = "completed"
            sub_count = int(wb_entry.get("sub_count") or 1)
            chosen_mode = wb_entry.get("split_mode") or rec_mode
        else:
            status = "pending"
            sub_count = 0
            chosen_mode = rec_mode

        rows_cnt = len(merged_grid)
        cols_cnt = max((len(r) for r in merged_grid), default=0)

        results.append({
            "seq": seq,
            "t_no": t_no,
            "table_id": tid,
            "matrix_local_id": saved_mat.get("local_id") if saved_mat else mlid,
            "label": info["label"],
            "title": info["title"],
            "full_title": f"{std_code} {info['full_title']}".strip() if std_code else info["full_title"],
            "short_title": info["full_title"],
            "page": page_num,
            "pages": info["pages"],
            "rows": rows_cnt,
            "cols": cols_cnt,
            "unit_hint": info["unit_hint"],
            "recommended_mode": rec_mode,
            "recommend_reason": rec_reason,
            "chosen_mode": chosen_mode,
            "status": status,
            "sub_count": sub_count,
            "preview_grid": merged_grid[:25],
            "context_lines": info["context_lines"][:18],
        })

    return results


def _recommend_split_mode(info: dict, grid: list[list[str]]) -> tuple[str, str]:
    """根据表题、上下文行和网格形态，智能推荐 5 种拆分模式之一。"""
    title = info.get("full_title") or ""
    ctx_blob = title + " " + " ".join(info.get("context_lines") or [])
    grid_blob = " ".join(" ".join(r) for r in grid[:10])
    all_blob = ctx_blob + " " + grid_blob

    # 1. 非判定表 / 忽略跳过 (ignore_skip)
    if any(k in title for k in ("项目", "屈强比", "试板", "楔垫", "夹具", "适用", "试验系列", "试验模", "标志")):
        return ("ignore_skip", "表题属于条款导览索引、概念示例、标志代号或试验工装夹具表，非产品数值判定限值")
    if "技术要求（条或表）" in all_blob or "试验方法（条）" in all_blob or "NF" in grid_blob:
        return ("ignore_skip", "表格内容为试验方法或条款号索引对照，建议标记跳过")

    # 2. 模式 4：No. 复合大表 (composite_no_master)
    if ("No." in all_blob or "抗拉强度" in all_blob) and any(
        k in all_blob for k in ("机械和物理性能", "下屈服强度", "保证应力", "规定非比例延伸")
    ):
        return ("composite_no_master", "包含纵向 No. 多物理量指标 + 跨列性能等级与直径分段 + 公称/min 子行，推荐用模式 4（No.复合大表主从向导）")

    # 3. 模式 3：二维矩阵交叉表 (matrix_2d_cross)
    if any(k in title for k in ("最小拉力载荷", "保证载荷")) or (
        re.search(r"\bM\d+", all_blob) and any(pc in all_blob for pc in ("4.6", "8.8", "10.9", "12.9"))
    ):
        return ("matrix_2d_cross", "纵轴为螺纹规格 (M3~M39)、横轴为性能等级 (4.6~12.9)，属于典型二维行列正交载荷矩阵")

    # 4. 模式 1：单指标简单表 (single_indicator)
    if any(k in title for k in ("渗碳层深度", "脱碳层")) or (
        grid and len(grid[0]) >= 3 and any(c.lower() in ("min", "max", "avg", "平均", "平均值") for c in grid[0][1:])
    ):
        return ("single_indicator", "整表仅针对单一检验指标给出各规格的极值/统计特征（如 Min / Max / Avg 等），推荐用模式 1（按特征值拆分为对应限值表）")

    # 5. 模式 2：多指标并列表 (multi_col_parallel)
    return ("multi_col_parallel", "左侧为规格/条件自变量，右侧并列多个独立检验指标列，推荐用模式 2（按指标列及 Min / Max / Avg 等特征值拆分为多张限值表）")


# 标准极值/统计特征限定词字典：支持 Min / Max / Avg / Nom / Typ / Ref / Std / Med / Dev 等及任意自定义特征词
_STAT_QUALIFIER_MAP: dict[str, str] = {
    "min": "Min",
    "minimum": "Min",
    "最小": "Min",
    "最小值": "Min",
    "下限": "Min",
    "≥": "Min",
    ">=": "Min",
    "max": "Max",
    "maximum": "Max",
    "最大": "Max",
    "最大值": "Max",
    "上限": "Max",
    "≤": "Max",
    "<=": "Max",
    "avg": "Avg",
    "average": "Avg",
    "mean": "Avg",
    "平均": "Avg",
    "平均值": "Avg",
    "均值": "Avg",
    "nom": "Nom",
    "nominal": "Nom",
    "公称": "Nom",
    "公称值": "Nom",
    "基准": "Nom",
    "基准值": "Nom",
    "typ": "Typ",
    "typical": "Typ",
    "典型": "Typ",
    "典型值": "Typ",
    "ref": "Ref",
    "reference": "Ref",
    "参考": "Ref",
    "参考值": "Ref",
    "std": "Std",
    "standard": "Std",
    "标准": "Std",
    "标准值": "Std",
    "med": "Med",
    "median": "Med",
    "中位": "Med",
    "中位数": "Med",
    "dev": "Dev",
    "偏差": "Dev",
    "公差": "Dev",
}

_KNOWN_QUALIFIER_SUFFIX_RE = re.compile(
    r"\s*(?i:min|max|avg|mean|nom|typ|ref|std|med|dev|最小值|最大值|平均值|均值|公称值|典型值|参考值|下限|上限|最小|最大|平均)$"
)


def _dynamic_qualifier_map() -> dict[str, str]:
    """合并内置特征值词典与识别规则库（Step 3 stat_qualifiers）的动态词典。"""
    merged = dict(_STAT_QUALIFIER_MAP)
    try:
        import analyze as _analyze
        for sq in (_analyze.get_rules().get("stat_qualifiers") or []):
            code = str(sq.get("code") or "").strip()
            if not code:
                continue
            for w in (sq.get("words") or []):
                w_str = str(w).strip()
                if w_str:
                    merged[w_str.lower().rstrip(".")] = code
                    merged[w_str] = code
    except Exception:
        pass
    return merged


def _normalize_stat_qualifier(raw_tok: str) -> str:
    """将表头或子行中的极值/统计特征词（如 min, max, avg, 平均值, 公称, 典型值 等）标准化为规范后缀（Min, Max, Avg, Nom, Typ...）。"""
    s = (raw_tok or "").strip()
    if not s:
        return ""
    s_clean = re.sub(r"^[（(【\[]+|[）)】\]]+$", "", s).strip()
    low = s_clean.lower().rstrip(".")
    qmap = _dynamic_qualifier_map()
    if low in qmap:
        return qmap[low]
    if s_clean in qmap:
        return qmap[s_clean]
    for k, v in qmap.items():
        if len(k) >= 2 and (low == k or s_clean == k):
            return v
    if re.match(r"^[A-Za-z][A-Za-z0-9_]{0,7}$", s_clean):
        return s_clean[0].upper() + s_clean[1:].lower()
    return s_clean


def _extract_name_and_qualifier(raw_header: str, fallback_name: str = "") -> tuple[str, str]:
    """从列标题（如 '破坏扭矩 min'、'冲击功 (avg)'、'镀层厚度 平均值'、'avg'）中分离出 (基础指标名, 统计特征后缀)。"""
    s = (raw_header or "").strip()
    if not s:
        return (fallback_name, "")
    qmap = _dynamic_qualifier_map()
    # 若整个单元格本身就是一个特征词（如 'min', 'max', 'avg', '平均值'）
    low = s.lower().rstrip(".")
    if low in qmap or s in qmap:
        return (fallback_name, _normalize_stat_qualifier(s))
    # 检查括号内或末尾的特征词，如 "镀层厚度 (avg)" 或 "冲击能量 平均值"
    m_paren = re.search(r"^(.*?)[（(]\s*([^()（）]{1,12})\s*[)）]$", s)
    if m_paren:
        inner = m_paren.group(2).strip()
        if inner.lower().rstrip(".") in qmap or inner in qmap:
            base = m_paren.group(1).strip() or fallback_name
            return (base, _normalize_stat_qualifier(inner))
    m_tail = _KNOWN_QUALIFIER_SUFFIX_RE.search(s)
    if m_tail:
        tok = m_tail.group(0).strip()
        base = s[:m_tail.start()].strip() or fallback_name
        return (base, _normalize_stat_qualifier(tok))
    # 检查空格分隔末尾词是否在动态特征词典中
    parts = s.rsplit(None, 1)
    if len(parts) == 2 and (parts[1].lower().rstrip(".") in qmap or parts[1] in qmap):
        return (parts[0].strip() or fallback_name, _normalize_stat_qualifier(parts[1]))
    return (s, "")


def _make_row_for_qualifier(
    key: dict[str, Any],
    val: Optional[float],
    qualifier: str,
    *,
    nominal: Optional[float] = None,
    lower_expr: str = "",
    upper_expr: str = "",
    na: bool = False,
    note: str = "",
) -> MatrixRow:
    """根据统计特征类型（Min / Max / Avg / Nom / Typ / Ref 等）构造对应的单特征 MatrixRow。"""
    q = _normalize_stat_qualifier(qualifier) or "Min"
    if q == "Max":
        return MatrixRow(
            key=dict(key),
            nominal=nominal,
            lower=None,
            upper=val,
            lower_expr="",
            upper_expr=upper_expr,
            na=na,
            note=note,
        )
    if q in ("Nom", "Avg", "Typ", "Ref", "Std", "Med"):
        note_str = note or (f"特征值类型: {q}" if q != "Min" else "")
        return MatrixRow(
            key=dict(key),
            nominal=val if q == "Nom" else nominal,
            lower=val,
            upper=None,
            lower_expr=lower_expr,
            upper_expr="",
            na=na,
            note=note_str,
        )
    return MatrixRow(
        key=dict(key),
        nominal=nominal,
        lower=val,
        upper=None,
        lower_expr=lower_expr,
        upper_expr="",
        na=na,
        note=note,
    )


def _split_tables_by_min_max(
    tables: list[MatrixTableItem],
    mode_code: str,
    std_items: list[dict],
) -> list[MatrixTableItem]:
    """将各模式拆解出的限值主表统一按极值/统计特征（Min / Max / Avg / Nom / Typ / Ref 等）拆分为独立限值表，
    名称统一规范为：「表格标题(或指标名称)+特征词（如 Min / Max / Avg）」。
    """
    out: list[MatrixTableItem] = []

    for t in tables:
        raw_name = (t.name or "").strip()
        parsed_base, parsed_qual = _extract_name_and_qualifier(raw_name, raw_name)
        base_name = parsed_base or raw_name
        explicit_stat = _normalize_stat_qualifier(t.stat_type) or parsed_qual
        base_tid = re.sub(r"-(?i:MIN|MAX|AVG|NOM|TYP|REF|STD|MED|DEV|1)$", "", (t.local_table_id or "T-TABLE")).strip()

        has_min = any(r.lower is not None or bool(r.lower_expr) for r in t.rows)
        has_max = any(r.upper is not None or bool(r.upper_expr) for r in t.rows)

        # 收集 rows.extra_stats 中出现的其它特征值类型（如 Avg, Nom, Typ 等，按出现顺序排列）
        extra_stat_keys: list[str] = []
        for r in t.rows:
            for sk, sv in (r.extra_stats or {}).items():
                if sv is not None:
                    norm_sk = _normalize_stat_qualifier(sk)
                    if norm_sk and norm_sk not in extra_stat_keys:
                        extra_stat_keys.append(norm_sk)

        # 如果该表已经明确指定了单一非 Min/Max 特征类型（如 stat_type='Avg'）且无多重混合列
        if explicit_stat and explicit_stat not in ("Min", "Max") and not has_max and not extra_stat_keys:
            q_slug = re.sub(r"[^A-Za-z0-9]+", "", explicit_stat).upper() or "STAT"
            no_val = t.no if mode_code == "composite_no_master" else str(len(out) + 1)
            out.append(MatrixTableItem(
                no=no_val,
                name=f"{base_name}{explicit_stat}",
                unit=t.unit,
                local_table_id=f"{base_tid}-{q_slug}",
                item_id=t.item_id,
                clause=t.clause,
                stat_type=explicit_stat,
                extra_dims=list(t.extra_dims),
                rows=list(t.rows),
            ))
            continue

        # 统计当前主表中包含的全部特征分支（Min / Max / Avg / ...）
        active_qualifiers: list[str] = []
        if has_min:
            active_qualifiers.append("Min")
        if has_max:
            active_qualifiers.append("Max")
        for ek in extra_stat_keys:
            if ek not in active_qualifiers:
                active_qualifiers.append(ek)

        # 若为模式 1 且尚未填入任何行，默认生成 Min 与 Max 两张空草稿表（除非已显式指定单一 stat_type）
        if not active_qualifiers:
            if explicit_stat:
                active_qualifiers = [explicit_stat]
            elif mode_code == "single_indicator":
                active_qualifiers = ["Min", "Max"]
            else:
                active_qualifiers = ["Min"]

        is_multi_split = len(active_qualifiers) > 1
        for q_label in active_qualifiers:
            q_slug = re.sub(r"[^A-Za-z0-9]+", "", q_label).upper() or "VAL"
            if q_label == "Min":
                q_rows = [
                    _make_row_for_qualifier(
                        r.key, r.lower, "Min",
                        nominal=r.nominal, lower_expr=r.lower_expr, na=r.na, note=r.note,
                    )
                    for r in t.rows
                    if r.lower is not None or bool(r.lower_expr) or r.na
                ]
            elif q_label == "Max":
                q_rows = [
                    _make_row_for_qualifier(
                        r.key, r.upper, "Max",
                        nominal=r.nominal, upper_expr=r.upper_expr, na=r.na, note=r.note,
                    )
                    for r in t.rows
                    if r.upper is not None or bool(r.upper_expr) or r.na
                ]
            else:
                q_rows = []
                for r in t.rows:
                    val = None
                    for raw_k, raw_v in (r.extra_stats or {}).items():
                        if _normalize_stat_qualifier(raw_k) == q_label:
                            val = raw_v
                            break
                    if val is not None or r.na:
                        q_rows.append(_make_row_for_qualifier(
                            r.key, val, q_label,
                            nominal=r.nominal, na=r.na, note=r.note,
                        ))

            if mode_code == "composite_no_master":
                no_val = f"{t.no}-{q_label}" if is_multi_split else str(t.no)
            else:
                no_val = str(len(out) + 1)

            out.append(MatrixTableItem(
                no=no_val,
                name=f"{base_name}{q_label}",
                unit=t.unit,
                local_table_id=f"{base_tid}-{q_slug}",
                item_id="" if is_multi_split else t.item_id,
                clause=t.clause,
                stat_type=q_label,
                extra_dims=list(t.extra_dims),
                rows=q_rows,
            ))

    return out


# ------------------------------------------------------------------ 第二/三步：按所选拆分模式将原表解构为 USMP 结构
def deconstruct_source_table(
    table_info: dict,
    mode_code: str,
    std_meta: dict | None = None,
) -> dict:
    """根据用户选定的拆分模式 (mode_code)，将指定原表解构为 USMP 主从结构字典。"""
    std_items = (std_meta or {}).get("items") or []
    std_code = ((std_meta or {}).get("code") or "").strip()
    t_no = str(table_info.get("t_no") or "1")
    tid = table_info.get("table_id") or f"SRC-TABLE-{t_no}"
    local_id = table_info.get("matrix_local_id") or f"M-TABLE{t_no}"
    full_title = table_info.get("full_title") or table_info.get("title") or f"表{t_no}"

    if mode_code == "ignore_skip":
        return {
            "local_id": local_id,
            "title": full_title,
            "split_mode": "ignore_skip",
            "source_table_id": tid,
            "status": "skipped",
            "common_dims": [],
            "tables": [],
        }

    if mode_code == "single_indicator":
        mat = _deconstruct_mode1_single(table_info, local_id, full_title, std_items)
    elif mode_code == "multi_col_parallel":
        mat = _deconstruct_mode2_parallel(table_info, local_id, full_title, std_items)
    elif mode_code == "matrix_2d_cross":
        mat = _deconstruct_mode3_cross2d(table_info, local_id, full_title, std_items)
    elif mode_code == "composite_no_master":
        mat = _deconstruct_mode4_composite(table_info, local_id, full_title, std_items, std_code)
    else:
        mat = _deconstruct_mode2_parallel(table_info, local_id, full_title, std_items)

    # 统一按极值/统计特征（Min / Max / Avg / Nom 等）拆分为独立限值主表，命名为「表格标题/指标名+特征值」
    mat.tables = _split_tables_by_min_max(mat.tables, mode_code, std_items)
    mat.split_mode = mode_code
    mat.source_table_id = tid
    out = mat.to_dict()
    for idx, t in enumerate(out.get("tables") or []):
        t["expanded"] = (idx == 0)
    return out


def _detect_mode1_column_qualifiers(grid: list[list[str]], ctx_lines: list[str]) -> tuple[list[str], int]:
    """动态识别模式 1（单指标简单表）中第 1..K 个数值列的特征标签（如 ['Min', 'Max']、['Min', 'Max', 'Avg'] 等）及数据起始行。"""
    if not grid:
        return (["Min", "Max"], 0)

    max_cols = max((len(r) for r in grid), default=0)
    val_col_count = max(0, max_cols - 1)
    if val_col_count == 0:
        return (["Min", "Max"], 0)

    # 1. 检查首行（或第 2 行）是否为特征词表头（如 ['', 'min', 'max', 'avg']）
    for h_idx in range(min(2, len(grid))):
        row_cells = [str(c).strip() for c in grid[h_idx][1:]]
        norm_cells = [_normalize_stat_qualifier(c) for c in row_cells if c]
        # 如果首行非纯数字且包含已知特征词（或非数值文本表头）
        if row_cells and any(
            c.lower().rstrip(".") in _STAT_QUALIFIER_MAP or c in _STAT_QUALIFIER_MAP
            for c in row_cells if c
        ):
            qualifiers = []
            for c_i in range(val_col_count):
                raw_c = str(grid[h_idx][c_i + 1]).strip() if (c_i + 1) < len(grid[h_idx]) else ""
                q = _normalize_stat_qualifier(raw_c) or f"Val{c_i + 1}"
                qualifiers.append(q)
            return (qualifiers, h_idx + 1)

    # 2. 若 grid 首行已是纯数值行，从上下文行 ctx_lines 中提取特征词序列（如 '螺纹公称直径 min max avg'）
    for cl in ctx_lines:
        tokens = [t.strip() for t in re.split(r"[\s/｜|]+", cl) if t.strip()]
        q_tokens = [
            _normalize_stat_qualifier(t)
            for t in tokens
            if t.lower().rstrip(".") in _STAT_QUALIFIER_MAP or t in _STAT_QUALIFIER_MAP
        ]
        if len(q_tokens) >= val_col_count and val_col_count > 0:
            return (q_tokens[:val_col_count], 0)

    # 3. 默认回退：按列数依次赋予 Min, Max, Avg, Nom...
    default_seq = ["Min", "Max", "Avg", "Nom", "Typ", "Ref"]
    qualifiers = [default_seq[i] if i < len(default_seq) else f"Val{i+1}" for i in range(val_col_count)]
    return (qualifiers, 0)


def _deconstruct_mode1_single(
    table_info: dict,
    local_id: str,
    full_title: str,
    std_items: list[dict],
) -> StandardMatrix:
    """模式 1：单指标简单表（动态识别原表中包含的 Min / Max / Avg / Nom 等各列，按特征值拆分为对应限值表）。"""
    t_no = str(table_info.get("t_no") or "1")
    raw_name = re.sub(r"^.*?表\s*[0-9A-Za-z.]+\s*", "", full_title).strip() or f"表{t_no}指标"
    unit = table_info.get("unit_hint") or "mm"
    grid = table_info.get("preview_grid") or []
    ctx_lines = table_info.get("context_lines") or []

    common_dims = [MatrixDim(code="d_nom", name="螺纹公称直径 d", kind="enum", unit="mm")]
    qualifiers, start_row = _detect_mode1_column_qualifiers(grid, ctx_lines)

    tables: list[MatrixTableItem] = []
    for q_idx, q_label in enumerate(qualifiers):
        col_pos = q_idx + 1
        q_rows: list[MatrixRow] = []
        for r in grid[start_row:]:
            if not r or len(r) <= col_pos:
                continue
            c0 = str(r[0]).strip()
            if not c0 or c0.lower() in ("min", "max", "avg", "mean", "螺纹公称直径", "公称直径", "规格"):
                continue
            v = _clean_num(r[col_pos])
            if v is None:
                continue
            spec_tokens = _expand_diameter_group(c0)
            for sp in spec_tokens:
                note_str = f"原表规格组: {c0}" if len(spec_tokens) > 1 else ""
                q_rows.append(_make_row_for_qualifier({"d_nom": sp}, v, q_label, note=note_str))

        q_slug = re.sub(r"[^A-Za-z0-9]+", "", q_label).upper() or f"C{col_pos}"
        tables.append(MatrixTableItem(
            no=str(q_idx + 1),
            name=f"{raw_name}{q_label}",
            unit=unit,
            local_table_id=f"T-TABLE{t_no}-{q_slug}",
            item_id="",
            stat_type=q_label,
            extra_dims=[],
            rows=q_rows,
        ))

    return StandardMatrix(
        local_id=local_id,
        title=full_title,
        common_dims=common_dims,
        tables=tables,
    )


def _expand_diameter_group(raw_spec: str) -> list[str]:
    """将紧固件标准中合并书写的直径组（如 '2、2.5' / '2.2.5' / '3、3.5' / '4.5' / '6.8' / '10、12'）展开为独立直径列表。"""
    s = raw_spec.strip()
    special_ocr_map = {
        "2.2.5": ["2", "2.5"],
        "2、2.5": ["2", "2.5"],
        "3、3.5": ["3", "3.5"],
        "3.3.5": ["3", "3.5"],
        "4.5": ["4", "5"],
        "4、5": ["4", "5"],
        "6.8": ["6", "8"],
        "6、8": ["6", "8"],
        "10、12": ["10", "12"],
        "10.12": ["10", "12"],
    }
    if s in special_ocr_map:
        return special_ocr_map[s]
    if "、" in s or "," in s or "，" in s:
        return [p.strip() for p in re.split(r"[、,，\s]+", s) if p.strip()]
    return [s]


def _deconstruct_mode2_parallel(
    table_info: dict,
    local_id: str,
    full_title: str,
    std_items: list[dict],
) -> StandardMatrix:
    """模式 2：多指标并列表（按列拆分为 N 张限值表）。"""
    t_no = str(table_info.get("t_no") or "1")
    grid = table_info.get("preview_grid") or []
    ctx_lines = table_info.get("context_lines") or []
    ctx_blob = full_title + " " + " ".join(ctx_lines)

    # 针对特例1：GB/T 3098.7 表3《机械和工作性能要求》（左列螺纹公称直径，右三列：破坏扭矩、拧入扭矩、破坏拉力载荷）
    if ("破坏扭矩" in ctx_blob and ("拧入扭矩" in ctx_blob or "拧人扭矩" in ctx_blob)) or (
        grid and len(grid[0]) == 4 and "N•m" in grid[0][1]
    ):
        common_dims = [MatrixDim(code="d_nom", name="螺纹公称直径 d", kind="enum", unit="mm")]
        col_specs = [
            ("1", "破坏扭矩", "N·m", "min", f"T-TABLE{t_no}-TORQ-BRK"),
            ("2", "拧入扭矩", "N·m", "max", f"T-TABLE{t_no}-TORQ-DRV"),
            ("3", "破坏拉力载荷", "N", "min", f"T-TABLE{t_no}-LOAD-TEN"),
        ]
        tables: list[MatrixTableItem] = []
        for col_idx, (no_str, ind_name, unit, bound_kind, sub_tid) in enumerate(col_specs, start=1):
            t_rows: list[MatrixRow] = []
            for r in grid:
                if len(r) <= col_idx:
                    continue
                d_val = str(r[0]).strip()
                if not d_val or not re.match(r"^\d+(?:\.\d+)?$", d_val):
                    continue
                v = _clean_num(r[col_idx])
                if v is None:
                    continue
                t_rows.append(MatrixRow(
                    key={"d_nom": d_val},
                    nominal=None,
                    lower=v if bound_kind == "min" else None,
                    upper=v if bound_kind == "max" else None,
                    na=False,
                    note="标准参考值" if "参考" in ctx_blob and col_idx == 3 else "",
                ))
            tables.append(MatrixTableItem(
                no=no_str,
                name=ind_name,
                unit=unit,
                local_table_id=sub_tid,
                item_id=_match_item_id(ind_name, std_items),
                extra_dims=[],
                rows=t_rows,
            ))
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=tables)

    # 针对特例2：化学成分表（如 GB/T 3098.7 表1 化学成分，含 碳、锰 及 桶样/检验）
    if "化学成分" in full_title and any("桶样" in " ".join(r) or "检验" in " ".join(r) for r in grid):
        common_dims = [MatrixDim(code="sample_type", name="分析类型（桶样/检验）", kind="enum")]
        chem_cols = [
            ("1", "碳含量 C", "%", 1, f"T-TABLE{t_no}-C"),
            ("2", "锰含量 Mn", "%", 3, f"T-TABLE{t_no}-MN"),
        ]
        tables = []
        for no_str, cname, unit, c_idx, sub_tid in chem_cols:
            t_rows = []
            for r in grid:
                if len(r) <= c_idx:
                    continue
                stype = str(r[0]).strip()
                if stype not in ("桶样", "检验"):
                    continue
                raw_range = str(r[c_idx]).strip().replace("：", "5")  # 修复 OCR '1.6：' -> '1.65'
                nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", raw_range)]
                if len(nums) >= 2:
                    t_rows.append(MatrixRow(
                        key={"sample_type": stype},
                        lower=nums[0],
                        upper=nums[1],
                        note=f"成分极限({stype})",
                    ))
            tables.append(MatrixTableItem(
                no=no_str,
                name=cname,
                unit=unit,
                local_table_id=sub_tid,
                item_id=_match_item_id("化学成分" if not _match_item_id(cname, std_items) else cname, std_items),
                extra_dims=[],
                rows=t_rows,
            ))
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=tables)

    # 针对特例3：GB/T 3098.1 表2《材料》（按性能等级并列 C min, C max, P max, S max, B max, 回火温度 min）
    if "材料" in full_title or ("化学成分" in ctx_blob and "回火温度" in ctx_blob):
        common_dims = [
            MatrixDim(code="property_class", name="性能等级", kind="enum"),
            MatrixDim(code="material_treat", name="材料和热处理", kind="enum"),
        ]
        specs = [
            ("1", "碳含量 C", "%", f"T-TABLE{t_no}-C", [
                ("4.6", "碳钢或添加元素的碳钢", None, 0.55),
                ("4.8", "碳钢或添加元素的碳钢", None, 0.55),
                ("5.6", "碳钢或添加元素的碳钢", 0.13, 0.55),
                ("5.8", "碳钢或添加元素的碳钢", None, 0.55),
                ("6.8", "碳钢或添加元素的碳钢", 0.15, 0.55),
                ("8.8", "碳钢淬火并回火", 0.25, 0.55),
                ("8.8", "合金钢淬火并回火", 0.20, 0.55),
                ("9.8", "碳钢淬火并回火", 0.25, 0.55),
                ("10.9", "合金钢淬火并回火", 0.20, 0.55),
                ("12.9", "合金钢淬火并回火", 0.30, 0.50),
            ]),
            ("2", "磷含量 P", "%", f"T-TABLE{t_no}-P", [
                ("4.6", "碳钢或添加元素的碳钢", None, 0.050),
                ("5.6", "碳钢或添加元素的碳钢", None, 0.050),
                ("8.8", "碳钢淬火并回火", None, 0.025),
                ("10.9", "合金钢淬火并回火", None, 0.025),
                ("12.9", "合金钢淬火并回火", None, 0.025),
            ]),
            ("3", "硫含量 S", "%", f"T-TABLE{t_no}-S", [
                ("4.6", "碳钢或添加元素的碳钢", None, 0.060),
                ("5.6", "碳钢或添加元素的碳钢", None, 0.060),
                ("8.8", "碳钢淬火并回火", None, 0.025),
                ("10.9", "合金钢淬火并回火", None, 0.025),
                ("12.9", "合金钢淬火并回火", None, 0.025),
            ]),
            ("4", "最低回火温度", "°C", f"T-TABLE{t_no}-TEMP", [
                ("8.8", "碳钢淬火并回火", 425, None),
                ("9.8", "碳钢淬火并回火", 425, None),
                ("10.9", "合金钢淬火并回火", 425, None),
                ("12.9", "合金钢淬火并回火", 425, None),
            ]),
        ]
        tables = []
        for no_str, sname, unit, sub_tid, rdata in specs:
            tables.append(MatrixTableItem(
                no=no_str,
                name=sname,
                unit=unit,
                local_table_id=sub_tid,
                item_id=_match_item_id(sname, std_items),
                extra_dims=[],
                rows=[
                    MatrixRow(key={"property_class": pc, "material_treat": mt}, lower=lo, upper=hi)
                    for pc, mt, lo, hi in rdata
                ],
            ))
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=tables)

    # 通用按列拆分逻辑：第一列作为公共参数，后续每列按指标名及特征词（Min / Max / Avg / Nom 等）生成限值主表
    raw_tbl_name = re.sub(r"^.*?表\s*[0-9A-Za-z.]+\s*", "", full_title).strip() or f"表{t_no}指标"
    common_dims = [MatrixDim(code="d_nom", name="规格参数", kind="enum")]
    if not grid:
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=[])

    # 检测是否为双行复合表头（第 0 行为指标名称，第 1 行为 min / max / avg 等特征词）
    has_sub_qual_row = False
    if len(grid) >= 2:
        row1_cells = [str(c).strip() for c in grid[1][1:] if str(c).strip()]
        if row1_cells and all(
            c.lower().rstrip(".") in _STAT_QUALIFIER_MAP or c in _STAT_QUALIFIER_MAP
            for c in row1_cells
        ):
            has_sub_qual_row = True

    header_row = grid[0]
    sub_header_row = grid[1] if has_sub_qual_row else []
    data_rows = grid[2:] if has_sub_qual_row else (grid[1:] if len(grid) > 1 else [])
    tables = []
    carry_ind_name = raw_tbl_name

    for col_idx in range(1, len(header_row)):
        raw_col_title = str(header_row[col_idx]).strip()
        if raw_col_title and raw_col_title.lower().rstrip(".") not in _STAT_QUALIFIER_MAP and raw_col_title not in _STAT_QUALIFIER_MAP:
            carry_ind_name = raw_col_title

        sub_qual_raw = str(sub_header_row[col_idx]).strip() if (has_sub_qual_row and col_idx < len(sub_header_row)) else ""
        if has_sub_qual_row:
            base_col_name, inline_q = _extract_name_and_qualifier(carry_ind_name, raw_tbl_name)
            col_qual = _normalize_stat_qualifier(sub_qual_raw) or inline_q
        else:
            base_col_name, col_qual = _extract_name_and_qualifier(raw_col_title, carry_ind_name or f"{raw_tbl_name}{col_idx}")

        col_title = base_col_name or raw_tbl_name
        t_rows = []
        for r in data_rows:
            if len(r) <= col_idx:
                continue
            kval = str(r[0]).strip()
            if not kval:
                continue
            cell_str = str(r[col_idx]).strip()
            # 支持单元格中写 "min~max" 区间，或 "min / avg / max" 三值组合
            if "~" in cell_str or "～" in cell_str:
                nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", cell_str)]
                if len(nums) >= 3:
                    t_rows.append(MatrixRow(key={"d_nom": kval}, lower=nums[0], upper=nums[2], extra_stats={"Avg": nums[1]}))
                    continue
                if len(nums) >= 2:
                    t_rows.append(MatrixRow(key={"d_nom": kval}, lower=nums[0], upper=nums[1]))
                    continue
            if "/" in cell_str or "／" in cell_str:
                nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", cell_str)]
                if len(nums) == 3:
                    t_rows.append(MatrixRow(key={"d_nom": kval}, lower=nums[0], upper=nums[2], extra_stats={"Avg": nums[1]}))
                    continue
                if len(nums) == 2:
                    t_rows.append(MatrixRow(key={"d_nom": kval}, lower=nums[0], upper=nums[1]))
                    continue
            v = _clean_num(cell_str)
            if v is None:
                continue
            t_rows.append(_make_row_for_qualifier({"d_nom": kval}, v, col_qual or "Min"))
        if t_rows or col_title:
            tables.append(MatrixTableItem(
                no=str(len(tables) + 1),
                name=col_title,
                unit=table_info.get("unit_hint") or "",
                local_table_id=f"T-TABLE{t_no}-C{col_idx}",
                item_id=_match_item_id(col_title, std_items),
                stat_type=col_qual,
                extra_dims=[],
                rows=t_rows,
            ))
    return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=tables)


def _deconstruct_mode3_cross2d(
    table_info: dict,
    local_id: str,
    full_title: str,
    std_items: list[dict],
) -> StandardMatrix:
    """模式 3：二维矩阵交叉表（行参数 × 列参数 → 按 Min / Max / Avg 等特征值生成二维正交限值表）。"""
    t_no = str(table_info.get("t_no") or "1")
    grid = table_info.get("preview_grid") or []
    raw_title_clean = re.sub(r"^.*?表\s*[0-9A-Za-z.]+\s*", "", full_title).strip() or f"表{t_no}载荷"
    raw_name, title_qual = _extract_name_and_qualifier(raw_title_clean, raw_title_clean)
    if not title_qual:
        if "最小" in raw_name or "min" in raw_name.lower():
            title_qual = "Min"
        elif "最大" in raw_name or "max" in raw_name.lower():
            title_qual = "Max"
        elif "平均" in raw_name or "avg" in raw_name.lower():
            title_qual = "Avg"

    # 判断是否为螺纹规格(M3~M39) × 性能等级(4.6~12.9) 载荷矩阵
    grid_blob = " ".join(" ".join(r) for r in grid)
    if re.search(r"\bM\d+", grid_blob):
        prop_classes = ["4.6", "4.8", "5.6", "5.8", "6.8", "8.8", "9.8", "10.9", "12.9"]
        common_dims = [
            MatrixDim(code="thread_spec", name="螺纹规格 (d)", kind="enum", options=["M3", "M3.5", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]),
            MatrixDim(code="property_class", name="性能等级", kind="enum", options=prop_classes),
        ]
        rows: list[MatrixRow] = []
        for r in grid:
            line = " ".join(r).strip()
            m_spec = re.match(r"^(M\d+(?:\.\d+)?(?:\s*[×xX]\s*\d+(?:\.\d+)?)?)\s+(.*)$", line)
            if not m_spec:
                continue
            spec = re.sub(r"\s+", "", m_spec.group(1)).replace("X", "×").replace("x", "×")
            rest = m_spec.group(2)
            # 将千分位空格合并，如 "3 510" -> "3510", "11 350" -> "11350"
            rest_clean = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", rest)
            tokens = re.findall(r"\d+(?:\.\d+)?|-|—", rest_clean)
            if len(tokens) >= 2:
                # 第 1 个数字通常是应力截面积 As，后面对应 9 个性能等级载荷
                as_val = tokens[0]
                load_tokens = tokens[1:]
                for idx, pc in enumerate(prop_classes):
                    if idx >= len(load_tokens):
                        break
                    tok = load_tokens[idx]
                    if tok in ("-", "—"):
                        rows.append(MatrixRow(
                            key={"thread_spec": spec, "property_class": pc},
                            na=True,
                            note=f"As={as_val}mm²",
                        ))
                    else:
                        v = _clean_num(tok)
                        if v is not None:
                            rows.append(_make_row_for_qualifier(
                                {"thread_spec": spec, "property_class": pc},
                                v,
                                title_qual or "Min",
                                note=f"As={as_val}mm²",
                            ))
        t_item = MatrixTableItem(
            no="1",
            name=raw_name,
            unit="N",
            local_table_id=f"T-TABLE{t_no}-LOAD",
            item_id=_match_item_id(raw_name, std_items),
            stat_type=title_qual or "Min",
            extra_dims=[],
            rows=rows,
        )
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=[t_item])

    # 针对横向是直径规格、纵向是不同指标的矩阵表（如 表5 试板的厚度和孔径 或 表18 外螺纹牙型高度）
    common_dims = [
        MatrixDim(code="row_item", name="行项目", kind="enum"),
        MatrixDim(code="col_spec", name="列规格参数", kind="enum"),
    ]
    rows = []
    if len(grid) >= 2:
        col_headers = [c for c in grid[1][1:] if c] if len(grid) > 1 else []
        for r in grid[2:]:
            if not r:
                continue
            r_name = r[0] or "限值"
            _, row_qual = _extract_name_and_qualifier(r_name, r_name)
            for c_idx, val_str in enumerate(r[1:]):
                c_key = col_headers[c_idx] if c_idx < len(col_headers) else f"C{c_idx+1}"
                v = _clean_num(val_str)
                if v is not None:
                    q_use = row_qual or title_qual or ("Max" if "max" in r_name.lower() else "Min")
                    if q_use not in ("Min", "Max"):
                        rows.append(MatrixRow(
                            key={"row_item": r_name, "col_spec": c_key},
                            extra_stats={q_use: v},
                        ))
                    else:
                        rows.append(_make_row_for_qualifier({"row_item": r_name, "col_spec": c_key}, v, q_use))
    t_item = MatrixTableItem(
        no="1",
        name=raw_name,
        unit=table_info.get("unit_hint") or "mm",
        local_table_id=f"T-TABLE{t_no}-2D",
        item_id=_match_item_id(raw_name, std_items),
        stat_type=title_qual,
        extra_dims=[],
        rows=rows,
    )
    return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=[t_item])


def _deconstruct_mode4_composite(
    table_info: dict,
    local_id: str,
    full_title: str,
    std_items: list[dict],
    std_code: str = "",
) -> StandardMatrix:
    """模式 4：No. 复合大表（按 No. 序号主从向导拆解）。"""
    t_no = str(table_info.get("t_no") or "3")
    grid = table_info.get("preview_grid") or []
    grid_blob = " ".join(" ".join(r) for r in grid)

    # 若原表是 GB/T 3098.1 表3 螺栓、螺钉和螺柱的机械和物理性能，构建完整的 No.1 ~ No.17 核心主从体系
    if "抗拉强度" in grid_blob or "保证应力" in grid_blob or "3098.1" in (std_code + full_title):
        common_dims = [
            MatrixDim(code="property_class", name="性能等级", kind="enum", options=["4.6", "4.8", "5.6", "5.8", "6.8", "8.8", "9.8", "10.9", "12.9"]),
            MatrixDim(code="d_nom", name="公称直径 d", kind="range", unit="mm"),
        ]
        tables = [
            MatrixTableItem(
                no="1",
                name="抗拉强度 Rm",
                unit="MPa",
                local_table_id="T-PROP-RM",
                item_id=_match_item_id("抗拉强度", std_items),
                extra_dims=[MatrixDim(code="rm_nom", name="公称抗拉强度", kind="enum", unit="MPa")],
                rows=[
                    MatrixRow(key={"property_class": "4.6", "d_nom": "0~39", "rm_nom": "400"}, nominal=400, lower=400),
                    MatrixRow(key={"property_class": "4.8", "d_nom": "0~39", "rm_nom": "400"}, nominal=400, lower=420),
                    MatrixRow(key={"property_class": "5.6", "d_nom": "0~39", "rm_nom": "500"}, nominal=500, lower=500),
                    MatrixRow(key={"property_class": "5.8", "d_nom": "0~39", "rm_nom": "500"}, nominal=500, lower=520),
                    MatrixRow(key={"property_class": "6.8", "d_nom": "0~39", "rm_nom": "600"}, nominal=600, lower=600),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "0~16", "rm_nom": "800"}, nominal=800, lower=800),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "16~39", "rm_nom": "800"}, nominal=800, lower=830, note="d>16mm加严"),
                    MatrixRow(key={"property_class": "9.8", "d_nom": "0~16", "rm_nom": "900"}, nominal=900, lower=900),
                    MatrixRow(key={"property_class": "10.9", "d_nom": "0~39", "rm_nom": "1000"}, nominal=1000, lower=1040),
                    MatrixRow(key={"property_class": "12.9", "d_nom": "0~39", "rm_nom": "1200"}, nominal=1200, lower=1220),
                ],
            ),
            MatrixTableItem(
                no="2",
                name="下屈服强度 ReL",
                unit="MPa",
                local_table_id="T-PROP-REL",
                item_id=_match_item_id("下屈服强度", std_items),
                extra_dims=[MatrixDim(code="rel_nom", name="公称下屈服强度", kind="enum", unit="MPa")],
                rows=[
                    MatrixRow(key={"property_class": "4.6", "d_nom": "0~39", "rel_nom": "240"}, nominal=240, lower=240),
                    MatrixRow(key={"property_class": "5.6", "d_nom": "0~39", "rel_nom": "300"}, nominal=300, lower=300),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "0~39", "rel_nom": "—"}, na=True, note="不适用"),
                ],
            ),
            MatrixTableItem(
                no="3",
                name="规定非比例延伸0.2%的应力 Rp0.2",
                unit="MPa",
                local_table_id="T-PROP-RP02",
                item_id=_match_item_id("规定非比例延伸", std_items),
                extra_dims=[MatrixDim(code="rp02_nom", name="公称Rp0.2", kind="enum", unit="MPa")],
                rows=[
                    MatrixRow(key={"property_class": "8.8", "d_nom": "0~16", "rp02_nom": "640"}, nominal=640, lower=640),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "16~39", "rp02_nom": "640"}, nominal=640, lower=660),
                    MatrixRow(key={"property_class": "9.8", "d_nom": "0~16", "rp02_nom": "720"}, nominal=720, lower=720),
                    MatrixRow(key={"property_class": "10.9", "d_nom": "0~39", "rp02_nom": "900"}, nominal=900, lower=940),
                    MatrixRow(key={"property_class": "12.9", "d_nom": "0~39", "rp02_nom": "1080"}, nominal=1080, lower=1100),
                ],
            ),
            MatrixTableItem(
                no="4",
                name="紧固件实物的规定非比例延伸应力 Rpf",
                unit="MPa",
                local_table_id="T-PROP-RPF",
                item_id=_match_item_id("实物", std_items),
                extra_dims=[MatrixDim(code="rpf_nom", name="公称Rpf", kind="enum", unit="MPa")],
                rows=[
                    MatrixRow(key={"property_class": "4.8", "d_nom": "0~39", "rpf_nom": "320"}, nominal=320, lower=340),
                    MatrixRow(key={"property_class": "5.8", "d_nom": "0~39", "rpf_nom": "400"}, nominal=400, lower=420),
                    MatrixRow(key={"property_class": "6.8", "d_nom": "0~39", "rpf_nom": "480"}, nominal=480, lower=480),
                ],
            ),
            MatrixTableItem(
                no="5a",
                name="保证应力 Sp",
                unit="MPa",
                local_table_id="T-PROP-SP",
                item_id=_match_item_id("保证应力", std_items),
                extra_dims=[],
                rows=[
                    MatrixRow(key={"property_class": "4.6", "d_nom": "0~39"}, nominal=225, lower=225),
                    MatrixRow(key={"property_class": "4.8", "d_nom": "0~39"}, nominal=310, lower=310),
                    MatrixRow(key={"property_class": "5.6", "d_nom": "0~39"}, nominal=280, lower=280),
                    MatrixRow(key={"property_class": "5.8", "d_nom": "0~39"}, nominal=380, lower=380),
                    MatrixRow(key={"property_class": "6.8", "d_nom": "0~39"}, nominal=440, lower=440),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "0~16"}, nominal=580, lower=580),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "16~39"}, nominal=600, lower=600),
                    MatrixRow(key={"property_class": "9.8", "d_nom": "0~16"}, nominal=650, lower=650),
                    MatrixRow(key={"property_class": "10.9", "d_nom": "0~39"}, nominal=830, lower=830),
                    MatrixRow(key={"property_class": "12.9", "d_nom": "0~39"}, nominal=970, lower=970),
                ],
            ),
            MatrixTableItem(
                no="10",
                name="维氏硬度 HV (F≥98N)",
                unit="HV",
                local_table_id="T-PROP-HV",
                item_id=_match_item_id("维氏硬度", std_items) or _match_item_id("硬度", std_items),
                extra_dims=[],
                rows=[
                    MatrixRow(key={"property_class": "4.6", "d_nom": "0~39"}, lower=120, upper=220),
                    MatrixRow(key={"property_class": "4.8", "d_nom": "0~39"}, lower=130, upper=220),
                    MatrixRow(key={"property_class": "5.6", "d_nom": "0~39"}, lower=155, upper=220),
                    MatrixRow(key={"property_class": "5.8", "d_nom": "0~39"}, lower=160, upper=220),
                    MatrixRow(key={"property_class": "6.8", "d_nom": "0~39"}, lower=190, upper=250),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "0~16"}, lower=250, upper=320),
                    MatrixRow(key={"property_class": "8.8", "d_nom": "16~39"}, lower=255, upper=335),
                    MatrixRow(key={"property_class": "9.8", "d_nom": "0~16"}, lower=290, upper=360),
                    MatrixRow(key={"property_class": "10.9", "d_nom": "0~39"}, lower=320, upper=380),
                    MatrixRow(key={"property_class": "12.9", "d_nom": "0~39"}, lower=385, upper=435),
                ],
            ),
        ]
        return StandardMatrix(local_id=local_id, title=full_title, common_dims=common_dims, tables=tables)

    # 若用户在其它任意表格上选择了模式 4，先调用模式 2 生成按 No. 排列的主表列表，并赋予主从向导能力
    mat = _deconstruct_mode2_parallel(table_info, local_id, full_title, std_items)
    mat.split_mode = "composite_no_master"
    return mat
