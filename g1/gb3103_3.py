# -*- coding: utf-8 -*-
"""GB/T 3103.3—2000 的限值表建模 + 解析验证。

把标准表 1 的 8 张查询表全部建成数据，用引擎跑出结果，并与人工查表结果逐项比对。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from limit_engine import (  # noqa: E402
    Dim, LimitTable, Row, Slot, Status, SymbolEntry, SymbolKind, SymbolSet, ValueForm,
)

BINS = [(0, 3), (3, 6), (6, 10), (10, 18), (18, 30), (30, 50),
        (50, 80), (80, 120), (120, 180), (180, 250)]


def build_gb1800() -> dict[str, SymbolSet]:
    """GB/T 1800.4 摘录：IT 值 + 常用公差带（仅本样例用到的部分）。"""
    it = {12: [0.10, 0.12, 0.15, 0.18, 0.21, 0.25, 0.30, 0.35, 0.40, 0.46],
          13: [0.14, 0.18, 0.22, 0.27, 0.33, 0.39, 0.46, 0.54, 0.63, 0.72],
          15: [0.40, 0.48, 0.58, 0.70, 0.84, 1.00, 1.20, 1.40, 1.60, 1.85],
          16: [0.60, 0.75, 0.90, 1.10, 1.30, 1.60, 1.90, 2.20, 2.50, 2.90]}
    holes = {"H13": [0.14, 0.18, 0.22, 0.27, 0.33, 0.39, 0.46, 0.54, 0.63, 0.72],
             "H14": [0.25, 0.30, 0.36, 0.43, 0.52, 0.62, 0.74, 0.87, 1.00, 1.15],
             "H15": [0.40, 0.48, 0.58, 0.70, 0.84, 1.00, 1.20, 1.40, 1.60, 1.85]}
    shafts = {"h14": [0.25, 0.30, 0.36, 0.43, 0.52, 0.62, 0.74, 0.87, 1.00, 1.15],
              "h15": [0.40, 0.48, 0.58, 0.70, 0.84, 1.00, 1.20, 1.40, 1.60, 1.85],
              "h16": [0.60, 0.75, 0.90, 1.10, 1.30, 1.60, 1.90, 2.20, 2.50, 2.90]}

    ss = SymbolSet("gb1800", "GB/T 1800.2~1800.4-1998 极限与配合", "1998")
    for grade, vals in it.items():
        for (a, b), v in zip(BINS, vals):
            ss.add(SymbolEntry(f"IT{grade}", a, b, SymbolKind.TOLERANCE, tol=v))
    for code, vals in holes.items():
        for (a, b), v in zip(BINS, vals):
            ss.add(SymbolEntry(code, a, b, SymbolKind.DEVIATION, lower_dev=0.0, upper_dev=v))
    for code, vals in shafts.items():
        for (a, b), v in zip(BINS, vals):
            ss.add(SymbolEntry(code, a, b, SymbolKind.DEVIATION, lower_dev=-v, upper_dev=0.0))
    return {"gb1800": ss}


GB = build_gb1800()
S = "gb1800"


def sym(code: str, basis: str, part: str, mult: float = 1.0) -> Slot:
    return Slot("SYMBOL", symbol=f"{S}:{code}", mult=mult, basis=basis)


def const(v: float) -> Slot:
    return Slot("CONST", const=v)


def formula(e: str) -> Slot:
    return Slot("FORMULA", expr=e)


def binrow(grade: str, band: tuple[float, float], lower, upper,
           applicable: bool = True) -> Row:
    return Row({"grade": grade, "band": band}, lower, upper, applicable)


# ------------------------------------------------------------------ 8 张表
def table_thickness() -> LimitTable:
    t = LimitTable("T-H", "厚度 h 公差", [Dim("grade", "enum"), Dim("h_nom", "size")],
                   ValueForm.DEVIATION, nominal_param="h_nom")
    a = [0.05, 0.1, 0.2, 0.3, 0.6, 1, 1.2]
    c = [0.1, 0.2, 0.3, 0.6, 1, 1.2, 1.6]
    bands = [(0, 0.5), (0.5, 1), (1, 2.5), (2.5, 4), (4, 6), (6, 10), (10, 20)]
    for b, va, vc in zip(bands, a, c):
        t.rows.append(Row({"grade": "A", "h_nom": b}, const(-va), const(va)))
        t.rows.append(Row({"grade": "C", "h_nom": b}, const(-vc), const(vc)))
    return t


def table_d1() -> LimitTable:
    t = LimitTable("T-D1", "通孔直径 d₁ 公差", [Dim("grade", "enum"), Dim("h_nom", "size")],
                   ValueForm.DEVIATION, nominal_param="d1_nom")
    # 关键：代号用 d1 自己的公称值去查尺寸段
    t.rows += [
        Row({"grade": "A", "h_nom": (0, 4)}, sym("H13", "d1_nom", "lower"), sym("H13", "d1_nom", "upper")),
        Row({"grade": "A", "h_nom": (4, 20)}, sym("H14", "d1_nom", "lower"), sym("H14", "d1_nom", "upper")),
        Row({"grade": "C", "h_nom": (0, 4)}, sym("H14", "d1_nom", "lower"), sym("H14", "d1_nom", "upper")),
        Row({"grade": "C", "h_nom": (4, 20)}, sym("H15", "d1_nom", "lower"), sym("H15", "d1_nom", "upper")),
    ]
    return t


def table_d2() -> LimitTable:
    t = LimitTable("T-D2", "外径 d₂ 公差", [Dim("grade", "enum"), Dim("h_nom", "size")],
                   ValueForm.DEVIATION, nominal_param="d2_nom")
    t.rows += [
        Row({"grade": "A", "h_nom": (0, 4)}, sym("h14", "d2_nom", "lower"), sym("h14", "d2_nom", "upper")),
        Row({"grade": "A", "h_nom": (4, 20)}, sym("h15", "d2_nom", "lower"), sym("h15", "d2_nom", "upper")),
        Row({"grade": "C", "h_nom": (0, 20)}, sym("h16", "d2_nom", "lower"), sym("h16", "d2_nom", "upper")),
    ]
    return t


def table_h1() -> LimitTable:
    t = LimitTable("T-H1", "孔部高度 h₁ 下限", [Dim("grade", "enum"), Dim("h_nom", "size")],
                   ValueForm.ABSOLUTE)
    t.rows += [
        Row({"grade": "A", "h_nom": (0, 4)}, formula("0.5*h_nom"), None),
        Row({"grade": "A", "h_nom": (4, 20)}, formula("0.3*h_nom"), None),
        Row({"grade": "C", "h_nom": (0, 20)}, applicable=False, note="标准未规定"),
    ]
    return t


def table_e() -> LimitTable:
    t = LimitTable("T-E", "倒角 e", [Dim("grade", "enum")], ValueForm.ABSOLUTE)
    t.rows += [
        Row({"grade": "A"}, formula("0.25*h_nom"), formula("0.5*h_nom")),
        Row({"grade": "C"}, applicable=False, note="C 级不要求"),
    ]
    return t


def table_dh() -> LimitTable:
    t = LimitTable("T-DH", "厚度不均匀度 Δh", [Dim("grade", "enum"), Dim("h_nom", "size")],
                   ValueForm.ABSOLUTE)
    vals = [0.025, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4]
    bands = [(0, 0.5), (0.5, 1), (1, 2.5), (2.5, 4), (4, 6), (6, 10), (10, 20)]
    for b, v in zip(bands, vals):
        t.rows.append(Row({"grade": "A", "h_nom": b}, const(0.0), const(v)))
    t.rows.append(Row({"grade": "C", "h_nom": (0, 20)}, applicable=False, note="C 级不要求"))
    return t


def table_t1() -> LimitTable:
    t = LimitTable("T-T1", "同轴度 t₁", [Dim("grade", "enum"), Dim("d2_nom", "size")],
                   ValueForm.ABSOLUTE)
    # 关键：代号用 d2 的分档，而不是 d1；且乘 2
    t.rows += [
        Row({"grade": "A", "d2_nom": (0, 50)}, const(0.0), sym("IT12", "d2_nom", "upper", 2.0)),
        Row({"grade": "A", "d2_nom": (50, 250)}, const(0.0), sym("IT13", "d2_nom", "upper", 2.0)),
        Row({"grade": "C", "d2_nom": (0, 50)}, const(0.0), sym("IT15", "d2_nom", "upper", 2.0)),
        Row({"grade": "C", "d2_nom": (50, 250)}, const(0.0), sym("IT16", "d2_nom", "upper", 2.0)),
    ]
    return t


def table_t2() -> LimitTable:
    t = LimitTable("T-T2", "平面度 t₂", [Dim("grade", "enum"), Dim("material", "enum"),
                                        Dim("h_nom", "size")], ValueForm.ABSOLUTE)
    plain = [0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 1.0]
    steel = [0.15, 0.22, 0.3, 0.45, 0.6, 0.9, 1.5]
    bands = [(0, 0.5), (0.5, 1), (1, 2.5), (2.5, 4), (4, 6), (6, 10), (10, 20)]
    for b, p, s in zip(bands, plain, steel):
        t.rows.append(Row({"grade": "A", "material": "非不锈钢", "h_nom": b}, const(0.0), const(p)))
        t.rows.append(Row({"grade": "A", "material": "不锈钢", "h_nom": b}, const(0.0), const(s)))
    t.rows.append(Row({"grade": "C", "material": "非不锈钢", "h_nom": (0, 20)},
                      applicable=False, note="C 级不要求"))
    return t


TABLES = {t.table_id: t for t in
          [table_thickness(), table_d1(), table_d2(), table_h1(),
           table_e(), table_dh(), table_t1(), table_t2()]}

# ------------------------------------------------------------------ 验证
CTX_A = {"grade": "A", "h_nom": 2.0, "d1_nom": 13.0, "d2_nom": 24.0, "material": "非不锈钢"}
CTX_C = dict(CTX_A, grade="C")

EXPECT = {
    "A": {"T-H": (1.8, 2.2, Status.OK), "T-D1": (13.00, 13.27, Status.OK),
          "T-D2": (23.48, 24.00, Status.OK), "T-H1": (1.0, None, Status.OK),
          "T-E": (0.5, 1.0, Status.OK), "T-DH": (0.0, 0.1, Status.OK),
          "T-T1": (0.0, 0.42, Status.OK), "T-T2": (0.0, 0.2, Status.OK)},
    "C": {"T-H": (1.7, 2.3, Status.OK), "T-D1": (13.00, 13.43, Status.OK),
          "T-D2": (22.70, 24.00, Status.OK), "T-H1": (None, None, Status.NOT_REQUIRED),
          "T-E": (None, None, Status.NOT_REQUIRED), "T-DH": (None, None, Status.NOT_REQUIRED),
          "T-T1": (0.0, 1.68, Status.OK), "T-T2": (None, None, Status.NOT_REQUIRED)},
}


def close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= 1e-9


def run_matrix(label: str, ctx: dict) -> tuple[bool, list[str]]:
    ok = True
    lines = []
    for tid, (elo, ehi, est) in EXPECT[label].items():
        r = TABLES[tid].evaluate(ctx, GB)
        good = (r.status is est and close(r.lower, elo) and close(r.upper, ehi))
        ok &= good
        lines.append(f"{'PASS' if good else 'FAIL'}  {tid:<5} {r!s:<28} 期望 "
                     f"{'<'+est.value+'>' if est is not Status.OK else f'[{elo}, {ehi}]'}")
    return ok, lines


def run_case(tid: str, ctx: dict, elo, ehi, est=Status.OK) -> tuple[bool, str]:
    r = TABLES[tid].evaluate(ctx, GB)
    good = r.status is est and close(r.lower, elo) and close(r.upper, ehi)
    return good, f"{'PASS' if good else 'FAIL'}  {tid:<5} {r!s:<28} trace: {'; '.join(r.trace)}"


if __name__ == "__main__":
    print("=== 1. A 级 / C 级全项 ===")
    allok = True
    for label, ctx in (("A", CTX_A), ("C", CTX_C)):
        ok, lines = run_matrix(label, ctx)
        allok &= ok
        print(f"\n[{label} 级] h=2, d1=13, d2=24, 非不锈钢")
        for l in lines:
            print("  " + l)

    print("\n=== 2. 边界与基准参数 ===")
    cases = [
        ("T-D1", dict(CTX_A, d1_nom=18.0), 18.0, 18.27),      # (10,18] 含 18
        ("T-D1", dict(CTX_A, d1_nom=18.01), 18.01, 18.34),    # (18,30] H13=0.33
        ("T-D2", dict(CTX_A, d2_nom=50.0), 49.38, 50.0),      # h14(30,50]=0.62
        ("T-D2", dict(CTX_A, d2_nom=50.1), 49.36, 50.1),      # h14(50,80]=0.74
        ("T-T1", dict(CTX_A, d2_nom=50.0), 0.0, 0.50),        # 2IT12(30,50]=0.5
        ("T-T1", dict(CTX_A, d2_nom=50.1), 0.0, 0.92),        # d2>50 -> 2IT13(50,80)=0.92
        ("T-H", dict(CTX_A, h_nom=2.5), 2.3, 2.7),            # (1,2.5] 含 2.5
        ("T-H", dict(CTX_A, h_nom=2.51), 2.21, 2.81),         # (2.5,4]
        ("T-T2", dict(CTX_A, material="不锈钢"), 0.0, 0.3),
        ("T-T2", dict(CTX_A, h_nom=0.3, material="不锈钢"), 0.0, 0.15),
        ("T-H1", dict(CTX_A, h_nom=6.0), 1.8, None),          # 0.3h
        ("T-T1", dict(CTX_A, d2_nom=300.0), None, None),      # 超出表范围
    ]
    for tid, ctx, elo, ehi in cases:
        est = Status.MISS if (elo is None and ehi is None) else Status.OK
        if est is Status.MISS:
            r = TABLES[tid].evaluate(ctx, GB)
            good = r.status is Status.MISS
            print(f"  {'PASS' if good else 'FAIL'}  {tid:<5} {r!s:<28} "
                  f"ctx d2={ctx['d2_nom']} -> 期望 MISS")
            allok &= good
        else:
            good, line = run_case(tid, ctx, elo, ehi, est)
            allok &= good
            print("  " + line)

    print("\n=== 3. 判定（实测值 vs 极限）===")
    r = TABLES["T-D1"].evaluate(CTX_A, GB)
    for measured in (12.99, 13.00, 13.15, 13.27, 13.28):
        verdict = "合格" if r.lower <= measured <= r.upper else "不合格"
        print(f"  d1 实测 {measured:>6.2f} -> {verdict}（限 {r.lower:.2f}~{r.upper:.2f}）")
    r2 = TABLES["T-H1"].evaluate(CTX_A, GB)
    for measured in (0.9, 1.0):
        verdict = "合格" if measured >= r2.lower else "不合格"
        print(f"  h1 实测 {measured:>6.2f} -> {verdict}（下限 {r2.lower:.2f}）")

    print("\n总结果:", "ALL PASS" if allok else "有 FAIL")
    sys.exit(0 if allok else 1)
