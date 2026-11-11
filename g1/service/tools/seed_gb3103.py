# -*- coding: utf-8 -*-
"""把 GB/T 3103.3—2000 的限值录成"随参数变化"的规则，发布成一个自定义标准。

这不是给用户用的工具，而是演示数据：证明第一步录入的规则能在第二步按参数算对。
限值全部取自标准的表 1 与附录 A，由符号表生成，不手抄。
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE.parent))   # g1/
sys.path.insert(0, str(SERVICE))          # g1/service/

from gb3103_3 import GB  # noqa: E402

BINS = [(0, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50),
        (50, 80), (80, 120), (120, 180), (180, 250)]
HBINS = [(0, 0.5), (0.5, 1), (1, 2.5), (2.5, 4), (4, 6), (6, 10), (10, 20)]


def dev(code: str, size: float, part: str) -> float:
    ss = GB["gb1800"]
    v = ss.lookup(code, size, part)
    if v is None:
        raise KeyError(f"{code}@{size}")
    return v


def tol(code: str, size: float) -> float:
    return dev(code, size, "upper")


def rules_for_hole() -> list[dict]:
    """3.1 通孔 d₁：A 级 h≤4→H13/h>4→H14；C 级 H14/H15。上限 = d_nom + 偏差。"""
    out = []
    for grade, small, large in (("A", "H13", "H14"), ("C", "H14", "H15")):
        for (_, hi) in BINS:
            mid = hi if grade == "A" else hi
            out.append({"if": f'grade=="{grade}" and h_nom<=4 and d_nom<={hi}',
                        "lower": "d_nom", "upper": f"d_nom+{dev(small, mid, 'upper'):g}"})
        for (_, hi) in BINS:
            out.append({"if": f'grade=="{grade}" and h_nom>4 and d_nom<={hi}',
                        "lower": "d_nom", "upper": f"d_nom+{dev(large, hi, 'upper'):g}"})
    return out


def rules_for_od() -> list[dict]:
    """3.2 外径 d₂：A 级 h≤4→h14/h>4→h15；C 级 h16。下限 = d2_nom − 偏差。"""
    out = []
    for grade, small, large in (("A", "h14", "h15"), ("C", "h16", "h16")):
        for (_, hi) in BINS:
            out.append({"if": f'grade=="{grade}" and (h_nom<=4 or grade=="C") and d2_nom<={hi}',
                        "lower": f"d2_nom-{abs(dev(small, hi, 'lower')):g}", "upper": "d2_nom"})
        for (_, hi) in BINS:
            out.append({"if": f'grade=="{grade}" and h_nom>4 and d2_nom<={hi}',
                        "lower": f"d2_nom-{abs(dev(large, hi, 'lower')):g}", "upper": "d2_nom"})
    return out


def rules_thickness() -> list[dict]:
    a = [0.05, 0.1, 0.2, 0.3, 0.6, 1, 1.2]
    c = [0.1, 0.2, 0.3, 0.6, 1, 1.2, 1.6]
    out = []
    for b, va, vc in zip(HBINS, a, c):
        out.append({"if": f'grade=="A" and h_nom<={b[1]}', "lower": f"h_nom-{va:g}", "upper": f"h_nom+{va:g}"})
        out.append({"if": f'grade=="C" and h_nom<={b[1]}', "lower": f"h_nom-{vc:g}", "upper": f"h_nom+{vc:g}"})
    return out


def rules_dh() -> list[dict]:
    a = [0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
    return [{"if": f'h_nom<={b[1]}', "lower": "0", "upper": f"{v:g}"}
            for b, v in zip(HBINS, a)]


def rules_t1() -> list[dict]:
    out = []
    for (_, hi) in BINS:
        if hi <= 30:
            pass
        out.append({"if": f'grade=="A" and d2_nom<=50 and d2_nom<={hi}',
                    "lower": "0", "upper": f"{2 * tol('IT12', hi):g}"})
        out.append({"if": f'grade=="A" and d2_nom>50 and d2_nom<={hi}',
                    "lower": "0", "upper": f"{2 * tol('IT13', hi):g}"})
        out.append({"if": f'grade=="C" and d2_nom<=50 and d2_nom<={hi}',
                    "lower": "0", "upper": f"{2 * tol('IT15', hi):g}"})
        out.append({"if": f'grade=="C" and d2_nom>50 and d2_nom<={hi}',
                    "lower": "0", "upper": f"{2 * tol('IT16', hi):g}"})
    return out


def rules_t2() -> list[dict]:
    plain = [0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 1.0]
    steel = [0.15, 0.22, 0.3, 0.45, 0.6, 0.9, 1.5]
    out = []
    for b, p, s in zip(HBINS, plain, steel):
        out.append({"if": f'material=="非不锈钢" and h_nom<={b[1]}', "lower": "0", "upper": f"{p:g}"})
        out.append({"if": f'material=="不锈钢" and h_nom<={b[1]}', "lower": "0", "upper": f"{s:g}"})
    return out


PARAMS = [
    {"code": "d_nom", "name": "通孔公称直径 d₁", "type": "number", "unit": "mm",
     "required": True, "min": 1, "max": 150},
    {"code": "d2_nom", "name": "外径公称 d₂", "type": "number", "unit": "mm",
     "required": True, "min": 1, "max": 250},
    {"code": "h_nom", "name": "公称厚度 h", "type": "number", "unit": "mm",
     "required": True, "min": 0.1, "max": 20},
    {"code": "grade", "name": "产品等级", "type": "enum", "options": ["A", "C"],
     "default": "A", "required": True},
    {"code": "material", "name": "材料类型", "type": "enum",
     "options": ["非不锈钢", "不锈钢"], "default": "非不锈钢", "required": True},
]


def main(base: str = "http://127.0.0.1:8022") -> int:
    payload = {
        "id": "custom-gb3103",
        "code": "GB/T 3103.3-2000",
        "title": "紧固件公差 平垫圈（规则版）",
        "category": "机械 / 紧固件产品 / 垫圈",
        "note": "限值随 d₁、d₂、h、等级、材料实时计算",
        "params": PARAMS,
        "items": [
            {"id": "d1", "title": "通孔（冲压）", "clause": "3.1", "category": "尺寸", "selected": True},
            {"id": "d2", "title": "外径（冲压）", "clause": "3.2", "category": "尺寸", "selected": True},
            {"id": "h", "title": "厚度", "clause": "3.3", "category": "尺寸", "selected": True},
            {"id": "e", "title": "倒角", "clause": "3.4", "category": "尺寸", "selected": True},
            {"id": "dh", "title": "同一部位厚度不均匀度", "clause": "3.5.1", "category": "形位", "selected": True},
            {"id": "t1", "title": "同轴度", "clause": "3.5.2", "category": "形位", "selected": True},
            {"id": "t2", "title": "平面度", "clause": "3.5.3", "category": "形位", "selected": True},
        ],
        "limits": {
            "d1": {"mode": "rule", "unit": "mm", "rules": rules_for_hole()},
            "d2": {"mode": "rule", "unit": "mm", "rules": rules_for_od()},
            "h": {"mode": "rule", "unit": "mm", "rules": rules_thickness()},
            "e": {"mode": "rule", "unit": "mm", "rules": [
                {"if": 'grade=="C"', "na": True},
                {"lower": "0.25*h_nom", "upper": "0.5*h_nom"}]},
            "dh": {"mode": "rule", "unit": "mm", "rules": [{"if": 'grade=="C"', "na": True}] + rules_dh()},
            "t1": {"mode": "rule", "unit": "mm", "rules": rules_t1()},
            "t2": {"mode": "rule", "unit": "mm", "rules": [{"if": 'grade=="C"', "na": True}] + rules_t2()},
        },
        "source": {"note": "由测试脚本生成，限值取自 GB/T 3103.3 表 1 与附录 A"},
    }
    req = urllib.request.Request(
        base + "/api/standards/publish",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        print(json.loads(r.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8022"))
