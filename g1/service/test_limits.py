# -*- coding: utf-8 -*-
"""限值随参数变化的验证：常量 / 公式 / 规则 / 不要求 / 未命中。

不需要服务，直接建标准求值。

    .venv/bin/python test_limits.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

from limit_engine import Status  # noqa: E402
from standards import build_from_payload  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def close(a, b):
    if a is None or b is None:
        return a is b
    return abs(a - b) < 1e-9


STD = build_from_payload({
    "id": "t-limits", "code": "TEST", "title": "限值形态测试",
    "params": [
        {"code": "d_nom", "name": "公称直径", "type": "number", "unit": "mm", "required": True},
        {"code": "h_nom", "name": "公称厚度", "type": "number", "unit": "mm", "required": True},
        {"code": "grade", "name": "等级", "type": "enum", "options": ["A", "C"], "default": "A"},
    ],
    "items": [
        {"id": "const", "title": "常量项", "clause": "1.1", "selected": True},
        {"id": "expr", "title": "公式项", "clause": "1.2", "selected": True},
        {"id": "rule", "title": "规则项", "clause": "1.3", "selected": True},
        {"id": "na", "title": "可豁免项", "clause": "1.4", "selected": True},
        {"id": "miss", "title": "未覆盖项", "clause": "1.5", "selected": True},
    ],
    "limits": {
        "const": {"mode": "range", "lower": 1.0, "upper": 2.0, "unit": "mm"},
        "expr": {"mode": "range", "lower": "0.25*h_nom", "upper": "0.5*h_nom", "unit": "mm"},
        "rule": {"mode": "rule", "unit": "mm", "rules": [
            {"if": 'grade=="C"', "na": True},
            {"if": "h_nom<=4 and d_nom<=18", "lower": "d_nom", "upper": "d_nom+0.27"},
            {"if": "h_nom>4 and d_nom<=18", "lower": "d_nom", "upper": "d_nom+0.43"},
            {"lower": "d_nom", "upper": "d_nom+1"},
        ]},
        "na": {"mode": "rule", "unit": "mm", "rules": [{"if": 'grade=="C"', "na": True}]},
        "miss": {"mode": "rule", "unit": "mm", "rules": [
            {"if": "d_nom>1000", "lower": "0", "upper": "1"},
        ]},
    },
})


def ev(item_id, **ctx):
    return STD.tables[f"L-{item_id}"].evaluate(ctx, {})


def main():
    print("1. 常量限值：不随参数变")
    r = ev("const", d_nom=13, h_nom=2, grade="A")
    check("13/2 → 1.000～2.000", close(r.lower, 1.0) and close(r.upper, 2.0), str(r))
    r = ev("const", d_nom=18, h_nom=6, grade="A")
    check("18/6 → 仍是 1.000～2.000", close(r.lower, 1.0) and close(r.upper, 2.0), str(r))

    print("2. 公式限值：随参数变")
    r = ev("expr", d_nom=13, h_nom=2, grade="A")
    check("h=2 → 0.500～1.000", close(r.lower, 0.5) and close(r.upper, 1.0), str(r))
    r = ev("expr", d_nom=18, h_nom=6, grade="A")
    check("h=6 → 1.500～3.000", close(r.lower, 1.5) and close(r.upper, 3.0), str(r))

    print("3. 规则限值：随参数与等级变")
    r = ev("rule", d_nom=13, h_nom=2, grade="A")
    check("d=13,h=2,A → 13.000～13.270", close(r.lower, 13.0) and close(r.upper, 13.27), str(r))
    r = ev("rule", d_nom=18, h_nom=6, grade="A")
    check("d=18,h=6,A → 18.000～18.430", close(r.lower, 18.0) and close(r.upper, 18.43), str(r))
    r = ev("rule", d_nom=18, h_nom=6, grade="C")
    check("C 级 → 不要求", r.status is Status.NOT_REQUIRED, str(r))
    check("轨迹里能看到命中的规则", any("命中规则" in t for t in r.trace), str(r.trace))

    print("4. 不要求 vs 未命中")
    check("C 级豁免项 → NOT_REQUIRED", ev("na", d_nom=13, h_nom=2, grade="C").status
          is Status.NOT_REQUIRED)
    check("A 级无匹配规则 → MISS", ev("na", d_nom=13, h_nom=2, grade="A").status is Status.MISS)
    r = ev("miss", d_nom=13, h_nom=2, grade="A")
    check("没有规则覆盖 → MISS 且提示", r.status is Status.MISS and r.trace, str(r.trace))

    print("5. 表达式安全")
    bad = build_from_payload({
        "code": "X", "title": "X", "params": [],
        "items": [{"id": "z", "title": "z", "clause": "9", "selected": True}],
        "limits": {"z": {"mode": "range", "lower": "__import__('os').system('ls')", "upper": "1"}},
    })
    raised = False
    try:
        bad.tables["L-z"].evaluate({}, {})
    except Exception:
        raised = True
    check("非白名单表达式被拒绝执行", raised)

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
