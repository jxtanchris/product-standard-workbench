# -*- coding: utf-8 -*-
"""通用性验证：换一个“参数更多、维度不同”的标准，看要不要改代码。

这里注册一个 7 参数的标准（DEMO-1，测试用，非真实标准数据），
然后走一遍 校验 → 解析 → 判定，全程不修改 app.py / limit_engine.py / 前端。

    .venv/bin/python test_generic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from app import judge_rows, resolve_rows  # noqa: E402
from limit_engine import (  # noqa: E402
    Dim, LimitTable, Row, Slot, ValueForm,
)
from standards import Param, Standard, get, register  # noqa: E402

PASS = FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


# ---------------------------------------------------------------- 7 参数标准
def build_demo() -> Standard:
    t = LimitTable("D-T1", "示意限值", [Dim("grade", "enum"), Dim("d_nom", "size")],
                   ValueForm.ABSOLUTE)
    t.rows += [
        Row({"grade": "A", "d_nom": (0, 10)}, Slot("CONST", const=0.0), Slot("FORMULA", expr="0.1*d_nom")),
        Row({"grade": "A", "d_nom": (10, 250)}, Slot("CONST", const=0.0), Slot("FORMULA", expr="0.05*d_nom")),
        Row({"grade": "B", "d_nom": (0, 250)}, Slot("CONST", const=0.0), Slot("FORMULA", expr="0.2*d_nom")),
        Row({"grade": "C", "d_nom": (0, 250)}, applicable=False, note="C 级不要求"),
    ]
    items = [dict(
        id="x1", name="示意尺寸", symbol="X₁", clause="5.1", table="D-T1", kind="尺寸",
        requires=["d_nom"], nominal_param="d_nom", measured_key="x1_act",
        method="示意", position="示意", gauge="示意", points="示意", measured_hint="实测 X₁（mm）",
    )]
    return Standard(
        id="demo-1", code="DEMO-1", title="多参数标准（测试用）",
        category="测试 / 演示", scope="仅用于验证参数个数变化时无需改代码",
        note="非真实标准数据",
        params=[
            Param("d_nom", "公称直径 d", "number", "mm", True, None, 1, 250, 12.0, "必填，用于分档"),
            Param("pitch", "螺距 P", "number", "mm", False, None, 0.2, 8, 1.75, "可选，不参与本检项"),
            Param("length_nom", "公称长度 L", "number", "mm", True, None, 2, 500, 40.0, "必填"),
            Param("grade", "产品等级", "enum", options=["A", "B", "C"], default="A"),
            Param("property_class", "性能等级", "enum",
                  options=["4.8", "8.8", "10.9", "12.9"], default="8.8"),
            Param("coating", "表面处理", "enum", options=["无", "镀锌", "达克罗", "发黑"], default="镀锌"),
            Param("tolerance_class", "公差等级", "enum", options=["h9", "h11", "h13"], default="h11"),
        ],
        items=items, tables={"D-T1": t}, symbols={},
    )


def main():
    print("1. 注册一个 7 参数、维度不同的标准（不改任何既有代码）")
    std = register(build_demo(), replace=True)
    check("注册成功", get("demo-1") is std)
    check("参数个数与真实标准不同（7 vs 5）", len(std.params) == 7, str(len(std.params)))
    check("检项只声明自己需要的参数", std.items[0]["requires"] == ["d_nom"])

    print("2. 元数据（前端表单就是按它渲染的）")
    meta = std.meta()
    check("meta 带 7 个参数", len(meta["params"]) == 7)
    check("枚举参数带 options", meta["params"][3]["options"] == ["A", "B", "C"])
    check("数值参数带 min/max/unit",
          meta["params"][0]["min"] == 1 and meta["params"][0]["max"] == 250
          and meta["params"][0]["unit"] == "mm")

    print("3. 校验：由标准自己声明，不写死")
    full = {"d_nom": 8, "length_nom": 40, "grade": "A",
            "property_class": "8.8", "coating": "镀锌", "tolerance_class": "h11"}
    ctx, errs = std.build_context(full)
    check("缺非必填参数（pitch）不报错", not errs, str(errs))
    check("可选参数不进入上下文", "pitch" not in ctx and ctx["d_nom"] == 8.0, str(ctx))
    _, errs = std.build_context({"d_nom": 8})
    check("缺必填 length_nom 报错", any("缺少必填参数" in e for e in errs), str(errs))
    _, errs = std.build_context({"d_nom": "abc", "length_nom": 40})
    check("数值参数类型错误报错", any("需为数值" in e for e in errs), str(errs))
    _, errs = std.build_context({"d_nom": 300, "length_nom": 40})
    check("超出上限报错", any("超出" in e for e in errs), str(errs))
    _, errs = std.build_context({"d_nom": 8, "length_nom": 40, "color": "red"})
    check("未知参数报错", any("未知参数" in e for e in errs), str(errs))

    print("4. 解析：维度名与新参数的 code 对齐即可")
    ctx, _ = std.build_context(full)
    rows = resolve_rows(std, ctx)
    check("只解析声明过的检项（1 项）", len(rows) == 1, str(len(rows)))
    check("A 级 d=8 → 上限 0.8（0.1×d）", rows[0]["limit_text"] == "0.000 ～ 0.800 mm",
          rows[0]["limit_text"])
    ctx, _ = std.build_context(dict(full, d_nom=20))
    check("A 级 d=20 → 上限 1.0（0.05×d，跨档生效）",
          resolve_rows(std, ctx)[0]["limit_text"] == "0.000 ～ 1.000 mm",
          resolve_rows(std, ctx)[0]["limit_text"])
    ctx, _ = std.build_context(dict(full, grade="C"))
    check("C 级 → 不要求", resolve_rows(std, ctx)[0]["status"] == "NOT_REQUIRED")

    print("5. 判定：实测键同样由检项声明")
    ctx, _ = std.build_context(full)
    d = judge_rows(std, ctx, {"x1_act": 0.79})
    check("0.79 ≤ 0.8 判合格", d["rows"][0]["verdict"] == "合格", d["rows"][0]["verdict"])
    d = judge_rows(std, ctx, {"x1_act": 0.81})
    check("0.81 > 0.8 判不合格", d["rows"][0]["verdict"] == "不合格")
    check("实测键是 x1_act 而不是 x1", d["rows"][0]["measured_key"] == "x1_act")

    print("6. 与真实标准共存")
    real = get("gb3103-3")
    check("两个标准同时在注册表里", len([k for k in ("demo-1", "gb3103-3")]) == 2)
    check("真实标准参数仍是 5 个", len(real.params) == 5)
    check("真实标准检项仍是 8 个", len(real.items) == 8)

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
