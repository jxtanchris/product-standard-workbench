#!/usr/bin/env bash
# 一键启动产品标准分析工作台。
#
#   ./start.sh            # 默认 http://127.0.0.1:8022
#   ./start.sh 8033       # 指定端口
#   PORT=8033 ./start.sh  # 同上，环境变量方式
#   ./start.sh --reinstall  # 强制重装 Python 依赖后启动
#
# 首次运行会：建 .venv → 装依赖 → 编译离线 OCR → 建库灌样例，然后启动服务。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV="$ROOT/.venv"
PY="$VENV/bin/python"
REQS="$ROOT/g1/service/requirements.txt"
SERVER="$ROOT/g1/service/run.sh"

REINSTALL=0
PORT_ARG=""
for arg in "$@"; do
  case "$arg" in
    --reinstall) REINSTALL=1 ;;
    -h|--help)
      sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      if [ -n "$PORT_ARG" ]; then
        echo "多余的参数：$arg" >&2
        exit 2
      fi
      PORT_ARG="$arg"
      ;;
  esac
done

# 1) Python 虚拟环境
if [ ! -x "$PY" ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "未找到 python3，请先安装 Python 3.11+" >&2
    exit 1
  fi
  echo "→ 创建虚拟环境 .venv（$(python3 -V 2>&1)）"
  python3 -m venv "$VENV"
  REINSTALL=1
fi

# 2) Python 依赖
if [ "$REINSTALL" -eq 1 ] || ! "$PY" -c "import fastapi, uvicorn, openpyxl, multipart" >/dev/null 2>&1; then
  echo "→ 安装 Python 依赖…"
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1 || true
  "$PY" -m pip install -r "$REQS"
fi

# 3) 交给服务脚本：OCR 编译 / 建库 / 启动
export PORT="${PORT_ARG:-${PORT:-8022}}"
exec "$SERVER"
