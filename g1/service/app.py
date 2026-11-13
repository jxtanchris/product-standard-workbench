# -*- coding: utf-8 -*-
"""检验卡服务：标准由注册表提供，参数由标准自报，路由不写死任何字段。

启动：
    ./run.sh            默认 http://127.0.0.1:8022
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import analyze  # noqa: E402
import card_std  # noqa: E402
import db as dbmod  # noqa: E402
import extract_doc  # noqa: E402
import jobs as jobstore  # noqa: E402
import matrix_protocol  # noqa: E402
from card import build_card  # noqa: E402
from limit_engine import Status  # noqa: E402
from standards import (  # noqa: E402
    REGISTRY, Standard, build_from_payload, get, load_custom, register, save_custom,
)

APP_DIR = Path(__file__).resolve().parent
DOC_INLINE_LIMIT = 20 * 1024 * 1024      # ≤20MB 直接入库，超过的只存路径
STATUS_TEXT = {
    Status.OK: "可判定",
    Status.NOT_REQUIRED: "不要求",
    Status.UNSPECIFIED: "未规定",
    Status.MISS: "无法判定",
}

app = FastAPI(title="产品标准检验卡服务", version="0.2.0")


# ------------------------------------------------------------------ 模型
class ResolveRequest(BaseModel):
    std: str = "gb3103-3"
    sc: str | None = None          # 层 id（标准 × 小类），不传则用第一层
    params: dict[str, Any] = Field(default_factory=dict)


class JudgeRequest(ResolveRequest):
    measured: dict[str, float | None] = Field(default_factory=dict)


# ------------------------------------------------------------------ 核心
def limit_text(r) -> str:
    if r.status is Status.NOT_REQUIRED:
        return "不要求"
    if r.status is Status.UNSPECIFIED:
        return "标准尚未规定"
    if r.status is Status.MISS:
        return "—（超出判定条件）"
    lo, hi = r.lower, r.upper
    if lo is None and hi is None:
        return "—"
    if lo is None:
        return f"≤ {hi:.3f} {r.unit}"
    if hi is None:
        return f"≥ {lo:.3f} {r.unit}"
    return f"{lo:.3f} ～ {hi:.3f} {r.unit}"


class LayerView:
    """把某一层包装成"像一个标准"，复用 resolve / 出卡的逻辑。"""

    def __init__(self, std: Standard, layer):
        self.id = std.id
        self.code = std.code
        self.title = std.title
        self.category = std.category
        self.scope = std.scope
        self.note = std.note
        self.custom = std.custom
        self.classes = std.classes
        self.symbols = std.symbols
        self.source = getattr(std, "source", {}) or {}
        self.layers = [layer]
        self.layer_id = layer.id
        self.class_id = layer.class_id
        self.params = layer.params or std.params
        self.items = layer.items or []
        self.tables = layer.tables or {}

    def build_context(self, raw):
        return Standard.build_context(self, raw)

    def meta(self):
        d = Standard.meta(self)
        d["layer"] = {"id": self.layer_id, "class_id": self.class_id}
        return d


def _scoped(std: Standard, sc: str | None):
    """带 sc 时返回层视图，否则返回标准本身。"""
    layer = std.layer(sc) if sc else None
    if sc and not layer:
        raise HTTPException(404, f"没有这一层：{sc}")
    return LayerView(std, layer) if layer else std


def resolve_rows(std: Standard, ctx: dict[str, Any]) -> list[dict]:
    import db as _db
    ctx = dict(ctx)
    for k in ("thread", "Thread", "螺纹规格", "bm_thread"):
        if k in ctx and ctx[k]:
            coords = _db.resolve_sub_coords(str(ctx[k]))
            for ck, cv in coords.items():
                ctx[ck] = cv  # 复合参数具有绝对主导权：强制覆盖二级参数
    rows = []
    for item in std.items:
        missing = [p for p in (item.get("requires") or []) if p not in ctx]
        if missing:
            rows.append(dict(
                id=item["id"], name=item["name"], symbol=item.get("symbol", ""),
                clause=item.get("clause", ""),
                kind=item.get("kind", "其他"), page=item.get("page"),
                status="MISS", status_text="缺少参数",
                limit_text=f"请先填写 {', '.join(missing)}", lower=None, upper=None, unit="mm",
                measured_key=item.get("measured_key"), nominal_param=item.get("nominal_param"),
                nominal_value=ctx.get(item.get("nominal_param")),
                method=item.get("method", ""), position=item.get("position", ""),
                gauge=item.get("gauge", ""), points=item.get("points", ""),
                measured_hint=item.get("measured_hint", ""),
                trace=[f"缺少参数 {', '.join(missing)}，无法解析"],
            ))
            continue
        tbl_id = item.get("table")
        if not tbl_id or tbl_id not in std.tables:
            rows.append(dict(
                id=item["id"], name=item["name"], symbol=item.get("symbol", ""),
                clause=item.get("clause", ""), kind=item.get("kind", "其他"),
                page=item.get("page"),
                status=Status.UNSPECIFIED.value, status_text=STATUS_TEXT[Status.UNSPECIFIED],
                limit_text="未配置限值表", lower=None, upper=None, unit="mm",
                measured_key=item.get("measured_key"), nominal_param=item.get("nominal_param"),
                nominal_value=ctx.get(item.get("nominal_param")),
                method=item.get("method", ""), position=item.get("position", ""),
                gauge=item.get("gauge", ""), points=item.get("points", ""),
                measured_hint=item.get("measured_hint", ""),
                trace=["未关联限值表，无法查表"],
            ))
            continue
        r = std.tables[tbl_id].evaluate(ctx, std.symbols)
        nom_val = getattr(r, "nominal", None)
        if nom_val is None:
            nom_val = ctx.get(item.get("nominal_param"))
        rows.append(dict(
            id=item["id"], name=item["name"], symbol=item.get("symbol", ""),
            clause=item.get("clause", ""), kind=item.get("kind", "其他"),
            page=item.get("page"),
            status=r.status.value, status_text=STATUS_TEXT[r.status],
            limit_text=limit_text(r), lower=r.lower, upper=r.upper, unit=r.unit,
            measured_key=item.get("measured_key"), nominal_param=item.get("nominal_param"),
            nominal_value=nom_val,
            method=item.get("method", ""), position=item.get("position", ""),
            gauge=item.get("gauge", ""), points=item.get("points", ""),
            measured_hint=item.get("measured_hint", ""),
            trace=r.trace,
        ))
    return rows


def judge_rows(std: Standard, ctx: dict, measured: dict) -> dict:
    rows = resolve_rows(std, ctx)
    counts = {"合格": 0, "不合格": 0, "未检测": 0, "不适用": 0, "无法判定": 0}
    out = []
    for row in rows:
        v = measured.get(row["measured_key"])
        if isinstance(v, str):
            v = None if v.strip() == "" else float(v)
        if row["status"] == "NOT_REQUIRED":
            verdict, note = "不适用", "标准对本等级不要求，不作判定"
        elif row["status"] == "UNSPECIFIED":
            verdict, note = "无法判定", "标准尚未规定，仅记录"
        elif row["status"] == "MISS":
            verdict, note = "无法判定", row["limit_text"]
        elif v is None:
            verdict, note = "未检测", ""
        else:
            lo, hi = row["lower"], row["upper"]
            ok = (lo is None or v >= lo - 1e-9) and (hi is None or v <= hi + 1e-9)
            verdict = "合格" if ok else "不合格"
            note = f"实测 {v:g}，限值 {row['limit_text']}"
        counts[verdict] = counts.get(verdict, 0) + 1
        out.append(dict(row, measured=v, verdict=verdict, note=note))

    overall = "不合格" if counts["不合格"] else ("待判定" if counts["未检测"] else "合格")
    return {"rows": out, "counts": counts, "overall": overall,
            "judged": counts["合格"] + counts["不合格"]}


def _std(std_id: str) -> Standard:
    try:
        return get(std_id)
    except KeyError:
        raise HTTPException(404, f"未注册的标准：{std_id}")


def _ctx(req: ResolveRequest):
    std = _scoped(_std(req.std), getattr(req, "sc", None))
    ctx, errors = std.build_context(req.params)
    if errors:
        raise HTTPException(422, detail={"errors": errors})
    return std, ctx


def default_params(std: Standard) -> dict:
    return {p.code: p.default for p in std.params if p.default is not None}


# ------------------------------------------------------------------ 路由
@app.get("/")
def index():
    return FileResponse(
        APP_DIR / "templates" / "index.html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/standards/{std_id}/tables")
def std_tables(std_id: str):
    """把某个标准的多维限值表原样吐出来，供界面核对。"""
    std = _std(std_id)
    out = []
    for tid, t in std.tables.items():
        rows = []
        getattr(t, "rows", [])
        for r in getattr(t, "rows", []):
            rows.append({
                "key": {k: list(v) if isinstance(v, tuple) else v for k, v in r.keys.items()},
                "lower": getattr(r.lower, "const", None) if getattr(r, "lower", None) else None,
                "upper": getattr(r.upper, "const", None) if getattr(r, "upper", None) else None,
                "lower_expr": getattr(r.lower, "expr", None) if getattr(r, "lower", None) else None,
                "upper_expr": getattr(r.upper, "expr", None) if getattr(r, "upper", None) else None,
                "na": not getattr(r, "applicable", True),
                "note": getattr(r, "note", ""),
            })
        out.append({
            "id": tid, "name": getattr(t, "name", tid),
            "unit": getattr(t, "unit", "mm"),
            "value_form": getattr(getattr(t, "value_form", None), "value", "absolute"),
            "nominal_param": getattr(t, "nominal_param", None),
            "dims": [{"code": d.name, "kind": d.kind} for d in getattr(t, "dims", [])],
            "rows": rows[:60], "row_count": len(rows),
        })
    return {"std": std.id, "code": std.code, "title": std.title, "tables": out}


class TableSave(BaseModel):
    id: str
    name: str = ""
    unit: str = "mm"
    value_form: str = "absolute"          # absolute | deviation
    nominal_param: str | None = None
    item_code: str = ""
    dims: list[dict] = Field(default_factory=list)   # [{code, kind, values}]
    rows: list[dict] = Field(default_factory=list)


def _reload(std_id: str) -> None:
    """改表后把注册表里的这个标准刷新一下。"""
    conn = dbmod.connect()
    for entry in dbmod.load_all(conn):
        if entry["id"] == std_id:
            from standards import from_loaded
            register(from_loaded(entry), replace=True)
            break


@app.get("/api/standards/{std_id}/editor")
def std_editor(std_id: str, sc: str | None = None):
    std = _scoped(_std(std_id), sc)
    conn = dbmod.connect()
    return {
        "std": std.id, "code": std.code, "title": std.title,
        "params": [p.meta() for p in std.params],
        "items": [{"code": i["id"], "name": i.get("name") or i.get("title") or i["id"],
                   "clause": i.get("clause", ""), "page": i.get("page"),
                   "table": i.get("table") or "",
                   "kind": i.get("kind") or i.get("category") or "其他"} for i in std.items],
        "tables": [t for t in dbmod.table_detail(conn, std.id)
                   if getattr(std, "layer_id", None) is None or t.get("sc_id") in (None, std.layer_id)],
    }


@app.put("/api/standards/{std_id}/tables/{table_id}")
def save_limit_table(std_id: str, table_id: str, payload: TableSave):
    _std(std_id)
    if payload.id != table_id:
        raise HTTPException(422, "路径与 body 的表 id 不一致")
    codes = {p.code for p in _std(std_id).params}
    for d in payload.dims:
        if d.get("code") not in codes:
            raise HTTPException(422, f"维度 {d.get('code')} 不是本标准的参数")
        if d.get("kind") not in ("enum", "range"):
            raise HTTPException(422, "维度类型只能是 enum 或 range")
    if not payload.rows:
        raise HTTPException(422, "至少保留一行限值")
    conn = dbmod.connect()
    dbmod.save_table(conn, std_id, payload.model_dump())
    dbmod.bind_table(conn, std_id, payload.item_code, payload.id)
    _reload(std_id)
    return {"ok": True, "rows": len(payload.rows)}


@app.post("/api/standards/{std_id}/tables/{table_id}")
def create_limit_table(std_id: str, table_id: str, payload: TableSave):
    return save_limit_table(std_id, table_id, payload)


@app.delete("/api/standards/{std_id}/tables/{table_id}")
def delete_limit_table(std_id: str, table_id: str):
    _std(std_id)
    dbmod.delete_table(dbmod.connect(), std_id, table_id)
    _reload(std_id)
    return {"ok": True}


# ------------------------------------------------------------------ 复合大表母表 (limit_matrix)
@app.get("/api/standards/{std_id}/matrices")
def get_standard_matrices(std_id: str):
    """获取标准下所有复合大表母表概要列表。"""
    _std(std_id)
    conn = dbmod.connect()
    return dbmod.list_matrices(conn, std_id)


@app.get("/api/standards/{std_id}/matrices/{matrix_id}")
def get_standard_matrix(std_id: str, matrix_id: str):
    """获取单个复合大表母表完整结构与矩阵数据。"""
    _std(std_id)
    conn = dbmod.connect()
    m = dbmod.get_matrix(conn, std_id, matrix_id)
    if not m:
        raise HTTPException(404, "母表不存在")
    return m


@app.post("/api/standards/{std_id}/matrices")
def save_standard_matrix(std_id: str, payload: dict = Body(...)):
    """保存母表定义，并自动切分编译为各个检项子表，联动检项关联。"""
    _std(std_id)
    if not payload.get("title") and not payload.get("local_id"):
        raise HTTPException(422, "母表名称或代号不能为空")
    if not payload.get("tables") and not payload.get("indicators"):
        raise HTTPException(422, "至少需要包含一笔限值主表或检项指标列")
    conn = dbmod.connect()
    res = dbmod.save_and_compile_matrix(conn, std_id, payload)
    _reload(std_id)
    return res


@app.delete("/api/standards/{std_id}/matrices/{matrix_id}")
def delete_standard_matrix(std_id: str, matrix_id: str):
    """删除复合大表母表及其拆解的所有子表。"""
    _std(std_id)
    conn = dbmod.connect()
    dbmod.delete_matrix(conn, std_id, matrix_id)
    _reload(std_id)
    return {"ok": True}


# ------------------------------------------------------------------ 拆分模式库 & 多步骤逐表拆解工作台
@app.get("/api/split-modes")
def get_split_modes():
    """获取预置及配置的 5 种表格拆分模式定义。"""
    conn = dbmod.connect()
    return dbmod.list_split_modes(conn)


@app.put("/api/split-modes/{mode_id}")
def put_split_mode(mode_id: str, payload: dict = Body(...)):
    """更新某个拆分模式的说明、规则与示例。"""
    conn = dbmod.connect()
    saved = dbmod.save_split_mode(conn, mode_id, payload)
    return {"ok": True, "mode": saved}


def _find_job_for_std(conn, std_id: str, std_obj) -> jobstore.Job | None:
    """查找标准关联的 OCR 分析作业对象。"""
    src = getattr(std_obj, "source", None) or {}
    jid = src.get("job_id")
    if jid:
        j = jobstore.STORE.get(jid)
        if j:
            return j
    doc = dbmod.document_for_standard(conn, std_id)
    if doc and doc["job_id"]:
        j = jobstore.STORE.get(doc["job_id"])
        if j:
            return j
    if doc and doc["id"]:
        j = jobstore.STORE.find_done_by_sha(doc["id"])
        if j:
            return j
    # 按标准号回退匹配
    code_norm = re.sub(r"\s+", "", (std_obj.code or ""))
    for j in jobstore.STORE._jobs.values():
        if j.published_id == std_id:
            return j
        if code_norm and re.sub(r"\s+", "", (j.code or "")) == code_norm:
            return j
    return None


@app.get("/api/standards/{std_id}/workbench/tables")
def get_std_workbench_tables(std_id: str):
    """第一步：获取已发布标准原件中盘点出的全部表格清单及推荐拆分模式。"""
    std = _std(std_id)
    conn = dbmod.connect()
    job = _find_job_for_std(conn, std_id, std)
    existing_mats = []
    for m_summary in dbmod.list_matrices(conn, std_id):
        full_m = dbmod.get_matrix(conn, std_id, m_summary["local_id"])
        if full_m:
            existing_mats.append(full_m)

    job_dict = job.to_dict_full() if job else {"text": "", "tables": [], "code": std.code}
    std_meta = {
        "id": std.id,
        "code": std.code,
        "title": std.title,
        "items": [{"id": it.get("id"), "title": it.get("name") or it.get("title")} for it in (std.items or [])],
    }
    tables = matrix_protocol.discover_source_tables(job_dict, std_meta, existing_matrices=existing_mats)
    return {
        "context_type": "standard",
        "std_id": std.id,
        "job_id": job.id if job else "",
        "code": std.code,
        "title": std.title,
        "filename": job.filename if job else "",
        "has_source": bool(job and (job.text or job.tables)),
        "tables": tables,
        "split_modes": dbmod.list_split_modes(conn),
    }


@app.post("/api/standards/{std_id}/workbench/deconstruct")
def post_std_workbench_deconstruct(std_id: str, payload: dict = Body(...)):
    """第二/三步：针对选定原表与人工拍板的拆分模式，生成主从拆解草稿。"""
    std = _std(std_id)
    conn = dbmod.connect()
    table_id = payload.get("table_id") or ""
    mode_code = payload.get("mode_code") or "multi_col_parallel"
    use_saved = bool(payload.get("use_saved", False))

    # 如果请求优先载入已保存的母表且模式未强制改变
    if use_saved:
        for m_summary in dbmod.list_matrices(conn, std_id):
            full_m = dbmod.get_matrix(conn, std_id, m_summary["local_id"])
            if full_m and (
                full_m.get("source_table_id") == table_id
                or full_m.get("local_id") == payload.get("matrix_local_id")
            ):
                return full_m

    job = _find_job_for_std(conn, std_id, std)
    job_dict = job.to_dict_full() if job else {"text": "", "tables": [], "code": std.code}
    std_meta = {
        "id": std.id,
        "code": std.code,
        "title": std.title,
        "items": [{"id": it.get("id"), "title": it.get("name") or it.get("title")} for it in (std.items or [])],
    }
    all_tables = matrix_protocol.discover_source_tables(job_dict, std_meta)
    t_info = next((t for t in all_tables if t["table_id"] == table_id), None)
    if not t_info:
        t_info = payload.get("table_info") or {
            "t_no": "1",
            "table_id": table_id or "SRC-TABLE-1",
            "matrix_local_id": payload.get("matrix_local_id") or "M-TABLE1",
            "title": payload.get("title") or "自定义表格",
            "full_title": payload.get("title") or "自定义表格",
            "preview_grid": payload.get("preview_grid") or [],
            "context_lines": [],
        }
    return matrix_protocol.deconstruct_source_table(t_info, mode_code, std_meta)


@app.post("/api/standards/{std_id}/workbench/save")
def post_std_workbench_save(std_id: str, payload: dict = Body(...)):
    """第三步落地：保存当前原表的拆分模式与拆解结果，编译生成子表或标记跳过。"""
    std = _std(std_id)
    conn = dbmod.connect()
    table_id = payload.get("table_id") or ""
    split_mode = payload.get("split_mode") or "composite_no_master"
    matrix_data = dict(payload.get("matrix") or {})
    matrix_data["split_mode"] = split_mode
    matrix_data["source_table_id"] = table_id

    job = _find_job_for_std(conn, std_id, std)
    wb_state = dict((job.workbench_state if job else {}) or {})

    if split_mode == "ignore_skip":
        # 如果之前拆解过该表，清理对应的母表及子表
        local_id = matrix_data.get("local_id") or payload.get("matrix_local_id") or ""
        if local_id:
            dbmod.delete_matrix(conn, std_id, local_id)
        wb_state[table_id] = {"status": "skipped", "split_mode": "ignore_skip", "sub_count": 0}
        if job:
            jobstore.STORE.update(job.id, workbench_state=wb_state)
        _reload(std_id)
        return {"ok": True, "status": "skipped", "table_id": table_id, "compiled_count": 0}

    if not matrix_data.get("tables") and not matrix_data.get("indicators"):
        raise HTTPException(422, "当前拆分模式下至少需要包含 1 笔限值主表（若无需生成限值表请选择模式 5：非判定表/忽略跳过）")

    res = dbmod.save_and_compile_matrix(conn, std_id, matrix_data)
    wb_state[table_id] = {
        "status": "completed",
        "split_mode": split_mode,
        "sub_count": res.get("compiled_count", len(matrix_data.get("tables") or [])),
        "matrix_local_id": res.get("matrix_id"),
    }
    if job:
        wb_mats = dict(job.workbench_matrices or {})
        wb_mats[table_id] = matrix_data
        jobstore.STORE.update(job.id, workbench_state=wb_state, workbench_matrices=wb_mats)
    _reload(std_id)
    return {**res, "status": "completed", "table_id": table_id, "split_mode": split_mode}


@app.get("/api/analyze/jobs/{job_id}/workbench/tables")
def get_job_workbench_tables(job_id: str):
    """在「标准分析（第 3 步：提取限值）」中获取当前作业的原表盘点清单。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "分析作业不存在")
    conn = dbmod.connect()
    existing_mats = list((job.workbench_matrices or {}).values())
    if job.published_id:
        for m_summary in dbmod.list_matrices(conn, job.published_id):
            full_m = dbmod.get_matrix(conn, job.published_id, m_summary["local_id"])
            if full_m:
                existing_mats.append(full_m)

    std_meta = {
        "code": job.code,
        "title": job.title,
        "items": [{"id": it.get("id"), "title": it.get("title") or it.get("name")} for it in (job.items or []) if it.get("selected", True)],
    }
    tables = matrix_protocol.discover_source_tables(job.to_dict_full(), std_meta, existing_matrices=existing_mats)
    return {
        "context_type": "job",
        "job_id": job.id,
        "std_id": job.published_id or "",
        "code": job.code,
        "title": job.title,
        "filename": job.filename,
        "has_source": bool(job.text or job.tables),
        "tables": tables,
        "split_modes": dbmod.list_split_modes(conn),
    }


