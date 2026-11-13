# -*- coding: utf-8 -*-
"""把产品目录 / 产品目录_参数 / 产品目录_参数定值 三份 CSV 导入参数库。

用法：
    .venv/bin/python g1/service/tools/import_catalog_csv.py \\
        data/产品目录.csv data/产品目录_参数.csv data/产品目录_参数定值.csv --clear

    （兼容两参数旧用法：`<参数.csv> <参数定值.csv> [--class=...]`）

文件格式：
  · 产品目录 CSV（2列）：      目录id, 产品小类名称
  · 产品目录_参数 CSV（5列）： 参数id, 目录id, 中文名, 英文名/符号, 单位
  · 产品目录_参数定值 CSV（5列）：定值id, 参数id, 排序号, 中文值, 英文值
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
ROOT = SERVICE.parent.parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

import db  # noqa: E402

# 参数中文名 → 规范代码（英文名过长或缩写不一时统一映射为规范代码）
NAME_TO_CODE = {
    "螺纹规格": "thread",
    "性能等级": "class",
    "公称长度": "length",
    "表面处理": "surface",
    "材料牌号": "material",
    "是否栓接结构": "structural_bolting",
    "产品等级": "grade",
    "螺钉头部滚花类型": "head_knurl_type",
    "产品类型": "product_type",
    "产品条件": "fasteners_condition",
    "紧固件代号": "fastener_code",
    "外螺纹公差等级": "thread_tolerance_class",
    "外螺纹公差或代号": "thread_tolerance_class",
    "螺栓头外形型式": "appearance",
    "螺钉头外形型式": "appearance",
    "美标 Grade和Class": "astm_grade_class",
    "材料和热处理情况": "material_heat_treatment",
    "是否易切削钢": "free_cutting_steel",
    "法兰螺栓头下形状": "flange_head_under_shape",
    "不锈钢类别/组别-性能等级/加工状态": "ss_class",
    "有色金属性能等级": "non_ferrous_class",
    "材料类型": "material_type",
    "bm长度": "bm",
    "螺柱类型": "stud_type",
    "是否全螺纹": "full_thread_or_not",
    "旋入机体端螺纹规格": "bm_thread",
    "螺柱外形": "studa",
    "旋入机体端螺纹公差或代号": "bm_dh",
    "HR-HV类型": "hr_hv",
    "是否头部弱螺栓": "weak_head",
    "是否腰状杆": "waist_shaped_rod",
    "十字槽类型": "cross_slot",
    "系列": "series",
    "类型": "type",
    "螺纹长度": "thread_length",
    "规格尺寸范围": "size_range",
    "产品分析": "product_analysis",
    "长度范围": "length_range",
    "公称直径": "nominal_diameter",
}

CODE_OVERRIDES = {
    "QYCPMLCS00000000151": "head_knurl_type",
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

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
FREE_MARKS = {"/", "／", "—", "-", "－"}


def read_csv(path: Path) -> list[list[str]]:
    """导出文件可能用 CR 作行分隔，先归一化再交给 csv 模块。"""
    raw = path.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(raw.replace("\r\n", "\n").replace("\r", "\n"))))
    return [r for r in rows if any(c.strip() for c in r)]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")[:31].rstrip("_")


def clear_catalog(conn) -> None:
    """清空参数库全部数据（sub_param, param_value, class_param, param_name, product_class）。"""
    conn.execute("PRAGMA foreign_keys = OFF;")
    for tbl in ("sub_param", "param_value", "class_param", "param_name", "product_class"):
        conn.execute(f"DELETE FROM {tbl}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name='param_value'")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")


def parse_thread_coords(val_text: str) -> tuple[str, str, str, str]:
    """根据螺纹定值文本拆解出 (公英制类型, 公称直径, 螺距, 粗细牙类型)。
    示例：'M1×0.25粗牙' -> ('公制', '1', '0.25', '粗牙')
          'M10×1.25细牙' -> ('公制', '10', '1.25', '细牙')
          'M16粗牙'     -> ('公制', '16', '', '粗牙')
    """
    txt = val_text.strip()
    if not txt:
        return ("", "", "", "")

    gyz = "公制"
    d_val = ""
    p_val = ""
    ylx = "粗牙"

    if "细牙" in txt:
        ylx = "细牙"
    elif "粗牙" in txt:
        ylx = "粗牙"

    # 匹配 M 开头的公制螺纹
    m = re.search(r"[Mm](\d+(?:\.\d+)?)(?:[×xX*](\d+(?:\.\d+)?))?", txt)
    if m:
        d_val = m.group(1) or ""
        p_val = m.group(2) or ""
    elif re.search(r"^\d+(?:\.\d+)?$", txt):
        d_val = txt
    else:
        # 非典型公制或英美制
        if "/" in txt or "UNC" in txt or "UNF" in txt:
            gyz = "英美制"

    return (gyz, d_val, p_val, ylx)


def migrate_job_class_ids(class_map_by_name: dict[str, str]) -> int:
    """将已有作业缓存中的旧小类 ID（如 cls-bolt / cls-screw）同步更新为新导入的产品目录 ID。"""
    jobs_dir = ROOT / "data" / "jobs"
    if not jobs_dir.exists():
        return 0
    legacy_map = {}
    if "螺栓" in class_map_by_name:
        legacy_map["cls-bolt"] = class_map_by_name["螺栓"]
    if "螺柱" in class_map_by_name:
        legacy_map["cls-stud"] = class_map_by_name["螺柱"]
    if "螺钉" in class_map_by_name:
        legacy_map["cls-screw"] = class_map_by_name["螺钉"]
    if not legacy_map:
        return 0

    updated = 0
    for f in sorted(jobs_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            changed = False
            old_cid = data.get("class_id") or ""
            if old_cid in legacy_map:
                data["class_id"] = legacy_map[old_cid]
                changed = True
            if isinstance(data.get("classes"), list):
                new_classes = [legacy_map.get(c, c) for c in data["classes"]]
                if new_classes != data["classes"]:
                    data["classes"] = new_classes
                    changed = True
            for it in data.get("items") or []:
                if isinstance(it, dict) and it.get("class_id") in legacy_map:
                    it["class_id"] = legacy_map[it["class_id"]]
                    changed = True
            for p in data.get("params_spec") or []:
                if isinstance(p, dict) and p.get("class_id") in legacy_map:
                    p["class_id"] = legacy_map[p["class_id"]]
                    changed = True
            if changed:
                f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                updated += 1
        except Exception:
            continue
    return updated


def main(argv: list[str]) -> int:
    positional = [a for a in argv if not a.startswith("--")]
    do_clear = "--clear" in argv or "--reset" in argv
    default_class_id = next((a.split("=", 1)[1] for a in argv if a.startswith("--class=")), "QYCPDLML00000000000")

    classes_csv: Path | None = None
    sub_params_csv: Path | None = None

    if len(positional) >= 4:
        classes_csv = Path(positional[0])
        params_csv = Path(positional[1])
        sub_params_csv = Path(positional[2])
        values_csv = Path(positional[3])
    elif len(positional) == 3:
        classes_csv = Path(positional[0])
        params_csv = Path(positional[1])
        values_csv = Path(positional[2])
        # 自动尝试同目录下同名文件
        cand = params_csv.parent / "产品目录_二级参数.csv"
        if cand.is_file():
            sub_params_csv = cand
    elif len(positional) == 2:
        classes_csv = None
        params_csv = Path(positional[0])
        values_csv = Path(positional[1])
        cand = params_csv.parent / "产品目录_二级参数.csv"
        if cand.is_file():
            sub_params_csv = cand
    else:
        print("用法：python import_catalog_csv.py [产品目录.csv] <产品目录_参数.csv> [产品目录_二级参数.csv] <产品目录_参数定值.csv> [--clear]")
        return 2

    for p in ([classes_csv] if classes_csv else []) + [params_csv, values_csv] + ([sub_params_csv] if sub_params_csv else []):
        if p and not p.is_file():
            print(f"找不到文件：{p}", file=sys.stderr)
            return 1

    conn = db.connect()

    if do_clear:
        clear_catalog(conn)
        print("✓ 已清空参数库旧数据（product_class / param_name / sub_param / class_param / param_value）")

    # 1. 导入产品目录（产品小类）
    class_names: dict[str, str] = {}
    if classes_csv:
        class_rows = read_csv(classes_csv)
        for idx, row in enumerate(class_rows, start=1):
            if len(row) < 2:
                continue
            cid, cname = row[0].strip(), row[1].strip()
            if not cid or not cname:
                continue
            db.save_class(conn, cid, cid, cname, parent="紧固件产品", sort=idx)
            class_names[cid] = cname
        print(f"✓ 已导入产品目录小类 {len(class_names)} 个：" +
              "、".join(f"{v}({k})" for k, v in class_names.items()))
    else:
        for r in conn.execute("SELECT * FROM product_class"):
            class_names[r["id"]] = r["name"]

    # 2. 读取参数定值 CSV 并按 param_id 分组
    values_rows = [r for r in read_csv(values_csv) if len(r) >= 3]
    grouped_vals: dict[str, list[tuple[float | None, str]]] = {}
    for row in values_rows:
        if len(row) >= 5:
            _vid, ref, raw_seq, zh, _en = (row + [""] * 5)[:5]
        else:
            _vid, ref, zh, _en = (row + [""] * 4)[:4]
            raw_seq = ""
        ref, zh, raw_seq = ref.strip(), zh.strip(), raw_seq.strip()
        if not ref or zh == "":
            continue
        try:
            seq_val = float(raw_seq) if raw_seq else None
        except ValueError:
            seq_val = None
        grouped_vals.setdefault(ref, []).append((seq_val, zh))

    # 3. 导入产品目录_参数 CSV
    params_rows = [r for r in read_csv(params_csv) if len(r) >= 3]
    param_to_class: dict[str, str] = {}
    class_used_codes: dict[str, set[str]] = {}
    class_sort_counter: dict[str, int] = {}

    imported_params = 0
    skipped_params = []
    total_vals_written = 0
    dup_val_count = 0

    print(f"\n{'所属小类':<8}{'参数ID':<22}{'参数名称':<20}{'参数代码':<24}{'多维':<6}{'维度':<6}{'类型':<8}定值数")
    print("-" * 110)

    for row in params_rows:
        if len(row) >= 7:
            # 11列格式：记录编号, 引用_产品目录_记录编号, 参数名称, 参数代码, 参数单位, 维度定义, 是否多维, 坐标1..4
            raw_id = row[0].strip()
            raw_cid = row[1].strip() or default_class_id
            name = row[2].strip()
            en = row[3].strip()
            unit = row[4].strip()
            raw_dim_count = row[5].strip()
            is_multi_dim = row[6].strip().upper()
            coord1_sub_id = row[7].strip() if len(row) > 7 else ""
            coord2_sub_id = row[8].strip() if len(row) > 8 else ""
            coord3_sub_id = row[9].strip() if len(row) > 9 else ""
            coord4_sub_id = row[10].strip() if len(row) > 10 else ""
            try:
                dim_count = int(raw_dim_count) if raw_dim_count else 0
            except ValueError:
                dim_count = 0
        elif len(row) >= 5:
            # 旧版5列格式
            raw_id, raw_cid, name, en, unit = (row + [""] * 5)[:5]
            raw_id = raw_id.strip()
            raw_cid = raw_cid.strip() or default_class_id
            name, en, unit = name.strip(), en.strip(), unit.strip()
            is_multi_dim = "N"
            dim_count = 0
            coord1_sub_id = coord2_sub_id = coord3_sub_id = coord4_sub_id = ""
        else:
            raw_id, name, en, unit = (row + [""] * 4)[:4]
            raw_id, raw_cid = raw_id.strip(), default_class_id
            name, en, unit = name.strip(), en.strip(), unit.strip()
            is_multi_dim = "N"
            dim_count = 0
            coord1_sub_id = coord2_sub_id = coord3_sub_id = coord4_sub_id = ""

        if not raw_id or not name:
            continue

        param_to_class[raw_id] = raw_cid

        raw_items = grouped_vals.get(raw_id, [])
        # 若参数名称本身为占位符 '/' 且没有任何定值，则跳过该无效占位行
        if name in FREE_MARKS and not raw_items:
            skipped_params.append(f"{raw_id}({class_names.get(raw_cid, raw_cid)}:{name})")
            continue

        # 确保所属小类存在
        if raw_cid not in class_names:
            db.save_class(conn, raw_cid, raw_cid, raw_cid, parent="紧固件产品", sort=len(class_names) + 1)
            class_names[raw_cid] = raw_cid

        # 生成该小类内规范且唯一的参数代码
        code = CODE_OVERRIDES.get(raw_id) or NAME_TO_CODE.get(name) or slugify(en or name)
        if not SLUG_RE.match(code):
            code = "param_" + re.sub(r"\W", "", raw_id)[-6:].lower()

        used_in_cls = class_used_codes.setdefault(raw_cid, set())
        base_code, n = code, 1
        while code in used_in_cls:
            n += 1
            code = f"{base_code[:28]}_{n}"
        used_in_cls.add(code)

        # 整理该参数下的定值（去重并保持 seq 顺序，多维螺纹参数自动拆解四维坐标）
        seen_zh: set[str] = set()
        uniq_vals: list[dict] = []
        is_thread_param = (code == "thread" or "螺纹" in name)

        for seq_val, zh in raw_items:
            if zh in seen_zh:
                dup_val_count += 1
                continue
            seen_zh.add(zh)
            item_dict: dict = {"sym": zh, "val": zh}
            if seq_val is not None:
                item_dict["seq"] = int(seq_val) if seq_val.is_integer() else seq_val

            if is_multi_dim == "Y" and is_thread_param:
                c1, c2, c3, c4 = parse_thread_coords(zh)
                item_dict["coord1_val"] = c1
                item_dict["coord2_val"] = c2
                item_dict["coord3_val"] = c3
                item_dict["coord4_val"] = c4

            uniq_vals.append(item_dict)

        ptype = "number" if (
            uniq_vals and all(NUM_RE.match(v["val"]) or v["val"] in FREE_MARKS for v in uniq_vals)
        ) else "enum"

        # 保存参数定义、挂载到对应产品目录小类、写入参数定值
        db.save_param_name(
            conn, raw_id, code, name, ptype, unit,
            is_multi_dim=is_multi_dim, dim_count=dim_count,
            coord1_sub_id=coord1_sub_id, coord2_sub_id=coord2_sub_id,
            coord3_sub_id=coord3_sub_id, coord4_sub_id=coord4_sub_id
        )
        sort_idx = class_sort_counter.get(raw_cid, 0) + 1
        class_sort_counter[raw_cid] = sort_idx
        db.attach_param(conn, raw_cid, raw_id, sort=sort_idx, required=False)
        db.save_param_values(conn, raw_id, uniq_vals)

        imported_params += 1
        total_vals_written += len(uniq_vals)
        cname = class_names.get(raw_cid, raw_cid)
        print(f"{cname:<8}{raw_id:<22}{name:<20}{code:<24}{is_multi_dim:<6}{dim_count:<6}{ptype:<8}{len(uniq_vals)}")

    # 4. 导入产品目录_二级参数 CSV (sub_param)，必须在主参数插入后导入以满足外键约束
    imported_sub_params = 0
    if sub_params_csv:
        sub_rows = [r for r in read_csv(sub_params_csv) if len(r) >= 5]
        for row in sub_rows:
            sid, pid, raw_seq, code, name = (row + [""] * 6)[:5]
            help_text = row[5].strip() if len(row) > 5 else ""
            sid, pid = sid.strip(), pid.strip()
            code, name = code.strip(), name.strip()
            if not sid or not pid or not name:
                continue
            try:
                seq = int(float(raw_seq)) if raw_seq.strip() else 1
            except ValueError:
                seq = 1
            cid = param_to_class.get(pid, default_class_id)
            db.save_sub_param(conn, sid=sid, class_id=cid, param_id=pid,
                              seq=seq, code=code, name=name, help=help_text)
            imported_sub_params += 1
        print(f"\n✓ 已导入二级参数 {imported_sub_params} 条（从 {sub_params_csv.name}）")

    # 同步已有作业中的旧小类 ID
    by_name_map = {v: k for k, v in class_names.items()}
    migrated_jobs = migrate_job_class_ids(by_name_map)

    print("-" * 110)
    print(f"汇总：{len(class_names)} 个小类 ｜ {imported_params} 个主参数 ｜ {imported_sub_params} 个二级参数 ｜ {total_vals_written} 条定值（自动去重 {dup_val_count} 条重复值）")
    if skipped_params:
        print(f"已忽略无效空占位参数 {len(skipped_params)} 条：{', '.join(skipped_params)}")
    if migrated_jobs:
        print(f"已同步更新现有分析作业小类绑定 {migrated_jobs} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
