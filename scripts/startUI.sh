#!/bin/bash
#===============================================================================
# Dashboard Service Manager
# Usage: ./startui.sh {start|s|down|d|stop|restart|r|status|t}
#===============================================================================

set -u
set -o pipefail

SCRIPT_PATH=$(realpath "$0")

cd ~/Projects/AntigravityProjects/AgentDeepDive/dashboard

ACTION="${1:-}"

# ── Help ────────────────────────────────────────────────────────────────────
if [[ -z "$ACTION" ]]; then
    echo "Usage: startui.sh { start|s|up | down|d|stop | restart|r | status|t }"
    echo ""
    echo "  start  | s|up   → 启动 Dashboard 服务"
    echo "  down   | d|stop → 停止 Dashboard 服务"
    echo "  restart| r      → 重启 Dashboard 服务"
    echo "  status | t      → 查看 Dashboard 服务"
    exit 1
fi

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$ACTION" in
    start|s|up)
        # 严格遵守单实例原则：检查端口 5173 是否已占用
        PORT_PID=$(lsof -t -i :5173 2>/dev/null | tr '\n' ',' | sed 's/,$//')
        if [ -n "$PORT_PID" ]; then
            echo -e "\033[38;5;214m[WARNING] Dashboard service is already running on port 5173 (PID: $PORT_PID).\033[0m"
            echo "To restart the service, please run: $SCRIPT_PATH restart"
            exit 0
        fi

        # 核心修复：后台异步运行并重定向日志，绝对不卡死主控制台
        npm run dev > dashboard.log 2>&1 &
        sleep 2
        
        echo "==> Recent dashboard logs:"
        if [ -f dashboard.log ]; then
            tail -n 5 dashboard.log
        fi
        echo -e "\033[38;5;46m[OK] Dashboard service started in background.\033[0m"
        exit 0
        ;;

    down|d|stop)
        echo "==> Stopping dashboard service..."
        # 放弃 pkill npm，改用更精准的端口 PID 释放
        PID=$(lsof -t -i :5173 2>/dev/null || true)
        if [ -n "$PID" ]; then
            kill -9 $PID 2>/dev/null || true
            echo -e "\033[38;5;196mDashboard service stopped.\033[0m"
        else
            echo -e "\033[38;5;196mNo dashboard service detected on port 5173.\033[0m"
        fi
        exit 0
        ;;

    restart|r)
        echo "==> Restarting dashboard service..."
        "$SCRIPT_PATH" down
        sleep 1
        "$SCRIPT_PATH" start
        exit 0
        ;;

    status|t)
        echo "==> Checking dashboard service..."
        #PID=$(lsof -t -i :5173 2>/dev/null || true)
        # 1. 捞出多行 PID -> tr 将换行换成逗号 -> sed 剥离掉最后一个尾巴逗号
        PORT_PID=$(lsof -t -i :5173 2>/dev/null | tr '\n' ',' | sed 's/,$//')
        # PORT_PID="${PORT_PID:-Unknown}"
        if [ -z "$PORT_PID" ]; then
            echo -e "\033[38;5;196mNo dashboard service running on port 5173.\033[0m"
        else
            echo -e "Dashboard service is running! (PID: \033[38;5;46m$PORT_PID\033[0m)"
            lsof -i :5173
        fi
        exit 0
        ;;

    *)
        echo "Unknown action: $ACTION"
        exit 1
        ;;
esac