@app.post("/api/analyze/jobs/{job_id}/workbench/deconstruct")
def post_job_workbench_deconstruct(job_id: str, payload: dict = Body(...)):
    """在「标准分析（第 3 步）」中针对选定原表与拆分模式生成主从拆解草稿。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "分析作业不存在")
    table_id = payload.get("table_id") or ""
    mode_code = payload.get("mode_code") or "multi_col_parallel"
    use_saved = bool(payload.get("use_saved", False))

    if use_saved and table_id in (job.workbench_matrices or {}):
        return job.workbench_matrices[table_id]

    std_meta = {
        "code": job.code,
        "title": job.title,
        "items": [{"id": it.get("id"), "title": it.get("title") or it.get("name")} for it in (job.items or []) if it.get("selected", True)],
    }
    all_tables = matrix_protocol.discover_source_tables(job.to_dict_full(), std_meta)
    t_info = next((t for t in all_tables if t["table_id"] == table_id), None)
    if not t_info:
        t_info = payload.get("table_info") or {
            "t_no": "1",
            "table_id": table_id or "SRC-TABLE-1",
            "matrix_local_id": payload.get("matrix_local_id") or "M-TABLE1",
            "title": payload.get("title") or "自定义表格",
            "full_title": payload.get("title") or "自定义表格",
            "preview_grid": payload.get("preview_grid") or [],
            "context_lines": [],
        }
    return matrix_protocol.deconstruct_source_table(t_info, mode_code, std_meta)


@app.post("/api/analyze/jobs/{job_id}/workbench/save")
def post_job_workbench_save(job_id: str, payload: dict = Body(...)):
    """在「标准分析（第 3 步）」中保存当前原表拆解结果，自动生成草稿限值表并联动参数与检项。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "分析作业不存在")
    table_id = payload.get("table_id") or ""
    split_mode = payload.get("split_mode") or "composite_no_master"
    matrix_data = dict(payload.get("matrix") or {})
    matrix_data["split_mode"] = split_mode
    matrix_data["source_table_id"] = table_id

    wb_state = dict(job.workbench_state or {})
    wb_mats = dict(job.workbench_matrices or {})
    drafts = list(job.table_drafts or [])
    links = dict(job.links or {})
    params_spec = list(job.params_spec or [])
    items = list(job.items or [])

    if split_mode == "ignore_skip":
        old_mat = wb_mats.pop(table_id, None)
        if old_mat:
            old_tids = {t.get("local_table_id") for t in (old_mat.get("tables") or [])}
            drafts = [d for d in drafts if d.get("id") not in old_tids and d.get("matrix_local_id") != old_mat.get("local_id")]
        wb_state[table_id] = {"status": "skipped", "split_mode": "ignore_skip", "sub_count": 0}
        jobstore.STORE.update(job_id, workbench_state=wb_state, workbench_matrices=wb_mats, table_drafts=drafts)
        return {"ok": True, "status": "skipped", "table_id": table_id, "compiled_count": 0}

    sub_tables = matrix_data.get("tables") or []
    if not sub_tables:
        raise HTTPException(422, "当前拆分模式下至少需要包含 1 笔限值主表")

    common_dims = matrix_data.get("common_dims") or []
    local_id = (matrix_data.get("local_id") or f"M-{table_id}").strip()
    matrix_data["local_id"] = local_id

    # 先移除该母表旧的草稿子表
    drafts = [d for d in drafts if d.get("matrix_local_id") != local_id]
    compiled_ids: list[str] = []

    for idx, tbl in enumerate(sub_tables):
        sub_tid = (tbl.get("local_table_id") or f"T-{local_id}-{idx+1}").strip()
        tbl["local_table_id"] = sub_tid
        t_name = (tbl.get("name") or f"指标{idx+1}").strip()
        t_unit = (tbl.get("unit") or "").strip()
        extra_dims = tbl.get("extra_dims") or []
        all_dims = list(common_dims) + list(extra_dims)

        # 确保维度参数存在于 job.params_spec 中
        for d in all_dims:
            dcode = (d.get("code") or "").strip()
            if not dcode:
                continue
            if not any(p.get("code") == dcode for p in params_spec):
                params_spec.append({
                    "code": dcode,
                    "name": d.get("name") or dcode,
                    "type": "enum" if d.get("kind") != "range" else "number",
                    "unit": d.get("unit") or ("mm" if "d_" in dcode else ""),
                    "required": True,
                    "options": d.get("options") or [],
                    "default": None,
                    "class_id": job.class_id or "",
                })

        # 匹配或自动创建检项
        item_id = (tbl.get("item_id") or "").strip()
        if not item_id:
            for it in items:
                if it.get("selected", True) and (it.get("title") or "").strip() == t_name:
                    item_id = it.get("id") or ""
                    break
        if not item_id:
            item_id = f"m-mat-{idx+1}-{uuid.uuid4().hex[:4]}"
            items.append({
                "id": item_id,
                "clause": tbl.get("clause") or "",
                "title": t_name,
                "category": "性能",
                "measurable": True,
                "selected": True,
                "page": 0,
                "class_id": job.class_id or "",
                "evidence": f"由原表拆解工作台 ({matrix_data.get('title')}) 自动生成",
            })
        tbl["item_id"] = item_id
        links[item_id] = sub_tid

        # 转换 rows（处理区间格式如 0~16 -> [0, 16]）
        norm_rows = []
        for r in (tbl.get("rows") or []):
            raw_k = r.get("key") or {}
            clean_k = {}
            for d in all_dims:
                dc = d.get("code")
                if not dc or dc not in raw_k:
                    continue
                kv = raw_k[dc]
                if d.get("kind") == "range" and isinstance(kv, str) and "~" in kv:
                    parts = [p.strip() for p in kv.split("~", 1)]
                    try:
                        clean_k[dc] = [float(parts[0]) if parts[0] else None, float(parts[1]) if parts[1] else None]
                    except ValueError:
                        clean_k[dc] = kv
                else:
                    clean_k[dc] = kv
            norm_rows.append({
                "key": clean_k,
                "nominal": r.get("nominal"),
                "lower": r.get("lower"),
                "upper": r.get("upper"),
                "lower_expr": r.get("lower_expr") or "",
                "upper_expr": r.get("upper_expr") or "",
                "na": bool(r.get("na", False)),
                "note": r.get("note") or "",
            })

        drafts.append({
            "id": sub_tid,
            "name": f"{matrix_data.get('title') or local_id} - {t_name}",
            "unit": t_unit,
            "value_form": "absolute",
            "nominal_param": None,
            "item_code": item_id,
            "matrix_local_id": local_id,
            "dims": [{"code": d.get("code"), "kind": "range" if d.get("kind") == "range" else "enum"} for d in all_dims if d.get("code")],
            "rows": norm_rows,
        })
        compiled_ids.append(sub_tid)

    wb_mats[table_id] = matrix_data
    wb_state[table_id] = {
        "status": "completed",
        "split_mode": split_mode,
        "sub_count": len(compiled_ids),
        "matrix_local_id": local_id,
    }
    jobstore.STORE.update(
        job_id,
        workbench_state=wb_state,
        workbench_matrices=wb_mats,
        table_drafts=drafts,
        links=links,
        params_spec=params_spec,
        items=items,
    )

    # 如果该作业已经发布为标准，同步写入数据库
    if job.published_id:
        conn = dbmod.connect()
        if conn.execute("SELECT 1 FROM standard WHERE id=?", (job.published_id,)).fetchone():
            dbmod.save_and_compile_matrix(conn, job.published_id, matrix_data)
            _reload(job.published_id)

    return {
        "ok": True,
        "status": "completed",
        "table_id": table_id,
        "split_mode": split_mode,
        "matrix_id": local_id,
        "compiled_tables": compiled_ids,
        "compiled_count": len(compiled_ids),
    }


