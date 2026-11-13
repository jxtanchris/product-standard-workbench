# -*- coding: utf-8 -*-
"""复合大表（力学性能矩阵）母表保存、自动切分与查表判定测试。

运行：
    python g1/service/test_matrix.py
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import db as dbmod
from app import resolve_rows
from standards import REGISTRY, Standard, register

PASS = FAIL = 0

def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")

def run_tests():
    global PASS, FAIL
    print("\n=== 开始测试复合大表母表 (limit_matrix) 编译切分与判定 ===")

    # 1. 准备测试数据库
    conn = dbmod.connect()
    test_std_id = "test-matrix-bolt"

    # 注册一个临时测试标准
    test_std = {
        "id": test_std_id,
        "code": "GB/T 3098.1—2010",
        "title": "紧固件机械性能 螺栓、螺钉和螺柱",
        "params": [
            {"code": "property_class", "name": "性能等级", "type": "enum", "values": ["4.8", "8.8", "10.9", "12.9"]},
            {"code": "d_nom", "name": "公称直径", "type": "num", "unit": "mm"}
        ],
        "items": [
            {"id": "it-exist", "title": "已有检查项", "category": "尺寸", "table": ""}
        ],
        "limits": {},
        "tables": []
    }
    dbmod.save_payload(conn, test_std)

    # 2. 构造 GB/T 3098.1 表3 复合力学矩阵（展示不同 No. 拥有不同、不定数量的专有维度）
    matrix_data = {
        "local_id": "M-PROP-BOLT",
        "title": "GB/T 3098.1 表3 螺栓机械性能总表",
        "dims": [
            {"code": "property_class", "name": "性能等级", "kind": "enum", "values": ["8.8", "10.9"]},
            {"code": "d_nom", "name": "公称直径", "kind": "range", "values": [[0, 16], [16, 39]]}
        ],
        "indicators": [
            {
                "col_key": "rm",
                "name": "抗拉强度 Rm",
                "unit": "MPa",
                "item_id": "it-rm",
                "local_table_id": "T-PROP-RM",
                # No.1 动态增加了专有的第 3 维度：公称抗拉强度
                "extra_dims": [{"code": "rm_nom", "name": "公称抗拉强度", "kind": "enum", "values": ["800", "1000"]}]
            },
            {
                "col_key": "hv",
                "name": "维氏硬度 HV",
                "unit": "HV",
                "item_id": "it-hv",
                "local_table_id": "T-PROP-HV"
                # 未增加额外维度，直接继承表头 2 个基础维度
            },
            {
                "col_key": "a",
                "name": "断后伸长率 A",
                "unit": "%",
                "item_id": "it-a",
                "local_table_id": "T-PROP-A"
                # 未增加额外维度，直接继承表头 2 个基础维度
            }
        ],
        "rows": [
            {
                "dim_values": {"property_class": "8.8", "d_nom": [0, 16]},
                "indicator_values": {
                    "rm": {"nominal": 800.0, "lower": 800.0, "upper": 1000.0, "rm_nom": "800", "note": "800~1000"},
                    "hv": {"lower": 250.0, "upper": 320.0, "note": "250~320"},
                    "a":  {"lower": 12.0, "upper": None, "note": "≥12"}
                }
            },
            {
                "dim_values": {"property_class": "8.8", "d_nom": [16, 39]},
                "indicator_values": {
                    "rm": {"nominal": 800.0, "lower": 830.0, "upper": 1030.0, "rm_nom": "800", "note": "830~1030"},
                    "hv": {"lower": 255.0, "upper": 335.0, "note": "255~335"},
                    "a":  {"lower": 12.0, "upper": None, "note": "≥12"}
                }
            },
            {
                "dim_values": {"property_class": "10.9", "d_nom": [0, 39]},
                "indicator_values": {
                    "rm": {"nominal": 1000.0, "lower": 1040.0, "upper": 1250.0, "rm_nom": "1000", "note": "1040~1250"},
                    "hv": {"lower": 320.0, "upper": 380.0, "note": "320~380"},
                    "a":  {"lower": 9.0, "upper": None, "note": "≥9"}
                }
            }
        ]
    }

    # 执行保存与编译切分
    res = dbmod.save_and_compile_matrix(conn, test_std_id, matrix_data)
    ok(res.get("ok") is True, "save_and_compile_matrix 执行成功")
    ok(len(res.get("sub_tables", [])) == 3, f"成功切分生成 3 张单指标子表 (实际: {len(res.get('sub_tables', []))})")

    # 3. 验证母表存储
    m_list = dbmod.list_matrices(conn, test_std_id)
    ok(len(m_list) == 1 and m_list[0]["local_id"] == "M-PROP-BOLT", "list_matrices 返回正确母表记录")

    m_detail = dbmod.get_matrix(conn, test_std_id, "M-PROP-BOLT")
    ok(m_detail is not None and m_detail["title"] == "GB/T 3098.1 表3 螺栓机械性能总表", "get_matrix 读取母表矩阵完整")
    ok(len(m_detail.get("rows", [])) == 3, "母表保存了 3 行原始矩阵数据")

    # 4. 验证子表与维度
    tables = dbmod.table_detail(conn, test_std_id)
    t_map = {t["id"]: t for t in tables}
    ok("T-PROP-RM" in t_map, "抗拉强度子表 T-PROP-RM 存在")
    ok("T-PROP-HV" in t_map, "维氏硬度子表 T-PROP-HV 存在")
    ok("T-PROP-A" in t_map, "断后伸长率子表 T-PROP-A 存在")

    rm_t = t_map["T-PROP-RM"]
    ok(rm_t.get("matrix_local_id") == "M-PROP-BOLT", "子表带有正确的母表 matrix_local_id 血缘标记")
    ok(rm_t.get("unit") == "MPa", "子表单位设置正确 (MPa)")
    ok(len(rm_t.get("rows", [])) == 3, "子表包含 3 行限值")
    ok(len(rm_t.get("dims", [])) == 3 and rm_t["dims"][2]["code"] == "rm_nom", f"No.1 抗拉强度子表独立增加了第3个维度 rm_nom (维度数: {len(rm_t.get('dims', []))})")
    ok(len(t_map["T-PROP-HV"].get("dims", [])) == 2, f"No.2 维氏硬度子表保持2个基础维度 (维度数: {len(t_map['T-PROP-HV'].get('dims', []))})")
    ok(rm_t["rows"][0]["key"].get("rm_nom") == "800", f"子表每行 key 成功合并第三维度取值: {rm_t['rows'][0]['key']}")

    # 5. 验证检项自动联动绑定
    s_row = conn.execute("SELECT item_json FROM standard WHERE id=?", (test_std_id,)).fetchone()
    items = json.loads(s_row[0] or "[]")
    item_map = {it["id"]: it for it in items}
    ok("it-rm" in item_map and item_map["it-rm"]["table"] == "T-PROP-RM", "检项 it-rm 自动生成并绑定到 T-PROP-RM")
    ok("it-hv" in item_map and item_map["it-hv"]["table"] == "T-PROP-HV", "检项 it-hv 自动生成并绑定到 T-PROP-HV")
    ok("it-a" in item_map and item_map["it-a"]["table"] == "T-PROP-A", "检项 it-a 自动生成并绑定到 T-PROP-A")

    # 6. 端到端求解判定验证 (resolve_rows)
    from standards import from_loaded
    std_obj = None
    for entry in dbmod.load_all(conn):
        if entry["id"] == test_std_id:
            std_obj = from_loaded(entry)
            break
    ok(std_obj is not None, "标准对象从数据库成功加载并实例化")

    # 场景 1：8.8 级，公称直径 12 (<=16)，公称抗拉强度 800 (三维精确定位)
    rows_88_12 = resolve_rows(std_obj, {"property_class": "8.8", "d_nom": 12, "rm_nom": "800"})
    card_items = {r["id"]: r for r in rows_88_12}
    c_rm = card_items.get("it-rm")
    c_hv = card_items.get("it-hv")
    c_a  = card_items.get("it-a")

    ok(c_rm is not None and c_rm["lower"] == 800.0 and c_rm["upper"] == 1000.0, f"8.8级 d=12 rm_nom=800 抗拉强度三维查表: {c_rm.get('lower')}~{c_rm.get('upper')} (期望 800~1000)")
    ok(c_rm.get("nominal_value") == 800.0, f"8.8级 d=12 成功输出标准公称基准值: {c_rm.get('nominal_value')} (期望 800)")
    ok(c_hv is not None and c_hv["lower"] == 250.0 and c_hv["upper"] == 320.0, f"8.8级 d=12 维氏硬度查表: {c_hv.get('lower')}~{c_hv.get('upper')} (期望 250~320)")
    ok(c_a is not None and c_a["lower"] == 12.0 and c_a["upper"] is None, f"8.8级 d=12 断后伸长率查表: >={c_a.get('lower')} (期望 >=12)")

    # 场景 2：8.8 级，公称直径 20 (>16)，公称抗拉强度 800 (三维精确定位大规格加严)
    rows_88_20 = resolve_rows(std_obj, {"property_class": "8.8", "d_nom": 20, "rm_nom": "800"})
    c2_items = {r["id"]: r for r in rows_88_20}
    c2_rm = c2_items.get("it-rm")
    c2_hv = c2_items.get("it-hv")
    ok(c2_rm is not None and c2_rm["lower"] == 830.0 and c2_rm["upper"] == 1030.0, f"8.8级 d=20 rm_nom=800 抗拉强度三维查表大规格加严: {c2_rm.get('lower')}~{c2_rm.get('upper')} (期望 830~1030)")
    ok(c2_hv is not None and c2_hv["lower"] == 255.0 and c2_hv["upper"] == 335.0, f"8.8级 d=20 维氏硬度查表: {c2_hv.get('lower')}~{c2_hv.get('upper')} (期望 255~335)")

    # 场景 3：10.9 级，公称直径 10，公称抗拉强度 1000
    rows_109_10 = resolve_rows(std_obj, {"property_class": "10.9", "d_nom": 10, "rm_nom": "1000"})
    c3_items = {r["id"]: r for r in rows_109_10}
    c3_rm = c3_items.get("it-rm")
    c3_hv = c3_items.get("it-hv")
    c3_a  = c3_items.get("it-a")
    ok(c3_rm is not None and c3_rm["lower"] == 1040.0 and c3_rm["upper"] == 1250.0, f"10.9级 抗拉强度查表: {c3_rm.get('lower')}~{c3_rm.get('upper')} (期望 1040~1250)")
    ok(c3_hv is not None and c3_hv["lower"] == 320.0 and c3_hv["upper"] == 380.0, f"10.9级 维氏硬度查表: {c3_hv.get('lower')}~{c3_hv.get('upper')} (期望 320~380)")
    ok(c3_a is not None and c3_a["lower"] == 9.0, f"10.9级 断后伸长率查表: >={c3_a.get('lower')} (期望 >=9)")

    # 7. 测试删除母表及联动子表
    dbmod.delete_matrix(conn, test_std_id, "M-PROP-BOLT")
    m_after = dbmod.list_matrices(conn, test_std_id)
    tables_after = dbmod.table_detail(conn, test_std_id)
    ok(len(m_after) == 0, "delete_matrix 成功清理母表")
    ok(len(tables_after) == 0, "delete_matrix 成功级联删除所有拆分出的子表")

    # 8. 测试全新的两级主从结构母表（按 No 序号划分清单，自动继承公共参数 + 确认加入专属参数 + 展开生成明细）
    wizard_payload = {
        "local_id": "M-PROP-WIZARD",
        "title": "向导式机械性能总表",
        "common_dims": [
            {"code": "property_class", "name": "性能等级", "kind": "enum"},
            {"code": "d_nom", "name": "公称直径 d", "kind": "range"}
        ],
        "tables": [
            {
                "no": "1",
                "name": "抗拉强度 Rm",
                "unit": "MPa",
                "local_table_id": "T-WIZARD-RM",
                "item_id": "it-wizard-rm",
                "extra_dims": [
                    {"code": "rm_nom", "name": "公称抗拉强度", "kind": "enum"}
                ],
                "rows": [
                    {"key": {"property_class": "8.8", "d_nom": [0, 16], "rm_nom": "800"}, "nominal": 800.0, "lower": 800.0, "upper": 1000.0},
                    {"key": {"property_class": "8.8", "d_nom": [16, 39], "rm_nom": "800"}, "nominal": 800.0, "lower": 830.0, "upper": 1030.0, "note": "加严"}
                ]
            },
            {
                "no": "2",
                "name": "下屈服强度 ReL",
                "unit: ": "MPa",
                "local_table_id": "T-WIZARD-REL",
                "item_id": "it-wizard-rel",
                "extra_dims": [],
                "rows": [
                    {"key": {"property_class": "4.6", "d_nom": [0, 39]}, "nominal": 240.0, "lower": 240.0, "upper": None}
                ]
            }
        ]
    }

    w_res = dbmod.save_and_compile_matrix(conn, test_std_id, wizard_payload)
    ok(w_res.get("ok") is True, "向导式主从结构 save_and_compile_matrix 编译成功")
    ok(len(w_res.get("sub_tables", [])) == 2, f"成功根据 No 序号切分生成 2 张限值主表 (实际: {len(w_res.get('sub_tables', []))})")

    # 验证 No. 1 的维度为 3，No. 2 的维度为 2
    w_tables = dbmod.table_detail(conn, test_std_id)
    w_map = {t["id"]: t for t in w_tables}
    w_t_rm = w_map["T-WIZARD-RM"]
    w_t_rel = w_map["T-WIZARD-REL"]
    ok(len(w_t_rm.get("dims", [])) == 3, f"No.1 抗拉强度继承后并加入专属参数，维度数为 3 (实际: {len(w_t_rm.get('dims', []))})")
    ok([d["code"] for d in w_t_rm.get("dims", [])] == ["property_class", "d_nom", "rm_nom"], "No.1 维度列表完全正确: property_class, d_nom, rm_nom")
    ok(len(w_t_rel.get("dims", [])) == 2, f"No.2 下屈服强度仅继承公共参数，维度数为 2 (实际: {len(w_t_rel.get('dims', []))})")

    # 查表判定验证
    from standards import from_loaded
    w_std = None
    for entry in dbmod.load_all(conn):
        if entry["id"] == test_std_id:
            w_std = from_loaded(entry)
            break
    rows_w = resolve_rows(w_std, {"property_class": "8.8", "d_nom": 20, "rm_nom": "800"})
    w_rm_res = next((r for r in rows_w if r["id"] == "it-wizard-rm"), None)
    ok(w_rm_res is not None and w_rm_res["lower"] == 830.0 and w_rm_res["upper"] == 1030.0, f"No.1 三维查表成功匹配大规格加严: {w_rm_res.get('lower')}~{w_rm_res.get('upper')} (期望 830~1030)")

    # 清理向导母表
    dbmod.delete_matrix(conn, test_std_id, "M-PROP-WIZARD")

    # 9. 测试拆分模式库 (table_split_mode) 与多步骤原表拆解引擎 (matrix_protocol)
    import matrix_protocol as mp
    modes = dbmod.list_split_modes(conn)
    ok(len(modes) == 5, f"拆分模式库预置了 5 种标准拆分模式 (实际: {len(modes)})")
    mode_codes = [m["code"] for m in modes]
    ok(
        mode_codes == ["single_indicator", "multi_col_parallel", "matrix_2d_cross", "composite_no_master", "ignore_skip"],
        f"5 种拆分模式顺序与编码正确: {mode_codes}"
    )

    # 模拟一份含表1(化学成分)、表3(多列机械性能)、表4(单指标渗碳层深度) 的标准作业
    sample_job = {
        "id": "job-test-wb",
        "code": "GB/T 3098.7—2000",
        "title": "紧固件机械性能 自挤螺钉",
        "text": (
            "表1 化学成分\n成分极限，%\n分析 碳 锰\n桶样 0.15~0.25 0.70~1.65\n检验 0.13~0.27 0.64~1.71\n"
            "表2 机械和工作性能项目\n性能项目 技术要求（条或表） 试验方法（条）\n"
            "表3 机械和工作性能要求\n破坏扭矩 拧入扭矩 破坏拉力载荷（参考）\n螺纹公称直径 min max min\nN•m N•m N\n2 0.5 0.3 1940\n3 2.1 1.1 4680\n"
            "表4 表面渗碳层深度mm\n螺纹公称直径 min max\n2.2.5 0.04 0.12\n4.5 0.10 0.25\n"
        ),
        "tables": [
            {
                "page": 4, "rows": 4, "cols": 4,
                "grid": [
                    ["分析", "", "成分极限，%", ""],
                    ["", "碳", "", "锰"],
                    ["桶样", "0.15~0.25", "", "0.70~1.65"],
                    ["检验", "0.13~0.27", "", "0.64~1.71"]
                ]
            },
            {
                "page": 5, "rows": 3, "cols": 4,
                "grid": [
                    ["", "N•m", "N•m", "N"],
                    ["2", "0.5", "0.3", "1940"],
                    ["3", "2.1", "1.1", "4680"]
                ]
            },
            {
                "page": 5, "rows": 3, "cols": 3,
                "grid": [
                    ["", "min", "max"],
                    ["2.2.5", "0.04", "0.12"],
                    ["4.5", "0.10", "0.25"]
                ]
            }
        ]
    }
    discovered = mp.discover_source_tables(sample_job, {"code": "GB/T 3098.7", "items": []})
    ok(len(discovered) == 4, f"discover_source_tables 成功识别出 4 张逻辑原表 (实际: {len(discovered)})")
    d_by_label = {t["label"]: t for t in discovered}
    ok(d_by_label["表2"]["recommended_mode"] == "ignore_skip", "表2 自动推荐为 ignore_skip（模式 5：非判定表）")
    ok(d_by_label["表3"]["recommended_mode"] == "multi_col_parallel", "表3 自动推荐为 multi_col_parallel（模式 2：多指标按列拆分）")
    ok(d_by_label["表4"]["recommended_mode"] == "single_indicator", "表4 自动推荐为 single_indicator（模式 1：单指标简单表）")

    dec_t1 = mp.deconstruct_source_table(d_by_label["表1"], "multi_col_parallel", {"code": "GB/T 3098.7", "items": []})
    t1_names = [t["name"] for t in dec_t1.get("tables", [])]
    ok(
        t1_names == ["碳含量 CMin", "碳含量 CMax", "锰含量 MnMin", "锰含量 MnMax"],
        f"表1 按模式 2 及 Min/Max 拆出 4 笔限值主表: {t1_names}"
    )

    dec_t3 = mp.deconstruct_source_table(d_by_label["表3"], "multi_col_parallel", {"code": "GB/T 3098.7", "items": []})
    t3_names = [t["name"] for t in dec_t3.get("tables", [])]
    ok(
        t3_names == ["破坏扭矩Min", "拧入扭矩Max", "破坏拉力载荷Min"],
        f"表3 按模式 2 拆出 3 笔限值主表（指标名+Min/Max）: {t3_names}"
    )

    dec_t4 = mp.deconstruct_source_table(d_by_label["表4"], "single_indicator", {"code": "GB/T 3098.7", "items": []})
    t4_names = [t["name"] for t in dec_t4.get("tables", [])]
    ok(
        t4_names == ["表面渗碳层深度Min", "表面渗碳层深度Max"]
        and len(dec_t4["tables"][0]["rows"]) == 4
        and len(dec_t4["tables"][1]["rows"]) == 4,
        f"表4 按模式 1 拆出 2 笔限值主表（表面渗碳层深度Min/Max）且成功展开合并直径组: {t4_names}"
    )

    # 10. 测试含 Avg（平均值）与 Nom（公称值）等多统计特征列的拆解能力（模式 1 与模式 2）
    avg_mode1_info = {
        "t_no": "6",
        "table_id": "SRC-TABLE-6",
        "matrix_local_id": "M-TABLE6",
        "title": "镀层厚度",
        "full_title": "表6 镀层厚度",
        "unit_hint": "μm",
        "preview_grid": [
            ["螺纹公称直径", "min", "max", "avg"],
            ["4", "5", "12", "8"],
            ["6", "6", "15", "10"],
        ],
        "context_lines": ["螺纹公称直径 min max avg"],
    }
    dec_avg_m1 = mp.deconstruct_source_table(avg_mode1_info, "single_indicator", {"code": "GB/T 5267.1", "items": []})
    avg_m1_names = [t["name"] for t in dec_avg_m1.get("tables", [])]
    ok(
        avg_m1_names == ["镀层厚度Min", "镀层厚度Max", "镀层厚度Avg"]
        and dec_avg_m1["tables"][2]["rows"][0]["lower"] == 8.0,
        f"模式 1 含 min/max/avg 三列时自动拆出 3 笔限值表: {avg_m1_names}"
    )

    avg_mode2_info = {
        "t_no": "7",
        "table_id": "SRC-TABLE-7",
        "matrix_local_id": "M-TABLE7",
        "title": "涂层与冲击性能",
        "full_title": "表7 涂层与冲击性能",
        "unit_hint": "",
        "preview_grid": [
            ["规格", "镀层厚度", "", "冲击功"],
            ["", "min", "max", "平均值"],
            ["M8", "5", "12", "27"],
            ["M10", "6", "15", "34"],
        ],
        "context_lines": [],
    }
    dec_avg_m2 = mp.deconstruct_source_table(avg_mode2_info, "multi_col_parallel", {"code": "GB/T 5267.1", "items": []})
    avg_m2_names = [t["name"] for t in dec_avg_m2.get("tables", [])]
    ok(
        avg_m2_names == ["镀层厚度Min", "镀层厚度Max", "冲击功Avg"]
        and dec_avg_m2["tables"][2]["rows"][0]["lower"] == 27.0,
        f"模式 2 双层表头含 min/max/平均值 时自动拆出 3 笔限值表: {avg_m2_names}"
    )

    # 11. 测试 4 步识别规则库与单标准自定义规则覆盖 (step1~step4)
    import analyze as _analyze
    rcat = _analyze.rules_catalog()
    ok(len(rcat.get("steps_meta", [])) == 4, "识别规则库包含完整的 4 个分析步骤元数据")
    sample_pages = [{"page": 1, "lines": ["5.1 特殊敲击度", "本条要求特殊敲击度不大于 0.5mm，对边宽度 s 应符合规定。"]}]
    cands_default = _analyze.parse(sample_pages)
    ok(not cands_default[0].selected, "默认规则下未知词汇「敲击度」未被选为检项")
    custom_rules = {"metric_words": _analyze.get_rules()["metric_words"] + ["敲击度"]}
    cands_custom = _analyze.parse(sample_pages, rules_override=custom_rules)
    ok(cands_custom[0].selected, "单标准在 Step 1 增加「敲击度」识别词后即刻命中检项")

    custom_param_rules = {
        "param_rules": _analyze.get_rules()["param_rules"] + [
            {"pattern": "对边宽度", "code": "s_nom", "name": "对边宽度 s", "type": "number", "unit": "mm", "options": [], "required": True}
        ]
    }
    sug_params = _analyze.suggest_params(sample_pages, rules_override=custom_param_rules)
    ok(any(p["code"] == "s_nom" for p in sug_params), "单标准在 Step 2 增加「对边宽度 -> s_nom」规则后成功提取参数")

    syn_links = _analyze.auto_link_items_and_tables(
        [{"id": "it-1", "title": "抗拉强度", "selected": True}],
        [{"id": "T1-RM-MIN", "name": "RmMin"}],
        existing_links={},
    )
    ok(syn_links.get("it-1") == "T1-RM-MIN", f"Step 4 同义词规则成功将「抗拉强度」自动关联到「RmMin」限值表: {syn_links}")

    # 清理测试标准
    dbmod.delete(conn, test_std_id)
    ok(True, "清理临时测试标准完成")

    print(f"\n测试汇总: 通过 {PASS} 项, 失败 {FAIL} 项")
    return FAIL == 0

if __name__ == "__main__":
    if not run_tests():
        sys.exit(1)
