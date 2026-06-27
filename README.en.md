# 🤖 AgentDeepDive

**Multi-Agent Orchestration Platform for Super Engineering**  
*Enterprise-Grade Multi-Agent Orchestration & Execution Platform for Complex Software Engineering*

![AgentDeepDive Banner](docs/agentdeepdive_banner.png)

---

[中文](README.md) | English

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.11%2B-green.svg)](pyproject.toml)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)]()

AgentDeepDive is a multi-agent orchestration and collaborative execution platform designed for complex, multi-stage, high-security enterprise engineering tasks. By integrating goal decomposition, concurrent scheduling, multi-channel Human-in-the-Loop (HITL) approval, sandbox isolation, and self-evolution flywheels, it provides a production-ready agent collaboration experience.

---

## 🌟 Core Features

1. **Distributed DAG Orchestration Engine**
   * **Dynamic Decomposition**: Automatically decomposes complex, long-horizon objectives into Directed Acyclic Graphs (DAG) of task nodes.
   * **Concurrent Scheduling**: Supports concurrent execution of independent branches, automatic dependency injection, and state transmission.
   * **State Recovery**: Enables system state recovery and resumption from a specific failed node in case of execution interrupts.
2. **Multi-Channel Approval (HITL Gateway)**
   * **Human-in-the-Loop**: Built-in L3-level HITL approval gateway for critical decisions.
   * **Multi-Channel Delivery**: Supports sending notifications and receiving authorizations directly via Slack, Discord, WeChat, etc.
3. **Secure Sandbox & Sentinel GC**
   * **Strict Isolation**: Runs agent actions in isolated Docker containers, preventing execution scripts from contaminating the host machine.
   * **Sentinel Garbage Collection**: A background sentinel daemon monitors sandbox status, automatically recycling zombie containers and hung processes.
4. **Zero-Container Lightweight Mode**
   * **Out-of-the-Box**: Launches a lightweight developer environment with a simple `-l` / `--lightweight` flag, swapping heavy cloud-native components with local SQLite, FAISS, and file locks.
5. **Enterprise Governance & Security Policy (OPA & Rego)**
   * **Dynamic Compliance**: Employs an embedded OPA (Open Policy Agent) micro-segmentation gateway, dynamically intercepting high-risk operations via Rego policies.
   * **Privacy Safeguard**: Built-in API Key masking to prevent leaks, along with tamper-proof cryptographic audit trails.
6. **Visual Cockpit Dashboard**
   * **Interactive Topology Canvas**: Powered by React Flow, visualizing node execution states (Not Started, Running, Success, Pending, Failed) dynamically.
   * **Hover Telemetry**: Features real-time hovering panels showcasing logs, runtime metadata, and variable scopes.
7. **Self-Evolution & E2E Validation**
   * **Self-Healing Flywheel**: Identifies and fixes execution issues automatically through multi-file AST syntax checks and strategy adjustments.
   * **pytest Guard**: Auto-runs comprehensive verification suites to ensure zero bugs leak into production.

---

## 📁 Repository Structure

```text
AgentDeepDive/
├── src/
│   ├── core/           # Core engine (orchestrator, skill registry, sandbox, locks, security)
│   ├── evolution/      # Self-evolution flywheel (self-diagnostics and strategy tuning)
│   ├── api/            # FastAPI Web routes and WebSocket event streaming
│   └── cli/            # Click-based command-line interface
├── dashboard/          # React + Vite + React Flow frontend console
├── skills/             # Pre-defined & dynamically registered agent skills (YAML)
├── docker/             # Compose configurations for PostgreSQL, Redis, Milvus, OPA, Jaeger
├── tests/              # Unit testing and E2E verification suites
├── docs/               # Detailed architecture specifications and roadmaps
└── LICENSE             # MIT License
```

---

## 🏛️ System Microservices & Containers

When running under standard containers or Kubernetes (K8s) environments, AgentDeepDive segregates tasks into multiple cooperating containers:

*   **`agentdeep-api` (Control Plane / API Server)**: Built with FastAPI, handling Web APIs, WebSocket event streams, user sessions, and metadata databases. It acts as the gateway for triggering DAG orchestration and timers.
*   **`agentdeep-worker` (Data Plane / Celery Worker)**: Listens to the Redis task broker, executes complex DAG node scheduling, runs agent models, and calls sandboxed tools. Can be horizontally scaled to handle high-concurrency tasks.
*   **`agentdeep-beat` (Cron Trigger)**: Powered by Celery Beat, constantly polling the database to trigger periodic scheduled tasks and dispatching workflows into Redis queues.
*   **`redis` (Message Broker)**: Decomposes communication between the API control plane and workers, ensuring asynchronous task distribution.
*   **`postgres` (Relational Metadata Store)**: Persists tenant accounts, Agent configurations, compiled DAG graphs, historic action telemetry, and security logs.
*   **`jaeger` (APM / Distributed Tracing)**: Records and traces API and tool executions. Facilitates visual debugging of latency and exceptions in complex multi-step agent flowchains.

For a detailed introduction to system dependency environments (PostgreSQL, Redis, Milvus, OPA, Jaeger) and individual application-level code modules (CentralBrain, DAGEngine, AdaptiveRouter, Sentinel, etc.), please refer to the [System Components and Environments Manual (system_components_and_environments.en.md)](docs/system_components_and_environments.en.md).

For Kubernetes (K8s) native controller component references, see the [K8s Deployment Guide (docs/deployment/kubernetes_deployment_guide.en.md)](docs/deployment/kubernetes_deployment_guide.en.md).

---

## 🤖 One-Line Setup for AI Agents

If you are using **Claude Code**, **Cursor**, **Windsurf**, or other AI coding assistants, you can pass the following prompt:

