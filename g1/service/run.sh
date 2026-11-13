#!/usr/bin/env bash
# 启动工作台：./run.sh [端口]
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "未找到虚拟环境 $ROOT/.venv"
  echo "请先执行："
  echo "  cd \"$ROOT\" && python3 -m venv .venv"
  echo "  .venv/bin/pip install -r g1/service/requirements.txt"
  exit 1
fi

# 1) 离线 OCR 组件（源码在 ocr/ocr.swift，首次启动时编译）
if [ ! -x "$ROOT/g1/service/bin/ocrkit" ] && command -v swiftc >/dev/null 2>&1; then
  echo "→ 编译离线 OCR 组件…"
  mkdir -p "$ROOT/g1/service/bin" "$ROOT/.build-cache"
  # 沙箱里默认 TMPDIR 不可写，模块缓存要指到项目内
  if TMPDIR="$ROOT/.build-cache" swiftc -O -module-cache-path "$ROOT/.build-cache/mc" \
        -o "$ROOT/g1/service/bin/ocrkit" "$ROOT/g1/service/ocr/ocr.swift" 2>/dev/null; then
    echo "  完成"
  else
    echo "  编译失败：上传分析将不可用（其余功能正常）"
  fi
fi

# 2) 数据库（首次启动时建库并灌入样例标准与参数库）
if [ ! -f "$ROOT/data/app.db" ]; then
  echo "→ 初始化数据库…"
  "$PY" "$ROOT/g1/service/tools/load_gb3103.py"
  if [ -f "$ROOT/data/产品目录.csv" ]; then
    echo "→ 初始化参数库与二级参数…"
    "$PY" "$ROOT/g1/service/tools/import_catalog_csv.py" \
      "$ROOT/data/产品目录.csv" "$ROOT/data/产品目录_参数.csv" \
      "$ROOT/data/产品目录_二级参数.csv" "$ROOT/data/产品目录_参数定值.csv"
  fi
fi

export PORT="${1:-${PORT:-8022}}"
echo "→ http://127.0.0.1:$PORT"
exec "$PY" app.py
