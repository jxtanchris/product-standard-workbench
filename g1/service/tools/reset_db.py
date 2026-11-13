# -*- coding: utf-8 -*-
"""清空上传/分析产生的数据（保留表结构，不删库文件，保留参数库）。

使用方式:
    .venv/bin/python g1/service/tools/reset_db.py              # 清空所有标准、限值表、矩阵、原件及作业缓存
    .venv/bin/python g1/service/tools/reset_db.py --restart    # 清空并自动重启 8022 服务
    .venv/bin/python g1/service/tools/reset_db.py --all        # 连参数库一起清空
    .venv/bin/python g1/service/tools/reset_db.py --dry-run    # 只查看将清掉多少，不动手
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
ROOT = SERVICE.parent.parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

import db  # noqa: E402

DATA = ROOT / "data"

# 业务/分析数据表（全部清空）
ANALYSIS_TABLES = (
    "standard_document",
    "document",
    "limit_row",
    "limit_dim",
    "limit_matrix",
    "limit_table",
    "standard_class",
    "standard",
)

# 基础资料参数库与拆分模式库表（默认保留）
CATALOG_TABLES = (
    "param_value",
    "class_param",
    "param_name",
    "product_class",
    "table_split_mode",
)


def counts(conn) -> dict:
    out = {}
    for t in ANALYSIS_TABLES + CATALOG_TABLES:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            out[t] = 0
    return out


def main() -> int:
    args = set(sys.argv[1:])
    dry = "--dry-run" in args
    with_catalog = "--all" in args or "--catalog" in args
    need_restart = "--restart" in args or "-r" in args

    conn = db.connect()
    conn.execute("PRAGMA foreign_keys = OFF;")
    before = counts(conn)

    print("=== 当前数据库统计 ===")
    for t, n in before.items():
        if n > 0:
            print(f"  {t:<20} {n}")

    targets = list(ANALYSIS_TABLES) + (list(CATALOG_TABLES) if with_catalog else [])
    jobs = sorted((DATA / "jobs").glob("*.json")) if (DATA / "jobs").exists() else []
    files = sorted((DATA / "uploads").glob("*")) if (DATA / "uploads").exists() else []

    if dry:
        print("\n[--dry-run 预览模式] 将清空以下数据：")
        print("  表:", ", ".join(t for t in targets if before.get(t, 0) > 0) or "（表已经是空的）")
        print(f"  作业缓存: {len(jobs)} 个")
        print(f"  上传原件: {len(files)} 个")
        return 0

    # 1. 清空数据表
    for t in targets:
        conn.execute(f"DELETE FROM {t}")
    conn.execute(
        "DELETE FROM sqlite_sequence WHERE name IN "
        "('limit_table','limit_dim','limit_matrix','limit_row','param_value')"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("VACUUM;")

    print("\n✓ 数据表已成功清空：", ", ".join(t for t in targets if before.get(t, 0) > 0) or "（原本即为空）")

    # 2. 清理磁盘文件 (jobs 与 uploads)
    for d in (DATA / "jobs", DATA / "uploads"):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    print(f"✓ 已清理作业缓存 {len(jobs)} 个、上传原件 {len(files)} 个")

    # 3. 清理根目录残留文件
    for rogue in (ROOT / "g1.db",):
        if rogue.exists():
            try:
                rogue.unlink()
                print(f"✓ 已清理临时文件: {rogue.name}")
            except Exception:
                pass

    # 4. 显示当前参数库留存状态
    if not with_catalog:
        cls_count = conn.execute("SELECT COUNT(*) FROM product_class").fetchone()[0]
        pn_count = conn.execute("SELECT COUNT(*) FROM param_name").fetchone()[0]
        pv_count = conn.execute("SELECT COUNT(*) FROM param_value").fetchone()[0]
        print(f"\n【参数库状态正常保留】: {cls_count} 个小类 | {pn_count} 个参数定义 | {pv_count} 条参数定值")
    else:
        print("\n【注意】参数库也已完全清空！")

    conn.close()

    # 5. 可选自动重启服务
    if need_restart:
        print("\n正在重启 8022 服务...")
        subprocess.run("lsof -ti :8022 | xargs kill -9 2>/dev/null || true", shell=True)
        run_sh = SERVICE / "run.sh"
        subprocess.Popen(["bash", str(run_sh)])
        print("✓ 8022 服务已重启！")
    else:
        print("\n提示：如需让网页端立即刷新内存注册表，可执行以下命令重启服务：")
        print("  lsof -ti :8022 | xargs kill -9 && bash g1/service/run.sh")

    return 0


if __name__ == "__main__":
    sys.exit(main())

