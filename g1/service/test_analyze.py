# -*- coding: utf-8 -*-
"""上传 → OCR → 识别 → 确认 → 出卡 的端到端测试。需要服务已启动。

    .venv/bin/python test_analyze.py [pdf_path] [base_url]

默认用仓库根目录的 GB3103-3.pdf（7 页扫描件）。
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "GB3103-3.pdf"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8022"
PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def upload(path: Path):
    boundary = "----dshboundary"
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode())
    body.write(b"Content-Type: application/pdf\r\n\r\n")
    body.write(path.read_bytes())
    body.write(f"\r\n--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"{BASE}/api/analyze/upload", data=body.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.read(), dict(r.headers)


def getjson(path):
    return json.loads(get(path)[1])


def post(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def put(path, payload):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    if not PDF.exists():
        print(f"找不到样例 PDF：{PDF}")
        return 2

    print("1. 上传")
    res = upload(PDF)
    job_id = res.get("job_id")
    check("返回 job_id", bool(job_id), str(res))

    print("2. 分析（离线 OCR）")
    t0 = time.time()
    job = {}
    while time.time() - t0 < 180:
        job = getjson(f"/api/analyze/jobs/{job_id}")
        if job["status"] in ("done", "error"):
            break
        time.sleep(1.5)
    check("作业完成", job.get("status") == "done", str(job.get("error"))[:120])
    check("页数识别正确", job.get("pages", 0) >= 7, str(job.get("pages")))
    check("取文引擎为 ocr", job.get("engine") == "ocr", job.get("engine"))
    check("取文质量分 > 0.4", job.get("quality", 0) > 0.4, str(job.get("quality")))
    check("识别出标准号", "3103.3" in job.get("code", ""), job.get("code"))
    check("识别出标准名称", "平垫圈" in job.get("title", ""), job.get("title"))
    elapsed = time.time() - t0
    print(f"        （7 页耗时 {elapsed:.1f}s）")

    items = job.get("items", [])
    clauses = {i["clause"] for i in items}
    check("候选检项 ≥ 6 条", len(items) >= 6, str(len(items)))
    check("识别出 3.1 通孔", "3.1" in clauses, str(sorted(clauses)))
    check("识别出 3.5.2 同轴度", any(i["clause"] == "3.5.2" and "同轴度" in i["title"] for i in items))
    check("识别出 3.5.3 平面度", any(i["clause"] == "3.5.3" and "平面度" in i["title"] for i in items))
    check("每条都有页码与原文依据",
          all(i["page"] and i["evidence"] for i in items))
    check("类别已分（尺寸/形位）",
          {"尺寸", "形位"} <= {i["category"] for i in items},
          str({i["category"] for i in items}))

    print("2b. 原文表格识别")
    tabs = getjson(f"/api/analyze/jobs/{job_id}/tables")["tables"]
    check("检测到表格", len(tabs) >= 5, str(len(tabs)))
    big = [t for t in tabs if t["rows"] >= 8]
    check("有 8 行以上的表", bool(big), str([(t["page"], t["rows"], t["cols"]) for t in tabs]))
    flat = " ".join(c for t in tabs for row in t["grid"] for c in row)
    check("格子里能读到关键文本（H13 / h≤4）",
          ("H13" in flat) or ("h≤4" in flat) or ("h≤" in flat), flat[:80])
    check("每张表都带页码", all(t.get("page") for t in tabs))

    print("3. 人工确认（改一条、删一条）")
    keep = [dict(i) for i in items]
    keep[0]["title"] = keep[0]["title"] + "（已确认）"
    dropped = keep.pop()
    r = put(f"/api/analyze/jobs/{job_id}/items",
            {"items": keep, "code": "GB/T 3103.3—2000", "title": "紧固件公差 平垫圈"})
    check("保存成功", r.get("ok") and r.get("count") == len(keep), str(r))
    job2 = getjson(f"/api/analyze/jobs/{job_id}")
    check("改动已持久化", job2["items"][0]["title"].endswith("（已确认）"))
    check("删除生效", all(i["clause"] != dropped["clause"] or i["id"] != dropped["id"]
                        for i in job2["items"]))

    print("4. 导出检验卡")
    st, body, headers = get(f"/api/analyze/jobs/{job_id}/card.xlsx")
    check("返回 200", st == 200)
    check("是 xlsx（PK）", body[:2] == b"PK")
    try:
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(body)).active
        check("能被 openpyxl 打开", ws.title == "检验卡")
        n = sum(1 for row in ws.iter_rows(min_col=1, max_col=1) if isinstance(row[0].value, int))
        check("行数等于确认后的检项数", n == len(keep), f"{n} vs {len(keep)}")
        check("首行含标准号", "3103.3" in str(ws.cell(row=1, column=1).value))
    except ImportError:
        print("  SKIP  openpyxl 未安装")

    print("5. 发布为标准 → 第二步选标准出卡")
    items = job2["items"]
    limits = {}
    for it in items:
        limits[it["id"]] = {"mode": "range", "lower": 1.0, "upper": 2.0, "unit": "mm"}
    limits[items[0]["id"]] = {"mode": "max", "lower": None, "upper": 0.5, "unit": "mm"}
    pub = post("/api/standards/publish", {
        "job_id": job_id, "code": "GB/T 9999-TEST", "title": "测试标准（自动发布）",
        "params": job2.get("params_spec") or [], "items": items, "limits": limits,
        "source": {"job_id": job_id},
    })
    std_id = pub.get("std_id")
    check("发布返回 std_id", bool(std_id), str(pub))
    check("参数随标准一起发布", pub.get("params", 0) >= 1, str(pub))
    check("检项数一致", pub.get("items") == len(items), f'{pub.get("items")} vs {len(items)}')

    stds = getjson("/api/standards")
    check("出现在标准列表里", any(s["id"] == std_id for s in stds))
    meta2 = getjson(f"/api/meta?std={std_id}")
    check("第二步能取到参数 schema", len(meta2["params"]) == pub["params"])
    check("参数带代码与类型", all("code" in p and "type" in p for p in meta2["params"]))

    params = {p["code"]: (p["options"][0] if p["type"] == "enum" else 1) for p in meta2["params"]}
    res = post("/api/resolve", {"std": std_id, "params": params})
    rows = res["rows"]
    check("第二步解析出全部检项", len(rows) == len(items), f"{len(rows)} vs {len(items)}")
    check("常量限值生效（≤0.5）", any(r["limit_text"] == "≤ 0.500 mm" for r in rows),
          str([r["limit_text"] for r in rows])[:120])
    check("区间限值生效（1.000～2.000）",
          any("1.000" in r["limit_text"] and "2.000" in r["limit_text"] for r in rows))

    measured = {r["measured_key"]: 1.5 for r in rows}
    measured[rows[0]["measured_key"]] = 0.8      # 第一项是 max 0.5 → 应判不合格
    jd = post("/api/judge", {"std": std_id, "params": params, "measured": measured})
    check("判定生效：超上限判不合格",
          jd["rows"][0]["verdict"] == "不合格", jd["rows"][0]["verdict"])
    check("判定生效：区间内判合格",
          sum(1 for r in jd["rows"] if r["verdict"] == "合格") >= 1, str(jd["counts"]))

    print("6. 原文与清理")
    req = urllib.request.Request(f"{BASE}/api/standards/unpublish/{std_id}", method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        check("下架自定义标准", r.status == 200)
    check("可取到 OCR 原文", len(getjson(f"/api/analyze/jobs/{job_id}/text")["text"]) > 500)
    req = urllib.request.Request(f"{BASE}/api/analyze/jobs/{job_id}", method="DELETE")
    with urllib.request.urlopen(req, timeout=10) as r:
        check("删除作业", r.status == 200)

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
