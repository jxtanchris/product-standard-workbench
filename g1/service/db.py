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
    matrix_local_id TEXT DEFAULT '',
    UNIQUE (std_id, local_id)
);

CREATE TABLE IF NOT EXISTS limit_matrix (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    std_id        TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
    local_id      TEXT NOT NULL,              -- 矩阵ID，如 M-PROP-1
    title         TEXT NOT NULL,              -- 矩阵标题，如 "表3 紧固件机械性能总表"
    matrix_json   TEXT NOT NULL DEFAULT '{}', -- 完整的矩阵结构定义
    created_at    REAL,
    updated_at    REAL,
    UNIQUE (std_id, local_id)
);

CREATE INDEX IF NOT EXISTS idx_lm_std ON limit_matrix(std_id);

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
    class_id    TEXT REFERENCES product_class(id) ON DELETE SET NULL,
    name        TEXT,
    sort        INTEGER DEFAULT 0,
    param_json  TEXT DEFAULT '[]',
    item_json   TEXT DEFAULT '[]',
    limits_json TEXT DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_sc_std_class
    ON standard_class(std_id, IFNULL(class_id, ''));

-- 产品小类下的参数库：小类 → 参数定义 → 参数值（最大集）
CREATE TABLE IF NOT EXISTS product_class (
    id      TEXT PRIMARY KEY,
    code    TEXT,
    name    TEXT,
    parent  TEXT,
    sort    INTEGER DEFAULT 0
);

-- 参数名称表（支持按产品小类独立挂载各自参数定义与定值集合）
CREATE TABLE IF NOT EXISTS param_name (
    id             TEXT PRIMARY KEY,
    code           TEXT NOT NULL,
    name           TEXT,
    type           TEXT DEFAULT 'enum',
    unit           TEXT DEFAULT '',
    help           TEXT DEFAULT '',
    is_multi_dim   TEXT DEFAULT 'N',     -- 是否多维: 'Y' / 'N'
    dim_count      INTEGER DEFAULT 0,    -- 维度定义: 2, 3, 4
    coord1_sub_id  TEXT DEFAULT '',      -- 第一坐标_引用二级参数 (二级参数id)
    coord2_sub_id  TEXT DEFAULT '',      -- 第二坐标_引用二级参数
    coord3_sub_id  TEXT DEFAULT '',      -- 第三坐标_引用二级参数
    coord4_sub_id  TEXT DEFAULT '',      -- 第四坐标_引用二级参数
    is_primary     INTEGER DEFAULT 0,    -- 主参数 (0/1)
    category       TEXT DEFAULT ''       -- 参数分类
);

-- 二级参数表（对应 FileMaker: 产品目录_二级参数）
CREATE TABLE IF NOT EXISTS sub_param (
    id         TEXT PRIMARY KEY,          -- 记录编号，如 EJCPLCS00000000002
    class_id   TEXT REFERENCES product_class(id) ON DELETE CASCADE,  -- 引用_产品目录_记录编号
    param_id   TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE, -- 引用_产品目录参数_编号
    seq        INTEGER DEFAULT 1,         -- 序号 (1, 2, 3, 4)
    code       TEXT NOT NULL,             -- 参数代码，如 GYZLX, D, P, YLX
    name       TEXT NOT NULL,             -- 参数名称，如 公英制类型, 公称直径
    help       TEXT DEFAULT ''            -- 参数说明 / 单位 (如 mm, /)
);

-- 小类用哪些参数（多对多）
CREATE TABLE IF NOT EXISTS class_param (
    class_id TEXT NOT NULL REFERENCES product_class(id) ON DELETE CASCADE,
    param_id TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE,
    sort     INTEGER DEFAULT 0,
    required INTEGER DEFAULT 1,
    PRIMARY KEY (class_id, param_id)
);

-- 参数值表（挂在参数名称下，多维参数可含坐标拆解值）
CREATE TABLE IF NOT EXISTS param_value (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    param_id    TEXT REFERENCES param_name(id) ON DELETE CASCADE,
    seq         INTEGER,
    sym         TEXT,
    val         TEXT,
    coord1_val  TEXT DEFAULT '',          -- 第一坐标对应值 (如 公制)
    coord2_val  TEXT DEFAULT '',          -- 第二坐标对应值 (如 1)
    coord3_val  TEXT DEFAULT '',          -- 第三坐标对应值 (如 0.25)
    coord4_val  TEXT DEFAULT ''           -- 第四坐标对应值 (如 粗牙)
);

CREATE INDEX IF NOT EXISTS idx_sub_param_param ON sub_param(param_id);
CREATE INDEX IF NOT EXISTS idx_sub_param_class ON sub_param(class_id);
CREATE INDEX IF NOT EXISTS idx_cp_class ON class_param(class_id);
CREATE INDEX IF NOT EXISTS idx_pv_param ON param_value(param_id);
CREATE INDEX IF NOT EXISTS idx_lt_std ON limit_table(std_id);
CREATE INDEX IF NOT EXISTS idx_lr_tbl ON limit_row(table_id);

