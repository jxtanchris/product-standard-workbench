# -*- coding: utf-8 -*-
"""分析作业：上传 → OCR → 识别 → 人工确认 → 出卡。

作业是文件落盘的（data/jobs/<id>.json），进程重启后还能打开；
PDF 原件留在 data/uploads/ 便于复核与重跑分析。
"""
from __future__ import annotations

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
    items: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)      # 从原文检测到的表格网格
    params_spec: list[dict] = field(default_factory=list)   # 选择规格的参数
    limits: dict = field(default_factory=dict)              # item_id -> 限值定义
    published_id: str = ""                                  # 发布后对应的标准 id
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

    def create(self, filename: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], filename=filename)
        with _LOCK:
            self._jobs[job.id] = job
            self._save(job)
        return job

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
                 "items": len(j.items), "created_at": j.created_at} for j in jobs]

    def pdf_path(self, job_id: str) -> Path:
        return UPLOADS / f"{job_id}.pdf"


STORE = Store()


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
        cands = analyze.parse(pages)
        STORE.update(job_id, status="done", progress=100,
                     items=[c.to_dict() for c in cands],
                     params_spec=analyze.suggest_params(pages),
                     limits=_default_limits(cands),
                     tables=tablefind.detect(pages))
    except Exception as e:  # noqa: BLE001
        STORE.update(job_id, status="error", error=str(e), progress=100)


def start(job_id: str, pdf_path: Path):
    t = threading.Thread(target=_run, args=(job_id, pdf_path), daemon=True)
    t.start()


def run_from_text(job_id: str, text: str):
    """无 PDF 或 OCR 不可用时的兜底：直接分析粘贴的文本。"""
    lines = [ln for ln in text.splitlines()]
    pages = [{"page": 1, "lines": lines}]
    cands = analyze.parse(pages)
    STORE.update(job_id, status="done", progress=100, pages=1, engine="text",
                 text=text, quality=1.0, items=[c.to_dict() for c in cands],
                 params_spec=analyze.suggest_params(pages),
                 limits=_default_limits(cands))
