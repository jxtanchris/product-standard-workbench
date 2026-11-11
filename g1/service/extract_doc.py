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


ICS_RE = re.compile(r"^ICS[\s\d.]", re.I)

# 标准号优先级：GB/T → GB → 其他标准化组织
CODE_RULES = [
    re.compile(r"GB\s*/\s*T\s*\d+(?:\.\d+)*\s*[-—–]\s*\d{4}"),
    re.compile(r"GB\s*/\s*T\s*\d+(?:\.\d+)*"),
    re.compile(r"GB\s*\d+(?:\.\d+)*\s*[-—–]\s*\d{4}"),
    re.compile(r"(?:ISO|IEC|DIN|EN|JIS|ASTM|ASME|SAE|BS|NF)\s?[A-Z]?\s?\d+(?:\.\d+)*"
               r"(?:\s*[-—:]\s*\d{4})?"),
]


def _looks_like_code_line(line: str) -> bool:
    """封面上的标准号/ICS/发布日期这类行，不能拿来当标题。"""
    if ICS_RE.match(line):
        return True
    if re.fullmatch(r"[\d\s\-—–.:]+", line):
        return True
    return bool(re.search(r"[A-Za-z]{2,}", line))


def guess_standard_id(pages: list[dict]) -> dict:
    """猜标准号与名称。

    踩过的坑：封面的 ICS 分类号（如 "ICS 21.060.10"）最像"字母+数字"，
    会被误当成标准号；而真正的 GB/T 3098.1-2010 因为 OCR 断行被拆开了。
    所以按"GB/T → GB → 其他组织"的优先级找，并跳过 ICS 行。
    """
    lines = [ln.strip() for p in pages[:3] for ln in p.get("lines", [])]
    text = "\n".join(lines)

    code = ""
    for rule in CODE_RULES:
        for m in rule.finditer(text):
            cand = re.sub(r"\s+", " ", m.group(0)).strip()
            # 落在 ICS 行里的不算
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start:line_end if line_end > 0 else len(text)]
            if ICS_RE.match(line.strip()):
                continue
            code = re.sub(r"\s*[-–]\s*", "—", cand)   # 年份分隔统一成破折号
            break
        if code:
            break

    # 优先在写着“中华人民共和国国家标准”的那一页找标题
    cover = [p for p in pages[:4]
             if any("中华人民共和国国家标准" in ln for ln in p.get("lines", []))]
    pool = cover[0].get("lines", []) if cover else lines

    def clean_title(raw: str) -> str:
        c = re.split(r"(代替|发布|实施|Tolerances)", raw)[0].strip()
        return re.sub(r"\s{2,}", " ", c)

    def usable(c: str) -> bool:
        cjk = len(re.findall(r"[\u4e00-\u9fa5]", c))
        return (2 <= cjk <= 24 and "标准" not in c and "。" not in c
                and "，" not in c and not _looks_like_code_line(c))

    title = ""
    for i, ln in enumerate(pool):
        if "国家标准" not in ln:
            continue
        parts: list[str] = []
        for cand in pool[i + 1:i + 8]:
            c = clean_title(cand)
            if not c:
                if parts:            # 标题后面紧跟英文名/“代替…”，说明标题已结束
                    break
                continue
            if usable(c):
                parts.append(c)
                if len(parts) == 2:      # 最多拼两行：主标题 + 副标题
                    break
            elif parts:
                break                     # 已经拿到标题，遇到非标题行就停
        title = " ".join(parts)
        break

    if not title:
        for ln in pool[:20]:
            c = clean_title(ln)
            if usable(c):
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
