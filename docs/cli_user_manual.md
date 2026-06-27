# AgentDeepDive CLI User Manual

> **Document Type**: Operation Guide & Reference Manual  
> **Date**: June 13, 2026  
> **Status**: Completed  
> **CLI Entry**: `agentdeep`

---

## 1. Quick Start & Shell Autocomplete

`agentdeep` is a unified Click-based command-line interface for managing agent execution, diagnostic checks, database migrations, security audits, and Docker containers.

### 1.0 Environment Configuration (Exposing `agentdeep`)
Since `agentdeep` is installed inside the project's virtual environment, the shell needs to know where the executable resides. You can expose it by adding the project's `.venv/bin` directory to your `PATH` in your shell configuration profile (e.g. `~/.bashrc` or `~/.zshrc`):

```bash
# Add AgentDeepDive CLI to PATH
export PATH="/path/to/AgentDeepDive/.venv/bin:$PATH"
```

### 1.1 Enabling Shell Autocomplete
Once `agentdeep` is added to your `PATH`, you can enable autocomplete for command args, flags, and options:

#### Bash
Add the following line to your `~/.bashrc`:
```bash
eval "$(_AGENTDEEP_COMPLETE=bash_source agentdeep)"
```
Or generate and source directly:
```bash
agentdeep completion bash > ~/.agentdeep-complete.bash
source ~/.agentdeep-complete.bash
```

#### Zsh
Add the following line to your `~/.zshrc`:
```zsh
eval "$(_AGENTDEEP_COMPLETE=zsh_source agentdeep)"
```

#### Fish
Add the following line to your `~/.config/fish/config.fish`:
```fish
_AGENTDEEP_COMPLETE=fish_source agentdeep | source
```

### 1.2 Click Completion Notes
Click autocompletion relies on standard shell profiles. If you want to automatically enable completion, append the corresponding evaluation/source command to your shell's rc file (`~/.bashrc`, `~/.zshrc`, or `config.fish`) as detailed above. The legacy script `./scripts/setup_autocomplete.sh` is deprecated.

---

## 2. Adaptive Run Modes (Remote vs. Local)

The CLI features an **auto-adaptive runtime mode** governed by `src/cli/context.py`.

```
                  ┌─────────────────────────────────┐
                  │      agentdeep execution        │
                  └────────────────┬────────────────┘
                                   │
                           [Mode Detection]
                                   │
                ┌──────────────────┴──────────────────┐
        [API Server Online]                   [API Server Offline]
                │                                     │
      ┌─────────▼─────────┐                 ┌─────────▼─────────┐
      │    REMOTE MODE    │                 │    LOCAL MODE     │
      │   (httpx calls)   │                 │ (direct database) │
      └───────────────────┘                 └───────────────────┘
```

- **Remote Mode**: Selected automatically when the FastAPI server is online at `localhost:8000`. Submits task payloads via HTTP.
- **Local Mode (Direct Connect)**: Selected automatically when the API server is offline. CLI connects directly to PostgreSQL and Redis to query data and execute tasks, avoiding any system downtime.
- **Dual Mode Coverage**: The following command groups support both **Remote** and **Local** modes:
  - `run`: Submits/runs tasks.
  - `skill`: lists, registers, shows, and deletes skills.
  - `dag`: splits tasks, executes DAGs, and shows DAG status.
  - `budget`: shows token budgets.
  - `pool`: displays agent concurrency and slots.
  - `approval`: lists, approves, and rejects HITL tasks.
  - `evolution`: evaluates trace executions and optimizes skill prompts with A/B testing grey variants.

### 2.1 Global CLI Overrides & Options

You can override the autodetected mode or active tenant namespace using global flags before the subcommand:
- `--tenant`, `-t <ID_OR_NAME>`: Specifies the tenant ID or name override (resolves automatically to UUID).
- `--local`: Forces the CLI to operate in **Local** mode directly against the local databases.
- `--remote`: Forces the CLI to operate in **Remote** mode using HTTP calls.

Example:
```bash
# Force local mode and query a skill under the "finance" tenant
agentdeep --local --tenant finance skill show report-generator
```

---

## 3. Command Reference

### 3.1 Adaptive Commands (`run`, `status`)

#### `agentdeep status`
Displays the connectivity, CLI resolution mode, and sub-service health checks.
- If in **Remote** mode, queries FastAPI `/health` and `/health/ready`.
- If in **Local** mode, performs direct DB/Redis pings.
- **Third-Party Integrations (`--channels` / `-c`)**: Runs a comprehensive connectivity and authorization diagnostic across all configured external notification and SaaS integrations (Telegram, Discord, WeChat, Slack, Feishu, DingTalk, WhatsApp, QQ, Twitter, Notion, Supabase, Airtable) and displays the results in a beautiful Rich Table.
  ```bash
  agentdeep status --channels
  # Or using short option
  agentdeep status -c
  ```

#### `agentdeep run`
Submits a task description for agent execution.
```bash
agentdeep run "Retrieve all system errors from yesterday" --model gpt-4o --context "debug_run=true"
```
- **Local Fallback**: If the API server is down, resolves skills via local `SkillRouter` and runs the agent locally via `AgentExecutor`.
- Options:
  - `--model`: Override default LLM.
  - `--context`: Pass additional context.
  - `--skill`: Force explicit skill routing.

