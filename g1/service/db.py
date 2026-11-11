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
    classes_json  TEXT DEFAULT '[]',
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
    sc_id         TEXT,
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
    job_id        TEXT,
    filename      TEXT,
    mime          TEXT DEFAULT 'application/pdf',
    size          INTEGER,
    storage       TEXT DEFAULT 'db',         -- db: 内容在库里 | file: 只有路径
    path          TEXT,
    content       BLOB,
    created_at    REAL
);

-- 一份原件可以挂到多个标准上
CREATE TABLE IF NOT EXISTS standard_document (
    std_id     TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    doc_id     TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    created_at REAL,
    PRIMARY KEY (std_id, doc_id)
);

CREATE INDEX IF NOT EXISTS idx_sd_doc ON standard_document(doc_id);
CREATE INDEX IF NOT EXISTS idx_doc_job ON document(job_id);

-- 标准 × 产品小类 这一层：检项、参数、限值都挂在它下面
CREATE TABLE IF NOT EXISTS standard_class (
    id          TEXT PRIMARY KEY,
    std_id      TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    class_id    TEXT,
    name        TEXT,
    sort        INTEGER DEFAULT 0,
    param_json  TEXT DEFAULT '[]',
    item_json   TEXT DEFAULT '[]',
    limits_json TEXT DEFAULT '{}'
);

-- 产品小类下的参数库：小类 → 参数定义 → 参数值（最大集）
CREATE TABLE IF NOT EXISTS product_class (
    id      TEXT PRIMARY KEY,
    code    TEXT,
    name    TEXT,
    parent  TEXT,
    sort    INTEGER DEFAULT 0
);

-- 参数名称表（全局，两层中的第一层）
CREATE TABLE IF NOT EXISTS param_name (
    id   TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT,
    type TEXT DEFAULT 'enum',
    unit TEXT DEFAULT '',
    help TEXT DEFAULT ''
);

-- 小类用哪些参数（多对多）
CREATE TABLE IF NOT EXISTS class_param (
    class_id TEXT NOT NULL REFERENCES product_class(id) ON DELETE CASCADE,
    param_id TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE,
    sort     INTEGER DEFAULT 0,
    required INTEGER DEFAULT 1,
    PRIMARY KEY (class_id, param_id)
);

-- 参数值表（两层中的第二层，挂在参数名称下）
CREATE TABLE IF NOT EXISTS param_value (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    param_id TEXT REFERENCES param_name(id) ON DELETE CASCADE,
    seq      INTEGER,
    sym      TEXT,
    val      TEXT
);

CREATE INDEX IF NOT EXISTS idx_cp_class ON class_param(class_id);
CREATE INDEX IF NOT EXISTS idx_pv_param ON param_value(param_id);
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


def _migrate_document_links(conn: sqlite3.Connection) -> None:
    """把 document.std_id（一份原件只能属于一个标准）迁到 standard_document。"""
    cols = _columns(conn, "document")
    if not cols or "std_id" not in cols:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("CREATE TABLE IF NOT EXISTS _doc_links (std_id TEXT, doc_id TEXT)")
    conn.execute("INSERT INTO _doc_links SELECT std_id, id FROM document WHERE std_id IS NOT NULL")
    conn.executescript("""
        ALTER TABLE document RENAME TO old_document;
        CREATE TABLE document (
            id            TEXT PRIMARY KEY,
            job_id        TEXT,
            filename      TEXT,
            mime          TEXT DEFAULT 'application/pdf',
            size          INTEGER,
            storage       TEXT DEFAULT 'db',
            path          TEXT,
            content       BLOB,
            created_at    REAL
        );
        INSERT INTO document(id, job_id, filename, mime, size, storage, path, content, created_at)
            SELECT id, job_id, filename, mime, size, storage, path, content, created_at
            FROM old_document;
        DROP TABLE old_document;
    """)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS standard_document (
            std_id     TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
            doc_id     TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
            created_at REAL,
            PRIMARY KEY (std_id, doc_id)
        );
        CREATE INDEX IF NOT EXISTS idx_sd_doc ON standard_document(doc_id);
    """)
    conn.execute("INSERT OR IGNORE INTO standard_document(std_id, doc_id, created_at)"
                 " SELECT std_id, doc_id, ? FROM _doc_links", (time.time(),))
    conn.execute("DROP TABLE _doc_links")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库（limit_table.id 为全局 TEXT 主键）→ 新库（标准内唯一 + 代理键）。"""
    cols = _columns(conn, "limit_table")
    if not cols or "local_id" in cols:
        _migrate_document_links(conn)
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
    _migrate_document_links(conn)


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
def _ensure_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    if col not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        conn.commit()