def _send_document(doc):
    if doc is None:
        raise HTTPException(404, "没有存档原件")
    name = doc["filename"] or "source.pdf"
    if doc["storage"] == "db" and doc["content"] is not None:
        return Response(content=bytes(doc["content"]), media_type=doc["mime"] or "application/pdf",
                        headers={"Content-Disposition":
                                 f"inline; filename*=UTF-8''{quote(name)}"})
    p = Path(doc["path"] or "")
    if not p.exists():
        raise HTTPException(410, "原件文件已丢失（库里只有路径）")
    return FileResponse(p, media_type=doc["mime"] or "application/pdf", filename=name)


class SourcePayload(BaseModel):
    job_id: str


def _doc_pages(doc) -> list[dict]:
    """取出原件的分页文本（优先复用作业缓存，否则重新 OCR）。"""
    if doc["storage"] == "file" and doc["path"]:
        return extract_doc.run_ocr(doc["path"], 200)["pages"]
    tmp = jobstore.UPLOADS / f"backfill-{doc['id'][:12]}.pdf"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(bytes(doc["content"]))
    try:
        return extract_doc.run_ocr(tmp, 200)["pages"]
    finally:
        tmp.unlink(missing_ok=True)


def _clause_page(pages: list[dict], clause: str, name: str) -> int | None:
    """按条款号找页码。

    评分：行首就是条款号（标题行）> 条款号 + 名称开头 > 只出现条款号。
    这样能避开前言里的"……（3.5.3条）"这类引用。
    """
    clause = (clause or "").strip()
    if not clause:
        return None
    pat = re.compile(r"(?<![\d.])" + re.escape(clause) + r"(?![\d.])")
    head = (name or "").strip()[:2]
    best_score, best_page = 0, None
    for p in pages:
        for ln in p.get("lines", []):
            if not pat.search(ln):
                continue
            if ln.strip().startswith(clause):
                return int(p["page"])          # 标题行，最可信
            score = 2 if (head and head in ln) else 1
            if score > best_score:
                best_score, best_page = score, int(p["page"])
    return best_page


