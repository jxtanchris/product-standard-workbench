# -*- coding: utf-8 -*-
"""接口冒烟测试：不依赖测试框架，直接打 HTTP。先用 run.sh 启动服务。

    .venv/bin/python test_api.py [base_url]
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8022"
STD = "gb3103-3"
PASS = FAIL = 0
BASE_PARAMS = {"grade": "A", "material": "非不锈钢", "h_nom": 2, "d1_nom": 13, "d2_nom": 24}


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read(), dict(r.headers)


def getjson(path: str):
    return json.loads(get(path)[1])


def put(path: str, payload: dict):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"{}")


def post(path: str, payload: dict):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def resolve(params=None, std=STD):
    return post("/api/resolve", {"std": std, "params": params if params is not None else BASE_PARAMS})


def judge(measured, params=None):
    return post("/api/judge", {"std": STD, "params": params or BASE_PARAMS, "measured": measured})


def main():
    print("1. 页面与元数据")
    st, body, _ = get("/")
    check("GET / 返回页面", st == 200 and b"<html" in body.lower())
    st, body, _ = get("/api/standards")
    stds = json.loads(body)
    check("GET /api/standards 有注册标准", st == 200 and any(s["id"] == STD for s in stds))
    st, body, _ = get("/api/meta?std=" + STD)
    meta = json.loads(body)
    codes = [p["code"] for p in meta["params"]]
    check("参数由标准声明（5 个）", codes == ["grade", "material", "h_nom", "d1_nom", "d2_nom"], str(codes))
    check("检项带 measured_key", all("measured_key" in i for i in meta["items"]))
    check("实测键统一 *_act", all(i["measured_key"].endswith("_act") for i in meta["items"]))

    print("2. 解析（A 级 / C 级）")
    st, d = resolve()
    rows = {r["id"]: r for r in d["rows"]}
    check("A 级 8 项均可判定", st == 200 and all(r["status"] == "OK" for r in rows.values()))
    check("d1 = 13.000~13.270", "13.270" in rows["d1"]["limit_text"], rows["d1"]["limit_text"])
    check("t1 = 0.420（2IT12，按 d2=24 查档）", "0.420" in rows["t1"]["limit_text"], rows["t1"]["limit_text"])
    check("d1 解析轨迹含代号 H13", any("H13" in t for t in rows["d1"]["trace"]))
    check("t1 解析轨迹用 d2_nom 基准",
          any("d2_nom" in t for t in rows["t1"]["trace"])
          and any("IT12" in t for t in rows["t1"]["trace"]),
          str(rows["t1"]["trace"]))
    check("限值标明公称依据", rows["d1"]["nominal_param"] == "d1_nom"
          and rows["d1"]["nominal_value"] == 13.0)

    st, d = resolve(dict(BASE_PARAMS, grade="C"))
    rows = {r["id"]: r for r in d["rows"]}
    check("C 级 h1/e/Δh/t2 为不要求",
          all(rows[k]["status"] == "NOT_REQUIRED" for k in ("h1", "e", "dh", "t2")))
    check("C 级 d2 = 22.700~24.000（h16 18~30 档）", "22.700" in rows["d2"]["limit_text"],
          rows["d2"]["limit_text"])
    check("C 级 t1 = 1.680（2IT15）", "1.680" in rows["t1"]["limit_text"], rows["t1"]["limit_text"])

    print("2b. 条款可回溯到原件页码")
    meta2 = getjson("/api/meta?std=gb3103-3")
    check("meta 带 has_source", meta2.get("has_source") is True, str(meta2.get("has_source")))
    pages = {i["id"]: i.get("page") for i in meta2["items"]}
    check("检项带页码", pages.get("d1") == 4 and pages.get("t1") == 5, str(pages))
    check("解析结果也带页码",
          all(r.get("page") for r in
              post("/api/resolve", {"std": "gb3103-3", "params": BASE_PARAMS})[1]["rows"]))
    st, body, _ = get("/api/standards/gb3103-3/source.pdf")
    check("原件可下载", st == 200 and body[:4] == b"%PDF")

    print("3. 判定")
    st, d = judge({"d1_act": 13.12, "h1_act": 1.2, "d2_act": 23.9, "h_act": 2.05,
                   "e_act": 0.7, "dh_act": 0.06, "t1_act": 0.3, "t2_act": 0.12})
    check("八项全合格", d["counts"]["合格"] == 8 and d["overall"] == "合格", str(d["counts"]))

    st, d = judge({"d1_act": 13.28})
    v = {r["id"]: r["verdict"] for r in d["rows"]}
    check("d1_act=13.28 判不合格", v["d1"] == "不合格", v["d1"])
    check("其余未检测", d["counts"]["未检测"] == 7, str(d["counts"]))
    check("整体判定为不合格", d["overall"] == "不合格")

    st, d = judge({"d1_act": 13.0, "d2_act": 24.0, "h_act": 2.2, "t1_act": 0.42})
    v = {r["id"]: r["verdict"] for r in d["rows"]}
    check("边界值判合格", all(v[k] == "合格" for k in ("d1", "d2", "h", "t1")), str(v))

    print("4. 参数校验与降级")
    st, d = resolve(dict(BASE_PARAMS, d1_nom=None))
    rows = {r["id"]: r for r in d["rows"]}
    check("缺 d1_nom → d1 项无法判定", rows["d1"]["status"] == "MISS", rows["d1"]["status"])
    st, d = resolve(dict(BASE_PARAMS, d2_nom=300))
    check("d2_nom=300 超范围 → 422 且提示", st == 422
          and "超出" in json.dumps(d, ensure_ascii=False), str(d)[:120])
    st, d = resolve(dict(BASE_PARAMS, foo=1))
    check("未知参数 → 422", st == 422 and "未知参数" in json.dumps(d, ensure_ascii=False))
    st, d = resolve({k: v for k, v in BASE_PARAMS.items() if k != "h_nom"})
    check("缺必填 h_nom → 422", st == 422 and "缺少必填参数" in json.dumps(d, ensure_ascii=False))
    st, d = resolve(dict(BASE_PARAMS, grade="D"))
    check("等级非法 → 422", st == 422 and "不在" in json.dumps(d, ensure_ascii=False))

    print("5. 导出检验卡")
    qs = urllib.parse.urlencode({"std": STD, **BASE_PARAMS})
    st, body, headers = get("/api/card.xlsx?" + qs)
    check("xlsx 返回 200", st == 200)
    check("xlsx 是 zip 包（PK）", body[:2] == b"PK", body[:4].hex())
    check("文件名按 RFC 5987 编码", "filename*=UTF-8''" in headers.get("content-disposition", ""))
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(body))
        ws = wb.active
        check("可被 openpyxl 打开且为检验卡", ws.title == "检验卡")
        check("含 8 行检项", sum(1 for r in ws.iter_rows(min_col=1, max_col=1)
                                if isinstance(r[0].value, int)) == 8)
        spec_line = str(ws.cell(row=2, column=1).value)
        check("规格行由参数自动拼装", "公称厚度 h：2.0 mm" in spec_line, spec_line[:60])
    except ImportError:
        print("  SKIP  openpyxl 未安装，跳过内容校验")

    print("5c. 参数库（小类 → 参数 → 值）")
    post("/api/catalog/classes", {"id": "cls-test", "code": "T", "name": "测试小类",
                                  "parent": "测试中类"})
    post("/api/catalog/params", {"id": "p-test", "class_id": "cls-test", "code": "cls",
                                 "name": "性能等级", "type": "enum"})
    _, r = post("/api/catalog/params/p-test/values", {"values": [
        {"seq": 1, "sym": "8.8", "val": "8.8"},
        {"seq": 2, "sym": "10.9", "val": "10.9"}]})
    check("参数值写入", r.get("count") == 2, str(r))
    cat = getjson("/api/catalog")
    mine = next((c for c in cat if c["id"] == "cls-test"), None)
    check("小类可读回", mine is not None and len(mine["params"]) == 1, str(mine))
    check("参数带全部取值",
          [v["val"] for v in mine["params"][0]["values"]] == ["8.8", "10.9"])
    req = urllib.request.Request(f"{BASE}/api/catalog/classes/cls-test", method="DELETE")
    with urllib.request.urlopen(req, timeout=10) as rr:
        rr.read()
    check("删小类后消失", all(c["id"] != "cls-test" for c in getjson("/api/catalog")))

    print("6. 限值表编辑（录改即生效）")
    ed = getjson("/api/standards/gb3103-3/editor")
    check("取到编辑器数据", len(ed["tables"]) == 8, str(len(ed.get("tables", []))))
    check("参数与检项一起返回", len(ed["params"]) == 5 and len(ed["items"]) == 8)
    t = [x for x in ed["tables"] if x["id"] == "T-H1"][0]
    check("表带维度与取值", any(d["code"] == "grade" and d["values"] for d in t["dims"]),
          str(t["dims"]))

    before = {r["id"]: r["limit_text"] for r in
              post("/api/resolve", {"std": "gb3103-3", "params": BASE_PARAMS})[1]["rows"]}
    orig = [dict(r) for r in t["rows"]]
    for r in t["rows"]:
        if r["key"].get("grade") == "A" and r["key"]["h_nom"][1] == 4:
            r["lower_expr"] = "0.6*h_nom"
    save = put(f"/api/standards/gb3103-3/tables/T-H1", t)
    check("保存成功", save.get("ok") and save.get("rows") == 3, str(save))

    after = {r["id"]: r["limit_text"] for r in
             post("/api/resolve", {"std": "gb3103-3", "params": BASE_PARAMS})[1]["rows"]}
    check("改动立即生效（h1 下限 0.5h→0.6h）",
          after["h1"] == "≥ 1.200 mm" and before["h1"] == "≥ 1.000 mm",
          f'{before["h1"]} -> {after["h1"]}')

    t["rows"] = orig
    put("/api/standards/gb3103-3/tables/T-H1", t)
    back = {r["id"]: r["limit_text"] for r in
            post("/api/resolve", {"std": "gb3103-3", "params": BASE_PARAMS})[1]["rows"]}
    check("复原后回到 0.5h", back["h1"] == "≥ 1.000 mm", back["h1"])
    check("未牵连其他项", back["d1"] == before["d1"] and back["t1"] == before["t1"])

    print("7. 标准隔离（表 id 只在标准内唯一）")
    post("/api/standards/publish", {
        "id": "iso-test", "code": "TEST-ISO", "title": "隔离测试",
        "params": [{"code": "grade", "name": "等级", "type": "enum",
                    "options": ["A"], "default": "A"}],
        "items": [{"id": "x", "title": "别的检项", "clause": "1", "selected": True}],
        "limits": {"x": {"mode": "range", "lower": 0, "upper": 1}}})
    put("/api/standards/iso-test/tables/T-D1", {
        "id": "T-D1", "name": "它自己的 T-D1", "unit": "mm", "value_form": "absolute",
        "item_code": "x",                      # 挂到它自己的检项上
        "dims": [{"code": "grade", "kind": "enum", "values": ["A"]}],
        "rows": [{"key": {"grade": "A"}, "lower": 0, "upper": 9.9}]})

    ed2 = getjson("/api/standards/gb3103-3/editor")
    t2 = [x for x in ed2["tables"] if x["id"] == "T-D1"]
    check("另一个标准写同名表，不影响本标准", bool(t2) and len(t2[0]["rows"]) == 40,
          str(len(t2[0]["rows"]) if t2 else "表没了"))
    check("本标准的表名字没被改", t2 and "通孔" in (t2[0]["name"] or ""),
          t2[0]["name"] if t2 else "")
    after_iso = {r["id"]: r["limit_text"] for r in
                 post("/api/resolve", {"std": "gb3103-3", "params": BASE_PARAMS})[1]["rows"]}
    check("本标准判定不受影响", after_iso["d1"] == "13.000 ～ 13.270 mm", after_iso["d1"])
    iso = post("/api/resolve", {"std": "iso-test", "params": {"grade": "A"}})[1]
    check("另一个标准读自己的表", iso["rows"][0]["limit_text"] == "0.000 ～ 9.900 mm",
          iso["rows"][0]["limit_text"])

    req = urllib.request.Request(f"{BASE}/api/standards/unpublish/iso-test", method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()
    ed3 = getjson("/api/standards/gb3103-3/editor")
    check("删掉另一个标准，本标准 8 张表还在", len(ed3["tables"]) == 8, str(len(ed3["tables"])))

    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
