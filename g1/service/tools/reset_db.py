# -*- coding: utf-8 -*-
"""清空上传/分析产生的数据（保留表结构，不删库文件）。

    .venv/bin/python g1/service/tools/reset_db.py              # 只清标准及其层、限值表、原件
    .venv/bin/python g1/service/tools/reset_db.py --jobs       # 连作业与上传的 PDF 一起清
    .venv/bin/python g1/service/tools/reset_db.py --all        # 再连参数库一起清
    .venv/bin/python g1/service/tools/reset_db.py --dry-run    # 只看将清掉多少，不动手

"分析数据"指：标准、标准×小类层、限值表/维度/行、原件。
参数库（产品小类 / 参数名称 / 参数取值）是**基础资料**，默认不动，要清加 --all。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
sys.path.insert(0, str(SERVICE.parent))
sys.path.insert(0, str(SERVICE))

import db  # noqa: E402

DATA = SERVICE.parent.parent / "data"

ANALYSIS_TABLES = ("limit_row", "limit_dim", "limit_table", "standard_class",
                   "standard_document", "standard", "document")
CATALOG_TABLES = ("param_value", "class_param", "param_name", "product_class")


def counts(conn) -> dict:
    out = {}
    for t in ANALYSIS_TABLES + CATALOG_TABLES:
        out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return out


def main() -> int:
    args = set(sys.argv[1:])
    dry = "--dry-run" in args
    with_catalog = "--all" in args or "--catalog" in args
    with_jobs = "--jobs" in args or "--all" in args

    conn = db.connect()
    before = counts(conn)

    print("当前：")
    for t, n in before.items():
        if n:
            print(f"  {t:<18} {n}")

    targets = list(ANALYSIS_TABLES) + (list(CATALOG_TABLES) if with_catalog else [])
    jobs = sorted((DATA / "jobs").glob("*.json")) if (DATA / "jobs").exists() else []
    files = sorted((DATA / "uploads").glob("*")) if (DATA / "uploads").exists() else []

    if dry:
        print("\n将清空：", ", ".join(t for t in targets if before[t]) or "（已经是空的）")
        if with_jobs:
            print(f"  作业 {len(jobs)} 个，上传件 {len(files)} 个")
        print("（--dry-run，什么都没动）")
        return 0

    for t in targets:
        conn.execute(f"DELETE FROM {t}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN"
                 " ('limit_table','limit_dim','limit_row','param_value')")
    conn.commit()

    print("\n已清空：", ", ".join(t for t in targets if before[t]) or "（本来就是空的）")
    print("现在：", db.stats(conn))
    if not with_catalog:
        print("参数库保留：", conn.execute("SELECT COUNT(*) FROM product_class").fetchone()[0],
              "个小类 /", conn.execute("SELECT COUNT(*) FROM param_name").fetchone()[0], "个参数")
        print("（要连参数库一起清，加 --all）")

    if with_jobs:
        for d in (DATA / "jobs", DATA / "uploads"):
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
        print(f"已删除作业 {len(jobs)} 个、上传件 {len(files)} 个")

    print("\n提示：服务用的是内存注册表，清空后重启一次才不会再看到旧标准：")
    print("  kill $(lsof -nP -iTCP:8022 -sTCP:LISTEN -t) && ./g1/service/run.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
