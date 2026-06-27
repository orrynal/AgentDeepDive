# AgentDeepDive 测试指南 (Phase 1 & Phase 2 阶段)

> 本文档用于指导开发者和测试人员对 AgentDeepDive 的 Phase 1（单 Agent 执行）与 Phase 2（DAG 编排、并发控制、Token 预算及 Agent 池）进行功能性测试与验证。

---

## 一、当前阶段测试范围说明

目前系统已完成以下阶段的核心逻辑开发，本次测试指南仅针对这些组件：
*   **Phase 1**：Skill Registry 注册表、Skill Router 路由、Agent Executor 执行流、LiteLLM 模型适配、Trace 轨迹记录。
*   **Phase 2**：DAGEngine 调度引擎、TaskSplitter 任务拆解、FileLockManager 分布式文件锁、Priority 优先级分配、TokenBudgetManager 预算追踪、AgentPool 协程池与 MessageBus 通信。

*注：由于 Phase 3 的 Web Dashboard 和 Temporal 审批流、Phase 4 的评估诊断飞轮尚未开发，测试需要通过命令行 CLI 或 FastAPI OpenAPI 页面进行。*

---

## 二、测试前置条件与环境准备

在开始测试前，确保以下基础设施处于正常运行状态：
1.  **基础设施启动**：
    ```bash
    cd docker
    docker compose up -d
    ```
2.  **API 服务运行**：
    ```bash
    source .venv/bin/activate
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000
    ```
3.  **验证联通性**：
    使用 CLI 检查 API 与中间件服务状态：
    ```bash
    python3 src/cli/main.py status
    ```

---

## 三、测试用例与步骤 (Phase 1 & Phase 2)

### 3.1 测试用例 1：单 Agent 任务执行 (Phase 1)
*   **目的**：验证任务能否正确路由到最匹配的 Skill，并驱动 Agent 使用文件工具执行任务且生成轨迹。
*   **命令行测试步骤**：
    ```bash
    python3 src/cli/main.py run "分析 src/config.py 文件的基本圈复杂度"
    ```
*   **预期输出**：
    *   显示任务提交中。
    *   输出中应包含匹配使用的 Skill（例如 `code-analysis-v1`）。
    *   显示 Agent 的分析结果 JSON（包括复杂度详情）。
    *   底部打印 Trace ID、消耗的 Tokens 等统计。

### 3.2 测试用例 2：复杂任务 DAG 拆解与并行调度 (Phase 2A)
*   **目的**：验证 LLM 是否能将复杂文本任务拆分为多节点的 DAG，并且 DAG 引擎能并发执行无依赖节点。
*   **命令行测试步骤**：
    1.  **自动拆解任务**：
        ```bash
        python3 src/cli/main.py dag split "分析 src/config.py 文件的代码规范与复杂度，并编写一份质量报告"
        ```
        *记下输出的 `dag-xxxxxx` ID*
    2.  **执行整个 DAG**：
        ```bash
        python3 src/cli/main.py dag execute <dag_id>
        ```
    3.  **监控执行流状态**：
        ```bash
        python3 src/cli/main.py dag status <dag_id>
        ```
*   **预期输出**：
    *   `split` 成功生成带有前置依赖（`dependencies`）的节点表格（如 `step-1` 依赖无，`step-2` 依赖 `step-1`）。
    *   `status` 表格中可以查看到各节点的执行颜色变化（`green` 表示成功，`yellow` 表示运行中，`red` 表示失败）。
    *   无依赖节点能够异步并行运行。

### 3.3 测试用例 3：分布式文件锁与抢占 (Phase 2B)
*   **目的**：验证当多个 Agent 写入同一文件时，分布式锁是否能正确排队，以及高优先级 Agent 是否能抢占低优先级锁。
*   **测试方法**：
    运行内置单元与并发测试脚本：
    ```bash
    python3 -m unittest tests/test_concurrency.py
    # 或运行临时验证脚本
    python3 tests/integration/test_lock_concurrency.py
    ```
*   **预期输出**：
    *   Agent A（优先级 40）获得锁。
    *   Agent B（优先级 50）请求锁被拒绝并排队（Queue Position: 1）。
    *   Agent C（优先级 80）请求锁成功，因为优先级差超过 30 触发**强力抢占**。
    *   Agent C 释放后，锁自动**晋升**给 Agent B。

### 3.4 测试用例 4：Token 预算管理与模型路由 (Phase 2C)
*   **目的**：验证预算控制系统是否根据任务复杂度正确分流模型，并限制单次消耗。
*   **测试方法**：
    ```bash
    # 1. 运行单次分析任务（应当路由至 qwen3-coder:480b-cloud 等专业中端模型）
    python3 src/cli/main.py run "分析 src/config.py"
    # 2. 检查预算变化和余额
    python3 src/cli/main.py budget
    ```
*   **预期输出**：
    *   CLI 预算看板展示月度限额（$500.00）、已使用金额（Total Spent）和余额（Remaining Budget）相应更新。

---

## 四、未来全功能整体测试规划

当 Phase 3 与 Phase 4 编码完成后，需执行**端到端整体测试 (E2E Integration Test)**：

```mermaid
graph TD
    UI[Web UI Dashboard] -->|1. 触发任务| WebAPI[FastAPI Gateway]
    WebAPI -->|2. Temporal 工作流启动| Workflow[Temporal Workflow Engine]
    Workflow -->|3. 并行并发调度| DAG[DAG Scheduler]
    DAG -->|4. 检查预算和安全策略| Guard[OPA Guardrails]
    Guard -->|5. 锁定要修改的文件| Lock[Redis File Lock]
    DAG -->|6. 分配空闲容器| Pool[Agent Sandbox Pool]
    Pool -->|7. 启动隔离容器| Docker[Docker / gVisor Sandbox]
    Docker -->|8. 模型路由调用| LLM[Ollama / Cloud LLM]
    Docker -->|9. 执行完毕释放锁/容器| Pool
    Workflow -->|10. 人工审核挂起 (橙色)| Approval[Dashboard Approval UI]
    Workflow -->|11. 收集轨迹与评测| Eval[Multi-Judge Evaluator]
```

### 整体测试步骤设计
1.  **用户人机审批流测试**：
    - 提交删除关键文件或修改高风险模块任务。
    - 验证任务状态停留在 `orange`（Pending Approval）。
    - 在 Web UI 或 Temporal 控制台点击 "Approved" 后，工作流恢复执行。
2.  **物理沙箱网络隔离测试**：
    - Agent 尝试在沙箱内发起 `curl http://external-website.com`。
    - 验证网络连接被 iptables 或 Docker bridge 彻底拦截，而访问本地 Ollama API 正常。
3.  **飞轮自演进闭环测试**：
    - 执行失败任务（如 Agent 代码生成有语法错误）。
    - 验证 Evaluation 自动收集 trace 报告并启动诊断（Diagnostics），自动修补（Auto-patch）Skill 元数据中的 Prompt 规则。
