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

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import card_std  # noqa: E402
import db as dbmod  # noqa: E402
import extract_doc  # noqa: E402
import jobs as jobstore  # noqa: E402
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


def resolve_rows(std: Standard, ctx: dict[str, Any]) -> list[dict]:
    rows = []
    for item in std.items:
        missing = [p for p in item["requires"] if p not in ctx]
        if missing:
            rows.append(dict(
                id=item["id"], name=item["name"], symbol=item["symbol"], clause=item["clause"],
                kind=item["kind"], page=item.get("page"), status="MISS", status_text="缺少参数",
                limit_text=f"请先填写 {', '.join(missing)}", lower=None, upper=None, unit="mm",
                measured_key=item["measured_key"], nominal_param=item["nominal_param"],
                nominal_value=ctx.get(item["nominal_param"]),
                method=item["method"], position=item["position"], gauge=item["gauge"],
                points=item["points"], measured_hint=item["measured_hint"],
                trace=[f"缺少参数 {', '.join(missing)}，无法解析"],
            ))
            continue
        r = std.tables[item["table"]].evaluate(ctx, std.symbols)
        rows.append(dict(
            id=item["id"], name=item["name"], symbol=item["symbol"], clause=item["clause"],
            kind=item["kind"], page=item.get("page"),
            status=r.status.value, status_text=STATUS_TEXT[r.status],
            limit_text=limit_text(r), lower=r.lower, upper=r.upper, unit=r.unit,
            measured_key=item["measured_key"], nominal_param=item["nominal_param"],
            nominal_value=ctx.get(item["nominal_param"]),
            method=item["method"], position=item["position"], gauge=item["gauge"],
            points=item["points"], measured_hint=item["measured_hint"],
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
    std = _std(req.std)
    ctx, errors = std.build_context(req.params)
    if errors:
        raise HTTPException(422, detail={"errors": errors})
    return std, ctx


def default_params(std: Standard) -> dict:
    return {p.code: p.default for p in std.params if p.default is not None}


# ------------------------------------------------------------------ 路由
@app.get("/")
def index():
    return FileResponse(APP_DIR / "templates" / "index.html")


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
def std_editor(std_id: str):
    std = _std(std_id)
    conn = dbmod.connect()
    return {
        "std": std.id, "code": std.code, "title": std.title,
        "params": [p.meta() for p in std.params],
        "items": [{"code": i["id"], "name": i.get("name") or i.get("title") or i["id"],
                   "clause": i.get("clause", ""), "page": i.get("page"),
                   "kind": i.get("kind") or i.get("category") or "其他"} for i in std.items],
        "tables": dbmod.table_detail(conn, std.id),
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
                    "has_source": dbmod.document_for_standard(conn, s.id) is not None})
    return out


@app.get("/api/meta")
def meta(std: str = Query("gb3103-3")):
    s = _std(std)
    data = s.meta()
    data["default_params"] = default_params(s)
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


@app.post("/api/analyze/upload")
async def analyze_upload(file: UploadFile = File(...)):
    name = file.filename or "standard.pdf"
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "目前仅支持 PDF；扫描件也可以（走离线 OCR）")

    # 1) 落到临时文件，同时算 sha256
    tmp = jobstore.UPLOADS / f"tmp-{uuid.uuid4().hex}.pdf"
    digest, size = hashlib.sha256(), 0
    with open(tmp, "wb") as f:
        while chunk := await file.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
            f.write(chunk)
    sha = digest.hexdigest()

    conn = dbmod.connect()

    # 2) 同一份文件传过、且作业还在 → 直接复用，不重复 OCR
    existing = dbmod.find_document(conn, sha)
    if existing and existing["job_id"]:
        job = jobstore.STORE.get(existing["job_id"])
        if job:
            tmp.unlink(missing_ok=True)
            return {"job_id": job.id, "status": job.status, "reused": True,
                    "sha256": sha, "size": size}

    # 3) 建作业 + 归档原件
    job = jobstore.STORE.create(name)
    path = jobstore.STORE.pdf_path(job.id)
    shutil.move(str(tmp), path)

    inline = size <= DOC_INLINE_LIMIT
    dbmod.save_document(
        conn, sha, name, size,
        data=path.read_bytes() if inline else None,
        path=None if inline else str(path),
        job_id=job.id)
    jobstore.start(job.id, path)
    return {"job_id": job.id, "status": job.status, "sha256": sha, "size": size,
            "storage": "db" if inline else "file"}


@app.post("/api/analyze/text")
def analyze_text(payload: TextPayload):
    job = jobstore.STORE.create(payload.filename)
    jobstore.run_from_text(job.id, payload.text)
    return {"job_id": job.id, "status": "done"}


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
               "limits": "limits", "links": "links"}


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
    jobstore.STORE.update(job_id, status="ocr", progress=0, pages=0, items=[],
                          tables=[], params_spec=[], limits={}, code="", title="", error="",
                          steps={}, links={}, published_id="")
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
    if not data.get("id"):
        data["id"] = "custom-" + uuid.uuid4().hex[:8]   # 固化到文件，重启后不变
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
    register(std, replace=True)
    if payload.job_id:
        jobstore.STORE.update(payload.job_id, published_id=std.id,
                              params_spec=data["params"], limits=data["limits"])
    return {"std_id": std.id, "code": std.code, "title": std.title,
            "params": len(std.params), "items": len(std.items)}


@app.post("/api/standards/unpublish/{std_id}")
def unpublish(std_id: str):
    """下架自定义标准。幂等：内存里没有也照样清库，避免留下孤儿标准。"""
    std = REGISTRY.get(std_id)
    if std and not std.custom:
        raise HTTPException(400, "内置标准不能下架")
    REGISTRY.pop(std_id, None)
    conn = dbmod.connect()
    found = conn.execute("SELECT id FROM standard WHERE id=?", (std_id,)).fetchone()
    dbmod.delete(conn, std_id)
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
