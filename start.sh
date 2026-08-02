#!/usr/bin/env bash
set -e

# ============================================================
# Investment Agent 启动脚本
# 用法: ./start.sh [--reload] [--port PORT]
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
RELOAD_FLAG=""
PORT="${APP_PORT:-8000}"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --reload)
            RELOAD_FLAG="--reload"
            shift
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        --help|-h)
            echo "用法: ./start.sh [--reload] [--port PORT]"
            echo ""
            echo "选项:"
            echo "  --reload      启用 uvicorn 热重载（开发模式）"
            echo "  --port PORT   指定监听端口（默认 8000）"
            echo "  --help, -h    显示帮助信息"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: ./start.sh [--reload] [--port PORT]"
            exit 1
            ;;
    esac
done

# ----------------------------------------------------------
# Step 1: 创建/激活虚拟环境
# ----------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/3] 创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

echo "[1/3] 激活虚拟环境..."
source "$VENV_DIR/bin/activate"

# ----------------------------------------------------------
# Step 2: 安装依赖
# ----------------------------------------------------------
echo "[2/3] 安装依赖..."
#pip install -r requirements.txt

# ----------------------------------------------------------
# Step 3: 启动服务
# ----------------------------------------------------------
if [ -n "$RELOAD_FLAG" ]; then
    echo "[3/3] 启动服务（开发模式，热重载已启用） -> http://127.0.0.1:$PORT"
else
    echo "[3/3] 启动服务 -> http://127.0.0.1:$PORT"
fi

uvicorn investment_agent:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    $RELOAD_FLAG
