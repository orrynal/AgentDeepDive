# Skill Development & DSL Orchestration Guide

This guide is designed to help developers create custom **Agent Skills** and orchestrate complex engineering workflows using the **Directed Acyclic Graph (DAG) DSL** in AgentDeepDive.

---

## 1. Writing Agent Skills

Skills are the minimum cognitive and tool execution units for an agent. Each skill is defined declaratively in a `skills/<skill_name>/skill.yaml` file, which is dynamically loaded and registered into the global skill repository by the skill parser.

### 1.1 `skill.yaml` Schema Details

Below is a typical `skill.yaml` file definition:

```yaml
skill_id: "code-generator-v1"                         # Globally unique identifier for the skill
name: "Code Generation Expert"                         # Display name of the skill
version: "1.0.0"                                      # Version number of the skill
description: "Generates high-quality HTML, CSS, JS source code based on specs and writes to file" # Function description
tags:                                                 # Categorization tags for semantic search
  - "code"
  - "development"
trigger_patterns:                                     # Regex/Keyword trigger patterns (for router activation)
  - "write code"
  - "generate code"
  - "build game"
context_budget: 16000                                 # Maximum token context window limit
required_tools:                                       # Authorized system tools for this skill
  - "file_write"
  - "file_read"
  - "directory_list"
risk_level: "medium"                                  # Risk level (low / medium / high) tied to OPA policies
approval_required: true                               # Whether L3 Human-in-the-loop approval is required
estimated_tokens: 16000                               # Estimated maximum token consumption per run
estimated_duration_sec: 120                           # Estimated duration (seconds)
system_prompt: |                                      # System instructions injected into the LLM
  You are an elite full-stack developer. Based on the provided requirements and design docs, generate high-quality, structured, and runnable source code.
  
  Execution Rules:
  1. You MUST use the `file_write` tool to save your generated code to the specified target path.
  2. Use clean variable naming conventions and clear comments.
  3. Keep logic complete. Do NOT output placeholder comments like "TODO".
```

### 1.2 Core Field Design Principles

* **Trigger Patterns (`trigger_patterns`)**: When a user submits a prompt via `agentdeep run "target task"`, the router compares it against these patterns. Proper trigger patterns ensure accurate routing.
* **Tool Permissions (`required_tools`)**: An agent can *only* invoke tools explicitly listed here. If the `system_prompt` tells the agent to write a file, but `required_tools` does not include `file_write`, execution will be blocked.
* **Security & Approval (`risk_level` & `approval_required`)**:
  * `low`: Reading directories or checking status. Executed directly without user approval.
  * `medium`: File write operations. If `approval_required: true`, the user must confirm the action.
  * `high`: OS commands or shell executions. Must pass OPA evaluation and obtain manual authorization via integrated channels (Slack/Discord) before running.

---

## 2. DAG Orchestration DSL Guide

For multi-stage, high-certainty workflows (e.g., full lifecycle from architecture design and coding to test suite generation and OPA audits), a single monolithic agent prompt will break due to context decay. The platform uses a YAML-based **Directed Acyclic Graph (DAG) DSL** to decouple tasks and coordinate parallel execution.

### 2.1 DAG YAML DSL Example

Below is a typical game builder workflow (e.g., `docs/examples/snake_game_dag.yaml`):

```yaml
dag_id: "snake-builder-dag"
name: "Snake Game Builder Pipeline"
description: "Coordinates multiple agents in parallel to design, code, and test a Snake game"
routing_tier: "medium"
nodes:
  - node_id: "design"
    name: "Game Architecture Design"
    skill_id: "doc-writer-v1"
    description: >
      Design a single-page HTML5 Snake game layout.
      Include a 10x10 grid, canvas rendering, scoreboards, and a dark neon theme.
      Generate the design specification and write it to examples/snake_game/design.md using file_write.

  - node_id: "code"
    name: "Core Coding Stage"
    skill_id: "code-generator-v1"
    dependencies: 
      - "design"
    description: >
      Based on examples/snake_game/design.md, write a complete index.html file containing CSS/JS.
      Include movement, food spawning, collision checks, and restart buttons. Write to examples/snake_game/index.html.

  - node_id: "test"
    name: "Automated Verification"
    skill_id: "test-generator-v1"
    dependencies: 
      - "code"
    description: >
      Analyze examples/snake_game/index.html. Write a Python script verify.py to check tag closures, 
      HTML validity, and syntax. Execute using shell_exec to ensure it is completely functional.
```

