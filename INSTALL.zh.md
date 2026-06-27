# 安装与部署指南

中文 | [English](INSTALL.md)

本指南详细介绍了 AgentDeepDive 的**标准容器模式**与**轻量化模式**下的分步安装、环境配置、数据库初始化及常见问题排查步骤。

---

## 1. 系统要求

* **操作系统**：Linux (推荐，例如 Ubuntu 22.04+)、macOS 或 Windows (需启用 WSL2)。
* **Python**：Python 3.11 或 3.12。
* **容器引擎**：Docker Engine 24.0+ 和 Docker Compose v2.20+。
* **硬件规格**：
  * 最低规格：4 核 CPU，8GB 内存（标准容器模式）。
  * 轻量化模式：2 核 CPU，4GB 内存（无需启动容器）。

---

## 2. 分步安装步骤

### 步骤 2.1：克隆并进入仓库
```bash
git clone <repository_url> agentdeepdive
cd agentdeepdive
```

### 步骤 2.2：创建 Python 虚拟环境
建议使用本地虚拟环境以避免依赖包冲突：
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 步骤 2.3：安装平台依赖
以可编辑模式（Editable Mode）安装项目及开发依赖项：
```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

---

## 3. 配置与环境变量

从模板中复制并生成本地的 `.env` 配置文件：
```bash
cp .env.example .env
```

使用编辑器打开 `.env` 文件并配置相关参数：

### 核心环境设置
* `SYSTEM_MODE`：设置为 `standard`（使用 Docker 容器服务）或 `lightweight`（零容器，使用 SQLite 和 FAISS）。
* `DEEPSEEK_API_KEY`：填入您的 DeepSeek/LLM SaaS 模型 API 密钥。
* `DATABASE_URL`：PostgreSQL 连接串（默认指向本地 Docker 实例）。
* `REDIS_URL`：Redis 服务器连接串，用于任务队列与发布/订阅。
* `MILVUS_HOST` / `MILVUS_PORT`：Milvus 向量数据库连接坐标。

### 人工审批渠道集成 (可选)
如果希望直接在您的即时通讯频道中接收并处理 L3 级人工审批提示，请配置以下参数：
* `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
* `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID`
* `SLACK_WEBHOOK_URL`

---

## 4. 运行模式说明

### 模式 A：标准容器模式 (推荐用于生产与多租户环境)

标准模式使用 Docker 容器实现服务状态的强隔离。

#### 1. 启动基础设施服务
启动 PostgreSQL, Redis, Milvus 向量库以及 Jaeger 链路追踪容器：
```bash
agentdeep infra up
```
可以通过以下命令验证所有服务是否正常在线运行：
```bash
agentdeep infra status
```

#### 2. 数据库迁移与初始化
使用 Alembic 迁移工具初始化 PostgreSQL 数据库表结构：
```bash
agentdeep db upgrade head
```

#### 3. 启动后端 API 服务
使用 Uvicorn 启动 FastAPI 后端服务：
```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```
访问 `http://localhost:8000/docs` 可查看交互式 OpenAPI 接口文档。

#### 4. 运行 Cockpit UI 前端大屏
在新的终端窗口中，导航至 dashboard 目录并运行前端开发服务器：
```bash
cd dashboard
npm install
npm run dev
```
打开浏览器访问 `http://localhost:5173`。

---

### 模式 B：零容器轻量化模式 (推荐用于本地离线调试)

在轻量化模式下，所有组件直接运行在您本机的 Python 进程中，无需启动 Docker。

* **数据库**：使用本地 SQLite 文件 (`.memory/agentdeep.db`)。
* **向量检索**：使用本地 FAISS 和 SentenceTransformers 代替 Milvus 容器。
* **并发控制锁**：使用本地 Python 文件锁 (`fcntl` / file-locks)。

#### 立即执行任务：
无需运行任何启动命令！只需在执行任务时附带 `-l` 参数：
```bash
agentdeep run "Test hello world python script" -l
```

---

## 5. 常见问题排查与 FAQ

### 1. Docker 套接字权限拒绝 (Permission Denied)
* **错误**：`Permission denied when trying to connect to the Docker daemon socket.`
* **解决方案**：将当前用户加入 `docker` 用户组：
  ```bash
  sudo usermod -aG docker $USER
  ```
  然后注销并重新登录系统，或者在终端运行 `newgrp docker` 生效。

### 2. 端口冲突 (Address already in use)
* **错误**：`Bind for 0.0.0.0:5432 failed: port is already allocated.`
* **解决方案**：通常是因为您的宿主机系统上已经运行了本地的 PostgreSQL 或 Redis 服务。
  * 停止宿主机上的 PostgreSQL 服务：`sudo systemctl stop postgresql`
  * 或者修改 `docker/docker-compose.yml` 将外部映射端口改为其他值（例如将 PostgreSQL 映射为 `5433:5432`），并同步更新 `.env` 中的 `DATABASE_URL` 端口。

### 3. Milvus 向量库连接失败
* **错误**：`MilvusClient failed to connect to http://localhost:19530.`
* **解决方案**：Milvus 容器在首次启动时通常需要十几秒来完成初始化。请通过 `agentdeep infra status` 确认其状态，或通过 `agentdeep infra logs milvus` 查看日志。另外，请确保宿主机剩余空闲内存不低于 8GB。

### 4. 测试挂起或失败
* **错误**：`Test suite timeouts or verification loops.`
* **解决方案**：请确认您的沙箱虚拟环境 `.venv_sandbox` 是否已正确初始化，或者直接运行 pytest 对具体单元测试进行隔离调试：
  ```bash
  pytest tests/unit/
  ```
