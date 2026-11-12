# -*- coding: utf-8 -*-
"""国家/行业标准复合大表通用协议与数据结构 (USMP: Universal Standard Matrix Protocol).

适用于：
  1. 人机协同向导录入
  2. OCR / 视觉大模型 (LLM) 结构化抽取
  3. 复杂大表向多维正交单指标限值表自动编译
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, List, Optional, Dict


@dataclass
class MatrixDim:
    """维度定义（公共自变量或指标专属自变量）。"""
    code: str                      # 参数代码，如 property_class, d_nom, rm_nom
    name: str                      # 中文名称，如 性能等级, 公称直径 d
    kind: str = "enum"             # 类型: enum (枚举值) | range (数值区间)
    unit: str = ""                 # 物理单位
    options: List[str] = field(default_factory=list) # 可选枚举列表


@dataclass
class MatrixRow:
    """限值明细行（在完整多维正交坐标下的判定点）。"""
    key: Dict[str, Any]            # 完整坐标字典，例如 {'property_class': '8.8', 'd_nom': [16, 39], 'rm_nom': '800'}
    nominal: Optional[float] = None # 标准给出的公称基准值
    lower: Optional[float] = None   # 限值下限 (min / ≥)
    upper: Optional[float] = None   # 限值上限 (max / ≤)
    lower_expr: str = ""           # 动态表达式下限（若有）
    upper_expr: str = ""           # 动态表达式上限（若有）
    na: bool = False               # 是否不适用/不要求 (如 '—')
    note: str = ""                 # 特殊备注（如 '仅记录', '大规格加严'）


@dataclass
class MatrixTableItem:
    """按 No 序号切分出的单指标限值主表实体。"""
    no: str                        # 序号，如 '1', '2', '5', '5b'
    name: str                      # 检项/指标名称，如 '抗拉强度 Rm'
    unit: str = ""                 # 检项单位，如 'MPa', 'N', 'HV', '%'
    local_table_id: str = ""       # 标准内唯一的子表代号，如 'T-PROP-RM'
    item_id: str = ""              # 绑定的标准检项 ID
    clause: str = ""               # 标准条款号，如 '9.1'
    extra_dims: List[MatrixDim] = field(default_factory=list) # 专属增量参数树
    rows: List[MatrixRow] = field(default_factory=list)       # 该指标对应的所有多维明细行

    def all_dimensions(self, common_dims: List[MatrixDim]) -> List[MatrixDim]:
        """合并表头公共自变量与该主表专属自变量。"""
        return list(common_dims) + list(self.extra_dims)


@dataclass
class StandardMatrix:
    """复合大表/母表整体实体。"""
    local_id: str                  # 母表代号，如 'M-PROP-TABLE3'
    title: str                     # 母表标题，如 'GB/T 3098.1 表3 螺栓机械和物理性能'
    common_dims: List[MatrixDim] = field(default_factory=list) # 表头公共参数池 (所有主表默认继承)
    tables: List[MatrixTableItem] = field(default_factory=list) # 按 No 序号排列的限值主表清单
    category: str = "性能"

    def to_dict(self) -> dict:
        return {
            "local_id": self.local_id,
            "title": self.title,
            "category": self.category,
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