def backfill_pages(std_id: str) -> dict:
    std = _std(std_id)
    conn = dbmod.connect()
    doc = dbmod.document_for_standard(conn, std_id)
    if not doc:
        raise HTTPException(404, "这个标准还没有存档原件，无法回填页码")
    pages = _doc_pages(doc)
    found: dict[str, int] = {}
    detail = []
    for it in std.items:
        page = _clause_page(pages, it.get("clause") or "", it.get("name") or "")
        if page:
            found[it["id"]] = page
            detail.append({"id": it["id"], "clause": it.get("clause"), "page": page})
    n = dbmod.update_item_pages(conn, std_id, found)
    _reload(std_id)
    return {"ok": True, "matched": len(found), "changed": n, "items": detail}


@app.post("/api/standards/{std_id}/backfill-pages")
def backfill_pages_api(std_id: str):
    return backfill_pages(std_id)


@app.post("/api/standards/{std_id}/source")
def attach_source(std_id: str, payload: SourcePayload):
    """把某次上传的原件挂到这个标准上（人工整理的标准也能有原件）。"""
    _std(std_id)
    conn = dbmod.connect()
    doc = dbmod.document_for_job(conn, payload.job_id)
    if not doc:
        raise HTTPException(404, "该作业没有存档原件")
    dbmod.link_document(conn, payload.job_id, std_id)
    row = conn.execute("SELECT source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    import json as _json
    src = _json.loads(row[0] or "{}") if row else {}
    src.update({"job_id": payload.job_id, "filename": doc["filename"],
                "size": doc["size"], "sha256": doc["id"]})
    conn.execute("UPDATE standard SET source_json=? WHERE id=?",
                 (_json.dumps(src, ensure_ascii=False), std_id))
    conn.commit()
    try:
        back = backfill_pages(std_id)
    except Exception:
        back = {"matched": 0, "changed": 0}
    return {"ok": True, "filename": doc["filename"], "sha256": doc["id"],
            "linked": True,
            "pages_matched": back.get("matched", 0), "pages_changed": back.get("changed", 0)}


@app.get("/api/standards/{std_id}/source.pdf")
def standard_source(std_id: str):
    _std(std_id)
    return _send_document(dbmod.document_for_standard(dbmod.connect(), std_id))


@app.get("/api/analyze/jobs/{job_id}/source.pdf")
def job_source(job_id: str):
    if not jobstore.STORE.get(job_id):
        raise HTTPException(404, "作业不存在")
    return _send_document(dbmod.document_for_job(dbmod.connect(), job_id))


@app.delete("/api/standards/{std_id}/source")
def detach_source(std_id: str):
    _std(std_id)
    conn = dbmod.connect()
    doc = dbmod.document_for_standard(conn, std_id)
    if not doc:
        raise HTTPException(404, "这个标准没有挂原件")
    dbmod.unlink_document(conn, std_id, doc["id"])
    return {"ok": True, "sha256": doc["id"]}


@app.get("/api/documents")
def documents():
    conn = dbmod.connect()
    out = []
    for r in conn.execute("SELECT * FROM document ORDER BY created_at DESC"):
        stds = [x["std_id"] for x in
                conn.execute("SELECT std_id FROM standard_document WHERE doc_id=?", (r["id"],))]
        out.append({"id": r["id"], "filename": r["filename"], "size": r["size"],
                    "storage": r["storage"], "job_id": r["job_id"], "std_ids": stds})
    return out


@app.get("/api/db/stats")
def db_stats():
    return dbmod.stats(dbmod.connect())


@app.get("/api/standards")
def standards():
    conn = dbmod.connect()
    out = []
    for s in REGISTRY.values():
        out.append({"id": s.id, "code": s.code, "title": s.title,
                    "category": s.category, "param_count": len(s.params),
                    "item_count": len(s.items), "custom": s.custom,
                    "classes": s.classes,
                    "has_source": dbmod.document_for_standard(conn, s.id) is not None})
    return out


@app.get("/api/meta")
def meta(std: str = Query("gb3103-3"), sc: str | None = None):
    s = _std(std)
    view = _scoped(s, sc)
    data = view.meta()
    data["default_params"] = default_params(view)
    data["has_source"] = dbmod.document_for_standard(dbmod.connect(), s.id) is not None
    return data


@app.post("/api/resolve")
def resolve(req: ResolveRequest):
    std, ctx = _ctx(req)
    return {"std": std.id, "context": ctx, "rows": resolve_rows(std, ctx)}


@app.post("/api/judge")
def judge(req: JudgeRequest):
    std, ctx = _ctx(req)
    return judge_rows(std, ctx, req.measured)


@app.get("/api/card.xlsx")
def card(request: Request, std: str = Query("gb3103-3")):
    s = _std(std)
    # 除 std 外的查询参数即为规格参数，按参数名直接映射
    raw = {k: v for k, v in request.query_params.items() if k != "std"}
    ctx, errors = s.build_context(raw or default_params(s))
    if errors:
        raise HTTPException(422, detail={"errors": errors})
    rows = resolve_rows(s, ctx)
    data = build_card(s, ctx, rows)
    name = quote(f"检验卡_{s.code.replace('/', '-')}.xlsx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="card.xlsx"; filename*=UTF-8\'\'{name}'},
    )


# ------------------------------------------------------------------ 标准分析（上传 → 识别 → 确认 → 出卡）
class ItemsPayload(BaseModel):
    items: list[dict] = Field(default_factory=list)
    code: str | None = None
    title: str | None = None
    params_spec: list[dict] | None = None
    limits: dict[str, dict] | None = None


class PublishPayload(BaseModel):
    job_id: str | None = None
    classes: list[str] = Field(default_factory=list)   # 覆盖的产品小类
    id: str | None = None
    code: str = ""
    title: str = ""
    category: str = "自定义"
    scope: str = ""
    note: str = ""
    params: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    limits: dict[str, dict] = Field(default_factory=dict)


class StepPayload(BaseModel):
    data: dict = Field(default_factory=dict)
    confirmed: bool = True


class TextPayload(BaseModel):
    text: str
    filename: str = "粘贴的文本"
    class_id: str = ""


@app.post("/api/analyze/upload")
async def analyze_upload(
    file: UploadFile = File(...),
    class_id: str = Form(""),
):
    name = file.filename or "standard.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "目前仅支持 PDF；扫描件也可以（走离线 OCR）")

    cid = class_id.strip()
    if not cid:
        raise HTTPException(422, "上传标准时必须指定产品小类")

    conn = dbmod.connect()
    cls_row = conn.execute("SELECT id, name FROM product_class WHERE id=?", (cid,)).fetchone()
    if not cls_row:
        raise HTTPException(422, f"指定的产品小类不存在: {cid}")

    # 1) 落到临时文件，同时算 sha256
    tmp = jobstore.UPLOADS / f"tmp-{uuid.uuid4().hex}.pdf"
    digest, size = hashlib.sha256(), 0
    with open(tmp, "wb") as f:
        while chunk := await file.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
            f.write(chunk)
    sha = digest.hexdigest()

    # 2) 检查是否已有完全相同的文件 + 相同的产品小类作业
    existing_job = jobstore.STORE.find_by_sha_and_class(sha, cid)
    if existing_job:
        tmp.unlink(missing_ok=True)
        # 若该作业未绑定现存已发布标准（例如标准已被删除或之前仅为残留草稿），重新上传时重置 4 个步骤与拆解状态
        pub_id = getattr(existing_job, "published_id", "") or ""
        std_still_exists = bool(
            pub_id and (pub_id in REGISTRY or conn.execute("SELECT 1 FROM standard WHERE id=?", (pub_id,)).fetchone())
        )
        if not std_still_exists and existing_job.text:
            jobstore.clone_from_ocr(existing_job.id, existing_job, cid)
            existing_job = jobstore.STORE.get(existing_job.id) or existing_job
        conn.execute("UPDATE document SET job_id=? WHERE id=?", (existing_job.id, sha))
        conn.commit()
        return {
            "job_id": existing_job.id,
            "status": existing_job.status,
            "reused": std_still_exists,
            "reset": not std_still_exists,
            "class_id": cid,
            "sha256": sha,
            "size": size,
        }

    # 3) 检查同一份原件是否有其他小类的已完成 OCR 作业：若有，直接复用 OCR 数据，无需重复 OCR
    done_ocr_job = jobstore.STORE.find_done_by_sha(sha)

    job = jobstore.STORE.create(name, class_id=cid, sha256=sha)
    path = jobstore.STORE.pdf_path(job.id)
    shutil.move(str(tmp), path)

    inline = size <= DOC_INLINE_LIMIT
    dbmod.save_document(
        conn, sha, name, size,
        data=path.read_bytes() if inline else None,
        path=None if inline else str(path),
        job_id=job.id)

    if done_ocr_job:
        jobstore.clone_from_ocr(job.id, done_ocr_job, cid)
        return {
            "job_id": job.id,
            "status": "done",
            "class_id": cid,
            "sha256": sha,
            "size": size,
            "reused_ocr": True,
            "storage": "db" if inline else "file",
        }

    jobstore.start(job.id, path)
    return {
        "job_id": job.id,
        "status": job.status,
        "class_id": cid,
        "sha256": sha,
        "size": size,
        "storage": "db" if inline else "file",
    }


@app.post("/api/analyze/text")
def analyze_text(payload: TextPayload):
    cid = payload.class_id.strip()
    if not cid:
        raise HTTPException(422, "分析文本时必须指定产品小类")
    conn = dbmod.connect()
    if not conn.execute("SELECT 1 FROM product_class WHERE id=?", (cid,)).fetchone():
        raise HTTPException(422, f"指定的产品小类不存在: {cid}")
    job = jobstore.STORE.create(payload.filename, class_id=cid)
    jobstore.run_from_text(job.id, payload.text, class_id=cid)
    return {"job_id": job.id, "status": "done", "class_id": cid}


# ------------------------------------------------------------------ 参数库
class ClassPayload(BaseModel):
    id: str
    code: str = ""
    name: str = ""
    parent: str = ""
    sort: int = 0


class ParamPayload(BaseModel):
    id: str
    class_id: str
    code: str
    name: str = ""
    type: str = "enum"
    unit: str = ""
    required: bool = True
    help: str = ""
    sort: int = 0


class ValuesPayload(BaseModel):
    values: list[dict] = Field(default_factory=list)


@app.get("/api/catalog")
def get_catalog():
    return dbmod.catalog(dbmod.connect())


@app.get("/api/params")
def get_params():
    """参数名称表（全局）+ 每个参数的取值与用到它的小类。"""
    return dbmod.all_params(dbmod.connect())


@app.post("/api/catalog/classes/{class_id}/params/{param_id}")
def attach_param(class_id: str, param_id: str):
    dbmod.attach_param(dbmod.connect(), class_id, param_id)
    return {"ok": True}


@app.delete("/api/catalog/classes/{class_id}/params/{param_id}")
def detach_param(class_id: str, param_id: str):
    dbmod.detach_param(dbmod.connect(), class_id, param_id)
    return {"ok": True}


@app.post("/api/catalog/classes")
def post_class(payload: ClassPayload):
    dbmod.save_class(dbmod.connect(), payload.id, payload.code, payload.name,
                     payload.parent, payload.sort)
    return {"ok": True, "id": payload.id}


@app.post("/api/catalog/params")
def post_param(payload: ParamPayload):
    """建一个全局参数；带 class_id 时同时挂到该小类下。"""
    conn = dbmod.connect()
    dbmod.save_param_name(conn, payload.id, payload.code, payload.name,
                          payload.type, payload.unit, payload.help)
    if payload.class_id:
        dbmod.attach_param(conn, payload.class_id, payload.id, payload.sort, payload.required)
    return {"ok": True, "id": payload.id}


@app.post("/api/catalog/params/{param_id}/values")
def post_param_values(param_id: str, payload: ValuesPayload):
    n = dbmod.save_param_values(dbmod.connect(), param_id, payload.values)
    return {"ok": True, "count": n}


@app.delete("/api/catalog/classes/{class_id}")
def del_class(class_id: str):
    dbmod.delete_class(dbmod.connect(), class_id)
    return {"ok": True}


@app.get("/api/rules")
def rules():
    """识别规则原样返回，界面上照着调。"""
    return analyze.rules_catalog()


@app.put("/api/rules")
def update_rules(payload: dict):
    """保存用户手工修改的识别规则，无需修改源程序，即刻热生效。"""
    try:
        saved = analyze.save_rules(payload)
        return {"ok": True, "rules": saved}
    except Exception as e:
        raise HTTPException(422, f"保存识别规则失败: {e}")


@app.post("/api/rules/reset")
def reset_rules(payload: dict | None = Body(default=None)):
    """恢复系统出厂识别规则（可按 step_key 单独恢复某一步）。"""
    step_key = (payload or {}).get("step_key") if isinstance(payload, dict) else None
    res = analyze.reset_rules(step_key=step_key)
    return {"ok": True, "rules": res}


@app.get("/api/analyze/jobs/{job_id}/step-rules")
def get_job_step_rules(job_id: str):
    """获取指定标准分析作业当前生效的 4 步识别规则（默认从基础识别规则库带入，含该作业自定义修改）。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    return analyze.rules_catalog(override=job.step_rules or None)


@app.put("/api/analyze/jobs/{job_id}/step-rules")
def update_job_step_rules(job_id: str, payload: dict):
    """修改当前标准分析作业的识别规则，可选择是否立即重跑对应步骤及是否同步回基础库。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    rules_patch = payload.get("rules") if isinstance(payload.get("rules"), dict) else payload
    step = payload.get("step")
    rerun_step = bool(payload.get("rerun_step", True))
    sync_to_base = bool(payload.get("sync_to_base", False))
    try:
        updated_job = jobstore.apply_job_step_rules(
            job_id,
            rules_patch=rules_patch,
            step=int(step) if step is not None else None,
            rerun_step=rerun_step,
            sync_to_base=sync_to_base,
        )
        return {"ok": True, "job": updated_job, "rules": updated_job.get("step_rules")}
    except Exception as e:
        raise HTTPException(422, f"应用标准识别规则失败: {e}")


@app.post("/api/analyze/jobs/{job_id}/step-rules/reset")
def reset_job_step_rules(job_id: str, payload: dict | None = Body(default=None)):
    """将当前标准分析作业的某一步（或全部步骤）识别规则恢复为基础识别规则库的默认设置。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    step = (payload or {}).get("step") if isinstance(payload, dict) else None
    step_key = (payload or {}).get("step_key") if isinstance(payload, dict) else None
    rerun_step = bool((payload or {}).get("rerun_step", True)) if isinstance(payload, dict) else True

    base_rules = analyze.get_rules()
    if step_key and step_key in analyze.STEP_RULE_KEYS:
        cur = dict(job.step_rules or base_rules)
        for k in analyze.STEP_RULE_KEYS[step_key]:
            cur[k] = base_rules[k]
        target_rules = cur
    else:
        target_rules = base_rules

    updated_job = jobstore.apply_job_step_rules(
        job_id,
        rules_patch=target_rules,
        step=int(step) if step is not None else None,
        rerun_step=rerun_step,
        sync_to_base=False,
    )
    return {"ok": True, "job": updated_job, "rules": updated_job.get("step_rules")}


@app.get("/api/analyze/jobs")
def analyze_jobs():
    return jobstore.STORE.list()


@app.get("/api/analyze/jobs/{job_id}")
def analyze_job(job_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    return job.public()


STEP_FIELDS = {"items": "items", "params": "params_spec",
               "limits": "limits", "links": "links", "tables": "table_drafts"}


@app.post("/api/analyze/jobs/{job_id}/step/{name}")
def save_step(job_id: str, name: str, payload: StepPayload):
    """分步向导：每一步单独保存 + 标记确认。"""
    if name not in STEP_FIELDS:
        raise HTTPException(400, f"未知步骤 {name}")
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    field = STEP_FIELDS[name]
    kw = {field: payload.data.get(field, payload.data)}
    steps = dict(job.steps or {})
    steps[name] = {"confirmed": payload.confirmed, "at": time.time()}
    kw["steps"] = steps
    jobstore.STORE.update(job_id, **kw)
    return {"ok": True, "steps": steps}


@app.post("/api/analyze/jobs/{job_id}/tables")
def save_draft_table(job_id: str, payload: dict):
    """在作业里建/改一张限值表草稿（发布时一起落库）。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    t = dict(payload)
    if not t.get("id"):
        t["id"] = "T-" + uuid.uuid4().hex[:6]
    drafts = [d for d in (job.table_drafts or []) if d.get("id") != t["id"]]
    drafts.append(t)
    jobstore.STORE.update(job_id, table_drafts=drafts)
    return {"ok": True, "id": t["id"], "count": len(drafts)}


@app.delete("/api/analyze/jobs/{job_id}/tables/{table_id}")
def delete_draft_table(job_id: str, table_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    drafts = [d for d in (job.table_drafts or []) if d.get("id") != table_id]
    jobstore.STORE.update(job_id, table_drafts=drafts)
    return {"ok": True, "count": len(drafts)}


@app.put("/api/analyze/jobs/{job_id}/items")
def analyze_save(job_id: str, payload: ItemsPayload):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    items = []
    for i, it in enumerate(payload.items):
        items.append({
            "id": it.get("id") or f"m{i + 1:03d}",
            "clause": str(it.get("clause", "")).strip(),
            "title": str(it.get("title", "")).strip(),
            "category": it.get("category", "其他"),
            "measurable": bool(it.get("measurable", True)),
            "selected": bool(it.get("selected", True)),
            "score": float(it.get("score", 1.0)),
            "page": int(it.get("page", 0)),
            "evidence": str(it.get("evidence", ""))[:400],
            "table_ref": str(it.get("table_ref", "")),
            "method": str(it.get("method", "")),
            "note": str(it.get("note", "")),
        })
    extra = {}
    if payload.code is not None:
        extra["code"] = payload.code
    if payload.title is not None:
        extra["title"] = payload.title
    if payload.params_spec is not None:
        extra["params_spec"] = payload.params_spec
    if payload.limits is not None:
        extra["limits"] = payload.limits
    jobstore.STORE.update(job_id, items=items, **extra)
    return {"ok": True, "count": len(items)}


@app.post("/api/analyze/jobs/{job_id}/rerun")
def rerun_job(job_id: str):
    """用已存档的原件重新分析（改了识别逻辑后不必重新上传）。"""
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    doc = dbmod.document_for_job(dbmod.connect(), job_id)
    if not doc:
        raise HTTPException(404, "这个作业没有存档原件，无法重跑")
    tmp = jobstore.UPLOADS / f"rerun-{job_id}.pdf"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if doc["storage"] == "file" and doc["path"]:
        shutil.copyfile(doc["path"], tmp)
    else:
        tmp.write_bytes(bytes(doc["content"]))
    # 重跑会重新生成检项 id，草稿表的 item_code 可能失效 → 解绑但保留表数据
    drafts = [{**d, "item_code": ""} for d in (job.table_drafts or [])]
    jobstore.STORE.update(job_id, status="ocr", progress=0, pages=0, items=[],
                          tables=[], params_spec=[], limits={}, code="", title="", error="",
                          steps={}, links={}, published_id="", table_drafts=drafts)
    jobstore.start(job_id, tmp)
    return {"ok": True, "job_id": job_id, "status": "ocr"}


@app.get("/api/analyze/jobs/{job_id}/tables")
def analyze_tables(job_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    return {"tables": job.tables}


@app.get("/api/analyze/jobs/{job_id}/text")
def analyze_text_of(job_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    return {"text": job.text}


@app.get("/api/analyze/jobs/{job_id}/card.xlsx")
def analyze_card(job_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    items = [i for i in job.items if i.get("selected", True)]
    if not items:
        raise HTTPException(400, "没有勾选任何检项")
    data = card_std.build(job, items)
    name = quote(f"检验卡_{job.code or job.filename}.xlsx")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition":
                 f'attachment; filename="card.xlsx"; filename*=UTF-8\'\'{name}'},
    )


@app.post("/api/standards/publish")
def publish(payload: PublishPayload):
    data = payload.model_dump()
    if not data.get("title"):
        raise HTTPException(422, "标准名称不能为空")
    if not data.get("params"):
        data["params"] = []
    job = jobstore.STORE.get(payload.job_id) if payload.job_id else None
    if not data.get("id"):
        data["id"] = "custom-" + uuid.uuid4().hex[:8]   # 固化到文件，重启后不变
    if job and getattr(job, "class_id", ""):
        cid = job.class_id
        if not data.get("classes"):
            data["classes"] = [cid]
        elif cid not in data["classes"]:
            data["classes"].append(cid)
    try:
        std = build_from_payload(data)
    except ValueError as e:
        raise HTTPException(422, str(e))
    data["custom"] = 1
    conn = dbmod.connect()
    if payload.job_id:
        doc = dbmod.document_for_job(conn, payload.job_id)
        if doc:
            data["source"] = {**(data.get("source") or {}),
                              "job_id": payload.job_id,
                              "filename": doc["filename"],
                              "size": doc["size"], "sha256": doc["id"]}
    dbmod.save_payload(conn, data)          # 落库：参数 + 检项 + 限值
    if payload.job_id:
        dbmod.link_document(conn, payload.job_id, std.id)
        job = jobstore.STORE.get(payload.job_id)
        for draft in (job.table_drafts if job else []) or []:
            dbmod.save_table(conn, std.id, draft)
            if draft.get("item_code"):
                dbmod.bind_table(conn, std.id, draft["item_code"], draft["id"])
        for m_data in ((job.workbench_matrices if job else {}) or {}).values():
            if m_data and (m_data.get("tables") or m_data.get("indicators")):
                dbmod.save_and_compile_matrix(conn, std.id, m_data)
        for it in data.get("items") or []:
            if it.get("table"):
                dbmod.bind_table(conn, std.id, it["id"], it["table"])
    register(std, replace=True)
    _reload(std.id)              # 分层/绑定都以库为准，内存里的标准重读一遍
    if payload.job_id:
        jobstore.STORE.update(payload.job_id, published_id=std.id,
                              params_spec=data["params"], limits=data["limits"])
    return {"std_id": std.id, "code": std.code, "title": std.title,
            "params": len(std.params), "items": len(std.items)}


def _cleanup_jobs_for_standard(conn, std_id: str, std_row=None) -> list[str]:
    """删除标准时，同步清理其关联的分析作业缓存（data/jobs/<id>.json），避免重新上传时残留旧的4步状态。"""
    src_job_id = ""
    src_sha = ""
    std_code = ""
    if std_row:
        std_code = (std_row["code"] or "").strip() if "code" in std_row.keys() else ""
        try:
            src = json.loads(std_row["source_json"] or "{}") if "source_json" in std_row.keys() else {}
            src_job_id = (src.get("job_id") or "").strip()
            src_sha = (src.get("sha256") or "").strip()
        except Exception:
            pass
    removed = []
    for j in list(jobstore.STORE._jobs.values()):
        pub_id = getattr(j, "published_id", "") or ""
        if (
            pub_id == std_id
            or (src_job_id and j.id == src_job_id)
            or (src_sha and getattr(j, "sha256", "") == src_sha and not pub_id)
            or (std_code and (getattr(j, "code", "") or "").strip() == std_code and not pub_id)
        ):
            jobstore.STORE.delete(j.id)
            removed.append(j.id)
    return removed


@app.delete("/api/standards/{std_id}")
def delete_standard(std_id: str):
    """删除某笔 标准+小类 主数据，并级联清理其后面的所有规格参数、检验项目、限值表、关联以及分析作业缓存。"""
    REGISTRY.pop(std_id, None)
    conn = dbmod.connect()
    found = conn.execute("SELECT id, code, source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if not found:
        raise HTTPException(404, "标准不存在")
    dbmod.delete(conn, std_id)
    removed_jobs = _cleanup_jobs_for_standard(conn, std_id, found)
    return {"ok": True, "deleted_id": std_id, "deleted_jobs": removed_jobs}


@app.post("/api/standards/unpublish/{std_id}")
def unpublish(std_id: str):
    """下架自定义标准。幂等：内存里没有也照样清库，避免留下孤儿标准。"""
    std = REGISTRY.get(std_id)
    conn0 = dbmod.connect()
    row = conn0.execute("SELECT id, code, custom, source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    if (std and not std.custom) or (row and not row["custom"]):
        raise HTTPException(400, "内置标准不能下架")     # 注册表里没有也要查库
    REGISTRY.pop(std_id, None)
    conn = dbmod.connect()
    found = conn.execute("SELECT id, code, source_json FROM standard WHERE id=?", (std_id,)).fetchone()
    dbmod.delete(conn, std_id)
    _cleanup_jobs_for_standard(conn, std_id, found or row)
    if not found:
        raise HTTPException(404, "标准不存在")
    return {"ok": True}


@app.delete("/api/analyze/jobs/{job_id}")
def analyze_delete(job_id: str):
    job = jobstore.STORE.get(job_id)
    if not job:
        raise HTTPException(404, "作业不存在")
    jobstore.STORE.pdf_path(job_id).unlink(missing_ok=True)
    (jobstore.JOBS / f"{job_id}.json").unlink(missing_ok=True)
    jobstore.STORE._jobs.pop(job_id, None)
    return {"ok": True}


@app.exception_handler(HTTPException)
def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


_LOADED = load_custom()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8022")),
                log_level="info")
