# -*- coding: utf-8 -*-
"""把 GB/T 3103.3—2000 的数据填进数据库。

填的是四张业务表：
  ① standard   —— 标准本身与规格参数
  ② limit_table/limit_dim/limit_row —— 标准表 1 拆成的 8 张多维限值表
  ③ standard.item_json —— 8 个检项
数据来源：标准表 1 + 附录 A 的 IT 值与极限偏差表（由符号表生成，不手抄）。

    .venv/bin/python g1/service/tools/load_gb3103.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE.parent))   # g1/
sys.path.insert(0, str(SERVICE))          # g1/service/

import db  # noqa: E402
from gb3103_3 import GB  # noqa: E402

BINS = [(0, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50),
        (50, 80), (80, 120), (120, 180), (180, 250)]
HBINS = [(0, 0.5), (0.5, 1), (1, 2.5), (2.5, 4), (4, 6), (6, 10), (10, 20)]
HSPLIT = [(0, 4), (4, 20)]          # 3.1/3.2 按 h≤4 与 h>4 分叉

SS = GB["gb1800"]


def dev(code: str, size: float, part: str) -> float:
    v = SS.lookup(code, size, part)
    if v is None:
        raise KeyError(f"{code}@{size}")
    return round(v, 4)


def table(tid, name, item_code, dims, value_form="absolute", nominal=None):
    return {"id": tid, "name": name, "item_code": item_code, "unit": "mm",
            "value_form": value_form, "nominal_param": nominal, "dims": dims, "rows": []}


D_GRADE = {"code": "grade", "kind": "enum", "values": ["A", "C"]}
D_MAT = {"code": "material", "kind": "enum", "values": ["非不锈钢", "不锈钢"]}
D_H = {"code": "h_nom", "kind": "range", "values": [[0, 4], [4, 20]]}


def t_d1():
    t = table("T-D1", "通孔直径 d₁ 公差（H13/H14/H15）", "d1",
              [D_GRADE, D_H, {"code": "d1_nom", "kind": "range", "values": [list(b) for b in BINS]}],
              value_form="deviation", nominal="d1_nom")
    plan = {"A": {True: "H13", False: "H14"}, "C": {True: "H14", False: "H15"}}
    for grade in ("A", "C"):
        for small, (lo, hi) in zip((True, False), HSPLIT):
            code = plan[grade][small]
            for (a, b) in BINS:
                t["rows"].append({
                    "key": {"grade": grade, "h_nom": [lo, hi], "d1_nom": [a, b]},
                    "lower": dev(code, b, "lower"), "upper": dev(code, b, "upper"),
                    "note": f"{code} @ ({a}, {b}]"})
    return t


def t_d2():
    t = table("T-D2", "外径 d₂ 公差（h14/h15/h16）", "d2",
              [D_GRADE, D_H, {"code": "d2_nom", "kind": "range", "values": [list(b) for b in BINS]}],
              value_form="deviation", nominal="d2_nom")
    plan = {"A": {True: "h14", False: "h15"}, "C": {True: "h16", False: "h16"}}
    for grade in ("A", "C"):
        for small, (lo, hi) in zip((True, False), HSPLIT):
            code = plan[grade][small]
            for (a, b) in BINS:
                t["rows"].append({
                    "key": {"grade": grade, "h_nom": [lo, hi], "d2_nom": [a, b]},
                    "lower": dev(code, b, "lower"), "upper": dev(code, b, "upper"),
                    "note": f"{code} @ ({a}, {b}]"})
    return t


def t_h():
    a = [0.05, 0.1, 0.2, 0.3, 0.6, 1, 1.2]
    c = [0.1, 0.2, 0.3, 0.6, 1, 1.2, 1.6]
    t = table("T-H", "厚度 h 公差", "h", [D_GRADE, {"code": "h_nom", "kind": "range", "values": [list(b) for b in HBINS]}],
              value_form="deviation", nominal="h_nom")
    for grade, vals in (("A", a), ("C", c)):
        for (lo, hi), v in zip(HBINS, vals):
            t["rows"].append({"key": {"grade": grade, "h_nom": [lo, hi]},
                              "lower": -v, "upper": v})
    return t


def t_h1():
    t = table("T-H1", "孔部高度 h₁ 下限", "h1",
              [D_GRADE, {"code": "h_nom", "kind": "range", "values": [list(b) for b in HBINS]}])
    for (lo, hi), expr in zip(HSPLIT, ("0.5*h_nom", "0.3*h_nom")):
        t["rows"].append({"key": {"grade": "A", "h_nom": [lo, hi]}, "lower_expr": expr})
    t["rows"].append({"key": {"grade": "C", "h_nom": [0, 20]}, "na": True, "note": "C 级未规定"})
    return t


def t_e():
    t = table("T-E", "倒角 e、α", "e", [D_GRADE])
    t["rows"].append({"key": {"grade": "A"},
                      "lower_expr": "0.25*h_nom", "upper_expr": "0.5*h_nom",
                      "note": "另需确认 α=30°~45°"})
    t["rows"].append({"key": {"grade": "C"}, "na": True, "note": "C 级不要求"})
    return t


def t_dh():
    vals = [0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
    t = table("T-DH", "同一部位厚度不均匀度 Δh", "dh",
              [D_GRADE, {"code": "h_nom", "kind": "range", "values": [list(b) for b in HBINS]}])
    for (lo, hi), v in zip(HBINS, vals):
        t["rows"].append({"key": {"grade": "A", "h_nom": [lo, hi]}, "lower": 0.0, "upper": v})
    t["rows"].append({"key": {"grade": "C", "h_nom": [0, 20]}, "na": True, "note": "C 级不要求"})
    return t


def t_t1():
    t = table("T-T1", "同轴度 t₁（2IT12/2IT13/2IT15/2IT16）", "t1",
              [D_GRADE, {"code": "d2_nom", "kind": "range", "values": [list(b) for b in BINS]}])
    for grade in ("A", "C"):
        for (a, b) in BINS:
            if grade == "A":
                code = "IT12" if b <= 50 else "IT13"
            else:
                code = "IT15" if b <= 50 else "IT16"
            t["rows"].append({"key": {"grade": grade, "d2_nom": [a, b]},
                              "lower": 0.0, "upper": round(2 * dev(code, b, "upper"), 4),
                              "note": f"2×{code} @ ({a}, {b}]"})
    return t


def t_t2():
    plain = [0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 1.0]
    steel = [0.15, 0.22, 0.3, 0.45, 0.6, 0.9, 1.5]
    t = table("T-T2", "平面度 t₂", "t2",
              [D_GRADE, D_MAT, {"code": "h_nom", "kind": "range", "values": [list(b) for b in HBINS]}])
    for mat, vals in (("非不锈钢", plain), ("不锈钢", steel)):
        for (lo, hi), v in zip(HBINS, vals):
            t["rows"].append({"key": {"grade": "A", "material": mat, "h_nom": [lo, hi]},
                              "lower": 0.0, "upper": v})
    t["rows"].append({"key": {"grade": "C", "material": "非不锈钢", "h_nom": [0, 20]},
                      "na": True, "note": "C 级不要求"})
    t["rows"].append({"key": {"grade": "C", "material": "不锈钢", "h_nom": [0, 20]},
                      "na": True, "note": "C 级不要求"})
    return t


PARAMS = [
    {"code": "grade", "name": "产品等级", "type": "enum", "unit": "",
     "required": True, "options": ["A", "C"], "default": "A",
     "help": "决定检项数量：C 级不要求 h₁、倒角、Δh、t₂"},
    {"code": "material", "name": "材料类型", "type": "enum", "unit": "",
     "required": True, "options": ["非不锈钢", "不锈钢"], "default": "非不锈钢",
     "help": "影响平面度 t₂"},
    {"code": "h_nom", "name": "公称厚度 h", "type": "number", "unit": "mm",
     "required": True, "min": 0.1, "max": 20, "default": 2.0,
     "help": "决定 d₁、d₂、Δh、t₂ 的分档"},
    {"code": "d1_nom", "name": "通孔公称直径 d₁", "type": "number", "unit": "mm",
     "required": False, "min": 1, "max": 150, "default": 13.0,
     "help": "通孔公差按此查档"},
    {"code": "d2_nom", "name": "外径公称 d₂", "type": "number", "unit": "mm",
     "required": False, "min": 1, "max": 250, "default": 24.0,
     "help": "外径与同轴度按此查档"},
]

ITEMS = [
    {"id": "d1", "name": "通孔直径", "page": 4, "symbol": "d₁", "clause": "3.1", "table": "T-D1",
     "kind": "尺寸", "measured_key": "d1_act", "measured_hint": "实测 d₁（mm）",
     "method": "塞规通止；计量用内径千分尺在互相垂直两方向测量",
     "position": "孔壁圆柱直段（h₁ 段）内，避开塌边", "gauge": "塞规、内径千分尺(0.01)"},
    {"id": "h1", "name": "孔部高度", "page": 4, "symbol": "h₁", "clause": "3.1", "table": "T-H1",
     "kind": "尺寸", "measured_key": "h1_act", "measured_hint": "实测 h₁（mm）",
     "method": "投影仪 5∶1 放大测孔壁直段", "position": "不含塌边与撕裂带",
     "gauge": "投影仪、工具显微镜"},
    {"id": "d2", "name": "外径", "page": 4, "symbol": "d₂", "clause": "3.2", "table": "T-D2",
     "kind": "尺寸", "measured_key": "d2_act", "measured_hint": "实测 d₂（mm）",
     "method": "外径千分尺两方向测量取最大最小", "position": "d₂ 圆柱面，避开塌边",
     "gauge": "外径千分尺(0.01)"},
    {"id": "h", "name": "厚度", "page": 4, "symbol": "h", "clause": "3.3", "table": "T-H",
     "kind": "尺寸", "measured_key": "h_act", "measured_hint": "实测 h（mm）",
     "method": "外径千分尺平测头，镀前状态", "position": "带宽中部，避开倒角与塌边",
     "gauge": "外径千分尺(0.01)"},
    {"id": "e", "name": "倒角", "page": 4, "symbol": "e、α", "clause": "3.4", "table": "T-E",
     "kind": "尺寸", "measured_key": "e_act", "measured_hint": "实测 e（mm）",
     "method": "投影仪测倒角轴向宽度 e 与角度 α", "position": "圆周抽测 2~3 处",
     "gauge": "投影仪、角度尺"},
    {"id": "dh", "name": "同一部位厚度不均匀度", "page": 5, "symbol": "Δh", "clause": "3.5.1", "table": "T-DH",
     "kind": "形位", "measured_key": "dh_act", "measured_hint": "实测 Δh（mm）",
     "method": "中间带内圆周均布 ≥3 处，取 h_max−h_min",
     "position": "距孔边与外缘各 x=0.1(d₂−d₁) 的中间带", "gauge": "千分尺(0.001)、测厚夹具"},
    {"id": "t1", "name": "同轴度", "page": 5, "symbol": "t₁", "clause": "3.5.2", "table": "T-T1",
     "kind": "形位", "measured_key": "t1_act", "measured_hint": "同轴度误差（mm）",
     "method": "CMM 测内外圆柱按 GB/T 1182 评定；批量用心轴+百分表",
     "position": "基准 A 为 φd₂ 外圆轴线", "gauge": "三坐标、同轴度检具"},
    {"id": "t2", "name": "平面度", "page": 5, "symbol": "t₂", "clause": "3.5.3", "table": "T-T2",
     "kind": "形位", "measured_key": "t2_act", "measured_hint": "平面度误差（mm）",
     "method": "去毛刺后自由置于 0 级平板，塞尺/百分表测最大间隙",
     "position": "整件自由状态", "gauge": "0 级平板、塞尺、百分表"},
]


def payload() -> dict:
    tables = [t_d1(), t_d2(), t_h(), t_h1(), t_e(), t_dh(), t_t1(), t_t2()]
    return {
        "id": "gb3103-3", "code": "GB/T 3103.3—2000", "title": "紧固件公差  平垫圈",
        "category": "机械 / 紧固件产品 / 垫圈",
        "scope": "螺纹公称直径 1～150 mm 的螺栓、螺钉和螺母用 A 级、C 级冲压平垫圈",
        "note": "公差适用于镀前尺寸（GB/T 5267）",
        "custom": 0,
        "source": {"standard": "GB/T 3103.3—2000", "tables": "表 1、附录 A"},
        "params": PARAMS, "items": ITEMS,
        "tables": tables, "limits": {},
    }


def main() -> int:
    conn = db.connect()
    data = payload()
    db.save_payload(conn, data)
    rows = sum(len(t["rows"]) for t in data["tables"])
    print(f"已写入 {data['id']}：{len(data['params'])} 参数 / {len(data['items'])} 检项 / "
          f"{len(data['tables'])} 张限值表 / {rows} 行")
    print("库统计:", db.stats(conn))
    for t in data["tables"]:
        dims = " × ".join(d["code"] for d in t["dims"]) or "（无维度）"
        print(f"  {t['id']:<6} {t['name'][:26]:<28} 维度 {dims:<48} {len(t['rows']):>3} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