#### `agentdeep chat`
Launches the **Interactive Chat REPL Terminal** where you can converse with the autonomous developer agent.
```bash
agentdeep chat --model gpt-4o
```
- **Context Injection (`@file`)**: You can attach local file contents directly into the conversation by prepending `@` to a relative or absolute file path (e.g. `Help me debug @src/cli/main.py`). The terminal will automatically locate and load the file content.
- **Episodic memory recall**: When you input a prompt, the terminal automatically retrieves similar historical errors and patch fixes from Milvus to help steer the agent.
- **Real-time token cost status bar**: The terminal displays a bottom status bar tracking active model, active tenant, and estimated context tokens.
- **Role-Aware Context Truncation**: When the conversation size exceeds the max context token budget, the REPL automatically truncates older dialogue but **fully protects and preserves all system-role prompts** (e.g. sub-agent instructions). It also guarantees the latest user/assistant turn is retained, preventing the model from losing active focus.
- **Interactive Slash Commands**:
   - `/help`: Show all commands.
   - `/clear`: Clear message history.
   - `/model [name]`: Print or hot-switch LLM model.
   - `/status`: Show detailed session and token stats.
   - `/save [filename]`: Save current session log as JSON.
   - `/load <filename>`: Load a previous session log.
   - `/locks`: List active Redis concurrency locks.
   - `/doctor`: Run dependency diagnostics.
   - `/dag [dag_id]`: Display a beautiful visual ASCII/Unicode topology tree of the last or specified DAG execution.
   - `/exit` or `/quit`: Exit REPL.

---

### 3.2 Infrastructure Command Group (`infra`)

Manages Docker Compose container dependencies (PostgreSQL, Redis, Milvus, Jaeger).

```bash
# Start all container infrastructure services
agentdeep infra up

# Start only PostgreSQL and Redis
agentdeep infra up --service pg --service redis

# View runtime statuses of docker containers
agentdeep infra status

# Tail logs of Redis container
agentdeep infra logs redis

# Stop and remove all containers
agentdeep infra down

# Hard reset all volume storage (WARNING: destructive)
agentdeep infra reset --confirm
```

---

### 3.3 System Diagnostics Command (`doctor`)

Checks all host-level environments, dependencies, configurations, and connectivity.

```bash
agentdeep doctor
```
Checks performed:
- Python runtime check
- PostgreSQL connection and version check
- Redis pool connection check
- Milvus ORM connection check
- Jaeger tracing socket reachable check
- OPA decision API reachable check
- Docker Compose config syntax check

---

### 3.4 Distributed Lock Manager Group (`lock`)

Manages cluster synchronization locks stored in Redis.

```bash
# List all active locks
agentdeep lock list

# Show details of a specific lock
agentdeep lock show lock_key_xyz

# Force release a locked key
agentdeep lock release lock_key_xyz

# Clean all expired or stale locks
agentdeep lock clean --stale

# Release all locks held by a specific agent ID
agentdeep lock clean --agent agent-01
```

---

### 3.5 Security Audit Log Group (`audit`)

Queries, exports, and purges agent activity, tool invocations, and policy evaluations.

```bash
# List recent audit logs
agentdeep audit list --limit 10 --level WARNING

# Export audit logs to local CSV report
agentdeep audit export --format csv --output ./logs/audit_report.csv

# Render an ASCII statistic graph of audit actions
agentdeep audit stats

# Purge logs older than 30 days from PostgreSQL and JSONL log file
agentdeep audit purge --before 30 --confirm
```

---

### 3.6 OPA Engine Policy Group (`opa`)

Integrates with Open Policy Agent for Rego-defined security rules.

```bash
# Push local guardrails.rego file to OPA server
agentdeep opa push

# Diagnose and test connectivity with OPA
agentdeep opa status

# Local test evaluation of a JSON payload against rules
agentdeep opa eval --input '{"input": {"action": "shell", "command": "rm -rf /"}}'
```

---

### 3.7 Tenant Authentication & Profile Group (`auth`)

Manages client-side sessions, user registration, local authentication caching, and active profiles.

```bash
# Register a new tenant namespace and its admin user account
agentdeep auth register --tenant acme --username admin --password securepass

# Login to fetch a JWT access token and cache it locally
agentdeep auth login --username admin --password securepass

# Check the current active session, roles, and profile details
agentdeep auth me

# Clear cached credentials and logout
agentdeep auth logout
```

---

### 3.8 Database Migration Group (`db`)

Wraps Alembic command execution directly via SQLAlchemy configuration.

```bash
# Apply pending migration scripts
agentdeep db migrate

# Generate a new migration script
agentdeep db revision "add_audit_table"

# View current database version schema revision ID
agentdeep db current

# View history of applied database migration steps
agentdeep db history
```

---

### 3.9 Real-time Monitor Dashboard (`monitor`)

Renders a live, responsive terminal UI using Rich layout grids to trace active status.

```bash
# Start the real-time terminal monitor dashboard
agentdeep monitor --interval 2.0
```

#### Keyboard Interactive Controls:
- `q`: Quit the monitor.
- `r`: Force manual immediate refresh of all metrics.
- `l`: Toggle displaying/hiding the **Distributed Locks** section.
- `a`: Toggle displaying/hiding the **Governance Audits** section.

---

## 4. Typical Operations Workflow

### Scenario: Setting Up a Clean Development Environment
1. Check the configuration:
   ```bash
   agentdeep config show
   ```
2. Spin up the container services:
   ```bash
   agentdeep infra up
   ```
3. Verify connections and dependencies:
   ```bash
   agentdeep doctor
   ```
4. Run database migrations:
   ```bash
   agentdeep db migrate
   ```
5. Push the OPA policies:
   ```bash
   agentdeep opa push
   ```
6. Check overall system status:
   ```bash
   agentdeep status
   ```
7. Start executing tasks:
   ```bash
   agentdeep run "Test system capability"
   ```

---
⏱️ System Current Time: 2026年06月14日08时10分00秒
