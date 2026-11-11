# -*- coding: utf-8 -*-
"""PDF 取文：优先离线 OCR（macOS Vision），失败时回落到文本层。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parent / "bin" / "ocrkit"


class ExtractError(RuntimeError):
    pass


def ocr_available() -> bool:
    return BIN.exists() and os.access(BIN, os.X_OK)


def run_ocr(pdf_path: str | Path, dpi: int = 300, timeout: int = 600) -> dict:
    """返回 {"pages":[{"page":1,"lines":[...]}], "engine":"ocr"}"""
    if not ocr_available():
        raise ExtractError("未找到 ocrkit（离线 OCR 组件）")
    try:
        out = subprocess.run([str(BIN), str(pdf_path), str(dpi)],
                             capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise ExtractError(f"OCR 超时（>{timeout}s），页面过多时请拆分后上传")
    if out.returncode != 0:
        raise ExtractError(f"OCR 失败（退出码 {out.returncode}）：{out.stderr[:200].decode('utf-8', 'ignore')}")
    data = json.loads(out.stdout or b"{}")
    data["engine"] = "ocr"
    return data


def doc_text(pages: list[dict]) -> str:
    return "\n".join("\n".join(p.get("lines", [])) for p in pages)


def quality(pages: list[dict]) -> float:
    """粗糙的取文质量分：CJK 字符占比 + 行数是否合理。0~1"""
    text = doc_text(pages)
    if not text.strip():
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fa5]", text))
    total = len(re.sub(r"\s", "", text)) or 1
    ratio = cjk / total
    lines = sum(len(p.get("lines", [])) for p in pages)
    per_page = lines / max(1, len(pages))
    return round(min(1.0, ratio * 1.6) * min(1.0, per_page / 12), 3)


def guess_standard_id(pages: list[dict]) -> dict:
    """从封面页猜标准号与名称，猜不到就留空让用户改。"""
    head = doc_text(pages[:3])
    code = ""
    m = re.search(r"\b([A-Z]{2,4}(?:/[A-Z])?\s?\d+(?:\.\d+)*(?:\s?[—\-–]\s?\d{4})?)\b", head)
    if m:
        code = re.sub(r"\s+", " ", m.group(1))

    # 优先在写着“中华人民共和国国家标准”的那一页找标题
    cover = [p for p in pages[:4]
             if any("中华人民共和国国家标准" in ln for ln in p.get("lines", []))]
    pool = cover[0].get("lines", []) if cover else \
        [ln for p in pages[:3] for ln in p.get("lines", [])]

    title = ""
    for i, ln in enumerate(pool):
        if "国家标准" in ln:
            for cand in pool[i + 1:i + 8]:
                c = re.split(r"(代替|发布|实施|Tolerances)", cand)[0].strip()
                c = re.sub(r"\s{2,}", " ", c)
                cjk = len(re.findall(r"[\u4e00-\u9fa5]", c))
                if (2 <= cjk <= 20 and "标准" not in c and "。" not in c and "，" not in c
                        and not re.search(r"[A-Z]{2}/?T", c)):
                    title = c
                    break
            break
    if not title:
        for ln in pool[:20]:
            c = ln.strip()
            cjk = len(re.findall(r"[\u4e00-\u9fa5]", c))
            if (4 <= cjk <= 20 and "。" not in c and "，" not in c
                    and not re.search(r"[A-Za-z]{2,}", c)):
                title = c
                break
    return {"code": code, "title": title}


def cleanup(pdf_path: str | Path) -> None:
    for p in (pdf_path,):
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


def which_pdf_tools() -> str:
    return shutil.which("pdftotext") or ""
