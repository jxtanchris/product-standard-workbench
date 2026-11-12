# -*- coding: utf-8 -*-
"""分析作业：上传 → OCR → 识别 → 人工确认 → 出卡。

作业是文件落盘的（data/jobs/<id>.json），进程重启后还能打开；
PDF 原件留在 data/uploads/ 便于复核与重跑分析。
"""
from __future__ import annotations

import copy
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import analyze
import extract_doc
import tablefind

DATA = Path(__file__).resolve().parent.parent.parent / "data"
JOBS = DATA / "jobs"
UPLOADS = DATA / "uploads"
JOBS.mkdir(parents=True, exist_ok=True)
UPLOADS.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()


@dataclass
class Job:
    id: str
    filename: str
    status: str = "queued"      # queued | ocr | analyzing | done | error
    progress: int = 0
    pages: int = 0
    quality: float = 0.0
    engine: str = ""
    code: str = ""
    title: str = ""
    error: str = ""
    text: str = ""
    class_id: str = ""                                      # 绑定的产品小类
    classes: list[str] = field(default_factory=list)        # 覆盖的产品小类
    sha256: str = ""                                        # 原件哈希
    items: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)      # 从原文检测到的表格网格
    params_spec: list[dict] = field(default_factory=list)   # 选择规格的参数
    limits: dict = field(default_factory=dict)              # item_id -> 限值定义
    published_id: str = ""                                  # 发布后对应的标准 id
    steps: dict = field(default_factory=dict)               # 每一步是否已确认
    links: dict = field(default_factory=dict)               # item_id -> 限值来源
    table_drafts: list[dict] = field(default_factory=list)   # 发布前在作业里建的限值表草稿
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        d = asdict(self)
        d["text"] = self.text[:4000]
        d["has_text"] = bool(self.text)
        return d


class Store:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self):
        for f in sorted(JOBS.glob("*.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                allowed = {f for f in Job.__dataclass_fields__}
                self._jobs[raw["id"]] = Job(**{k: v for k, v in raw.items() if k in allowed})
            except Exception:
                continue

    def _save(self, job: Job):
        (JOBS / f"{job.id}.json").write_text(
            json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")

    def create(self, filename: str, class_id: str = "", sha256: str = "") -> Job:
        classes = [class_id] if class_id else []
        job = Job(id=uuid.uuid4().hex[:10], filename=filename,
                  class_id=class_id, classes=classes, sha256=sha256)
        with _LOCK:
            self._jobs[job.id] = job
            self._save(job)
        return job

    def find_by_sha_and_class(self, sha256: str, class_id: str) -> Job | None:
        if not sha256:
            return None
        for j in sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True):
            if getattr(j, "sha256", "") == sha256 and (getattr(j, "class_id", "") or "") == (class_id or ""):
                return j
        return None

    def find_done_by_sha(self, sha256: str) -> Job | None:
        if not sha256:
            return None
        for j in sorted(self._jobs.values(), key=lambda x: x.created_at, reverse=True):
            if getattr(j, "sha256", "") == sha256 and j.status == "done" and j.text:
                return j
        return None

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **kw):
        with _LOCK:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in kw.items():
                setattr(job, k, v)
            self._save(job)

    def list(self) -> list[dict]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [{"id": j.id, "filename": j.filename, "status": j.status,
                 "code": j.code, "title": j.title, "pages": j.pages,
                 "class_id": getattr(j, "class_id", ""),
                 "classes": getattr(j, "classes", []),
                 "items": len(j.items), "created_at": j.created_at} for j in jobs]

    def pdf_path(self, job_id: str) -> Path:
        return UPLOADS / f"{job_id}.pdf"


STORE = Store()


def clone_from_ocr(new_job_id: str, src_job: Job, class_id: str):
    """从已有完成 OCR 的作业中复用 OCR 文本与解析结果，瞬间生成绑定新小类的独立作业。"""
    cands = [dict(c) for c in src_job.items]
    for c in cands:
        c["class_id"] = class_id
    params = [dict(p) for p in src_job.params_spec]
    for p in params:
        p["class_id"] = class_id
    limits = copy.deepcopy(src_job.limits)
    tables = copy.deepcopy(src_job.tables)

    STORE.update(new_job_id,
                 status="done", progress=100,
                 pages=src_job.pages,
                 quality=src_job.quality,
                 engine=src_job.engine,
                 code=src_job.code,
                 title=src_job.title,
                 text=src_job.text,
                 class_id=class_id,
                 classes=[class_id] if class_id else [],
                 items=cands,
                 params_spec=params,
                 limits=limits,
                 tables=tables)


def _drop_file_if_stored(job_id: str, pdf_path: Path) -> None:
    """原件已经进库了，磁盘上的副本可以删。"""
    try:
        import db as _db
        doc = _db.document_for_job(_db.connect(), job_id)
        if doc and doc["storage"] == "db":
            Path(pdf_path).unlink(missing_ok=True)
    except Exception:
        pass


def _default_limits(cands) -> dict:
    """默认定价：能判定的给区间空值，其余记为仅记录。"""
    out = {}
    for c in cands:
        out[c.id] = {"mode": "range" if c.measurable else "none",
                     "lower": None, "upper": None, "unit": "mm"}
    return out


# ---------------------------------------------------------------- 分析流程
def _run(job_id: str, pdf_path: Path):
    try:
        STORE.update(job_id, status="ocr", progress=10)
        data = extract_doc.run_ocr(pdf_path, dpi=300)
        pages = data["pages"]
        text = extract_doc.doc_text(pages)
        guess = extract_doc.guess_standard_id(pages)
        STORE.update(job_id, status="analyzing", progress=70, pages=len(pages),
                     engine=data.get("engine", ""), text=text,
                     quality=extract_doc.quality(pages),
                     code=guess["code"], title=guess["title"])
        _drop_file_if_stored(job_id, pdf_path)
        cands = analyze.parse(pages)
        cand_dicts = [c.to_dict() for c in cands]
        job = STORE.get(job_id)
        cid = getattr(job, "class_id", "") if job else ""
        if cid:
            for it in cand_dicts:
                if not it.get("class_id"):
                    it["class_id"] = cid
        params = analyze.suggest_params(pages)
        if cid:
            for p in params:
                if not p.get("class_id"):
                    p["class_id"] = cid
        STORE.update(job_id, status="done", progress=100,
                     items=cand_dicts,
                     params_spec=params,
                     limits=_default_limits(cands),
                     tables=tablefind.detect(pages),
                     classes=[cid] if cid else [])
    except Exception as e:  # noqa: BLE001
        STORE.update(job_id, status="error", error=str(e), progress=100)


def start(job_id: str, pdf_path: Path):
    t = threading.Thread(target=_run, args=(job_id, pdf_path), daemon=True)
    t.start()


def run_from_text(job_id: str, text: str, class_id: str = ""):
    """无 PDF 或 OCR 不可用时的兜底：直接分析粘贴的文本。"""
    lines = [ln for ln in text.splitlines()]
    pages = [{"page": 1, "lines": lines}]
    cands = analyze.parse(pages)
    cand_dicts = [c.to_dict() for c in cands]
    if class_id:
        for it in cand_dicts:
            it["class_id"] = class_id
    params = analyze.suggest_params(pages)
    if class_id:
        for p in params:
            p["class_id"] = class_id
    STORE.update(job_id, status="done", progress=100, pages=1, engine="text",
                 text=text, quality=1.0, items=cand_dicts,
                 class_id=class_id, classes=[class_id] if class_id else [],
                 params_spec=params,
                 limits=_default_limits(cands))
