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

    # 清理测试标准
    dbmod.delete(conn, test_std_id)
    ok(True, "清理临时测试标准完成")

    print(f"\n测试汇总: 通过 {PASS} 项, 失败 {FAIL} 项")
    return FAIL == 0

if __name__ == "__main__":
    if not run_tests():
        sys.exit(1)