### 2.2 Deep Dive into DAG Core Mechanisms

#### A. Topological Sorting and Concurrency
Upon loading the YAML definition, the DAG engine parses the `dependencies` array:
* **Concurreny**: Independent nodes (or nodes whose dependencies are all completed and green) are executed **in parallel** using multithreading or isolated sub-sandboxes.
* **Topological Sort**: Calculates execution paths, detects circular dependencies, and ensures task execution determinism.

#### B. Dynamic Data Passing (`input_mapping`)
In advanced scenarios, downstream nodes need to consume variables outputted by upstream nodes. This is achieved via `input_mapping`:

```yaml
  - node_id: "code-review"
    name: "Code Audit"
    skill_id: "code-reviewer-v1"
    dependencies:
      - "code"
    input_mapping:
      source_code: "code.result.file_content"  # Injects output field 'file_content' from node 'code' as 'source_code' input
    description: >
      Perform code quality and vulnerability audits on the passed source_code.
```
The DAG engine evaluates these expressions on the fly, fetching the target variables and injecting them into the downstream agent's prompt context.

#### C. State Machine & Node Color System
The engine uses visual color-coding to represent node lifecycles. States transitions are strictly managed:

* **Gray (GRAY)**: Pending. Waiting for its parent dependencies to complete.
* **Blue (BLUE)**: Queued. Dependencies completed, queued for execution resource allocation.
* **Yellow (YELLOW)**: Running. Sandbox initialized, LLM actively driving tools.
* **Green (GREEN)**: Completed. Node executed successfully, output saved.
* **Orange (ORANGE)**: Awaiting Approval. Execution suspended, waiting for manual L3 authorization.
* **Red (RED)**: Failed. Node threw an unhandled exception, failed tests, or was blocked by OPA.
* **Suspended (SUSPENDED)**: Suspended. Can be manually bypassed or restored from the UI/CLI.

---

## 3. Development and Debugging Practices

### 3.1 Registrations and Self-checks

To test your custom skills or DAG flows:

1. **Register Skill**: Place your YAML file in `skills/<skill_name>/skill.yaml`.
2. **Environment Doctor**: Run the diagnostics CLI to check backend configurations:
   ```bash
   agentdeep doctor
   ```
3. **Single Run Test**: Manually invoke the skill to check routing and prompt compliance:
   ```bash
   agentdeep run "Execute test logic using my custom skill"
   ```

### 3.2 Running a DAG Pipeline

To run a pipeline YAML file (e.g., `my_pipeline.yaml`), execute via the CLI:

```bash
# Execute in standard container mode (uses Docker backend)
agentdeep dag execute -f my_pipeline.yaml

# Execute in zero-container lightweight mode (SQLite / FAISS)
agentdeep dag execute -f my_pipeline.yaml -l
```

### 3.3 Dashboard Observability & Diagnostics

1. Start the React dashboard server:
   ```bash
   cd dashboard && npm run dev
   ```
2. Navigate to `http://localhost:5173`.
3. The dashboard renders the DAG flow topologies visually.
4. **Breakpoint Recovery**:
   * If a node turns **Red (RED)**, click the node to examine stderr traces and logs in the Telemetry panel.
   * Fix the issue (or update local files), then click **"Restore Task"** on the node. The engine resets the target node and its downstream branches to `GRAY` and restarts the execution flow without needing to rerun the entire DAG.
