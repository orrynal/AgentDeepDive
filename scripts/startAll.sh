#!/bin/bash
#===============================================================================
# All Service Manager
# Usage: ./startAll.sh {start|s|down|d|stop|restart|r|status|st}
#===============================================================================

set -u
set -o pipefail

SCRIPT_PATH=$(realpath "$0")

cd ~/Projects/AntigravityProjects/AgentDeepDive/scripts

ACTION="${1:-}"

# ── Help ────────────────────────────────────────────────────────────────────
if [[ -z "$ACTION" ]]; then
    echo "Usage: startAll.sh { start|s|up | down|d|stop | restart|r | status|st }"
    echo ""
    echo "  start  | s|up   → 启动 All 服务"
    echo "  down   | d|stop → 停止 All 服务"
    echo "  restart| r      → 重启 All 服务"
    echo "  status | st     → 查看 All 服务"
    exit 1
fi

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$ACTION" in
    start|s|up)
        echo -e "========== [ STARTING ALL SERVICES ] ==========\n"
        echo "==> [Step 1/3] Launching Docker Environment..."
        ./startDocker.sh start 
        echo 

        echo "==> [Step 2/3] Deploying Backend FastAPI Core..."
        ./startFastAPI.sh start 
        echo 

        echo "==> [Step 3/3] Powering Up Dashboard UI..."
        ./startUI.sh start 
        echo -e "================================================\n"
        exit 0
        ;;

    down|d|stop)
        echo -e "========== [ STOPPING ALL SERVICES ] ==========\n"
        echo "==> [Step 1/3] Taking down Dashboard UI..."
        ./startUI.sh stop 
        echo 

        echo "==> [Step 2/3] Termination of FastAPI Backend..."
        ./startFastAPI.sh stop 
        echo 

        echo "==> [Step 3/3] Stopping Docker Environment..."
        ./startDocker.sh stop
        echo -e "================================================\n"
        exit 0
        ;;

    restart|r)
        echo -e "========== [ RESTARTING ALL SERVICES ] ==========\n"
        "$SCRIPT_PATH" down
        sleep 2
        "$SCRIPT_PATH" start
        exit 0
        ;;

    status|st|t)
        echo -e "========== [ CLUSTER STATUS MATRIX ] ==========\n"
        echo "==> Infrastructure layer:"
        ./startDocker.sh status
        echo 

        echo "==> Application Service layer:"
        ./startFastAPI.sh status
        echo 

        echo "==> Presentation UI layer:"
        ./startUI.sh status
        echo -e "================================================\n"
        exit 0
        ;;

    *)
        echo "Unknown action: $ACTION"
        exit 1
        ;;
esac