```text
Help me bootstrap AgentDeepDive for local development by following the guides in README.md and INSTALL.md
```

The AI agent will analyze the workspace, resolve dependencies, and automatically boot up the development environment.

---

## 🚀 Quick Start

For step-by-step setup guides, multi-tenant deployment, and resource tuning, refer to [INSTALL.md](INSTALL.md).

### 1. Prerequisites
* Python 3.11+
* Docker & Docker Compose

### 2. Dependency Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Environment Variables
```bash
cp .env.example .env
# Edit .env to set your LLM API Keys and IM channel tokens
```

### 4. Running the Platform

AgentDeepDive supports two startup modes:

#### A. Standard Container Mode (Recommended for Production/Full Flow)
```bash
# 1. Start Docker infrastructure services (PostgreSQL, Redis, Milvus, OPA)
agentdeep infra up

# 2. Run database migrations
agentdeep db upgrade head

# 3. Spin up the FastAPI server
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

#### B. Zero-Container Lightweight Mode (Recommended for local dev & testing)
Add the `-l` / `--lightweight` flag to bypass Docker. The database and index store will fallback to local SQLite and FAISS files:
```bash
agentdeep run "Develop a simple minesweeper game" -l
```

---

## 📊 Deployment Sizing Recommendations

| Deployment Tier | Specs | Best Use Cases | Core Components |
| :--- | :--- | :--- | :--- |
| **Lightweight Dev** | 2 vCPU / 4 GB | Local code testing, CLI automation scripting, skill writing | Local SQLite, FAISS, File Locks |
| **Standard Server** | 4 vCPU / 8 GB | Team collaboration, E2E testing, visual Cockpit monitoring | Docker compose, PostgreSQL, Redis, Milvus, OPA |
| **HA Production** | 8 vCPU / 16 GB+ | High-concurrency agent execution, strict OPA Rego audits | Cluster Databases, K8s execution sandboxes, Jaeger |

*Note: The above profiles exclude running local LLMs (e.g., Llama 3 or DeepSeek via vLLM). Allocate extra GPU resources accordingly if self-hosting models.*

---

## 🛠️ Sample Configuration (`config.yaml`)

Configure your Large Language Models (OpenAI, Claude, Gemini, DeepSeek, or vLLM deployments) and security parameters:

```yaml
# AgentDeepDive Configuration
app:
  name: "AgentDeepDive"
  env: "development"

# Model Router Settings
models:
  default: "gemini-1.5-pro"
  providers:
    openai:
      api_key: "${OPENAI_API_KEY}"
      base_url: "https://api.openai.com/v1"
    gemini:
      api_key: "${GEMINI_API_KEY}"
    deepseek:
      api_key: "${DEEPSEEK_API_KEY}"
      base_url: "https://api.deepseek.com"
    vllm:
      api_key: "placeholder"
      base_url: "http://localhost:8000/v1"

# Orchestration & Sandbox Settings
sandbox:
  mode: "docker" # Options: docker / local
  docker:
    image: "agentdeepdive-sandbox:latest"
    cpu_limit: 2.0
    memory_limit: "4g"
  sentinel:
    enabled: true
    gc_interval_seconds: 60

# Policy Control (OPA)
security:
  opa:
    enabled: true
    url: "http://localhost:8181/v1/data/agent_policy"
  audit:
    cryptographic_integrity: true
```

---

## 🛠️ CLI Reference

AgentDeepDive CLI provides deep diagnostics and interaction capability, auto-detecting service availability.

### Infrastructure Management (`agentdeep infra`)
* `agentdeep infra up` — Spin up backend Docker infrastructure.
* `agentdeep infra status` — View status of running containers and ports.
* `agentdeep infra stop` — Stop infrastructure containers without deleting data.
* `agentdeep infra start` — Resume stopped infrastructure containers.
* `agentdeep infra down` — Tear down docker containers safely (preserving volume data).
* `agentdeep infra reset` — Clean up all containers and wipe volume stores (Caution!).

### Execution & Orchestration
* `agentdeep run "TASK_DESCRIPTION" [-l]` — Run a single agent step (lightweight flag supported).
* `agentdeep dag split "TASK_DESCRIPTION" [-l]` — Parse target task and output parsed DAG nodes.
* `agentdeep dag execute [DAG_ID] [-f FILE.yaml] [-l]` — Run a registered or file-loaded DAG concurrently.

### Human Approvals & Self-Testing
* `agentdeep approval list` — Show all pending L3 approvals.
* `agentdeep approval approve <TASK_ID>` — Force bypass approval on a blocked action node.
* `agentdeep doctor` — Perform connection tests and environmental self-tests.

---

## 📊 Cockpit Dashboard

Access the React Flow dashboard to monitor topologies and telemetry in real time:
```bash
cd dashboard
npm install
npm run dev
```
Open `http://localhost:5173` to explore the interactive canvas, triggers for task restoration (Restore Task), and real-time OPA logs.

---

## ⚠️ Security Notice

1. **Sandbox Isolation**: Always set sandbox mode to `docker` in production environments. Running untrusted third-party agents under `local` execution mode bypasses host protection and may harm host systems.
2. **OPA Rego Enforcement**: We recommend configuring rigid OPA rules to explicitly deny dangerous execution operations (e.g., `rm -rf /` or forbidden outbound connections).
3. **Secret Security**: Ensure your `.env` configuration file is included in `.gitignore` to prevent leaking API Keys, Slack tokens, or other credentials.

---

## 🤝 Contributing

We welcome community contributions to AgentDeepDive! 
1. Fork the repo and create your Feature Branch.
2. Ensure your changes pass all AST validation scripts and pytest test sets.
3. Submit a Pull Request outlining your modifications.

---

## 📄 License

This repository is licensed under the **[MIT License](LICENSE)**.
