# -*- coding: utf-8 -*-
"""清空业务数据（保留表结构、不删库文件）。

注意：直接删 data/app.db 会让 run.sh 在下次启动时重新灌入样例标准；
如果只想清空内容、保持空库，用这个脚本。

    .venv/bin/python g1/service/tools/reset_db.py [--jobs]

--jobs 同时清掉上传的 PDF 与分析作业。
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


def main() -> int:
    conn = db.connect()
    for table in ("limit_row", "limit_dim", "limit_table", "standard"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN"
                 " ('limit_table','limit_dim','limit_row')")
    conn.commit()
    print("已清空业务数据:", db.stats(conn))

    if "--jobs" in sys.argv:
        for name in ("jobs", "uploads"):
            d = DATA / name
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
        print("已清空作业与上传件:", DATA / "jobs", DATA / "uploads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