-- 拆分模式库：预置 5 种标准表格拆分模式，支持浏览与配置
CREATE TABLE IF NOT EXISTS table_split_mode (
    id            TEXT PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    seq           INTEGER DEFAULT 1,
    name          TEXT NOT NULL,
    short_name    TEXT DEFAULT '',
    output_ratio  TEXT DEFAULT '',
    complexity    TEXT DEFAULT '简单',
    badge_color   TEXT DEFAULT '#0b5cab',
    scenario      TEXT DEFAULT '',
    rule_summary  TEXT DEFAULT '',
    std_examples  TEXT DEFAULT '[]',
    sample_before TEXT DEFAULT '{}',
    sample_after  TEXT DEFAULT '[]',
    config_json   TEXT DEFAULT '{}'
);
"""


# ------------------------------------------------------------------ 连接与迁移
def _migrate_param_name_unique(conn: sqlite3.Connection) -> None:
    """移除旧版 param_name.code 的全局 UNIQUE 约束，并修复外键指向 param_name。"""
    row_pn = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='param_name'"
    ).fetchone()
    row_cp = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='class_param'"
    ).fetchone()
    need_pn = bool(row_pn and "UNIQUE" in (row_pn[0] or "").upper())
    need_fk = bool(row_cp and "_old_param_name" in (row_cp[0] or ""))
    if not need_pn and not need_fk:
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    if need_pn:
        conn.executescript("""
            ALTER TABLE param_name RENAME TO _old_param_name;
            CREATE TABLE param_name (
                id   TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT,
                type TEXT DEFAULT 'enum',
                unit TEXT DEFAULT '',
                help TEXT DEFAULT ''
            );
            INSERT INTO param_name(id, code, name, type, unit, help)
                SELECT id, code, name, type, unit, help FROM _old_param_name;
            DROP TABLE _old_param_name;
        """)
    if need_fk:
        conn.executescript("""
            ALTER TABLE class_param RENAME TO _old_class_param;
            CREATE TABLE class_param (
                class_id TEXT NOT NULL REFERENCES product_class(id) ON DELETE CASCADE,
                param_id TEXT NOT NULL REFERENCES param_name(id) ON DELETE CASCADE,
                sort     INTEGER DEFAULT 0,
                required INTEGER DEFAULT 1,
                PRIMARY KEY (class_id, param_id)
            );
            INSERT INTO class_param(class_id, param_id, sort, required)
                SELECT class_id, param_id, sort, required FROM _old_class_param;
            DROP TABLE _old_class_param;

            ALTER TABLE param_value RENAME TO _old_param_value;
            CREATE TABLE param_value (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                param_id TEXT REFERENCES param_name(id) ON DELETE CASCADE,
                seq      INTEGER,
                sym      TEXT,
                val      TEXT
            );
            INSERT INTO param_value(id, param_id, seq, sym, val)
                SELECT id, param_id, seq, sym, val FROM _old_param_value;
            DROP TABLE _old_param_value;
        """)
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate_multi_dim_params(conn: sqlite3.Connection) -> None:
    """平滑升级表结构，支持多维参数、二级参数和坐标定值。"""
    pn_cols = _columns(conn, "param_name")
    if pn_cols:
        new_cols = [
            ("is_multi_dim", "TEXT DEFAULT 'N'"),
            ("dim_count", "INTEGER DEFAULT 0"),
            ("coord1_sub_id", "TEXT DEFAULT ''"),
            ("coord2_sub_id", "TEXT DEFAULT ''"),
            ("coord3_sub_id", "TEXT DEFAULT ''"),
            ("coord4_sub_id", "TEXT DEFAULT ''"),
            ("is_primary", "INTEGER DEFAULT 0"),
            ("category", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in new_cols:
            if col_name not in pn_cols:
                conn.execute(f"ALTER TABLE param_name ADD COLUMN {col_name} {col_def}")

    pv_cols = _columns(conn, "param_value")
    if pv_cols:
        new_pv_cols = [
            ("coord1_val", "TEXT DEFAULT ''"),
            ("coord2_val", "TEXT DEFAULT ''"),
            ("coord3_val", "TEXT DEFAULT ''"),
            ("coord4_val", "TEXT DEFAULT ''"),
        ]
        for col_name, col_def in new_pv_cols:
            if col_name not in pv_cols:
                conn.execute(f"ALTER TABLE param_value ADD COLUMN {col_name} {col_def}")
    conn.commit()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    _migrate_param_name_unique(conn)
    _migrate_multi_dim_params(conn)
    conn.executescript(SCHEMA)
    ensure_split_modes(conn)
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


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    if col not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        conn.commit()


def _insert_table(conn, std_id: str, t: dict) -> int:
    conn.execute("DELETE FROM limit_table WHERE std_id=? AND local_id=?", (std_id, t["id"]))
    _ensure_column(conn, "limit_table", "matrix_local_id", "TEXT DEFAULT ''")
    _ensure_column(conn, "limit_row", "nominal", "REAL")
    cur = conn.execute(
        "INSERT INTO limit_table(std_id, local_id, name, unit, value_form, nominal_param,"
        " item_code, sort, matrix_local_id) VALUES (?,?,?,?,?,?,?,?,?)",
        (std_id, t["id"], t.get("name", t["id"]), t.get("unit", "mm"),
         t.get("value_form", "absolute"), t.get("nominal_param"),
         t.get("item_code", ""), t.get("sort", 0), t.get("matrix_local_id", "")))
    table_pk = cur.lastrowid
    for seq, d in enumerate(t.get("dims") or []):
        conn.execute("INSERT INTO limit_dim(table_id, seq, code, kind, values_json)"
                     " VALUES (?,?,?,?,?)",
                     (table_pk, seq, d["code"], d.get("kind", "enum"),
                      json.dumps(d.get("values") or [], ensure_ascii=False)))
    for r in t.get("rows") or []:
        conn.execute("INSERT INTO limit_row(table_id, key_json, lower, upper, lower_expr,"
                     " upper_expr, na, note, nominal) VALUES (?,?,?,?,?,?,?,?,?)",
                     (table_pk, json.dumps(r.get("key") or {}, ensure_ascii=False),
                      _num(r.get("lower")), _num(r.get("upper")),
                      r.get("lower_expr"), r.get("upper_expr"),
                      int(bool(r.get("na"))), r.get("note", ""), _num(r.get("nominal"))))
    return table_pk


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
        classes = [c for c in (payload.get("classes") or []) if c]
    if not classes:
        classes = [""]
    conn.execute("DELETE FROM standard_class WHERE std_id=?", (sid,))
    sc_of_class = {}
    seen_class = set()
    for i, cid in enumerate(classes):
        if cid in seen_class:
            continue                      # 同一小类只留一层
        seen_class.add(cid)
        sc_id = f"sc-{sid}-{cid or 'all'}"
        sc_of_class[cid] = sc_id
        ps = [p for p in (payload.get("params") or []) if (p.get("class_id") or "") in ("", cid)]
        its = [_norm_item(it) for it in (payload.get("items") or [])
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
    # 彻底级联删除：表行、表维度、限值表、标准小类覆盖、标准原件关联、标准母表、标准主表
    conn.execute(
        "DELETE FROM limit_row WHERE table_id IN (SELECT id FROM limit_table WHERE std_id = ?)",
        (std_id,))
    conn.execute(
        "DELETE FROM limit_dim WHERE table_id IN (SELECT id FROM limit_table WHERE std_id = ?)",
        (std_id,))
    conn.execute("DELETE FROM limit_table WHERE std_id = ?", (std_id,))
    conn.execute("DELETE FROM limit_matrix WHERE std_id = ?", (std_id,))
    conn.execute("DELETE FROM standard_class WHERE std_id = ?", (std_id,))
    conn.execute("DELETE FROM standard_document WHERE std_id = ?", (std_id,))
    conn.execute("DELETE FROM standard WHERE id = ?", (std_id,))
    conn.commit()


def delete_table(conn: sqlite3.Connection, std_id: str, local_id: str) -> None:
    conn.execute("DELETE FROM limit_table WHERE std_id=? AND local_id=?", (std_id, local_id))
    conn.commit()


# ------------------------------------------------------------------ 复合大表母表 (limit_matrix)
def list_matrices(conn: sqlite3.Connection, std_id: str) -> list[dict]:
    """获取某个标准下的所有复合大表母表概要列表。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS limit_matrix (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            std_id      TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
            local_id    TEXT NOT NULL,
            title       TEXT NOT NULL,
            matrix_json TEXT NOT NULL DEFAULT '{}',
            created_at  REAL,
            updated_at  REAL,
            UNIQUE (std_id, local_id)
        )
    """)
    rows = conn.execute(
        "SELECT id, local_id, title, matrix_json, created_at, updated_at FROM limit_matrix WHERE std_id=? ORDER BY id",
        (std_id,)
    ).fetchall()
    out = []
    for r in rows:
        mjson = {}
        try:
            mjson = json.loads(r["matrix_json"] or "{}")
        except Exception:
            pass
        common_dims = mjson.get("common_dims") or mjson.get("dims") or []
        tables = mjson.get("tables")
        if tables:
            indicators_count = len(tables)
            rows_count = sum(len(t.get("rows") or []) for t in tables)
        else:
            indicators_count = len(mjson.get("indicators") or [])
            rows_count = len(mjson.get("rows") or [])

        out.append({
            "id": r["id"],
            "local_id": r["local_id"],
            "title": r["title"],
            "split_mode": mjson.get("split_mode") or "composite_no_master",
            "source_table_id": mjson.get("source_table_id") or "",
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "dims_count": len(common_dims),
            "indicators_count": indicators_count,
            "rows_count": rows_count,
        })
    return out


def get_matrix(conn: sqlite3.Connection, std_id: str, local_id: str) -> dict | None:
    """获取单个母表完整结构与矩阵数据。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS limit_matrix (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            std_id      TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
            local_id    TEXT NOT NULL,
            title       TEXT NOT NULL,
            matrix_json TEXT NOT NULL DEFAULT '{}',
            created_at  REAL,
            updated_at  REAL,
            UNIQUE (std_id, local_id)
        )
    """)
    row = conn.execute(
        "SELECT id, local_id, title, matrix_json, created_at, updated_at FROM limit_matrix WHERE std_id=? AND local_id=?",
        (std_id, local_id)
    ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["matrix_json"] or "{}")
    except Exception:
        data = {}
    data["id"] = row["id"]
    data["local_id"] = row["local_id"]
    data["title"] = row["title"]
    return data


def save_and_compile_matrix(conn: sqlite3.Connection, std_id: str, matrix_data: dict) -> dict:
    """保存母表定义，并自动切分编译为单指标 limit_table、limit_dim、limit_row，同时联动检项。"""
    mid = (matrix_data.get("local_id") or "").strip()
    if not mid:
        mid = f"M-{int(time.time() * 1000)}"
    matrix_data["local_id"] = mid
    title = (matrix_data.get("title") or "").strip() or mid
    matrix_data["title"] = title

    conn.execute("""
        CREATE TABLE IF NOT EXISTS limit_matrix (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            std_id      TEXT NOT NULL REFERENCES standard(id) ON DELETE CASCADE,
            local_id    TEXT NOT NULL,
            title       TEXT NOT NULL,
            matrix_json TEXT NOT NULL DEFAULT '{}',
            created_at  REAL,
            updated_at  REAL,
            UNIQUE (std_id, local_id)
        )
    """)
    _ensure_column(conn, "limit_table", "matrix_local_id", "TEXT DEFAULT ''")

    # 查之前该母表生成过的旧子表
    old_sub_rows = conn.execute(
        "SELECT local_id FROM limit_table WHERE std_id=? AND matrix_local_id=?",
        (std_id, mid)
    ).fetchall()
    old_sub_tids = {r[0] for r in old_sub_rows}

    # 1. 存入母表记录
    now = time.time()
    conn.execute("""
        INSERT INTO limit_matrix(std_id, local_id, title, matrix_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(std_id, local_id) DO UPDATE SET
            title=excluded.title,
            matrix_json=excluded.matrix_json,
            updated_at=excluded.updated_at
    """, (std_id, mid, title, json.dumps(matrix_data, ensure_ascii=False), now, now))

    # 2. 读取标准现有检项，准备绑定或新建
    s_row = conn.execute("SELECT item_json FROM standard WHERE id=?", (std_id,)).fetchone()
    items = json.loads(s_row[0] or "[]") if s_row else []
    item_map = {it.get("id"): it for it in items}
    items_changed = False

    tables = matrix_data.get("tables")
    common_dims = matrix_data.get("common_dims") or matrix_data.get("dims") or []
    new_sub_tids = set()

    # 3. 逐个切分/保存每张限值主表
    if tables:
        # 新架构：按 No 序号生成的主从限值表列表（名称直接采用 表格标题/指标名+Min(或Max)）
        used_item_ids: set[str] = set()
        for idx, tbl in enumerate(tables):
            no_label = str(tbl.get("no") or (idx + 1)).strip()
            name_label = (tbl.get("name") or f"指标{idx+1}").strip()
            sub_tid = (tbl.get("local_table_id") or f"T-{mid}-NO{no_label}").strip()
            new_sub_tids.add(sub_tid)

            item_id = (tbl.get("item_id") or "").strip()
            if not item_id:
                for it in items:
                    if (it.get("title") or it.get("name") or "").strip() == name_label:
                        item_id = it.get("id") or ""
                        break
            if not item_id or item_id in used_item_ids:
                suffix_slug = "max" if name_label.lower().endswith("max") else ("min" if name_label.lower().endswith("min") else no_label.lower())
                item_id = f"m-{mid.lower()}-{idx+1}-{suffix_slug}"
            used_item_ids.add(item_id)
            # 若需要一键新建检项
            if item_id and item_id not in item_map:
                new_item = {
                    "id": item_id,
                    "clause": tbl.get("clause") or "",
                    "title": name_label,
                    "name": name_label,
                    "category": tbl.get("category") or "性能",
                    "kind": tbl.get("category") or "性能",
                    "table": sub_tid,
                    "evidence": f"源自母表 {title} No.{no_label}"
                }
                items.append(new_item)
                item_map[item_id] = new_item
                items_changed = True
            elif item_id and item_id in item_map:
                if item_map[item_id].get("table") != sub_tid:
                    item_map[item_id]["table"] = sub_tid
                    items_changed = True

            # 维度合并：表头公共参数 + 本表专属自增参数
            tbl_dims = tbl.get("dims") or (list(common_dims) + list(tbl.get("extra_dims") or []))
            dim_kind_map = {d.get("code"): d.get("kind", "enum") for d in tbl_dims if d.get("code")}

            # 整理明细行（将区间维度的 '0~16' 规范化为 [0.0, 16.0]）
            tbl_rows = []
            for r in tbl.get("rows") or []:
                raw_key = dict(r.get("key") or {})
                for k_code, k_val in list(raw_key.items()):
                    if dim_kind_map.get(k_code) == "range" and isinstance(k_val, str) and "~" in k_val:
                        parts = [p.strip() for p in k_val.split("~", 1)]
                        try:
                            lo_v = float(parts[0]) if parts[0] else None
                            hi_v = float(parts[1]) if parts[1] else None
                            raw_key[k_code] = [lo_v, hi_v]
                        except ValueError:
                            pass
                tbl_rows.append({
                    "key": raw_key,
                    "nominal": r.get("nominal"),
                    "lower": r.get("lower"),
                    "upper": r.get("upper"),
                    "lower_expr": r.get("lower_expr") or "",
                    "upper_expr": r.get("upper_expr") or "",
                    "na": bool(r.get("na")),
                    "note": r.get("note") or ""
                })

            sub_table_dict = {
                "id": sub_tid,
                "name": name_label,
                "unit": tbl.get("unit") or "",
                "value_form": tbl.get("value_form") or "absolute",
                "nominal_param": tbl.get("nominal_param") or None,
                "item_code": item_id,
                "sort": idx,
                "matrix_local_id": mid,
                "dims": tbl_dims,
                "rows": tbl_rows
            }
            _insert_table(conn, std_id, sub_table_dict)
    else:
        # 兼容旧架构：横向多指标平面大表
        indicators = matrix_data.get("indicators") or []
        dims = common_dims
        rows = matrix_data.get("rows") or []

        for idx, ind in enumerate(indicators):
            col_key = ind.get("col_key") or f"col_{idx}"
            sub_tid = ind.get("local_table_id") or f"T-{mid}-{col_key}"
            new_sub_tids.add(sub_tid)

            item_id = (ind.get("item_id") or "").strip()
            if item_id and item_id not in item_map:
                new_item = {
                    "id": item_id,
                    "clause": "",
                    "title": ind.get("name") or col_key,
                    "category": ind.get("category") or "性能",
                    "table": sub_tid,
                    "evidence": f"源自复合母表: {title}"
                }
                items.append(new_item)
                item_map[item_id] = new_item
                items_changed = True
            elif item_id and item_id in item_map:
                if item_map[item_id].get("table") != sub_tid:
                    item_map[item_id]["table"] = sub_tid
                    items_changed = True

            ind_dims = ind.get("dims") or (list(dims) + list(ind.get("extra_dims") or []))
            sub_table_dict = {
                "id": sub_tid,
                "name": f"{title} - {ind.get('name') or col_key}",
                "unit": ind.get("unit") or "",
                "value_form": ind.get("value_form") or "absolute",
                "nominal_param": ind.get("nominal_param") or None,
                "item_code": item_id,
                "sort": idx,
                "matrix_local_id": mid,
                "dims": ind_dims,
                "rows": []
            }

            for r in rows:
                dim_vals = dict(r.get("dim_values") or {})
                ival = (r.get("indicator_values") or {}).get(col_key) or {}
                if ival.get("extra_dim_values"):
                    dim_vals.update(ival["extra_dim_values"])
                elif ind.get("extra_dims"):
                    for ed in ind["extra_dims"]:
                        code = ed["code"]
                        if code in ival:
                            dim_vals[code] = ival[code]
                        elif code in ("rm_nom", "nominal") and ival.get("nominal") is not None:
                            dim_vals[code] = ival["nominal"]

                sub_table_dict["rows"].append({
                    "key": dim_vals,
                    "nominal": ival.get("nominal"),
                    "lower": ival.get("lower"),
                    "upper": ival.get("upper"),
                    "lower_expr": ival.get("lower_expr") or "",
                    "upper_expr": ival.get("upper_expr") or "",
                    "na": bool(ival.get("na")),
                    "note": ival.get("note") or ""
                })

            _insert_table(conn, std_id, sub_table_dict)

    # 4. 清理旧版本中已移除指标对应的孤儿子表
    for tid in (old_sub_tids - new_sub_tids):
        delete_table(conn, std_id, tid)

    # 5. 更新 standard.item_json 及 standard_class
    if items_changed:
        conn.execute("UPDATE standard SET item_json=? WHERE id=?",
                     (json.dumps(items, ensure_ascii=False), std_id))
        conn.execute("UPDATE standard_class SET item_json=? WHERE std_id=?",
                     (json.dumps(items, ensure_ascii=False), std_id))

    conn.commit()
    return {
        "ok": True,
        "matrix_id": mid,
        "title": title,
        "sub_tables": list(new_sub_tids),
        "compiled_tables": list(new_sub_tids),
        "compiled_count": len(new_sub_tids),
        "items_updated": items_changed
    }


def delete_matrix(conn: sqlite3.Connection, std_id: str, local_id: str) -> bool:
    """删除母表及其拆解的所有子表。"""
    sub_rows = conn.execute(
        "SELECT local_id FROM limit_table WHERE std_id=? AND matrix_local_id=?",
        (std_id, local_id)
    ).fetchall()
    for r in sub_rows:
        delete_table(conn, std_id, r[0])
    conn.execute("DELETE FROM limit_matrix WHERE std_id=? AND local_id=?", (std_id, local_id))
    conn.commit()
    return True


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
        nom = r["nominal"] if "nominal" in r.keys() else None
        if r["na"]:
            table.rows.append(Row(key, applicable=False, note=r["note"] or "标准不要求", nominal=nom))
        else:
            table.rows.append(Row(key, lo, hi, note=r["note"] or "", nominal=nom))
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


def _norm_item(it: dict) -> dict:
    """层里的检项补全缺省字段，保证和从 payload 建出来的形状一致。"""
    return {
        **it,
        "name": it.get("name") or it.get("title") or it.get("id"),
        "symbol": it.get("symbol") or "",
        "clause": it.get("clause") or "",
        "kind": it.get("kind") or it.get("category") or "其他",
        "table": it.get("table") or f"L-{it.get('id')}",
        "requires": list(it.get("requires") or []),
        "measured_key": it.get("measured_key") or f"{it.get('id')}_act",
        "nominal_param": it.get("nominal_param") or "",
    }


def layers_of(conn: sqlite3.Connection, std_id: str) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM standard_class WHERE std_id=? ORDER BY sort, id", (std_id,)):
        items = [_norm_item(it) for it in json.loads(r["item_json"] or "[]")]
        out.append({"id": r["id"], "class_id": r["class_id"] or "", "name": r["name"] or "",
                    "params": json.loads(r["param_json"] or "[]"),
                    "items": items,
                    "limits": json.loads(r["limits_json"] or "{}")})
    return out


def load_all(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for s in conn.execute("SELECT * FROM standard ORDER BY created_at"):
        tables = {}
        sc_tables: dict[str, list] = {}
        for t in conn.execute("SELECT * FROM limit_table WHERE std_id=? ORDER BY sort", (s["id"],)):
            tables[t["local_id"]] = _build_table(conn, t)
            sc_tables.setdefault(t["sc_id"] or "", []).append(t["local_id"])
        layers = layers_of(conn, s["id"])
        for l in layers:
            l["table_ids"] = sc_tables.get(l["id"], [])
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
                         "nominal": r["nominal"] if "nominal" in r.keys() else None,
                         "lower": r["lower"], "upper": r["upper"],
                         "lower_expr": r["lower_expr"], "upper_expr": r["upper_expr"],
                         "na": bool(r["na"]), "note": r["note"] or ""})
        out.append({"id": t["local_id"], "name": t["name"], "unit": t["unit"],
                    "value_form": t["value_form"], "nominal_param": t["nominal_param"],
                    "item_code": t["item_code"], "dims": dims, "rows": rows,
                    "sc_id": t["sc_id"] if "sc_id" in t.keys() else None,
                    "matrix_local_id": t["matrix_local_id"] if "matrix_local_id" in t.keys() else ""})
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
    row = conn.execute("SELECT * FROM document WHERE job_id=? ORDER BY created_at DESC",
                       (job_id,)).fetchone()
    if not row:
        try:
            import jobs as _jobs
            j = _jobs.STORE.get(job_id)
            if j and getattr(j, "sha256", ""):
                row = conn.execute("SELECT * FROM document WHERE id=?", (j.sha256,)).fetchone()
        except Exception:
            pass
    return row


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
    if not rows:
        try:
            import jobs as _jobs
            j = _jobs.STORE.get(job_id)
            if j and getattr(j, "sha256", ""):
                rows = list(conn.execute("SELECT id FROM document WHERE id=?", (j.sha256,)))
        except Exception:
            pass
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
                    type_: str = "enum", unit: str = "", help: str = "",
                    is_multi_dim: str = "N", dim_count: int = 0,
                    coord1_sub_id: str = "", coord2_sub_id: str = "",
                    coord3_sub_id: str = "", coord4_sub_id: str = "",
                    is_primary: int = 0, category: str = "") -> str:
    conn.execute(
        "INSERT INTO param_name(id, code, name, type, unit, help, is_multi_dim, dim_count,"
        " coord1_sub_id, coord2_sub_id, coord3_sub_id, coord4_sub_id, is_primary, category)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name,"
        " type=excluded.type, unit=excluded.unit, help=excluded.help,"
        " is_multi_dim=excluded.is_multi_dim, dim_count=excluded.dim_count,"
        " coord1_sub_id=excluded.coord1_sub_id, coord2_sub_id=excluded.coord2_sub_id,"
        " coord3_sub_id=excluded.coord3_sub_id, coord4_sub_id=excluded.coord4_sub_id,"
        " is_primary=excluded.is_primary, category=excluded.category",
        (pid, code, name, type_, unit, help, is_multi_dim, dim_count,
         coord1_sub_id, coord2_sub_id, coord3_sub_id, coord4_sub_id, is_primary, category)
    )
    conn.commit()
    return pid


def save_sub_param(conn: sqlite3.Connection, sid: str, class_id: str, param_id: str,
                   seq: int, code: str, name: str, help: str = "") -> str:
    conn.execute(
        "INSERT INTO sub_param(id, class_id, param_id, seq, code, name, help) VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET class_id=excluded.class_id, param_id=excluded.param_id,"
        " seq=excluded.seq, code=excluded.code, name=excluded.name, help=excluded.help",
        (sid, class_id, param_id, seq, code, name, help)
    )
    conn.commit()
    return sid


def list_sub_params(conn: sqlite3.Connection, param_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM sub_param WHERE param_id=? ORDER BY seq, id", (param_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_sub_param(conn: sqlite3.Connection, sid: str) -> None:
    conn.execute("DELETE FROM sub_param WHERE id=?", (sid,))
    conn.commit()


def attach_param(conn: sqlite3.Connection, class_id: str, param_id: str,
                 sort: int = 0, required: bool = True) -> None:
    conn.execute("INSERT INTO class_param(class_id, param_id, sort, required)"
                 " VALUES (?,?,?,?)"
                 " ON CONFLICT(class_id, param_id) DO UPDATE SET sort=excluded.sort, required=excluded.required",
                 (class_id, param_id, sort, int(required)))
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
                " WHERE cp.class_id=? ORDER BY cp.sort, pn.id", (c["id"],)):
            vals = [{
                "seq": v["seq"], "sym": v["sym"], "val": v["val"],
                "coord1_val": v["coord1_val"] if "coord1_val" in v.keys() else "",
                "coord2_val": v["coord2_val"] if "coord2_val" in v.keys() else "",
                "coord3_val": v["coord3_val"] if "coord3_val" in v.keys() else "",
                "coord4_val": v["coord4_val"] if "coord4_val" in v.keys() else "",
            } for v in conn.execute("SELECT * FROM param_value WHERE param_id=? ORDER BY seq, id",
                                  (p["id"],))]

            sub_params = [dict(sp) for sp in conn.execute(
                "SELECT * FROM sub_param WHERE param_id=? ORDER BY seq, id", (p["id"],)
            ).fetchall()]

            params.append({
                "id": p["id"], "code": p["code"], "name": p["name"], "type": p["type"],
                "unit": p["unit"], "required": bool(p["req"]), "help": p["help"],
                "is_multi_dim": p["is_multi_dim"] if "is_multi_dim" in p.keys() else "N",
                "dim_count": p["dim_count"] if "dim_count" in p.keys() else 0,
                "coord1_sub_id": p["coord1_sub_id"] if "coord1_sub_id" in p.keys() else "",
                "coord2_sub_id": p["coord2_sub_id"] if "coord2_sub_id" in p.keys() else "",
                "coord3_sub_id": p["coord3_sub_id"] if "coord3_sub_id" in p.keys() else "",
                "coord4_sub_id": p["coord4_sub_id"] if "coord4_sub_id" in p.keys() else "",
                "is_primary": p["is_primary"] if "is_primary" in p.keys() else 0,
                "category": p["category"] if "category" in p.keys() else "",
                "sub_params": sub_params,
                "values": vals
            })
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

    def _seq_key(idx_val):
        idx, v = idx_val
        s = v.get("seq")
        try:
            return (float(s), idx)
        except (ValueError, TypeError):
            return (999999.0, idx)

    sorted_vals = [v for _, v in sorted(enumerate(values), key=_seq_key)] if values else []
    for i, v in enumerate(sorted_vals, start=1):
        raw_seq = v.get("seq")
        try:
            if raw_seq not in (None, ""):
                f = float(raw_seq)
                seq = int(f) if f.is_integer() else f
            else:
                seq = i
        except (ValueError, TypeError):
            seq = i
        conn.execute(
            "INSERT INTO param_value(param_id, seq, sym, val, coord1_val, coord2_val, coord3_val, coord4_val)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (param_id, seq, v.get("sym", ""), v.get("val", ""),
             v.get("coord1_val", ""), v.get("coord2_val", ""),
             v.get("coord3_val", ""), v.get("coord4_val", ""))
        )
    conn.commit()
    return len(values)


def delete_class(conn: sqlite3.Connection, cid: str) -> None:
    conn.execute("DELETE FROM product_class WHERE id=?", (cid,))
    conn.commit()


# ------------------------------------------------------------------ 拆分模式库 (table_split_mode)
DEFAULT_SPLIT_MODES: list[dict[str, Any]] = [
    {
        "id": "mode-1-single",
        "code": "single_indicator",
        "seq": 1,
        "name": "模式 1：单指标简单表",
        "short_name": "单指标简单表",
        "output_ratio": "1 张原表 → 按 Min / Max / Avg 等特征值拆分为对应限值表（表格标题+特征值）",
        "complexity": "简单",
        "badge_color": "#0284c7",
        "scenario": "整张表格只描述某 1 个检验项目/物理指标的限值（如表面渗碳层深度、镀层厚度、单项公差），左侧列为规格自变量（如螺纹公称直径 d），右侧列为 min、max、avg（平均值）、nom（公称值）等特征列。",
        "rule_summary": "1. 提取左侧第 1 列（或前 N 列）作为公共自变量参数（如 d_nom 公称直径）；\n2. 动态识别右侧所有特征列（如 Min、Max、Avg、Nom、Typ 等），按特征列拆分为独立限值主表，名称为「表格标题+Min」、「表格标题+Max」、「表格标题+Avg」等；\n3. 将各列数值分别填入对应限值主表的明细行。",
        "std_examples": [
            {"std": "GB/T 3098.7—2000", "table": "表4 表面渗碳层深度", "desc": "左列为螺纹公称直径 (2~12)，按 min、max 拆分为「表面渗碳层深度Min」与「表面渗碳层深度Max」两张限值表"},
            {"std": "涂镀层 / 冲击试验标准", "table": "单指标多统计特征表", "desc": "含 min、max、avg 三列时，自动拆分为「表格标题+Min」、「表格标题+Max」、「表格标题+Avg」三张限值表"}
        ],
        "sample_before": {
            "caption": "表4 表面渗碳层深度 (单位: mm)",
            "headers": ["螺纹公称直径", "min", "max"],
            "rows": [
                ["2、2.5", "0.04", "0.12"],
                ["3、3.5", "0.05", "0.18"],
                ["4、5", "0.10", "0.25"],
                ["6、8", "0.15", "0.28"],
                ["10、12", "0.15", "0.32"]
            ]
        },
        "sample_after": [
            {
                "no": "1",
                "name": "表面渗碳层深度Min",
                "unit": "mm",
                "common_dims": ["螺纹公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [
                    {"key": "d_nom=2", "lower": "0.04", "upper": "—"},
                    {"key": "d_nom=2.5", "lower": "0.04", "upper": "—"},
                    {"key": "d_nom=4", "lower": "0.10", "upper": "—"}
                ]
            },
            {
                "no": "2",
                "name": "表面渗碳层深度Max",
                "unit": "mm",
                "common_dims": ["螺纹公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [
                    {"key": "d_nom=2", "lower": "—", "upper": "0.12"},
                    {"key": "d_nom=2.5", "lower": "—", "upper": "0.12"},
                    {"key": "d_nom=4", "lower": "—", "upper": "0.25"}
                ]
            }
        ],
        "config": {"header_dir": "col", "target_tables": "single_min_max"}
    },
    {
        "id": "mode-2-parallel",
        "code": "multi_col_parallel",
        "seq": 2,
        "name": "模式 2：多指标并列表（按列拆分）",
        "short_name": "多指标按列拆分",
        "output_ratio": "1 张原表 → 按指标列及 Min / Max / Avg 等特征值拆分为 N 张限值表（指标名称+特征值）",
        "complexity": "中等",
        "badge_color": "#0d9488",
        "scenario": "表格左侧第 1~2 列是公共规格参数（如螺纹公称直径 d、螺距 P、分析类型），右侧并列了多个不同检项/指标列，每列可能是单特征（如 min、max、avg、nom）或双层子列/区间（如同一指标下分 min、max、avg）。",
        "rule_summary": "1. 左侧规格列提取为表头公共参数池（common_dims），所有子表自动继承；\n2. 右侧每个指标列按极值/统计特征（Min、Max、Avg、Nom、Typ、Ref 等）拆分为独立限值主表，名称为「指标名称+Min」、「指标名称+Max」、「指标名称+Avg」等；\n3. 自动识别各列的物理单位（如 N·m、N、mm、%），分别填入各主表明细行。",
        "std_examples": [
            {"std": "GB/T 3098.7—2000", "table": "表3 机械和工作性能要求", "desc": "拆分为 3 张限值表：破坏扭矩Min、拧入扭矩Max、破坏拉力载荷Min"},
            {"std": "GB/T 3098.7—2000", "table": "表1 化学成分", "desc": "碳 C 与锰 Mn 均含上下限，拆分为 4 张限值表：碳含量 CMin、碳含量 CMax、锰含量 MnMin、锰含量 MnMax"},
            {"std": "多指标含平均值表", "table": "几何尺寸 / 涂镀层并列表", "desc": "若某列或子列为 avg（平均值），自动生成「指标名称+Avg」限值表"}
        ],
        "sample_before": {
            "caption": "表3 机械和工作性能要求",
            "headers": ["螺纹公称直径 (mm)", "破坏扭矩 min (N·m)", "拧入扭矩 max (N·m)", "破坏拉力载荷 min (N)"],
            "rows": [
                ["2", "0.5", "0.3", "1940"],
                ["2.5", "1.2", "0.6", "3150"],
                ["3", "2.1", "1.1", "4680"],
                ["4", "4.9", "2.5", "8170"]
            ]
        },
        "sample_after": [
            {
                "no": "1",
                "name": "破坏扭矩Min",
                "unit": "N·m",
                "common_dims": ["螺纹公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [{"key": "d_nom=2", "lower": "0.5", "upper": "—"}, {"key": "d_nom=3", "lower": "2.1", "upper": "—"}]
            },
            {
                "no": "2",
                "name": "拧入扭矩Max",
                "unit": "N·m",
                "common_dims": ["螺纹公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [{"key": "d_nom=2", "lower": "—", "upper": "0.3"}, {"key": "d_nom=3", "lower": "—", "upper": "1.1"}]
            },
            {
                "no": "3",
                "name": "破坏拉力载荷Min",
                "unit": "N",
                "common_dims": ["螺纹公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [{"key": "d_nom=2", "lower": "1940", "upper": "—"}, {"key": "d_nom=3", "lower": "4680", "upper": "—"}]
            }
        ],
        "config": {"header_dir": "col", "target_tables": "multi_col_min_max_avg"}
    },
    {
        "id": "mode-3-cross2d",
        "code": "matrix_2d_cross",
        "seq": 3,
        "name": "模式 3：二维矩阵交叉表（行列正交）",
        "short_name": "二维矩阵交叉表",
        "output_ratio": "行参数 × 列参数 → 按 Min / Max / Avg 等特征值生成二维正交限值表（表格标题+特征值）",
        "complexity": "中等",
        "badge_color": "#2563eb",
        "scenario": "表格的「行」是一个规格参数（如螺纹规格 M3~M39），表格的「列」是另一个规格参数（如性能等级 4.6~12.9），行列交叉处的单元格是同一个检项指标的 min、max、avg、nom 等特征限值。",
        "rule_summary": "1. 自动将纵轴行头参数（如 thread_spec 螺纹规格）与横轴列头参数（如 property_class 性能等级）共同纳入公共参数池（2 维正交）；\n2. 按表格或行项目的特征属性（Min、Max、Avg、Nom 等）生成「表格标题+特征值」二维限值主表；\n3. 将每个交叉单元格 (row_i, col_j) 展开为一条二维坐标明细行：{thread_spec: M_i, property_class: C_j} => 对应特征限值。",
        "std_examples": [
            {"std": "GB/T 3098.1—2010", "table": "表4 最小拉力载荷（粗牙螺纹）", "desc": "纵轴为螺纹规格 M3~M39，横轴为性能等级 4.6~12.9，生成「最小拉力载荷（粗牙螺纹）Min」二维限值表"},
            {"std": "GB/T 3098.1—2010", "table": "表5 保证载荷（粗牙螺纹）", "desc": "纵轴为螺纹规格 M3~M39，横轴为性能等级 4.6~12.9，生成二维正交限值表"},
            {"std": "GB/T 3098.1—2010", "table": "表6/表7 细牙螺纹载荷表", "desc": "纵轴为细牙规格 M8×1~M39×3，横轴为性能等级"}
        ],
        "sample_before": {
            "caption": "表4 最小拉力载荷（粗牙螺纹） (单位: N)",
            "headers": ["螺纹规格 (d)", "4.6", "4.8", "5.6", "8.8", "10.9", "12.9"],
            "rows": [
                ["M3", "2010", "2110", "2510", "4020", "5230", "6140"],
                ["M4", "3510", "3690", "4390", "7020", "9130", "10700"],
                ["M6", "8040", "8440", "10000", "16100", "20900", "24500"]
            ]
        },
        "sample_after": [
            {
                "no": "1",
                "name": "最小拉力载荷Min",
                "unit": "N",
                "common_dims": ["螺纹规格 (thread_spec)", "性能等级 (property_class)"],
                "extra_dims": [],
                "preview_rows": [
                    {"key": "thread_spec=M3 × property_class=8.8", "lower": "4020", "upper": "—"},
                    {"key": "thread_spec=M6 × property_class=10.9", "lower": "20900", "upper": "—"}
                ]
            }
        ],
        "config": {"header_dir": "both_2d", "target_tables": "cross_product_min_max_avg"}
    },
    {
        "id": "mode-4-composite",
        "code": "composite_no_master",
        "seq": 4,
        "name": "模式 4：No. 复合大表（主从向导拆解）",
        "short_name": "No.复合大表主从向导",
        "output_ratio": "1 张复合母表 → 按 No. 及 Min / Max / Avg 等特征值拆分为 N 张多维主从限值表（指标名称+特征值）",
        "complexity": "高阶",
        "badge_color": "#7c3aed",
        "scenario": "标准中最复杂的复合大表：表头具有跨列嵌套参数（如性能等级 4.6~12.9 下再分 d≤16mm 与 d>16mm），表体纵向按 No. 序号排列十余个不同物理指标（抗拉强度、屈服强度、硬度、脱碳层、冲击功等），且指标内部包含 min、max、avg（平均值）、nom（公称值）等不同子行。",
        "rule_summary": "采用 4 步主从向导：\n1. 按纵向 No. 序号及各指标包含的特征值（Min、Max、Avg、Nom 等）拆分为对应笔数的「限值主表」，命名为「指标名称+Min」、「指标名称+Max」、「指标名称+Avg」等；\n2. 每笔主表自动继承表头公共参数（如性能等级 + 公称直径区间）；\n3. 针对含公称子行或特殊试验条件的 No. 主表，由人工确认加入「专属增量参数」（如公称抗拉强度 rm_nom、试验温度等）；\n4. 展开生成每笔主表在 (公共参数 × 专属参数) 完整维度下的明细行，并一键切分编译。",
        "std_examples": [
            {"std": "GB/T 3098.1—2010", "table": "表3 螺栓、螺钉和螺柱的机械和物理性能", "desc": "No.1 拆为「抗拉强度 RmMin」，No.10 维氏硬度含 min/max 自动拆为「维氏硬度 HV (F≥98N)Min」与「维氏硬度 HV (F≥98N)Max」"},
            {"std": "GB/T 3098.2—2015", "table": "螺母机械性能总表", "desc": "跨性能等级与螺纹直径分段的多指标主从复合表"}
        ],
        "sample_before": {
            "caption": "表3 螺栓、螺钉和螺柱的机械和物理性能",
            "headers": ["No.", "机械或物理性能", "子项", "4.6", "8.8 (d≤16)", "8.8 (d>16)", "10.9"],
            "rows": [
                ["1", "抗拉强度 Rm / MPa", "公称", "400", "800", "800", "1000"],
                ["1", "抗拉强度 Rm / MPa", "min", "400", "800", "830", "1040"],
                ["10", "维氏硬度 HV (F≥98N)", "min", "120", "250", "255", "320"],
                ["10", "维氏硬度 HV (F≥98N)", "max", "220", "320", "335", "380"]
            ]
        },
        "sample_after": [
            {
                "no": "1",
                "name": "抗拉强度 RmMin",
                "unit": "MPa",
                "common_dims": ["性能等级 (property_class)", "公称直径 d (d_nom)"],
                "extra_dims": ["⭐ 公称抗拉强度 (rm_nom)"],
                "preview_rows": [
                    {"key": "8.8 × 0~16 × rm_nom=800", "lower": "800", "upper": "—"},
                    {"key": "8.8 × 16~39 × rm_nom=800", "lower": "830", "upper": "—"}
                ]
            },
            {
                "no": "10-Min",
                "name": "维氏硬度 HV (F≥98N)Min",
                "unit": "HV",
                "common_dims": ["性能等级 (property_class)", "公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [
                    {"key": "8.8 × 0~16", "lower": "250", "upper": "—"},
                    {"key": "8.8 × 16~39", "lower": "255", "upper": "—"}
                ]
            },
            {
                "no": "10-Max",
                "name": "维氏硬度 HV (F≥98N)Max",
                "unit": "HV",
                "common_dims": ["性能等级 (property_class)", "公称直径 d (d_nom)"],
                "extra_dims": [],
                "preview_rows": [
                    {"key": "8.8 × 0~16", "lower": "—", "upper": "320"},
                    {"key": "8.8 × 16~39", "lower": "—", "upper": "335"}
                ]
            }
        ],
        "config": {"header_dir": "nested_col_no_row", "target_tables": "master_detail_no_min_max_avg"}
    },
    {
        "id": "mode-5-skip",
        "code": "ignore_skip",
        "seq": 5,
        "name": "模式 5：非判定表 / 忽略跳过",
        "short_name": "非判定表/跳过",
        "output_ratio": "0 张限值表（仅归档备查）",
        "complexity": "忽略",
        "badge_color": "#64748b",
        "scenario": "标准文本中出现的符号与缩略语表、条款索引导览表、试验夹具/试板工装尺寸表、引用标准对照表等，不属于被检产品本身的合格判定限值。",
        "rule_summary": "1. 将该原表标记为「⏭️ 已跳过（非产品判定限值表）」；\n2. 不生成限值子表，保留原表网格供查阅标准时参考；\n3. 若后续需要提取其中数据，可随时切换回模式 1~4 重新拆解。",
        "std_examples": [
            {"std": "GB/T 3098.7—2000", "table": "表2 机械和工作性能项目", "desc": "仅列出性能项目对应的技术要求条号与试验方法条号，无具体限值"},
            {"std": "GB/T 3098.7—2000", "table": "表5 试板的厚度和孔径", "desc": "规定试验用工装试板的厚度和孔径，非螺钉本体尺寸"},
            {"std": "GB/T 3098.1—2010", "table": "表1 屈强比 / 表8~11 试验方法适用表", "desc": "概念示例表或试验系列导览表"}
        ],
        "sample_before": {
            "caption": "表2 机械和工作性能项目（索引表）",
            "headers": ["性能项目", "技术要求（条或表）", "试验方法（条）"],
            "rows": [
                ["表面硬度", "4.3", "5.2"],
                ["渗碳层深度", "4.4、表4", "5.3"],
                ["破坏扭矩", "4.5、表3", "5.4"]
            ]
        },
        "sample_after": [],
        "config": {"header_dir": "none", "target_tables": "skip"}
    }
]


def ensure_split_modes(conn: sqlite3.Connection) -> None:
    """确保拆分模式库中有预置的 5 种拆分模式（并自动升级旧版未含 Avg 等特征值规则的预置描述）。"""
    row_m1 = conn.execute("SELECT output_ratio FROM table_split_mode WHERE id='mode-1-single'").fetchone()
    if row_m1 and "Avg" in (row_m1[0] or ""):
        return
    for m in DEFAULT_SPLIT_MODES:
        conn.execute(
            """INSERT OR REPLACE INTO table_split_mode(
                id, code, seq, name, short_name, output_ratio, complexity, badge_color,
                scenario, rule_summary, std_examples, sample_before, sample_after, config_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                m["id"], m["code"], m["seq"], m["name"], m["short_name"],
                m["output_ratio"], m["complexity"], m["badge_color"],
                m["scenario"], m["rule_summary"],
                json.dumps(m["std_examples"], ensure_ascii=False),
                json.dumps(m["sample_before"], ensure_ascii=False),
                json.dumps(m["sample_after"], ensure_ascii=False),
                json.dumps(m["config"], ensure_ascii=False),
            )
        )
    conn.commit()


