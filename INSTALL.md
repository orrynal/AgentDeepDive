# Installation & Deployment Guide

[中文](INSTALL.zh.md) | English

This guide details the step-by-step installation, environment setup, database initialization, and troubleshooting steps for both **Standard Container Mode** and **Lightweight Mode** in AgentDeepDive.

---

## 1. System Requirements

* **Operating System**: Linux (recommended, e.g., Ubuntu 22.04+), macOS, or Windows (WSL2 required).
* **Python**: Python 3.11 or 3.12.
* **Container Engine**: Docker Engine 24.0+ and Docker Compose v2.20+.
* **Hardware Specs**:
  * Minimum: 4 Cores, 8GB RAM (Standard Mode).
  * Lightweight Mode: 2 Cores, 4GB RAM (No containers required).

---

## 2. Step-by-Step Installation

### Step 2.1: Clone and Enter the Repository
```bash
git clone <repository_url> agentdeepdive
cd agentdeepdive
```

### Step 2.2: Setup Python Virtual Environment
We recommend using a local virtual environment to prevent package conflicts:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 2.3: Install Package and Dependencies
Install the package in editable mode with development dependencies:
```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

---

## 3. Configuration & Environment Variables

Create your local `.env` file from the provided example:
```bash
cp .env.example .env
```

Open `.env` in your editor and configure the parameters:

### Core Environment Settings
* `SYSTEM_MODE`: Set to `standard` (uses Docker services) or `lightweight` (zero-container, SQLite & FAISS).
* `DEEPSEEK_API_KEY`: Paste your DeepSeek/LLM SaaS API key.
* `DATABASE_URL`: PostgreSQL connection string (defaults to local Docker instance).
* `REDIS_URL`: Redis server URL for queue and pub/sub.
* `MILVUS_HOST` / `MILVUS_PORT`: Milvus vector storage coordinates.

### Human-in-the-Loop Integrations (Optional)
Configure these keys if you want to receive L3 approval prompts directly on your workspace chat:
* `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`
* `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID`
* `SLACK_WEBHOOK_URL`

---

## 4. Run Mode Instructions

### Option A: Standard Container Mode (Production & Multi-Tenant Setup)

Standard mode utilizes Docker containers for service state isolation.

#### 1. Spin Up Infrastructure
Start the database, vector storage, key-value stores, and Jaeger tracers:
```bash
agentdeep infra up
```
To verify that all services are online, run:
```bash
agentdeep infra status
```

#### 2. Run Database Migrations
Initialize the PostgreSQL database schema using Alembic:
```bash
agentdeep db upgrade head
```

#### 3. Start the Backend API Server
Launch the FastAPI server using Uvicorn:
```bash
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```
Visit `http://localhost:8000/docs` to verify the OpenAPI docs.

#### 4. Run the Cockpit UI Frontend
In a new terminal window, navigate to the dashboard directory and run the development server:
```bash
cd dashboard
npm install
npm run dev
```
Open your browser to `http://localhost:5173`.

---

### Option B: Zero-Container Lightweight Mode (Local Testing)

In Lightweight Mode, all components run directly inside your host python process without requiring Docker.

* **Database**: Uses a local SQLite file (`.memory/agentdeep.db`).
* **Memory Vector Store**: Uses local FAISS and SentenceTransformers instead of Milvus.
* **Concurrency Locking**: Uses localized python file-locking (`fcntl` / file-locks).

#### Run tasks instantly:
No setup command required! Simply execute commands with the `-l` flag:
```bash
agentdeep run "Test hello world python script" -l
```

---

## 5. Troubleshooting & FAQ

### 1. Docker Socket Permission Denied
**Error**: `Permission denied when trying to connect to the Docker daemon socket.`
* **Solution**: Add your user to the docker group:
  ```bash
  sudo usermod -aG docker $USER
  ```
  Then log out and log back in, or run `newgrp docker`.

### 2. Port Collision (Address already in use)
**Error**: `Bind for 0.0.0.0:5432 failed: port is already allocated.`
* **Solution**: You likely have PostgreSQL or Redis running locally on your system.
  * Stop your system PostgreSQL service: `sudo systemctl stop postgresql`
  * Or edit `docker/docker-compose.yml` to map host ports to alternatives (e.g., map Postgres to `5433:5432`), and update your `.env` `DATABASE_URL` port accordingly.

### 3. Milvus Connection Issues
**Error**: `MilvusClient failed to connect to http://localhost:19530.`
* **Solution**: Milvus requires several seconds to initialize on the first launch. Check status with `agentdeep infra status` or view logs with `agentdeep infra logs milvus`. Ensure your machine has at least 8GB of RAM.

### 4. Tests Hanging or Failing
**Error**: `Test suite timeouts or verification loops.`
* **Solution**: Ensure your sandbox virtual environment `.venv_sandbox` is initialized, or run pytest directly to isolate issues:
  ```bash
  pytest tests/unit/
  ```
