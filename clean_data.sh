#!/usr/bin/env bash
# ==============================================================================
# clean_data.sh: 一键清空系统除参数库外的所有业务数据
# 包含：标准库、限值表、母表矩阵、原件文档、分析作业、上传临时文件
# 完整保留：产品小类、参数名称、参数取值（参数库）
#
# 使用方式:
#   ./clean_data.sh            # 默认执行清理
#   ./clean_data.sh --restart  # 清理并自动重启 8022 服务
#   ./clean_data.sh --dry-run  # 仅预览将被清理的数据，不实际删除
#   ./clean_data.sh --all      # 警告：连同参数库一起彻底清空
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${ROOT_DIR}/.venv/bin/python"

if [ ! -x "$PY" ]; then
    PY="python3"
fi

RESTART=false
for arg in "$@"; do
    if [ "$arg" == "--restart" ] || [ "$arg" == "-r" ]; then
        RESTART=true
    fi
done

# 执行 Python 核心清理脚本（不让 Python 内部重启，由本 shell 统一控制）
ARGS=()
for arg in "$@"; do
    if [ "$arg" != "--restart" ] && [ "$arg" != "-r" ]; then
        ARGS+=("$arg")
    fi
done

if [ ${#ARGS[@]} -gt 0 ]; then
    "$PY" "${ROOT_DIR}/g1/service/tools/reset_db.py" "${ARGS[@]}"
else
    "$PY" "${ROOT_DIR}/g1/service/tools/reset_db.py"
fi

if [ "$RESTART" = true ]; then
    echo ""
    echo "=========================================="
    echo "正在重启 8022 服务..."
    echo "=========================================="
    lsof -ti :8022 | xargs kill -9 2>/dev/null || true
    sleep 1
    nohup bash "${ROOT_DIR}/g1/service/run.sh" >/dev/null 2>&1 &
    sleep 1
    echo "✓ 8022 服务已在后台成功启动 (http://127.0.0.1:8022)"
fi