def list_split_modes(conn: sqlite3.Connection) -> list[dict]:
    """读取全部拆分模式（按 seq 排序）。"""
    ensure_split_modes(conn)
    out = []
    for r in conn.execute("SELECT * FROM table_split_mode ORDER BY seq, id"):
        out.append({
            "id": r["id"],
            "code": r["code"],
            "seq": r["seq"],
            "name": r["name"],
            "short_name": r["short_name"],
            "output_ratio": r["output_ratio"],
            "complexity": r["complexity"],
            "badge_color": r["badge_color"],
            "scenario": r["scenario"],
            "rule_summary": r["rule_summary"],
            "std_examples": json.loads(r["std_examples"] or "[]"),
            "sample_before": json.loads(r["sample_before"] or "{}"),
            "sample_after": json.loads(r["sample_after"] or "[]"),
            "config": json.loads(r["config_json"] or "{}"),
        })
    return out


def save_split_mode(conn: sqlite3.Connection, mode_id: str, payload: dict) -> dict:
    """更新或保存某个拆分模式的说明、规则与示例。"""
    ensure_split_modes(conn)
    existing = conn.execute("SELECT * FROM table_split_mode WHERE id=?", (mode_id,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO table_split_mode(
                id, code, seq, name, short_name, output_ratio, complexity, badge_color,
                scenario, rule_summary, std_examples, sample_before, sample_after, config_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                mode_id,
                payload.get("code") or mode_id,
                int(payload.get("seq") or 99),
                payload.get("name") or mode_id,
                payload.get("short_name") or "",
                payload.get("output_ratio") or "",
                payload.get("complexity") or "中等",
                payload.get("badge_color") or "#0b5cab",
                payload.get("scenario") or "",
                payload.get("rule_summary") or "",
                json.dumps(payload.get("std_examples") or [], ensure_ascii=False),
                json.dumps(payload.get("sample_before") or {}, ensure_ascii=False),
                json.dumps(payload.get("sample_after") or [], ensure_ascii=False),
                json.dumps(payload.get("config") or {}, ensure_ascii=False),
            )
        )
    else:
        conn.execute(
            """UPDATE table_split_mode SET
                name=?, short_name=?, output_ratio=?, complexity=?, badge_color=?,
                scenario=?, rule_summary=?, std_examples=?, sample_before=?, sample_after=?, config_json=?
               WHERE id=?""",
            (
                payload.get("name", existing["name"]),
                payload.get("short_name", existing["short_name"]),
                payload.get("output_ratio", existing["output_ratio"]),
                payload.get("complexity", existing["complexity"]),
                payload.get("badge_color", existing["badge_color"]),
                payload.get("scenario", existing["scenario"]),
                payload.get("rule_summary", existing["rule_summary"]),
                json.dumps(payload.get("std_examples", json.loads(existing["std_examples"] or "[]")), ensure_ascii=False),
                json.dumps(payload.get("sample_before", json.loads(existing["sample_before"] or "{}")), ensure_ascii=False),
                json.dumps(payload.get("sample_after", json.loads(existing["sample_after"] or "[]")), ensure_ascii=False),
                json.dumps(payload.get("config", json.loads(existing["config_json"] or "{}")), ensure_ascii=False),
                mode_id,
            )
        )
    conn.commit()
    modes = [m for m in list_split_modes(conn) if m["id"] == mode_id]
    return modes[0] if modes else {}


def resolve_sub_coords(val: str, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """从参数定值（如 'M2×0.4粗牙'）解构出其二级参数及派生别名。
    返回字典如：{'GYZLX': '公制', 'D': 2, 'd': 2, 'd_nom': 2, 'P': 0.4, 'p_pitch': 0.4, 'p_nom': 0.4, 'YLX': '粗牙'}
    """
    if not val or not isinstance(val, str):
        return {}
    val = val.strip()
    if not val:
        return {}

    out: dict[str, Any] = {}
    close_conn = False
    if conn is None:
        try:
            conn = connect()
            close_conn = True
        except Exception:
            conn = None

    c1, c2, c3, c4 = "", "", "", ""
    sub_map = {}

    if conn is not None:
        try:
            row = conn.execute("""
                SELECT pv.coord1_val, pv.coord2_val, pv.coord3_val, pv.coord4_val,
                       pn.coord1_sub_id, pn.coord2_sub_id, pn.coord3_sub_id, pn.coord4_sub_id
                FROM param_value pv
                JOIN param_name pn ON pn.id = pv.param_id
                WHERE pv.val=? LIMIT 1
            """, (val,)).fetchone()
            if row:
                c1, c2, c3, c4 = row[0] or "", row[1] or "", row[2] or "", row[3] or ""
                sub_ids = [row[4], row[5], row[6], row[7]]
                for idx, sid in enumerate(sub_ids):
                    if sid:
                        srow = conn.execute("SELECT code, name FROM sub_param WHERE id=?", (sid,)).fetchone()
                        if srow:
                            sub_map[idx + 1] = srow[0]
        except Exception:
            pass
        finally:
            if close_conn:
                conn.close()

    # 兜底正则解析螺纹规格（如 M2×0.4粗牙 或 M6×0.75细牙）
    if not c1 and not c2 and not c3 and not c4:
        ylx = "细牙" if "细牙" in val else "粗牙"
        gyz = "英美制" if ("/" in val or "UNC" in val or "UNF" in val) else "公制"
        m = re.search(r"[Mm](\d+(?:\.\d+)?)(?:[×xX*](\d+(?:\.\d+)?))?", val)
        if m:
            c1, c2, c3, c4 = gyz, m.group(1) or "", m.group(2) or "", ylx
        elif re.search(r"^\d+(?:\.\d+)?$", val):
            c1, c2, c3, c4 = gyz, val, "", ylx

    code1 = sub_map.get(1, "GYZLX")
    code2 = sub_map.get(2, "D")
    code3 = sub_map.get(3, "P")
    code4 = sub_map.get(4, "YLX")

    def _as_num(s):
        try:
            f = float(s)
            return int(f) if f.is_integer() else f
        except (ValueError, TypeError):
            return s

    if c1:
        out[code1] = c1
    if c2:
        num2 = _as_num(c2)
        out[code2] = num2
        out["d"] = num2
        out["d_nom"] = num2
        out["nominal_diameter"] = num2
    if c3:
        num3 = _as_num(c3)
        out[code3] = num3
        out["p"] = num3
        out["p_pitch"] = num3
        out["p_nom"] = num3
    if c4:
        out[code4] = c4

    return out


