# -*- coding: utf-8 -*-
"""数据层：SQLite。

限值表**属于标准**，但表 id 只在标准内唯一：

    limit_table (id INTEGER PK, std_id, local_id, ...)  UNIQUE(std_id, local_id)

这样两个标准可以各有一张 `T-D1`，互不影响；删标准级联删自己的表。
（跨标准复用留待后续：届时把表提到库层，标准持有引用。）

表头 value_form：
  absolute —— 值就是绝对量
  deviation —— 值是偏差，判定时叠加 nominal_param 的公称值
限值行的值可以是数值（lower/upper），也可以是表达式（lower_expr/upper_expr）。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from limit_engine import (
    Dim, LimitTable, Row, Rule, RuleTable, Slot, ValueForm,
)

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "app.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS standard (
    id            TEXT PRIMARY KEY,
    code          TEXT NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT DEFAULT '',
    scope         TEXT DEFAULT '',
    note          TEXT DEFAULT '',
    custom        INTEGER DEFAULT 0,
    source_json   TEXT DEFAULT '{}',
    param_json    TEXT DEFAULT '[]',
    item_json     TEXT DEFAULT '[]',
    limits_json   TEXT DEFAULT '{}',
    created_at    REAL
);

CREATE TABLE IF NOT EXISTS limit_table (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id        TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id      TEXT NOT NULL,              -- 标准内的表 id，如 T-D1
    name          TEXT,
    unit          TEXT DEFAULT 'mm',
    value_form    TEXT DEFAULT 'absolute',
    nominal_param TEXT,
    item_code     TEXT,
    sort          INTEGER DEFAULT 0,
    UNIQUE (std_id, local_id)
);

CREATE TABLE IF NOT EXISTS limit_dim (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER REFERENCES limit_table(id) ON DELETE CASCADE,
    seq           INTEGER,
    code          TEXT,
    kind          TEXT,
    values_json   TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS limit_row (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id      INTEGER REFERENCES limit_table(id) ON DELETE CASCADE,
    key_json      TEXT,
    lower         REAL,
    upper         REAL,
    lower_expr    TEXT,
    upper_expr    TEXT,
    na            INTEGER DEFAULT 0,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS document (
    id            TEXT PRIMARY KEY,          -- sha256，天然去重
    std_id        TEXT REFERENCES standard(id) ON DELETE CASCADE,
    job_id        TEXT,
    filename      TEXT,
    mime          TEXT DEFAULT 'application/pdf',
    size          INTEGER,
    storage       TEXT DEFAULT 'db',         -- db: 内容在库里 | file: 只有路径
    path          TEXT,
    content       BLOB,
    created_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_doc_std ON document(std_id);
CREATE INDEX IF NOT EXISTS idx_doc_job ON document(job_id);
CREATE INDEX IF NOT EXISTS idx_lt_std ON limit_table(std_id);
CREATE INDEX IF NOT EXISTS idx_lr_tbl ON limit_row(table_id);
"""


