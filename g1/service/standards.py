# -*- coding: utf-8 -*-
"""标准注册表：每个标准自报"需要哪些参数"，服务端与前端都不写死。

加一个标准 = 注册一个 Standard：
    id / code / title / category / scope
    params   规格参数清单（决定界面表单长什么样、几个字段）
    items    检项清单（每个检项声明自己 requires 哪些参数）
    tables   限值表（维度名必须与参数 code 对齐）
    symbols  符号表
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gb3103_3 import GB, TABLES
from items import ITEMS
from limit_engine import Dim, LimitTable, Row, Rule, RuleTable, Slot, SymbolSet, ValueForm

STANDARD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "standards"


@dataclass
class Param:
    code: str                     # 参数代码，如 h_nom
    name: str                     # 中文名，如 公称厚度 h
    type: str = "number"          # number | enum
    unit: str = ""
    required: bool = True
    options: list[str] = field(default_factory=list)
    minimum: float | None = None
    maximum: float | None = None
    default: Any = None
    help: str = ""
    values_list: list = field(default_factory=list)   # [{sym, val}] 该参数的全部可能值
    class_id: str = ""                                # 来自哪个产品小类

    def layer(self, sc_id: str | None = None) -> "Layer | None":
        if not self.layers:
            return None
        if not sc_id:
            return self.layers[0]
        return next((l for l in self.layers if l.id == sc_id), None)

    def meta(self) -> dict:
        return {
            "code": self.code, "name": self.name, "type": self.type, "unit": self.unit,
            "required": self.required, "options": self.options,
            "min": self.minimum, "max": self.maximum,
            "default": self.default, "help": self.help,
            "values_list": self.values_list or [{"sym": v, "val": v} for v in (self.options or [])],
            "class_id": self.class_id,
        }


@dataclass
class Layer:
    """标准 × 产品小类：这一层下有自己的参数、检项、限值、限值表。"""
    id: str
    class_id: str = ""
    name: str = ""
    params: list = field(default_factory=list)     # list[Param]
    items: list = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    tables: dict = field(default_factory=dict)


@dataclass
class Standard:
    id: str
    code: str
    title: str
    category: str
    scope: str
    params: list[Param]
    items: list[dict]
    tables: dict[str, Any]
    symbols: dict[str, SymbolSet]
    note: str = ""
    custom: bool = False          # 由“上传分析”发布的标准
    classes: list = field(default_factory=list)   # 覆盖的产品小类 id
    layers: list = field(default_factory=list)    # 标准 × 小类 分层
    source: dict = field(default_factory=dict)   # 来源作业、文件名等

    # ---------- 参数校验：把用户输入整理成引擎上下文 ----------
    def build_context(self, raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        ctx: dict[str, Any] = {}
        errors: list[str] = []
        known = {p.code: p for p in self.params}

        for key in raw:
            if key not in known:
                errors.append(f"未知参数 {key}")

        for p in self.params:
            v = raw.get(p.code, None)
            if v is None or (isinstance(v, str) and v.strip() == ""):
                if p.required:
                    errors.append(f"缺少必填参数 {p.name}（{p.code}）")
                continue
            if p.type == "enum":
                if v not in p.options:
                    errors.append(f"{p.name} 取值 {v!r} 不在 {p.options} 中")
                    continue
                ctx[p.code] = v
            else:
                try:
                    num = float(v)
                except (TypeError, ValueError):
                    errors.append(f"{p.name} 需为数值，收到 {v!r}")
                    continue
                if p.minimum is not None and num < p.minimum:
                    errors.append(f"{p.name} = {num} 小于下限 {p.minimum}")
                if p.maximum is not None and num > p.maximum:
                    errors.append(f"{p.name} = {num} 超出本标准适用范围上限 {p.maximum}")
                ctx[p.code] = num
        return ctx, errors

    def layer(self, sc_id: str | None = None) -> "Layer | None":
        if not self.layers:
            return None
        if not sc_id:
            return self.layers[0]
        return next((l for l in self.layers if l.id == sc_id), None)

    def meta(self) -> dict:
        return {
            "id": self.id, "code": self.code, "title": self.title,
            "category": self.category, "scope": self.scope, "note": self.note,
            "custom": self.custom,
            "source": self.source,
            "params": [p.meta() for p in self.params],
            "classes": self.classes,
            "layers": [{"id": l.id if hasattr(l, "id") else l.get("id"),
                        "class_id": getattr(l, "class_id", None) if hasattr(l, "class_id") else l.get("class_id", ""),
                        "name": getattr(l, "name", "") if hasattr(l, "name") else l.get("name", ""),
                        "params": len(getattr(l, "params", []) if hasattr(l, "params") else l.get("params") or []),
                        "items": len(getattr(l, "items", []) if hasattr(l, "items") else l.get("items") or [])}
                       for l in (self.layers or [])],
            "items": [{**{k: i[k] for k in
                        ("id", "name", "symbol", "clause", "kind", "measured_key",
                         "nominal_param", "requires") if k in i},
                       "page": i.get("page")} for i in self.items],
        }


REGISTRY: dict[str, Standard] = {}


def register(std: Standard, *, replace: bool = False) -> Standard:
    if std.id in REGISTRY and not replace:
        raise ValueError(f"标准 {std.id} 已注册")
    REGISTRY[std.id] = std
    return std


def get(std_id: str) -> Standard:
    if std_id not in REGISTRY:
        raise KeyError(std_id)
    return REGISTRY[std_id]


# ---------------------------------------------------------------- GB/T 3103.3
# GB/T 3103.3 不再硬编码：由 tools/load_gb3103.py 灌进数据库，
# 标准只有一个来源 data/app.db，空库启动即“没有任何标准”。


# ---------------------------------------------------------------- 自定义标准
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


def _layer_tables(layer: dict, db_tables: dict) -> dict:
    """一层的限值表：库里按 sc_id 归属的表 + 由 limits_json 生成的规则表。"""
    out = {k: v for k, v in db_tables.items() if k in (layer.get("table_ids") or [])}
    limits = layer.get("limits") or {}
    for it in layer.get("items") or []:
        key = it.get("table") or f"L-{it.get('id')}"
        if key in out:
            continue
        lim = limits.get(it.get("id")) or {}
        if lim or f"L-{it.get('id')}" in out:
            out[key] = out.get(f"L-{it.get('id')}") or _limit_table(it, lim)
    return out


def _limit_table(item: dict, lim: dict) -> Any:
    """把一个检项的限值定义变成可求值的表。

    支持三种写法：
      · 常量/单边   mode=range|max|min，lower/upper 是数字
      · 公式        lower/upper 用表达式，如 "0.25*h_nom"、"d_nom+0.27"
      · 规则        mode=rule，rules=[{if:"h_nom<=4 and d_nom<=18", lower:..., upper:...}]
    """
    lim = lim or {}
    mode = lim.get("mode", "none")
    unit = lim.get("unit") or "mm"
    lo, hi = lim.get("lower"), lim.get("upper")
    label = item.get("name") or item.get("title") or item["id"]

    if mode == "rule":
        rules = [Rule(r.get("if") or None, r.get("lower"), r.get("upper"), bool(r.get("na")))
                 for r in (lim.get("rules") or [])]
        rules = [r for r in rules if r.na or r.lower or r.upper]
        if rules:
            return RuleTable(f"{label} 限值", rules, unit)
        return LimitTable(f"L-{item['id']}", f"{label} 限值", [], ValueForm.ABSOLUTE,
                          unit=unit, rows=[Row({}, None, None, note="仅记录")])

    # 表达式型：任一端是字符串就走规则表（单一 else 规则）
    if isinstance(lo, str) or isinstance(hi, str):
        return RuleTable(f"{label} 限值",
                         [Rule(None, lo if isinstance(lo, str) else _num(lo),
                               hi if isinstance(hi, str) else _num(hi))], unit)

    tbl = LimitTable(f"L-{item['id']}", f"{label} 限值", [], ValueForm.ABSOLUTE, unit=unit)
    if mode == "none" or (lo is None and hi is None):
        tbl.rows.append(Row({}, None, None, note="仅记录"))
    elif mode == "max":
        tbl.rows.append(Row({}, None, Slot("CONST", const=float(hi))))
    elif mode == "min":
        tbl.rows.append(Row({}, Slot("CONST", const=float(lo)), None))
    else:
        tbl.rows.append(Row({},
                            Slot("CONST", const=float(lo)) if lo is not None else None,
                            Slot("CONST", const=float(hi)) if hi is not None else None))
    return tbl


def _num(v) -> str | None:
    return None if v is None else str(float(v))


def build_from_payload(payload: dict) -> Standard:
    """把分析结果（参数 + 检项 + 限值）变成一个可用的 Standard。"""
    raw_params = payload.get("params") or []
    params: list[Param] = []
    for p in raw_params:
        code = str(p.get("code", "")).strip()
        if not SLUG_RE.match(code):
            raise ValueError(f"参数代码不合法：{code!r}（需小写字母开头，可含数字与下划线）")
        params.append(Param(
            code=code,
            name=str(p.get("name") or code),
            type=p.get("type", "number"),
            unit=p.get("unit", ""),
            required=bool(p.get("required", True)),
            options=list(p.get("options") or []),
            minimum=p.get("min"),
            maximum=p.get("max"),
            default=p.get("default"),
            help=p.get("help", ""),
            values_list=list(p.get("values_list") or []),
            class_id=p.get("class_id", ""),
        ))
    codes = [p.code for p in params]
    if len(codes) != len(set(codes)):
        raise ValueError("参数代码重复")

    items, tables = [], {}
    for i, it in enumerate(payload.get("items") or []):
        if not it.get("selected", True):
            continue
        iid = str(it.get("id") or f"i{i + 1}")
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        item = {
            "id": iid,
            "name": title,
            "symbol": it.get("symbol") or "",
            "clause": str(it.get("clause") or ""),
            "table": f"L-{iid}",
            "kind": it.get("category") or "其他",
            "requires": [],
            "nominal_param": None,
            "measured_key": f"{iid}_act",
            "method": it.get("method") or "",
            "position": it.get("position") or "见标准原文",
            "gauge": it.get("gauge") or "",
            "points": it.get("points") or "",
            "measured_hint": "实测值",
            "evidence": it.get("evidence", ""),
            "page": it.get("page", 0),
        }
        items.append(item)
        tables[item["table"]] = _limit_table(item, (payload.get("limits") or {}).get(iid, {}))
    if not items:
        raise ValueError("至少要保留一个检项")

    sid = payload.get("id") or f"custom-{int(time.time())}"
    std = Standard(
        id=sid,
        code=str(payload.get("code") or "").strip() or "（未命名标准）",
        title=str(payload.get("title") or "").strip() or "（未命名）",
        category=payload.get("category") or "自定义",
        scope=payload.get("scope") or "",
        note=payload.get("note") or "由上传分析发布",
        params=params, items=items, tables=tables, symbols={},
        custom=True,
        classes=list(payload.get("classes") or []),
        source=payload.get("source") or {},
    )
    return std


def save_custom(std: Standard, payload: dict) -> None:
    STANDARD_DIR.mkdir(parents=True, exist_ok=True)
    (STANDARD_DIR / f"{std.id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def from_loaded(entry: dict) -> Standard:
    """把 db.load_all() 的一条记录变成 Standard（限值表已在 db 层构造好）。"""
    params = [Param(
        code=p["code"], name=p.get("name", p["code"]), type=p.get("type", "number"),
        unit=p.get("unit", ""), required=bool(p.get("required", True)),
        options=list(p.get("options") or []), minimum=p.get("min"), maximum=p.get("max"),
        default=p.get("default"), help=p.get("help", ""),
        values_list=list(p.get("values_list") or [])) for p in entry["params"]]
    return Standard(
        id=entry["id"], code=entry["code"], title=entry["title"],
        category=entry.get("category", ""), scope=entry.get("scope", ""),
        note=entry.get("note", ""), params=params, items=entry["items"],
        tables=entry["tables"], symbols={}, custom=bool(entry.get("custom")),
        classes=entry.get("classes") or [],
        layers=[Layer(
            id=l["id"], class_id=l.get("class_id", ""), name=l.get("name", ""),
            params=[Param(code=p["code"], name=p.get("name", p["code"]),
                          type=p.get("type", "number"), unit=p.get("unit", ""),
                          required=bool(p.get("required", True)),
                          options=list(p.get("options") or []),
                          minimum=p.get("min"), maximum=p.get("max"),
                          default=p.get("default"), help=p.get("help", ""),
                          values_list=list(p.get("values_list") or []),
                          class_id=p.get("class_id", ""))
                    for p in (l.get("params") or [])],
            items=l.get("items") or [],
            limits=l.get("limits") or {},
            tables=_layer_tables(l, entry["tables"]),
        ) for l in (entry.get("layers") or [])],
        source=entry.get("source") or {},
    )


def load_custom() -> list[str]:
    """启动时把数据库里的标准全部装进注册表。"""
    import db as _db
    conn = _db.connect()
    loaded = []
    for entry in _db.load_all(conn):
        try:
            register(from_loaded(entry), replace=True)
            loaded.append(entry["id"])
        except Exception as e:  # noqa: BLE001
            print(f"[standards] 装载 {entry.get('id')} 失败: {e}")
    return loaded