def save_payload(conn: sqlite3.Connection, payload: dict) -> str:
    sid = payload["id"]
    conn.execute("DELETE FROM standard WHERE id = ?", (sid,))   # 级联删表
    _ensure_column(conn, "standard", "classes_json", "TEXT DEFAULT '[]'")
    conn.execute(
        "INSERT INTO standard(id, code, title, category, scope, note, custom,"
        " param_json, item_json, limits_json, source_json, classes_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, payload.get("code", ""), payload.get("title", ""),
         payload.get("category", ""), payload.get("scope", ""), payload.get("note", ""),
         int(payload.get("custom", 0)),
         json.dumps(payload.get("params") or [], ensure_ascii=False),
         json.dumps(payload.get("items") or [], ensure_ascii=False),
         json.dumps(payload.get("limits") or {}, ensure_ascii=False),
         json.dumps(payload.get("source") or {}, ensure_ascii=False),
         json.dumps(payload.get("classes") or [], ensure_ascii=False),
         time.time()))
    # 标准 × 小类：按参数/检项上的 class_id 分层
    classes = []
    for p in payload.get("params") or []:
        cid = p.get("class_id") or ""
        if cid and cid not in classes:
            classes.append(cid)
    if not classes:
        classes = [""]
    conn.execute("DELETE FROM standard_class WHERE std_id=?", (sid,))
    sc_of_class = {}
    for i, cid in enumerate(classes):
        sc_id = f"sc-{sid}-{cid or 'all'}"
        sc_of_class[cid] = sc_id
        ps = [p for p in (payload.get("params") or []) if (p.get("class_id") or "") == cid]
        its = [it for it in (payload.get("items") or [])
               if (it.get("class_id") or "") in ("", cid)]
        conn.execute("INSERT INTO standard_class(id, std_id, class_id, name, sort,"
                     " param_json, item_json, limits_json) VALUES (?,?,?,?,?,?,?,?)",
                     (sc_id, sid, cid, payload.get("title") or "", i,
                      json.dumps(ps, ensure_ascii=False),
                      json.dumps(its, ensure_ascii=False),
                      json.dumps(payload.get("limits") or {}, ensure_ascii=False)))

    for t in payload.get("tables") or []:
        item_class = ""
        for it in payload.get("items") or []:
            if it.get("id") == t.get("item_code"):
                item_class = it.get("class_id") or ""
                break
        t = {**t, "sc_id": sc_of_class.get(item_class) or sc_of_class.get("") or
             next(iter(sc_of_class.values()))}
        _insert_table(conn, sid, t)
    # 老表没有 sc_id 的兜底挂到第一层
    first_sc = next(iter(sc_of_class.values()))
    conn.execute("UPDATE limit_table SET sc_id=? WHERE std_id=? AND (sc_id IS NULL OR sc_id='')",
                 (first_sc, sid))
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


def layers_of(conn: sqlite3.Connection, std_id: str) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM standard_class WHERE std_id=? ORDER BY sort, id", (std_id,)):
        out.append({"id": r["id"], "class_id": r["class_id"] or "", "name": r["name"] or "",
                    "params": json.loads(r["param_json"] or "[]"),
                    "items": json.loads(r["item_json"] or "[]"),
                    "limits": json.loads(r["limits_json"] or "{}")})
    return out


def load_all(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for s in conn.execute("SELECT * FROM standard ORDER BY created_at"):
        tables = {}
        for t in conn.execute("SELECT * FROM limit_table WHERE std_id=? ORDER BY sort", (s["id"],)):
            tables[t["local_id"]] = _build_table(conn, t)
        layers = layers_of(conn, s["id"])
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
            "classes": json.loads(s["classes_json"] or "[]") if "classes_json" in s.keys() else [],
            "layers": layers,
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
                  job_id: str | None = None) -> str:
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
        "INSERT INTO document(id, job_id, filename, size, storage, path, content, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (sha, job_id, filename, size, storage,
         path if data is None else None, data, time.time()))
    conn.commit()
    return sha


def find_document(conn: sqlite3.Connection, sha: str):
    return conn.execute("SELECT * FROM document WHERE id=?", (sha,)).fetchone()