# ------------------------------------------------------------------ 连接与迁移
def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    conn.executescript(SCHEMA)
    return conn


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库（limit_table.id 为全局 TEXT 主键）→ 新库（标准内唯一 + 代理键）。"""
    cols = _columns(conn, "limit_table")
    if not cols or "local_id" in cols:
        return

    conn.executescript("""
        ALTER TABLE limit_table RENAME TO old_limit_table;
        ALTER TABLE limit_dim   RENAME TO old_limit_dim;
        ALTER TABLE limit_row   RENAME TO old_limit_row;
    """)
    conn.executescript(SCHEMA)
    mapping: dict[str, int] = {}
    for t in conn.execute("SELECT * FROM old_limit_table"):
        cur = conn.execute(
            "INSERT INTO limit_table(std_id, local_id, name, unit, value_form, nominal_param,"
            " item_code, sort) VALUES (?,?,?,?,?,?,?,?)",
            (t["std_id"], t["id"], t["name"], t["unit"], t["value_form"],
             t["nominal_param"], t["item_code"], t["sort"]))
        mapping[t["id"]] = cur.lastrowid
    for d in conn.execute("SELECT * FROM old_limit_dim"):
        new_id = mapping.get(d["table_id"])
        if new_id is None:
            continue
        conn.execute("INSERT INTO limit_dim(table_id, seq, code, kind, values_json)"
                     " VALUES (?,?,?,?,?)",
                     (new_id, d["seq"], d["code"], d["kind"], d["values_json"]))
    for r in conn.execute("SELECT * FROM old_limit_row"):
        new_id = mapping.get(r["table_id"])
        if new_id is None:
            continue
        conn.execute("INSERT INTO limit_row(table_id, key_json, lower, upper, lower_expr,"
                     " upper_expr, na, note) VALUES (?,?,?,?,?,?,?,?)",
                     (new_id, r["key_json"], r["lower"], r["upper"], r["lower_expr"],
                      r["upper_expr"], r["na"], r["note"]))
    conn.executescript("""
        DROP TABLE old_limit_dim;
        DROP TABLE old_limit_row;
        DROP TABLE old_limit_table;
    """)
    conn.commit()


# ------------------------------------------------------------------ 工具
def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _insert_table(conn, std_id: str, t: dict) -> int:
    conn.execute("DELETE FROM limit_table WHERE std_id=? AND local_id=?", (std_id, t["id"]))
    cur = conn.execute(
        "INSERT INTO limit_table(std_id, local_id, name, unit, value_form, nominal_param,"
        " item_code, sort) VALUES (?,?,?,?,?,?,?,?)",
        (std_id, t["id"], t.get("name", t["id"]), t.get("unit", "mm"),
         t.get("value_form", "absolute"), t.get("nominal_param"),
         t.get("item_code", ""), t.get("sort", 0)))
    table_pk = cur.lastrowid
    for seq, d in enumerate(t.get("dims") or []):
        conn.execute("INSERT INTO limit_dim(table_id, seq, code, kind, values_json)"
                     " VALUES (?,?,?,?,?)",
                     (table_pk, seq, d["code"], d.get("kind", "enum"),
                      json.dumps(d.get("values") or [], ensure_ascii=False)))
    for r in t.get("rows") or []:
        conn.execute("INSERT INTO limit_row(table_id, key_json, lower, upper, lower_expr,"
                     " upper_expr, na, note) VALUES (?,?,?,?,?,?,?,?)",
                     (table_pk, json.dumps(r.get("key") or {}, ensure_ascii=False),
                      _num(r.get("lower")), _num(r.get("upper")),
                      r.get("lower_expr"), r.get("upper_expr"),
                      int(bool(r.get("na"))), r.get("note", "")))
    return table_pk


# ------------------------------------------------------------------ 写入
def save_payload(conn: sqlite3.Connection, payload: dict) -> str:
    sid = payload["id"]
    conn.execute("DELETE FROM standard WHERE id = ?", (sid,))   # 级联删表
    conn.execute(
        "INSERT INTO standard(id, code, title, category, scope, note, custom,"
        " param_json, item_json, limits_json, source_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, payload.get("code", ""), payload.get("title", ""),
         payload.get("category", ""), payload.get("scope", ""), payload.get("note", ""),
         int(payload.get("custom", 0)),
         json.dumps(payload.get("params") or [], ensure_ascii=False),
         json.dumps(payload.get("items") or [], ensure_ascii=False),
         json.dumps(payload.get("limits") or {}, ensure_ascii=False),
         json.dumps(payload.get("source") or {}, ensure_ascii=False),
         time.time()))
    for t in payload.get("tables") or []:
        _insert_table(conn, sid, t)
    conn.commit()
    return sid


def save_table(conn: sqlite3.Connection, std_id: str, t: dict) -> None:
    """整表覆盖式保存（只动本标准的这张表）。"""
    _insert_table(conn, std_id, t)
    conn.commit()


def bind_table(conn: sqlite3.Connection, std_id: str, item_id: str, local_id: str) -> bool:
    """把表挂到检项上：table 选了"服务检项"，那个检项就该用它。"""
    if not item_id:
        return False
    row = conn.execute("SELECT item_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if not row:
        return False
    items = json.loads(row[0] or "[]")
    hit = False
    for it in items:
        if it.get("id") == item_id:
            it["table"] = local_id
            hit = True
    if hit:
        conn.execute("UPDATE standard SET item_json=? WHERE id=?",
                     (json.dumps(items, ensure_ascii=False), std_id))
        conn.commit()
    return hit


def delete(conn: sqlite3.Connection, std_id: str) -> None:
    conn.execute("DELETE FROM standard WHERE id = ?", (std_id,))
    conn.commit()


def delete_table(conn: sqlite3.Connection, std_id: str, local_id: str) -> None:
    conn.execute("DELETE FROM limit_table WHERE std_id=? AND local_id=?", (std_id, local_id))
    conn.commit()


# ------------------------------------------------------------------ 读取
def _slots(row: sqlite3.Row) -> tuple[Slot | None, Slot | None]:
    lo = (Slot("FORMULA", expr=row["lower_expr"]) if row["lower_expr"]
          else (Slot("CONST", const=row["lower"]) if row["lower"] is not None else None))
    hi = (Slot("FORMULA", expr=row["upper_expr"]) if row["upper_expr"]
          else (Slot("CONST", const=row["upper"]) if row["upper"] is not None else None))
    return lo, hi


def _build_table(conn: sqlite3.Connection, t: sqlite3.Row) -> LimitTable:
    dims = [Dim(d["code"], d["kind"]) for d in
            conn.execute("SELECT * FROM limit_dim WHERE table_id=? ORDER BY seq", (t["id"],))]
    vf = ValueForm.DEVIATION if t["value_form"] == "deviation" else ValueForm.ABSOLUTE
    table = LimitTable(t["local_id"], t["name"], dims, vf,
                       nominal_param=t["nominal_param"], unit=t["unit"] or "mm")
    for r in conn.execute("SELECT * FROM limit_row WHERE table_id=? ORDER BY id", (t["id"],)):
        key = json.loads(r["key_json"] or "{}")
        key = {k: (tuple(v) if isinstance(v, list) else v) for k, v in key.items()}
        lo, hi = _slots(r)
        if r["na"]:
            table.rows.append(Row(key, applicable=False, note=r["note"] or "标准不要求"))
        else:
            table.rows.append(Row(key, lo, hi, note=r["note"] or ""))
    return table


def _simple_table(code: str, lim: dict) -> LimitTable:
    """规则式限值里的「常量区间/单边」，重载时还原成一张零维表。"""
    mode = lim.get("mode", "none")
    lo, hi = lim.get("lower"), lim.get("upper")
    tbl = LimitTable(f"L-{code}", f"{code} 限值", [], ValueForm.ABSOLUTE,
                     unit=lim.get("unit") or "mm")
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


def load_all(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for s in conn.execute("SELECT * FROM standard ORDER BY created_at"):
        tables = {}
        for t in conn.execute("SELECT * FROM limit_table WHERE std_id=? ORDER BY sort", (s["id"],)):
            tables[t["local_id"]] = _build_table(conn, t)
        limits_json = json.loads(s["limits_json"] or "{}")
        items = json.loads(s["item_json"] or "[]")
        for code, lim in limits_json.items():
            if f"L-{code}" in tables:
                continue
            if lim.get("mode") == "rule":
                rules = [Rule(r.get("if") or None, r.get("lower"), r.get("upper"), bool(r.get("na")))
                         for r in (lim.get("rules") or [])]
                if rules:
                    tables[f"L-{code}"] = RuleTable(f"{code} 限值", rules, lim.get("unit", "mm"))
            elif isinstance(lim.get("lower"), str) or isinstance(lim.get("upper"), str):
                tables[f"L-{code}"] = RuleTable(
                    f"{code} 限值", [Rule(None, lim.get("lower"), lim.get("upper"))],
                    lim.get("unit", "mm"))
            else:
                tables[f"L-{code}"] = _simple_table(code, lim)
        for it in items:
            if it.get("table") not in tables and f"L-{it['id']}" in tables:
                it["table"] = f"L-{it['id']}"
            it.setdefault("name", it.get("title") or it["id"])
            it.setdefault("clause", it.get("clause", ""))
            it.setdefault("requires", [])
            tbl = tables.get(it.get("table"))
            it["nominal_param"] = getattr(tbl, "nominal_param", None)
            it.setdefault("measured_key", f"{it['id']}_act")
            it.setdefault("symbol", "")
            it.setdefault("kind", it.get("category", ""))
            it.setdefault("method", "")
            it.setdefault("position", "见标准原文")
            it.setdefault("gauge", "")
            it.setdefault("points", "")
            it.setdefault("measured_hint", "实测值")
        out.append({
            "id": s["id"], "code": s["code"], "title": s["title"],
            "category": s["category"], "scope": s["scope"], "note": s["note"],
            "custom": bool(s["custom"]),
            "source": json.loads(s["source_json"] or "{}"),
            "params": json.loads(s["param_json"] or "[]"),
            "items": items, "tables": tables,
        })
    return out


def table_detail(conn: sqlite3.Connection, std_id: str) -> list[dict]:
    """给浏览器/编辑器用：表头 + 维度（含取值）+ 行。id 用标准内的 local_id。"""
    out = []
    row = conn.execute("SELECT item_json FROM standard WHERE id=?", (std_id,)).fetchone()
    items = json.loads(row[0] or "[]") if row else []
    order = {it["id"]: i for i, it in enumerate(items)}
    tables = list(conn.execute("SELECT * FROM limit_table WHERE std_id=?", (std_id,)))
    tables.sort(key=lambda t: (order.get(t["item_code"], 999), t["local_id"]))
    for t in tables:
        dims = []
        for d in conn.execute("SELECT * FROM limit_dim WHERE table_id=? ORDER BY seq", (t["id"],)):
            vals = json.loads(d["values_json"] or "[]")
            if not vals:
                seen = []
                for r in conn.execute("SELECT key_json FROM limit_row WHERE table_id=?", (t["id"],)):
                    v = json.loads(r["key_json"] or "{}").get(d["code"])
                    if v not in seen and v is not None:
                        seen.append(v)
                vals = seen
            dims.append({"code": d["code"], "kind": d["kind"], "values": vals})
        rows = []
        for r in conn.execute("SELECT * FROM limit_row WHERE table_id=? ORDER BY id", (t["id"],)):
            rows.append({"key": json.loads(r["key_json"] or "{}"),
                         "lower": r["lower"], "upper": r["upper"],
                         "lower_expr": r["lower_expr"], "upper_expr": r["upper_expr"],
                         "na": bool(r["na"]), "note": r["note"] or ""})
        out.append({"id": t["local_id"], "name": t["name"], "unit": t["unit"],
                    "value_form": t["value_form"], "nominal_param": t["nominal_param"],
                    "item_code": t["item_code"], "dims": dims, "rows": rows})
    return out


def stats(conn: sqlite3.Connection) -> dict:
    def one(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]
    return {
        "standards": one("SELECT COUNT(*) FROM standard"),
        "tables": one("SELECT COUNT(*) FROM limit_table"),
        "dims": one("SELECT COUNT(*) FROM limit_dim"),
        "rows": one("SELECT COUNT(*) FROM limit_row"),
    }


# ------------------------------------------------------------------ 文档（PDF 原件）
def save_document(conn: sqlite3.Connection, sha: str, filename: str, size: int,
                  *, data: bytes | None = None, path: str | None = None,
                  job_id: str | None = None, std_id: str | None = None) -> str:
    """按 sha256 入库；同内容只存一份。"""
    row = conn.execute("SELECT id, storage FROM document WHERE id=?", (sha,)).fetchone()
    if row:
        # 同内容已在库：把 job 指针挪到最新一次上传（旧作业可能已被清掉）
        if job_id:
            conn.execute("UPDATE document SET job_id=? WHERE id=?", (job_id, sha))
        conn.commit()
        return sha
    storage = "db" if data is not None else "file"
    conn.execute(
        "INSERT INTO document(id, std_id, job_id, filename, size, storage, path, content, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (sha, std_id, job_id, filename, size, storage,
         path if data is None else None, data, time.time()))
    conn.commit()
    return sha


def find_document(conn: sqlite3.Connection, sha: str):
    return conn.execute("SELECT * FROM document WHERE id=?", (sha,)).fetchone()


def document_for_job(conn: sqlite3.Connection, job_id: str):
    return conn.execute("SELECT * FROM document WHERE job_id=? ORDER BY created_at DESC",
                        (job_id,)).fetchone()


def document_for_standard(conn: sqlite3.Connection, std_id: str):
    row = conn.execute("SELECT * FROM document WHERE std_id=? ORDER BY created_at DESC",
                       (std_id,)).fetchone()
    if row:
        return row
    s = conn.execute("SELECT source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if not s:
        return None
    src = json.loads(s[0] or "{}")
    if src.get("job_id"):
        return document_for_job(conn, src["job_id"])
    return None


def link_document(conn: sqlite3.Connection, job_id: str, std_id: str) -> None:
    conn.execute("UPDATE document SET std_id=? WHERE job_id=?", (std_id, job_id))
    conn.commit()


def update_item_pages(conn: sqlite3.Connection, std_id: str, pages: dict[str, int]) -> int:
    """把 {检项 id: 页码} 写回 item_json，返回改动条数。"""
    row = conn.execute("SELECT item_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if not row:
        return 0
    items = json.loads(row[0] or "[]")
    n = 0
    for it in items:
        page = pages.get(it.get("id"))
        if page and it.get("page") != page:
            it["page"] = page
            n += 1
    if n:
        conn.execute("UPDATE standard SET item_json=? WHERE id=?",
                     (json.dumps(items, ensure_ascii=False), std_id))
        conn.commit()
    return n
