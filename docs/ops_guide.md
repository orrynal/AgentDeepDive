# AgentDeepDive 实施运维指南 (Operations & Maintenance)

> 本文档用于指导系统运维与实施人员对 AgentDeepDive 多 Agent 平台进行部署、服务启动、停止、监控及故障排查。

---

## 一、系统架构组件清单

系统正常运行需要依赖以下组件：
*   **API/Orchestrator 服务**：基于 FastAPI，负责提供接口与 DAG 调度逻辑。
*   **PostgreSQL**：元数据与执行轨迹（Trace）持久化存储。
*   **Redis**：提供分布式锁服务、排队机制与 Agent 消息总线。
*   **Ollama (本地/云端)**：提供 LLM 智能推理底座。
*   **Milvus standalone** (包含 MinIO & etcd)：供 Skill 语义匹配向量库使用。
*   **Jaeger**：分布式链路追踪，收集 OpenTelemetry 性能轨迹。

---

## 二、程序启动与停止操作指南

### 2.1 依赖的中间件组件（Docker 容器组）

中间件的配置文件位于项目根目录的 `docker/docker-compose.yml` 中。

*   **全量启动中间件**：
    ```bash
    cd /path/to/AgentDeepDive/docker
    docker compose up -d
    ```
    *验证容器状态*：
    ```bash
    docker compose ps
    ```

*   **停止中间件**：
    ```bash
    cd /path/to/AgentDeepDive/docker
    docker compose down
    ```

*   **清理缓存与挂载卷（清理所有任务/锁历史）**：
    ```bash
    cd /path/to/AgentDeepDive/docker
    docker compose down -v
    ```

---

### 2.2 API 与调度服务器（Orchestrator Server）

API 服务需要运行在配置好的 Python 虚拟环境中。

*   **启动服务（后台静默运行）**：
    ```bash
    cd /path/to/AgentDeepDive
    source .venv/bin/activate
    # 使用 nohup 重定向日志，将后台进程 PID 记录到 server.pid 文件中
    nohup uvicorn src.api.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 & echo $! > server.pid
    echo "API server started. PID: $(cat server.pid)"
    ```

*   **停止服务**：
    ```bash
    cd /path/to/AgentDeepDive
    if [ -f server.pid ]; then
        PID=$(cat server.pid)
        echo "Stopping API server (PID: $PID)..."
        kill $PID
        rm server.pid
    else
        # 若 PID 文件丢失，使用 pkill 终止
        pkill -f "uvicorn src.api.main:app"
    fi
    ```

*   **重启服务**：
    ```bash
    # 停止后重新启动
    pkill -f "uvicorn src.api.main:app"
    nohup uvicorn src.api.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 & echo $! > server.pid
    ```

---

## 三、系统状态查看与监控

### 3.1 查看后台日志
*   **监控实时 API 访问与 Agent 执行日志**：
    ```bash
    cd /path/to/AgentDeepDive
    tail -f server.log
    ```

### 3.2 联通性监控命令
运维人员可以通过 CLI 检查各服务的实时在线状态：
```bash
cd /path/to/AgentDeepDive
source .venv/bin/activate
python3 src/cli/main.py status
```
*正常输出示例*：
```
        AgentDeepDive System Status        
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Service       ┃ Status    ┃ Detail      ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ API Server    │ ✅ Online │ 0.1.0-alpha │
│   └─ postgres │ ✅        │ ok          │
│   └─ redis    │ ✅        │ ok          │
└───────────────┴───────────┴─────────────┘
```

### 3.3 数据库迁移与初始化
如果修改了元数据 Schema（例如新增表），需执行迁移：
```bash
cd /path/to/AgentDeepDive
source .venv/bin/activate
# 执行 Alembic 数据库更新
alembic upgrade head
```

---

## 四、故障排查与诊断指南

### 4.1 端口占用冲突
如果启动 uvicorn 提示 `[Errno 98] Address already in use`：
```bash
# 查询占用 8000 端口的 PID
lsof -i :8000
# 强制杀掉该进程
kill -9 <PID>
```

### 4.2 Redis 锁发生死锁
如果某个文件长时间被锁定（Agent 意外死掉导致锁未正常释放）：
1.  **命令行查询活跃锁**：
    连接 Redis CLI 并查看活跃锁 key：
    ```bash
    docker exec -it docker-redis-1 redis-cli KEYS "agentdeep:lock:*"
    ```
2.  **强制释放锁**：
    删除对应的 lock 键：
    ```bash
    docker exec -it docker-redis-1 redis-cli DEL "agentdeep:lock:/path/to/locked_file"
    ```

### 4.3 Jaeger 追踪监控
如果你需要分析 API 耗时、查询 Agent 执行的 OTel Trace：
*   在浏览器中访问 Jaeger UI：`http://localhost:16686`
*   选择 Service 为 `AgentDeepDive` 并点击 `Find Traces` 查看分布式调用调用链。
