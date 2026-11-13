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
    workbench_state: dict = field(default_factory=dict)      # 多步骤逐表拆解工作台状态 (table_id -> {status, split_mode, sub_count})
    workbench_matrices: dict = field(default_factory=dict)   # 工作台中已拆解保存的矩阵定义 (table_id -> matrix_dict)
    step_rules: dict = field(default_factory=dict)           # 从基础「识别规则库」默认带入并可在当前标准独立修改的各步骤识别规则
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        d = asdict(self)
        d["text"] = self.text[:4000]
        d["has_text"] = bool(self.text)
        if not d.get("step_rules"):
            d["step_rules"] = analyze.get_rules()
        else:
            d["step_rules"] = analyze.get_rules(d["step_rules"])
        return d

    def to_dict_full(self) -> dict:
        return asdict(self)


class Store:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._load()

    def _load(self):
        for f in sorted(JOBS.glob("*.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                allowed = {f for f in Job.__dataclass_fields__}
                j = Job(**{k: v for k, v in raw.items() if k in allowed})
                if not j.step_rules:
                    j.step_rules = analyze.get_rules()
                self._jobs[raw["id"]] = j
            except Exception:
                continue

    def _save(self, job: Job):
        (JOBS / f"{job.id}.json").write_text(
            json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")

    def create(self, filename: str, class_id: str = "", sha256: str = "") -> Job:
        classes = [class_id] if class_id else []
        job = Job(id=uuid.uuid4().hex[:10], filename=filename,
                  class_id=class_id, classes=classes, sha256=sha256,
                  step_rules=analyze.get_rules())
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

    def delete(self, job_id: str) -> bool:
        with _LOCK:
            job = self._jobs.pop(job_id, None)
        self.pdf_path(job_id).unlink(missing_ok=True)
        (JOBS / f"{job_id}.json").unlink(missing_ok=True)
        return job is not None


STORE = Store()


def clone_from_ocr(new_job_id: str, src_job: Job, class_id: str):
    """从已有完成 OCR 的作业中复用 OCR 文本与表格网格，按最新识别规则重新生成全新的 4 步初始数据。"""
    s_rules = analyze.get_rules()
    pages = _text_to_pages(src_job.text)
    if pages:
        cands_obj = analyze.parse(pages, rules_override=s_rules)
        cands = [c.to_dict() for c in cands_obj]
        params = analyze.suggest_params(pages, rules_override=s_rules)
        limits = _default_limits(cands_obj)
    else:
        cands = [dict(c) for c in src_job.items]
        params = [dict(p) for p in src_job.params_spec]
        limits = copy.deepcopy(src_job.limits)

    for c in cands:
        c["class_id"] = class_id
    for p in params:
        p["class_id"] = class_id
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
                 tables=tables,
                 steps={},
                 links={},
                 table_drafts=[],
                 workbench_state={},
                 workbench_matrices={},
                 step_rules=s_rules,
                 published_id="")


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
def _text_to_pages(text: str) -> list[dict]:
    """将作业已保存的全文按分页标记或整体还原为 pages 列表，供免 OCR 快速重跑各步识别规则。"""
    if not text:
        return []
    import re as _re
    parts = _re.split(r"---\s*第\s*(\d+)\s*页\s*---", text)
    if len(parts) > 1:
        pages = []
        # parts[0] 为前缀，之后成对出现 (page_no, content)
        for i in range(1, len(parts), 2):
            pno = int(parts[i])
            body = parts[i + 1] if i + 1 < len(parts) else ""
            pages.append({"page": pno, "lines": [ln for ln in body.splitlines() if ln.strip()]})
        if pages:
            return pages
    return [{"page": 1, "lines": [ln for ln in text.splitlines() if ln.strip()]}]


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
        job = STORE.get(job_id)
        cid = getattr(job, "class_id", "") if job else ""
        s_rules = (job.step_rules if job and job.step_rules else None) or analyze.get_rules()
        cands = analyze.parse(pages, rules_override=s_rules)
        cand_dicts = [c.to_dict() for c in cands]
        if cid:
            for it in cand_dicts:
                if not it.get("class_id"):
                    it["class_id"] = cid
        params = analyze.suggest_params(pages, rules_override=s_rules)
        if cid:
            for p in params:
                if not p.get("class_id"):
                    p["class_id"] = cid
        STORE.update(job_id, status="done", progress=100,
                     items=cand_dicts,
                     params_spec=params,
                     limits=_default_limits(cands),
                     tables=tablefind.detect(pages),
                     step_rules=s_rules,
                     classes=[cid] if cid else [])
    except Exception as e:  # noqa: BLE001
        STORE.update(job_id, status="error", error=str(e), progress=100)


def start(job_id: str, pdf_path: Path):
    t = threading.Thread(target=_run, args=(job_id, pdf_path), daemon=True)
    t.start()


def run_from_text(job_id: str, text: str, class_id: str = ""):
    """无 PDF 或 OCR 不可用时的兜底：直接分析粘贴的文本。"""
    job = STORE.get(job_id)
    s_rules = (job.step_rules if job and job.step_rules else None) or analyze.get_rules()
    lines = [ln for ln in text.splitlines()]
    pages = [{"page": 1, "lines": lines}]
    cands = analyze.parse(pages, rules_override=s_rules)
    cand_dicts = [c.to_dict() for c in cands]
    if class_id:
        for it in cand_dicts:
            it["class_id"] = class_id
    params = analyze.suggest_params(pages, rules_override=s_rules)
    if class_id:
        for p in params:
            p["class_id"] = class_id
    STORE.update(job_id, status="done", progress=100, pages=1, engine="text",
                 text=text, quality=1.0, items=cand_dicts,
                 class_id=class_id, classes=[class_id] if class_id else [],
                 params_spec=params,
                 step_rules=s_rules,
                 limits=_default_limits(cands))


def apply_job_step_rules(
    job_id: str,
    rules_patch: dict,
    step: int | None = None,
    rerun_step: bool = True,
    sync_to_base: bool = False,
) -> dict:
    """更新指定标准分析作业的识别规则（默认带入后针对单标准修改），并可按需重跑对应步骤及同步回基础库。"""
    job = STORE.get(job_id)
    if not job:
        raise ValueError("作业不存在")

    merged = analyze.get_rules({**(job.step_rules or {}), **(rules_patch or {})})
    if sync_to_base:
        merged = analyze.save_rules(merged)

    updates: dict = {"step_rules": merged}
    cid = getattr(job, "class_id", "") or ""
    pages = _text_to_pages(job.text)

    if rerun_step:
        if step in (1, None) and pages:
            cands = analyze.parse(pages, rules_override=merged)
            cand_dicts = [c.to_dict() for c in cands]
            if cid:
                for it in cand_dicts:
                    if not it.get("class_id"):
                        it["class_id"] = cid
            updates["items"] = cand_dicts
            # 补充新检项的默认 limits
            cur_limits = dict(job.limits or {})
            for c in cands:
                cur_limits.setdefault(c.id, {
                    "mode": "range" if c.measurable else "none",
                    "lower": None, "upper": None, "unit": "mm",
                })
            updates["limits"] = cur_limits

        if step in (2, None) and pages:
            params = analyze.suggest_params(pages, rules_override=merged)
            if cid:
                for p in params:
                    if not p.get("class_id"):
                        p["class_id"] = cid
            updates["params_spec"] = params

        if step in (4, None):
            items_now = updates.get("items", job.items or [])
            drafts_now = job.table_drafts or []
            updates["links"] = analyze.auto_link_items_and_tables(
                items_now, drafts_now, existing_links=job.links, rules_override=merged
            )

    STORE.update(job_id, **updates)
    return STORE.get(job_id).public()
