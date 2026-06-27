#!/bin/bash
#===============================================================================
# Docker Service Manager
# Usage: ./startDocker.sh {start|s|up|down|d|stop|restart|r|status|t}
#===============================================================================

set -u
set -o pipefail

cd ~/Projects/AntigravityProjects/AgentDeepDive/docker

ACTION="${1:-}"

# ── Help ────────────────────────────────────────────────────────────────────
if [[ -z "$ACTION" ]]; then
    echo "Usage: startDocker.sh { start|s|up | down|d|stop | restart|r | status|t }"
    echo ""
    echo "  start  | s      → 启动 Docker 服务"
    echo "  down   | d|stop → 停止 Docker 服务"
    echo "  restart| r      → 重启 Docker 服务"
    echo "  status | st     → 查看 Docker 服务"
    exit 1
fi

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$ACTION" in
    start|s|up)
        echo "==> Starting Docker service..."
        docker compose up -d
        echo -e "==> Service status:\033[38;5;46m"
        docker compose ps
        echo -e "\033[0m"
        exit 0
        ;;

    down|d|stop)
        echo "==> Stopping Docker service..."
        docker compose stop
        echo -e "\033[38;5;196mDocker service stopped.\033[0m"
        exit 0
        ;;

    restart|r)
        echo "==> Restarting Docker service..."
        docker compose stop
        docker compose up -d
        echo -e "==> Service status:\033[38;5;46m"
        docker compose ps
        echo -e "\033[0m"
        exit 0
        ;;

    status|t)
        echo "==> Checking Docker service..."
        # 核心修复：使用现代安全的变量接收方式，避免 egrep 过滤空文本导致脚本中途自杀
        CONTAINERS=$(docker ps -q 2>/dev/null | grep -E -v '779|66d' || true)
        
        if [ -z "$CONTAINERS" ]; then 
            echo -e "\033[38;5;196mNo active targets running in Docker cluster.\033[0m"
        else
            echo -e "\033[38;5;46mDocker containers are running:"
            docker compose ps
	    echo -e "\033[0m"
        fi
        exit 0
        ;;

    *)
        echo "Unknown action: $ACTION"
        exit 1
        ;;
esac
