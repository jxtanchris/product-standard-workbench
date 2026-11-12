# -*- coding: utf-8 -*-
"""把产品目录的参数 / 参数定值两份 CSV 导入参数库。

    .venv/bin/python g1/service/tools/import_catalog_csv.py <参数.csv> <参数定值.csv> [--class=cls-bolt]

参数 CSV：  参数id, 中文名, 英文名, 单位
定值 CSV：  定值id, 参数id, 中文值, 英文值

行为：
  · 中文名与库中已有参数相同的，合并到该参数并沿用其代码，取值整组替换为 CSV 内容。
  · 其余按英文名生成合法代码（小写字母开头、可含数字与下划线）新建参数。
  · 参数挂到 --class 指定的小类（默认 cls-bolt / 螺栓）；已挂载的 required 不变，
    新挂载的为 required=0（参数库是最大集，不意味着每个标准都必填）。
  · 同一参数下中文值重复的行只保留第一条并列出来。
  · 可重复执行：再跑一次得到同样结果，不产生重复行。
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

import db  # noqa: E402

# 英文名不好直接 slug 化（过长或语义不合）的参数：参数id → 代码
CODE_OVERRIDES = {
    "QYCPMLCS00000000186": "fastener_code",
    "QYCPMLCS00000000235": "thread_tolerance_class",
    "QYCPMLCS00000000262": "material_heat_treatment",
    "QYCPMLCS00000000271": "flange_head_under_shape",
    "QYCPMLCS00000000288": "ss_class",
    "QYCPMLCS00000000289": "non_ferrous_class",
    "QYCPMLCS00000000458": "astm_grade_class",
    "QYCPMLCS00000000460": "size_range",
    "QYCPMLCS00000000516": "length_range",
}

# 中文名 → 库中已有参数 id（合并目标），命中后沿用原代码
MERGE_BY_NAME = {
    "螺纹规格": "pn-thread",
    "性能等级": "pn-class",
    "表面处理": "pn-surface",
    "材料牌号": "pn-material",
    "公称长度": "pn-length",
}

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
# 数值型参数无法枚举，用占位符表示「有这个参数、值不固定」（与前端 FREE_MARKS 一致）
FREE_MARKS = {"/", "／", "—", "-", "－"}


def read_csv(path: Path) -> list[list[str]]:
    """这两个导出文件用 CR 作行分隔，先归一化再交给 csv 模块。"""
    raw = path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw.replace("\r\n", "\n").replace("\r", "\n"))))
    return [r for r in rows if any(c.strip() for c in r)]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")[:31].rstrip("_")


def main(argv: list[str]) -> int:
    positional = [a for a in argv if not a.startswith("--")]
    if len(positional) < 2:
        print(__doc__)
        return 2
    class_id = next((a.split("=", 1)[1] for a in argv if a.startswith("--class=")), "cls-bolt")

    params_csv, values_csv = Path(positional[0]), Path(positional[1])
    for p in (params_csv, values_csv):
        if not p.is_file():
            print(f"找不到文件：{p}", file=sys.stderr)
            return 1

    params = [r for r in read_csv(params_csv) if len(r) >= 3]
    values = [r for r in read_csv(values_csv) if len(r) >= 3]

    conn = db.connect()

    cls = conn.execute("SELECT * FROM product_class WHERE id=?", (class_id,)).fetchone()
    if not cls:
        print(f"小类不存在：{class_id}", file=sys.stderr)
        return 1

    # 现有参数：按 id、按中文名建索引
    existing = {r["id"]: r for r in conn.execute("SELECT * FROM param_name")}
    by_name = {}
    for r in existing.values():
        by_name.setdefault((r["name"] or "").strip(), r["id"])
    used_codes = {r["code"] for r in existing.values()}

    csv_id_to_pn: dict[str, str] = {}     # CSV 参数id → param_name.id
    csv_id_to_name: dict[str, str] = {}
    created, merged = [], []

    for row in params:
        raw_id, name, en, unit = (row + ["", "", "", ""])[:4]
        raw_id, name, en, unit = raw_id.strip(), name.strip(), en.strip(), unit.strip()
        if not raw_id or not name:
            continue

        target = MERGE_BY_NAME.get(name) or by_name.get(name)
        if target and target in existing:
            merged.append(name)
        else:
            code = CODE_OVERRIDES.get(raw_id) or slugify(en or name)
            if not SLUG_RE.match(code):
                code = "param_" + re.sub(r"\W", "", raw_id)[-6:].lower()
            base, n = code, 1
            while code in used_codes:
                n += 1
                code = f"{base[:28]}_{n}"
            used_codes.add(code)
            target = "pn-" + code
            created.append(f"{name}({code})")

        old_code = existing[target]["code"] if target in existing else target.removeprefix("pn-")
        old_unit = existing[target]["unit"] if target in existing else ""
        # 名字与单位以 CSV 为准；CSV 单位为空时保留原值
        db.save_param_name(conn, target, old_code, name, "enum", unit or old_unit)

        csv_id_to_pn[raw_id] = target
        csv_id_to_name[raw_id] = name

    # 取值按参数分组
    grouped: dict[str, list[str]] = {}
    skipped = []
    for row in values:
        _vid, ref, zh, _en = (row + ["", "", "", ""])[:4]
        ref, zh = ref.strip(), zh.strip()
        if ref not in csv_id_to_pn or zh == "":
            skipped.append(f"{ref}:{zh!r}")
            continue
        grouped.setdefault(csv_id_to_pn[ref], []).append(zh)

    dup_report = {}
    total = 0
    print(f"{'参数':<24}{'代码':<28}{'类型':<8}取值")
    for target, items in grouped.items():
        seen, uniq, dups = set(), [], []
        for zh in items:
            if zh in seen:
                dups.append(zh)
                continue
            seen.add(zh)
            uniq.append({"sym": zh, "val": zh})
        if dups:
            dup_report[target] = dups

        ptype = "number" if all(NUM_RE.match(v["val"]) or v["val"] in FREE_MARKS
                                for v in uniq) else "enum"
        conn.execute("UPDATE param_name SET type=? WHERE id=?", (ptype, target))
        db.save_param_values(conn, target, uniq)
        db.attach_param(conn, class_id, target, sort=0, required=False)
        name = conn.execute("SELECT name FROM param_name WHERE id=?", (target,)).fetchone()["name"]
        code = conn.execute("SELECT code FROM param_name WHERE id=?", (target,)).fetchone()["code"]
        print(f"{name:<24}{code:<28}{ptype:<8}{len(uniq)}")
        total += len(uniq)

    print()
    print(f"小类：{cls['name']}（{class_id}）")
    print(f"新建参数 {len(created)} 个：{'、'.join(created) if created else '—'}")
    print(f"合并到已有参数 {len(merged)} 个：{'、'.join(merged) if merged else '—'}")
    print(f"写入取值 {total} 条")
    if dup_report:
        print("同一参数下标中文值重复、已只保留首条：")
        for target, dups in dup_report.items():
            print(f"  {target}: {'、'.join(dups)}")
    if skipped:
        print(f"跳过 {len(skipped)} 条：{'、'.join(skipped[:10])}"
              + ("…" if len(skipped) > 10 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
