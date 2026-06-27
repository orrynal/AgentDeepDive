#!/bin/bash
#===============================================================================
# FastAPI Service Manager
# Usage: ./startFastAPI.sh {start|s|down|d|stop|restart|r|status|st}
#===============================================================================

# 移除 -e，改用更安全的逻辑控制，防止 tmux has-session 失败时直接崩溃
set -u
set -o pipefail

SCRIPT_PATH=$(realpath "$0")

cd ~/Projects/AntigravityProjects/AgentDeepDive/

ACTION="${1:-}"

# ── Help ────────────────────────────────────────────────────────────────────
if [[ -z "$ACTION" ]]; then
    echo "Usage: startFastAPI.sh { start|s|up | down|d|stop | restart|r | status|t }"
    echo ""
    echo "  start  | s|up   → 启动 FastAPI 服务"
    echo "  down   | d|stop → 停止 FastAPI 服务"
    echo "  restart| r      → 重启 FastAPI 服务"
    echo "  status | st     → 查看 FastAPI 服务"
    exit 1
fi

SESSION_NAME="fastapi"

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$ACTION" in
    start|s|up)
        # 严格遵守单实例原则：检查端口 8000 是否已占用
        if ss -tuln | grep -q ":8000 "; then
            PORT_PID=$(lsof -t -i :8000 2>/dev/null | tr '\n' ',' | sed 's/,$//')
            echo -e "\033[38;5;214m[WARNING] FastAPI service is already running on port 8000 (PID: $PORT_PID).\033[0m"
            echo "To restart the service, please run: $SCRIPT_PATH restart"
            exit 0
        fi

        echo "==> Preparing environment..."
        
        # 1. 强行清理旧的同名会话，确保环境干净
        tmux kill-session -t "$SESSION_NAME" 2>/dev/null

        # 2. 创建全新的后台静默会话
        tmux new-session -d -s "$SESSION_NAME"

        echo "==> Dispatching startup commands to tmux..."
        # 3. 核心修复：把 cd 和 source 动作直接送到 tmux 内部去执行！这样虚拟环境才会对 uvicorn 生效
        tmux send-keys -t "$SESSION_NAME" "cd ~/Projects/AntigravityProjects/AgentDeepDive/" ENTER
        tmux send-keys -t "$SESSION_NAME" "source .venv/bin/activate" ENTER
        
        # 4. 在 tmux 内部启动 uvicorn
        tmux send-keys -t "$SESSION_NAME" "uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload > server.log 2>&1" ENTER
        
        echo "==> Starting FastAPI service in background..."
        sleep 2
        
        # 5. 优雅查看状态：只打印最后 10 行日志，绝对不用 tail -f 阻塞进程
        echo "==> Recent service logs:"
        if [ -f server.log ]; then
            tail -n 10 server.log
        fi
        
        echo -e "\033[38;5;46m[OK] FastAPI 已移交后台 tmux ($SESSION_NAME) 运行，管理脚本安全退出。\033[0m"
        exit 0
        ;;

    down|d|stop)
        echo "==> Stopping FastAPI service..."
        # 强行关闭整个 tmux 会话，里面的 uvicorn 会被连带干净地杀掉
        tmux kill-session -t "$SESSION_NAME" 2>/dev/null
        
        # 兜底清理：如果 reload 产生了孤儿进程，用 lsof 彻底断后
        PID=$(lsof -t -i :8000 2>/dev/null || true)
        if [ -n "$PID" ]; then
            echo "Cleaning lingering processes on port 8000..."
            kill -9 $PID 2>/dev/null || true
        fi
        echo -e "\033[38;5;196mFastAPI service stopped.\033[0m"
        exit 0
        ;;

    restart|r)
        echo "==> Restarting FastAPI service..."
        # 直接调用本脚本的 stop 和 start 组合拳，避免重写逻辑
        "$SCRIPT_PATH" down
        sleep 1
        "$SCRIPT_PATH" start
        exit 0
        ;;

    status|st|t)
        echo "==> Checking FastAPI service..."

	# 放弃多变的 lsof，改用更底层的 ss 命令专门看 8000 端口有没有被 LISTEN（监听）
        # grep -q 代表静默匹配，只要有 8000 端口在监听，状态码就是 0
        if ss -tuln | grep -q ":8000 "; then
            # 既然端口在，我们可以尝试捞一下它的 PID
            # PORT_PID=$(lsof -t -i :8000 2>/dev/null || echo "Unknown")

	    # 1. 捞出多行 PID -> tr 将换行换成逗号 -> sed 剥离掉最后一个尾巴逗号
            PORT_PID=$(lsof -t -i :8000 2>/dev/null | tr '\n' ',' | sed 's/,$//')
	    PORT_PID="${PORT_PID:-Unknown}"
            echo -e "FastAPI service is running perfectly! \n(PID: \033[38;5;46m$PORT_PID\033[0m)"
        else
            echo -e "\033[38;5;196mNo FastAPI service running on port 8000.\033[0m"
        fi

        # 修复严格模式下 lsof 为空导致的 unbound/错误问题
        # PID=$(lsof -t -i :8000 2>/dev/null || true)
        # if [ -z "$PID" ]; then 
        #    echo "No FastAPI service running on port 8000."
        # else
        #    echo "FastAPI service is running! (PID: $PID)"
        #    lsof -i :8000
        # fi
        
        # 顺便检查下 tmux 是否安好
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            echo "Backend tmux session [$SESSION_NAME] is ALIVE."
        else
            echo "Warning: tmux session [$SESSION_NAME] is DEAD."
        fi
        exit 0
        ;;

    *)
        echo "Unknown action: $ACTION"
        exit 1
        ;;
esac