def document_for_job(conn: sqlite3.Connection, job_id: str):
    return conn.execute("SELECT * FROM document WHERE job_id=? ORDER BY created_at DESC",
                        (job_id,)).fetchone()


def document_for_standard(conn: sqlite3.Connection, std_id: str):
    row = conn.execute(
        "SELECT d.* FROM document d JOIN standard_document sd ON sd.doc_id = d.id"
        " WHERE sd.std_id=? ORDER BY sd.created_at DESC", (std_id,)).fetchone()
    if row:
        return row
    s = conn.execute("SELECT source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if not s:
        return None
    src = json.loads(s[0] or "{}")
    if src.get("job_id"):
        return document_for_job(conn, src["job_id"])
    return None


def link_document(conn: sqlite3.Connection, job_id: str, std_id: str) -> int:
    """把某个作业的原件挂到标准上（可挂多个，不移动）。返回挂上的数量。"""
    rows = list(conn.execute("SELECT id FROM document WHERE job_id=?", (job_id,)))
    for r in rows:
        conn.execute("INSERT OR IGNORE INTO standard_document(std_id, doc_id, created_at)"
                     " VALUES (?,?,?)", (std_id, r["id"], time.time()))
    conn.commit()
    return len(rows)


def unlink_document(conn: sqlite3.Connection, std_id: str, doc_id: str) -> None:
    conn.execute("DELETE FROM standard_document WHERE std_id=? AND doc_id=?", (std_id, doc_id))
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


# ------------------------------------------------------------------ 参数库（产品小类 → 参数 → 值）
def migrate_layers(conn: sqlite3.Connection) -> None:
    """把老标准包成一层「标准 × 小类」，限值表挂到这一层上。"""
    _ensure_column(conn, "limit_table", "sc_id", "TEXT")
    for s in conn.execute("SELECT * FROM standard"):
        n = conn.execute("SELECT COUNT(*) FROM standard_class WHERE std_id=?", (s["id"],)).fetchone()[0]
        if n:
            continue
        classes = json.loads(s["classes_json"] or "[]") if "classes_json" in s.keys() else []
        sc_id = f"sc-{s['id']}-{classes[0] if classes else 'all'}"
        conn.execute("INSERT INTO standard_class(id, std_id, class_id, name, sort,"
                     " param_json, item_json, limits_json) VALUES (?,?,?,?,?,?,?,?)",
                     (sc_id, s["id"], classes[0] if classes else "", s["title"] or s["code"], 0,
                      s["param_json"] or "[]", s["item_json"] or "[]", s["limits_json"] or "{}"))
        conn.execute("UPDATE limit_table SET sc_id=? WHERE std_id=? AND sc_id IS NULL",
                     (sc_id, s["id"]))
    conn.commit()


def migrate_catalog(conn: sqlite3.Connection) -> None:
    """旧的两层半结构（param_def 挂小类）→ 参数名称表 + 关联表。"""
    if not _columns(conn, "param_def"):
        return
    # 旧 param_value 的外键指向 param_def，先重建为指向 param_name
    fks = list(conn.execute("PRAGMA foreign_key_list(param_value)"))
    if any(fk["table"] == "param_def" for fk in fks):
        conn.executescript("""
            PRAGMA foreign_keys = OFF;
            ALTER TABLE param_value RENAME TO old_param_value;
            CREATE TABLE param_value (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                param_id TEXT REFERENCES param_name(id) ON DELETE CASCADE,
                seq      INTEGER,
                sym      TEXT,
                val      TEXT
            );
            INSERT INTO param_value(id, param_id, seq, sym, val)
                SELECT id, param_id, seq, sym, val FROM old_param_value;
            DROP TABLE old_param_value;
            PRAGMA foreign_keys = ON;
        """)
    rows = list(conn.execute("SELECT * FROM param_def"))
    for r in rows:
        code = r["code"]
        pid = "pn-" + code
        conn.execute("INSERT OR IGNORE INTO param_name(id, code, name, type, unit, help)"
                     " VALUES (?,?,?,?,?,?)",
                     (pid, code, r["name"], r["type"], r["unit"], r["help"] or ""))
        conn.execute("INSERT OR IGNORE INTO class_param(class_id, param_id, sort, required)"
                     " VALUES (?,?,?,?)",
                     (r["class_id"], pid, r["sort"] or 0, r["required"]))
        hit = conn.execute("SELECT 1 FROM param_value WHERE param_id=? LIMIT 1", (pid,)).fetchone()
        if not hit:
            for v in conn.execute("SELECT * FROM param_value WHERE param_id=?", (r["id"],)):
                conn.execute("UPDATE param_value SET param_id=? WHERE id=?", (pid, v["id"]))
    conn.commit()


def all_params(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for p in conn.execute("SELECT * FROM param_name ORDER BY code"):
        vals = [{"seq": v["seq"], "sym": v["sym"], "val": v["val"]}
                for v in conn.execute("SELECT * FROM param_value WHERE param_id=? ORDER BY seq, id",
                                      (p["id"],))]
        classes = [r["class_id"] for r in
                   conn.execute("SELECT class_id FROM class_param WHERE param_id=?", (p["id"],))]
        out.append({"id": p["id"], "code": p["code"], "name": p["name"], "type": p["type"],
                    "unit": p["unit"], "help": p["help"], "values": vals, "classes": classes})
    return out


def save_param_name(conn: sqlite3.Connection, pid: str, code: str, name: str,
                    type_: str = "enum", unit: str = "", help: str = "") -> str:
    conn.execute("INSERT INTO param_name(id, code, name, type, unit, help) VALUES (?,?,?,?,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name,"
                 " type=excluded.type, unit=excluded.unit, help=excluded.help",
                 (pid, code, name, type_, unit, help))
    conn.commit()
    return pid


def attach_param(conn: sqlite3.Connection, class_id: str, param_id: str,
                 sort: int = 0, required: bool = True) -> None:
    conn.execute("INSERT OR IGNORE INTO class_param(class_id, param_id, sort, required)"
                 " VALUES (?,?,?,?)", (class_id, param_id, sort, int(required)))
    conn.commit()


def detach_param(conn: sqlite3.Connection, class_id: str, param_id: str) -> None:
    conn.execute("DELETE FROM class_param WHERE class_id=? AND param_id=?", (class_id, param_id))
    conn.commit()


def catalog(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for c in conn.execute("SELECT * FROM product_class ORDER BY sort, id"):
        params = []
        for p in conn.execute(
                "SELECT pn.*, cp.required AS req, cp.sort AS cpsort FROM param_name pn"
                " JOIN class_param cp ON cp.param_id = pn.id"
                " WHERE cp.class_id=? ORDER BY cp.sort, pn.code", (c["id"],)):
            vals = [{"seq": v["seq"], "sym": v["sym"], "val": v["val"]}
                    for v in conn.execute("SELECT * FROM param_value WHERE param_id=? ORDER BY seq, id",
                                          (p["id"],))]
            params.append({"id": p["id"], "code": p["code"], "name": p["name"], "type": p["type"],
                           "unit": p["unit"], "required": bool(p["req"]), "help": p["help"],
                           "values": vals})
        out.append({"id": c["id"], "code": c["code"], "name": c["name"],
                    "parent": c["parent"], "params": params})
    return out


def save_class(conn: sqlite3.Connection, cid: str, code: str, name: str,
               parent: str = "", sort: int = 0) -> str:
    conn.execute("INSERT INTO product_class(id, code, name, parent, sort) VALUES (?,?,?,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name,"
                 " parent=excluded.parent, sort=excluded.sort",
                 (cid, code, name, parent, sort))
    conn.commit()
    return cid


def save_param(conn: sqlite3.Connection, pid: str, class_id: str, code: str, name: str,
               type_: str = "enum", unit: str = "", required: bool = True,
               help: str = "", sort: int = 0) -> str:
    conn.execute("INSERT INTO param_def(id, class_id, code, name, type, unit, required, help, sort)"
                 " VALUES (?,?,?,?,?,?,?,?,?)"
                 " ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name,"
                 " type=excluded.type, unit=excluded.unit, required=excluded.required,"
                 " help=excluded.help, sort=excluded.sort",
                 (pid, class_id, code, name, type_, unit, int(required), help, sort))
    conn.commit()
    return pid


def save_param_values(conn: sqlite3.Connection, param_id: str, values: list[dict]) -> int:
    conn.execute("DELETE FROM param_value WHERE param_id=?", (param_id,))
    for i, v in enumerate(values, start=1):
        conn.execute("INSERT INTO param_value(param_id, seq, sym, val) VALUES (?,?,?,?)",
                     (param_id, v.get("seq", i), v.get("sym", ""), v.get("val", "")))
    conn.commit()
    return len(values)


def delete_class(conn: sqlite3.Connection, cid: str) -> None:
    conn.execute("DELETE FROM product_class WHERE id=?", (cid,))
    conn.commit()
