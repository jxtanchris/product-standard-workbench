# -*- coding: utf-8 -*-
"""限值解析引擎原型（G1 验证）。

支撑四类限值：常量 / 代号 / 公式 / 引用
外加三项必要语义：三态结果、偏差 vs 绝对值、代号解析的基准参数。
仅用标准库，可直接运行。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------- 结果三态
class Status(str, Enum):
    OK = "OK"                     # 有值，可判定
    NOT_REQUIRED = "NOT_REQUIRED"  # 标准明确"不要求"（如 C 级），跳过判定
    UNSPECIFIED = "UNSPECIFIED"    # 标准"尚未规定"，只记录不判废
    MISS = "MISS"                  # 上下文不完整 / 尺寸超出表覆盖范围


@dataclass
class Resolved:
    status: Status
    lower: float | None = None
    upper: float | None = None
    unit: str = "mm"
    trace: list[str] = field(default_factory=list)
    nominal: float | None = None

    def __str__(self) -> str:
        if self.status is not Status.OK:
            return f"<{self.status.value}>"
        lo = "-∞" if self.lower is None else f"{self.lower:.3f}"
        hi = "+∞" if self.upper is None else f"{self.upper:.3f}"
        return f"[{lo}, {hi}] {self.unit}"


# ---------------------------------------------------------------- 符号表
class SymbolKind(str, Enum):
    DEVIATION = "deviation"  # 极限偏差型：给上下偏差（H13、h14）
    TOLERANCE = "tolerance"  # 公差值型：只给公差宽度（IT12）


@dataclass
class SymbolEntry:
    code: str
    size_from: float
    size_to: float
    kind: SymbolKind
    lower_dev: float = 0.0
    upper_dev: float = 0.0
    tol: float = 0.0


class SymbolSet:
    """一套符号表（可对应一个国家标准的一张表，带版本）。"""

    def __init__(self, set_id: str, name: str, version: str):
        self.set_id = set_id
        self.name = name
        self.version = version
        self.entries: list[SymbolEntry] = []

    def add(self, entry: SymbolEntry) -> "SymbolSet":
        self.entries.append(entry)
        return self

    def lookup(self, code: str, size: float, part: str) -> float | None:
        for e in self.entries:
            if e.code != code:
                continue
            # 尺寸段左开右闭：(size_from, size_to]
            lo_ok = size > e.size_from or (e.size_from == 0 and size >= 0)
            if lo_ok and size <= e.size_to:
                if e.kind is SymbolKind.DEVIATION:
                    return e.lower_dev if part == "lower" else e.upper_dev
                return 0.0 if part == "lower" else e.tol
        return None


# ---------------------------------------------------------------- 表达式
_ALLOWED_FUNCS = {"min", "max", "round", "abs"}


class _Evaluator:
    """白名单 AST 求值，不使用 eval()。"""

    def __init__(self, variables: dict[str, float]):
        self.vars = variables

    def run(self, expr: str) -> float:
        return float(self._node(ast.parse(expr, mode="eval").body))

    def _node(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in self.vars:
                raise KeyError(f"未绑定变量: {node.id}")
            return float(self.vars[node.id])
        if isinstance(node, ast.BinOp):
            a, b = self._node(node.left), self._node(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            if isinstance(node.op, ast.Pow):
                return a ** b
            raise ValueError("不支持的运算符")
        if isinstance(node, ast.UnaryOp):
            v = self._node(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in _ALLOWED_FUNCS:
                raise ValueError(f"不允许的函数: {node.func.id}")
            args = [self._node(a) for a in node.args]
            return float(getattr(__builtins__, node.func.id)(*args)
                         if not isinstance(__builtins__, dict)
                         else __builtins__[node.func.id](*args))
        raise ValueError(f"不支持的表达式节点: {type(node).__name__}")


# ---------------------------------------------------------------- 限值表
class ValueForm(str, Enum):
    DEVIATION = "deviation"  # 给的是偏差，判定时叠加公称值
    ABSOLUTE = "absolute"    # 给的是绝对量（如 Δh、t2、h1min）


@dataclass
class Dim:
    name: str
    kind: str  # 'enum' | 'size'


@dataclass
class Slot:
    """一个值槽：下限或上限，可以是四类之一。"""

    vtype: str                    # CONST | SYMBOL | FORMULA | REF
    const: float | None = None
    symbol: str | None = None     # 代号，如 H13 / IT12
    mult: float = 1.0             # 代号系数，2IT12 -> 2.0
    basis: str | None = None      # 代号解析的基准参数（关键！）
    expr: str | None = None       # 公式
    ref: str | None = None        # 引用（另一张表/产品标准/实测值）


@dataclass
class Row:
    keys: dict[str, Any]
    lower: Slot | None = None
    upper: Slot | None = None
    applicable: bool = True
    note: str = ""
    nominal: float | None = None


@dataclass
class LimitTable:
    table_id: str
    name: str
    dims: list[Dim]
    value_form: ValueForm
    nominal_param: str | None = None   # 偏差型需叠加的公称值参数名
    unit: str = "mm"
    rows: list[Row] = field(default_factory=list)

    def evaluate(self, ctx: dict[str, Any], symbols: dict[str, SymbolSet]) -> Resolved:
        trace: list[str] = []
        row = self._match(ctx, trace)
        if row is None:
            return Resolved(Status.MISS, trace=trace + ["查表未命中"])
        if not row.applicable:
            return Resolved(Status.NOT_REQUIRED, trace=trace + ["该行标记为不适用/不要求"])

        lo = self._slot(row.lower, "lower", ctx, symbols, trace)
        hi = self._slot(row.upper, "upper", ctx, symbols, trace)
        if lo is _UNSPEC or hi is _UNSPEC:
            return Resolved(Status.UNSPECIFIED, trace=trace)
        if lo is None and hi is None:
            return Resolved(Status.UNSPECIFIED, trace=trace + ["无值"])

        nominal_val = row.nominal
        if self.value_form is ValueForm.DEVIATION:
            nominal = ctx.get(self.nominal_param) if self.nominal_param else None
            if nominal is None:
                return Resolved(Status.MISS, trace=trace + [f"缺少公称值 {self.nominal_param}"])
            lo = None if lo is None else nominal + lo
            hi = None if hi is None else nominal + hi
            trace.append(f"叠加公称值 {nominal}")
            nominal_val = nominal
        elif nominal_val is None and self.nominal_param:
            nominal_val = ctx.get(self.nominal_param)

        return Resolved(Status.OK, lo, hi, self.unit, trace, nominal=nominal_val)

    # --- 内部 ---
    def _match(self, ctx: dict[str, Any], trace: list[str]) -> Row | None:
        for row in self.rows:
            ok = True
            for d in self.dims:
                key = row.keys.get(d.name)
                val = ctx.get(d.name)
                if val is None:
                    return None
                if d.kind == "enum":
                    if key != val:
                        ok = False
                        break
                else:  # size: key = (from, to)
                    frm, to = key
                    if not (val > frm or (frm == 0 and val >= 0)) or val > to:
                        ok = False
                        break
            if ok:
                trace.append("命中维度 " + ", ".join(
                    f"{d.name}={row.keys.get(d.name)}" for d in self.dims))
                if getattr(row, "note", ""):
                    trace.append(f"行注记 {row.note}")
                return row
        return None

    def _slot(self, slot: Slot | None, part: str, ctx, symbols, trace):
        if slot is None:
            return None
        if slot.vtype == "CONST":
            return slot.const
        if slot.vtype == "SYMBOL":
            size = ctx.get(slot.basis)
            if size is None:
                raise KeyError(f"代号 {slot.symbol} 缺少基准参数 {slot.basis}")
            ss = symbols[slot.symbol.split(":", 1)[0]]
            code = slot.symbol.split(":", 1)[1]
            v = ss.lookup(code, float(size), part)
            if v is None:
                trace.append(f"代号 {code} 未覆盖尺寸 {size}")
                return _UNSPEC
            trace.append(f"代号 {code}@{size} -> {v}")
            return v * slot.mult
        if slot.vtype == "FORMULA":
            v = _Evaluator(ctx).run(slot.expr)
            trace.append(f"公式 {slot.expr} -> {v}")
            return v
        if slot.vtype == "REF":
            return _UNSPEC  # 原型未实现，真实系统按引用源解析
        raise ValueError(slot.vtype)


_UNSPEC = object()


# ---------------------------------------------------------------- 表达式 / 条件
import ast as _ast  # noqa: E402

_CMP = {
    _ast.Lt: lambda a, b: a < b, _ast.LtE: lambda a, b: a <= b,
    _ast.Gt: lambda a, b: a > b, _ast.GtE: lambda a, b: a >= b,
    _ast.Eq: lambda a, b: (a == b) if isinstance(a, str) or isinstance(b, str) else abs(a - b) < 1e-12,
    _ast.NotEq: lambda a, b: (a != b) if isinstance(a, str) or isinstance(b, str) else abs(a - b) >= 1e-12,
}


def eval_expr(expr: str, ctx: dict[str, Any]) -> float:
    """算术表达式求值（含参数变量）。"""
    return _Evaluator(ctx).run(expr)


def eval_cond(expr: str, ctx: dict[str, Any]) -> bool:
    """条件表达式：支持 <= >= < > == != and or not 与括号。"""
    tree = _ast.parse(expr, mode="eval").body

    def ev(node):
        if isinstance(node, _ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, _ast.And) else any(vals)
        if isinstance(node, _ast.UnaryOp) and isinstance(node.op, _ast.Not):
            return not ev(node.operand)
        if isinstance(node, _ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                fn = _CMP.get(type(op))
                if fn is None:
                    raise ValueError("不支持的条件运算符")
                if not fn(left, right):
                    return False
                left = right
            return True
        if isinstance(node, _ast.Constant):
            return node.value
        if isinstance(node, _ast.Name):
            if node.id not in ctx:
                raise KeyError(f"未绑定变量: {node.id}")
            v = ctx[node.id]
            return v
        if isinstance(node, _ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            for t, f in ((_ast.Add, lambda x, y: x + y), (_ast.Sub, lambda x, y: x - y),
                         (_ast.Mult, lambda x, y: x * y), (_ast.Div, lambda x, y: x / y)):
                if isinstance(node.op, t):
                    return f(a, b)
            raise ValueError("不支持的运算符")
        raise ValueError(f"不支持的条件节点: {type(node).__name__}")

    return bool(ev(tree))


@dataclass
class Rule:
    cond: str | None            # None = else
    lower: str | None
    upper: str | None
    na: bool = False            # 命中即"标准明确不要求"


class RuleTable:
    """按条件逐行匹配的限值表：条件里可引用参数，限值可以是表达式。"""

    def __init__(self, name: str, rules: list[Rule], unit: str = "mm"):
        self.name = name
        self.rules = rules
        self.unit = unit

    def evaluate(self, ctx: dict[str, Any], symbols: dict[str, SymbolSet]) -> Resolved:
        for i, r in enumerate(self.rules, 1):
            hit = True
            if r.cond:
                try:
                    hit = eval_cond(r.cond, ctx)
                except Exception:
                    hit = False
            if not hit:
                continue
            if r.na:
                return Resolved(Status.NOT_REQUIRED,
                                trace=[f"命中规则 {i}: {r.cond or 'else'} → 不要求"])
            lo = eval_expr(r.lower, ctx) if r.lower else None
            hi = eval_expr(r.upper, ctx) if r.upper else None
            trace = [f"命中规则 {i}: {r.cond or 'else'}",
                     f"下限 {r.lower or '—'} -> {lo}", f"上限 {r.upper or '—'} -> {hi}"]
            return Resolved(Status.OK, lo, hi, self.unit, trace)
        return Resolved(Status.MISS, trace=["没有命中任何限值规则（检查参数取值是否覆盖）"])
