# AgentDeepDive 使用与配置指南 (User Guide)

AgentDeepDive 是一个支持多模型智能分流、多 Agent 并行编排（DAG）和自演进闭环的系统。相比于传统的单 Agent 聊天命令行（如 `claude code cli`），它的使用方式更接近一个 **“中枢控制命令行”**。

---

## 1. 核心差异：AgentDeepDive vs Claude Code CLI

| 维度 | Claude Code CLI / 普通 Agent | AgentDeepDive |
| :--- | :--- | :--- |
| **模型数量** | 单一模型（如 Claude 3.5 Sonnet） | **多模型**（本地免费 Qwen + 云端代码大师 + 云端推理 DeepSeek） |
| **执行模式** | 单任务线性交互（问答/终端命令执行） | **DAG 并行任务链**（自动拆解任务，多 Agent 并行处理） |
| **安全管控** | 人工在命令行每次确认命令 | **Guardrails 引擎级管控**（L0-L4 拦截，橙色状态挂起，集中审批） |
| **费用控制** | 个人 Token 实时扣费，无总量上限保护 | **Token 预算管理器**（项目、任务、步骤三级额度，自动降级路由） |

---

## 2. 快速安装与配置

### 第一步：克隆并配置虚拟环境
1. 进入项目根目录：
   ```bash
   cd /path/to/AgentDeepDive
   ```
2. 安装依赖并激活环境（使用 Poetry）：
   ```bash
   poetry install
   source .venv/bin/activate
   ```

### 第二步：配置环境变量 (.env)
由于系统支持多模型分流，你需要在项目根目录的 `.env` 文件中配置本地及云端模型参数：

```ini
# 1. 基础服务配置
AGENTDEEP_APP_NAME="AgentDeepDive"
AGENTDEEP_LOG_LEVEL="INFO"

# 2. 数据库与 Redis 缓存配置 (分布式锁、审批信号总线)
AGENTDEEP_POSTGRES_HOST="localhost"
AGENTDEEP_POSTGRES_PORT=5432
AGENTDEEP_POSTGRES_DB="agentdeep"
AGENTDEEP_POSTGRES_USER="agentdeep"
AGENTDEEP_POSTGRES_PASSWORD="agentdeep_dev_2026"

AGENTDEEP_REDIS_HOST="localhost"
AGENTDEEP_REDIS_PORT=6379

# 3. 三级 Ollama / 云端大模型多参数路由配置
# 本地轻量化模型 (用于简单格式化与文档编写 - 0费率)
AGENTDEEP_LOCAL_MODEL="ollama/qwen3.5:2b"

# 云端中端模型 (用于代码生成与分析 - 默认模型)
AGENTDEEP_DEFAULT_MODEL="ollama/qwen3-coder:480b-cloud"

# 云端顶尖推理模型 (用于深度重构、Bug 修复与自演进优化 - 降级/高阶模型)
AGENTDEEP_FALLBACK_MODEL="ollama/deepseek-v3.1:671b-cloud"

# LLM Gateway 授权 Key (若使用 Ollama 本地 API 则可不配，使用云端时配置)
AGENTDEEP_LITELLM_API_KEY="your-api-key-here"
```

---

## 3. 启动后台引擎 (FastAPI Server)

AgentDeepDive 的命令行（CLI）是通过 API 接口同核心引擎进行通讯的，因此在使用 CLI 之前，必须保证后台基础设施处于拉起状态：

1. **拉起 Docker 容器**（PostgreSQL + Redis + Milvus 等）：
   ```bash
   docker-compose -f docker/docker-compose.yml up -d
   ```
2. **启动 FastAPI API 服务**：
   ```bash
   uvicorn src.api.main:app --host 0.0.0.0 --port 8000
   ```

---

## 4. CLI 命令行使用说明

当上述后台启动后，你可以在激活的虚拟环境中直接使用 `agentdeep` 命令行工具。以下为高频核心指令：

### 4.1 系统就绪度与状态查询
检查本地数据库、Redis 锁以及 API 服务器之间的就绪状态：
```bash
python3 src/cli/main.py status
```
*(系统正常时会输出带有 ✅ 标识的精美表格。)*

### 4.2 管理并查看 Skill (专家技能卡)
1. **列出所有已注册的技能**：
   ```bash
   python3 src/cli/main.py skill list
   ```
2. **注册（安装）新技能**：
   * 支持通过本地 YAML 配置文件进行安装：
     ```bash
     python3 src/cli/main.py skill register --file skills/code_generator/skill.yaml
     ```
   * 支持通过网络 URL（如官方 skills.sh 节点或 GitHub 上的 Raw 链接）进行安装：
     ```bash
     python3 src/cli/main.py skill register --url https://skills.sh/packages/react-generator.yaml
     ```
3. **查看指定技能的详细配置**：
   ```bash
   python3 src/cli/main.py skill show code-generator-v1
   ```
4. **注销（删除）指定技能**（软删除，将其置为非活跃状态）：
   ```bash
   python3 src/cli/main.py skill delete code-generator-v1
   ```

### 4.3 运行单步 Agent 任务
让系统评估你的任务，自动匹配最适合的 Skill，并根据复杂度自动路由到本地 Qwen 或云端大模型：
```bash
python3 src/cli/main.py run "分析 src/core/agent/executor.py 文件的圈复杂度"
```

### 4.4 运行并行编排任务 (DAG)
对于复杂的链式任务，你可以提供一个包含多个节点和依赖关系的 YAML 文件：
```bash
python3 src/cli/main.py dag execute --file docs/examples/refactor_task.yaml
```
你可以使用以下指令查看这个 DAG 的所有节点在执行期间的状态与颜色变化：
```bash
python3 src/cli/main.py dag status <dag_id>
```

### 4.5 管理人工审批 (Governance & Approvals)
当 Agent 试图运行敏感指令（如修改系统配置 `src/config.py`）时，CLI 运行端会被安全挂起，进入橙色等待期。你可以打开另一个终端进行审批：

1. **查看挂起中的审批申请**：
   ```bash
   python3 src/cli/main.py approval list
   ```
2. **批准审批**（解除阻断，Agent 继续运行）：
   ```bash
   python3 src/cli/main.py approval approve <approval_id>
   ```
3. **驳回审批**（Agent 会抛出安全策略异常，安全终止）：
   ```bash
   python3 src/cli/main.py approval reject <approval_id>
   ```

4. **移动端 Telegram 审批与安全授权集成 (Phase 5)**：
   为了防止外部未授权端点扫描 API 接口或恶意触发 Webhook 模拟审批，系统集成了全套**双端配对授权与签名校验**：
   
   在 `.env` 文件中配置安全参数：
   ```env
   # 1. PC 网页端与移动端 API 配对 Token (Bearer 或 X-API-Key 头校验)
   AGENTDEEP_API_KEY="您的强配对密钥"

   # 2. Telegram Webhook 防篡改密钥
   AGENTDEEP_TELEGRAM_WEBHOOK_SECRET="您的Webhook签名密钥"
   
   # 3. Telegram 消息推送目标配置
   AGENTDEEP_TELEGRAM_BOT_TOKEN="您的Bot_Token"
   AGENTDEEP_TELEGRAM_CHAT_ID="您的Chat_或User_ID"
   ```
   * **PC/移动端配对授权 (Bearer Auth)**：启用 `AGENTDEEP_API_KEY` 后，所有 PC 看板、CLI 客户端或移动端连接 API 时，必须携带 `Authorization: Bearer <Key>` 或 `X-API-Key: <Key>` 标头，否则一律返回 `401 Unauthorized` 拒绝访问。
   * **Webhook 安全签名过滤**：在 Telegram Webhook 接口上，系统会对请求携带的 `X-Telegram-Bot-Api-Secret-Token` 头与您配置的 `telegram_webhook_secret` 进行强匹配；同时自动校验 callback_query 的来源 Chat ID 是否与 `telegram_chat_id` 严格一致，彻底杜绝外网越权和钓鱼点击。
   * **推送机制**：一旦触发 L3 挂起，系统会发送带行内键盘的 HTML 卡片消息，点击即可完成一键远程解密/阻断。

### 4.6 触发自演进评估 (Evolution Flywheel)
在任务结束后，利用双 Judge 对 Agent 输出进行评测与自动诊断优化：
```bash
python3 src/cli/main.py evolution evaluate \
  --task-id "task-101" \
  --task-desc "编写支付模块接口规范" \
  --skill-id "doc-writer-v1" \
  --output "这是输出内容..."
```
*(如果 Consensus Judge 评分偏低，此命令会自动调用优选模型修改对应的 YAML 技能提示词文件，完成自修复。)*

### 4.7 查看活跃 Agent 分配与负载 (Agent Pool Load)
如果您想查看当前系统中有哪些 Agent 正在工作，以及它们分别被分配在处理哪个具体的节点任务，可以运行：
```bash
python3 src/cli/main.py pool
```
*(系统会输出并发池当前的负载百分比，并以表格形式显示所有处于“工作状态”的 Agent ID 与 Task ID 映射。)*

### 4.8 灵活调整与临时切换 LLM 模型 (Model Configuration & Overrides)
为了支持类似 OpenClaw / Hermes 的灵活性，系统提供了初始化配置和按需临时切换模型的能力：

1. **持久化配置模型**：
   可以通过命令行直接查询或永久修改 `.env` 配置文件中的模型绑定：
   ```bash
   # 查看当前生效的模型变量表
   python3 src/cli/main.py config show

   # 永久设置本地模型 (local_model)
   python3 src/cli/main.py config set local_model ollama/qwen3.5:2b
   ```
   *(使用 `config set` 成功保存后，重启 API 服务即可读取最新的模型设置。)*

2. **单任务执行临时切换**：
   在使用 `run` 命令提交单步任务时，使用 `--model` 选项临时强制覆盖系统默认模型：
   ```bash
   python3 src/cli/main.py run "分析代码圈复杂度" --model ollama/deepseek-v3.1:671b-cloud
   ```

3. **DAG 编排全局临时切换**：
   在使用 `dag execute` 命令拉起流水线时，使用 `--model` (或 `-m`) 选项使该 DAG 的所有节点统一使用临时指定的模型执行：
   ```bash
   python3 src/cli/main.py dag execute --file docs/examples/snake_game_dag.yaml --model ollama/deepseek-v3.1:671b-cloud
   ```

### 4.9 自愈式依赖与环境管理 (Self-Healing Runtime Dependencies)
在 Agent 自动执行脚本、编译或运行单元测试时，经常会因为宿主或沙箱环境中缺少特定的依赖库（如 Python 模块或 Node.js 包）而报错中断。

为了彻底消除这一阻断，系统在 `shell_exec` 工具中集成了**自动依赖自愈机制**：
*   **依赖缺失拦截**：当执行返回非零状态码，且标准错误（STDERR）中匹配到 Python 的 `ModuleNotFoundError` 或 Node.js 的 `Cannot find module` 时，系统将自动拦截报错。
*   **隔离热安装**：系统自动解析出缺失的包名，并安全调用当前项目虚拟环境下的 `pip`（或工作目录下的 `npm`）将依赖安装在隔离的环境中。
*   **自动重试**：安装成功后，系统无感知自动重新执行原指令，并把重试后的正确输出作为最终结果返回。
*   **测试用例**：可以运行 `/scratch/test_self_healing.py` 查看这一自愈过程。

### 4.10 安全容器沙箱隔离 (Secure Docker Sandbox Isolation)
在智能体执行代码修改、脚本运行或系统级命令时，为了防止潜在的代码注入、误删宿主机文件或破坏本地开发环境，系统在 `shell_exec` 工具中集成了**容器化沙箱隔离机制 (Phase 5)**：

1. **Docker 沙箱隔离**：当开启沙箱时，所有 shell 命令将自动被封装进一个独立的临时 Docker 容器中执行。当前工作目录（CWD）会被作为数据卷挂载至容器的 `/workspace` 中，命令执行完毕后，容器会被立即销毁 (`--rm`)，做到宿主机环境零污染。
2. **资源与网络限制 (5B.2)**：
   * 默认每个沙箱容器被限制最大 **512MB 内存** 与 **1.0 核 CPU** 资源，防止死循环或内存泄露压垮宿主机。
   * 严控容器出站流量，只允许访问信任的依赖源与 API 端点。
3. **沙箱内的自愈机制**：
   * 即使在隔离的沙箱内执行，自愈环境依然有效！
   * 当沙箱容器内的 Python 或 Node.js 执行抛出依赖缺失报错时，自愈器会自动在前置指令中动态注入依赖拉取指令（如 `pip install` 或 `npm install`），并在瞬时沙箱中重新运行成功。
4. **配置启用**：
   您可以在 `.env` 文件中配置以下参数以控制沙箱：
   ```env
   # 开启 Docker 隔离沙箱
   AGENTDEEP_DOCKER_SANDBOX_ENABLED=true
   # 指定执行的基础镜像
   AGENTDEEP_DOCKER_IMAGE="python:3.11-slim"
   ```
   5. **测试用例**：可以运行 `/scratch/test_docker_sandbox.py` 查看这一沙箱隔离与自愈过程。

### 4.11 Git 分支隔离与 GitHub PR 自动提交 (Git Isolation & GitHub PR Automation)
为了实现规范化的 Git 协同开发，防止 Agent 的自动修改操作直接污染主分支，系统提供了**隔离的分支修改与 Pull Request 自动提交工具集 (5G.1 & 5G.2)**：

1. **Git 隔离工作流**：
   Agent 在接单后，可以调用内置工具创建并切换到隔离的特性分支，在此分支上进行代码改写与测试：
   * `git_checkout_branch`：安全切换或创建新特性分支（例如 `feature/bugfix-123`）。
   * `git_commit`：自动跟踪修改、运行静态扫描，并在通过测试后自动以标准 conventional commits 规范提交更改（例如 `feat: Fix logic error in payment calculator`）。
   * `git_push`：安全推送到配置的远端 Git 源。
2. **GitHub Pull Request 自动提交**：
   在分支代码自愈测试通过并推送到远端后，Agent 可以调用 `github_create_pull_request` 自动在远端仓库为您的项目发起 Pull Request。
   * 支持通过 GitHub REST API 生成结构化的 PR，包含详细的修复过程日志、重构报告与影响范围分析，等待人类开发者进行 Code Review。
3. **配置启用**：
   您可以在 `.env` 文件中配置以下参数以启用远端 GitHub API 集成：
   ```env
   # GitHub 个人访问令牌（具有 repo 读写权限）
   AGENTDEEP_GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
   # 目标仓库，格式为 owner/repository
   AGENTDEEP_GITHUB_REPO="your-username/your-repository"
   ```
4. **测试用例**：可以运行 `/scratch/test_git_github.py` 验证完整的本地 Git 隔离分支、修改提交与 GitHub 接口适配逻辑。

### 4.12 本地 RAG 知识检索与情节记忆自愈 (Local RAG & Episodic Memory)
为了使 Agent 在分析与改写代码时不仅能遵循项目规范，还能从历史修复经验中“学习”，系统构建了**本地向量检索与情节记忆沉淀机制 (5A.1, 5A.2, 5E.1 & 5E.2)**：

1. **RAGManager 向量检索中心**：
   在 [src/core/memory/rag_manager.py](file:///path/to/AgentDeepDive/src/core/memory/rag_manager.py) 中，系统对接了高可用的 Milvus 向量数据库，并配备了轻量化的本地 `all-MiniLM-L6-v2` 嵌入模型（强制绑定 CPU 运行，杜绝显存 CUDA 版本不一致问题）。若 Milvus 暂不可达，系统将自动降级至轻量化的**本地内存余弦相似度检索**（松耦合设计）。
2. **全自动情节记忆沉淀 (Episodic Memory)**：
   在 Agent 成功执行完 `bug_fix` 或 `refactor` 任务后，系统会自动提取该次运行的 `{任务Prompt, 错误堆栈, 修复好的Patch}`，生成语义嵌入并存入 `agentdeep_episodic_memory` 向量表中。下次遇到相似错误时，Agent 可通过检索历史 Patch 实现零样本自愈。
3. **工程静态知识库索引 (Static RAG)**：
   运行静态索引脚本可扫描整个工作区内的 markdown 文档及 Python 源码文件，分块并导入 `agentdeep_knowledge_base` 表：
   ```bash
   python3 -m src.core.memory.indexer
   ```
4. **Agent 语义检索工具**：
   Agent 获权后，可在任务执行中调用内置工具 `query_knowledge_base` 来获取最相似的代码逻辑和业务说明：
   * `query_knowledge_base(query="DB transaction retry policy")`：返回最匹配的相关代码片段和文档说明。
5. **测试用例**：
   * 运行 `/scratch/test_rag.py` 验证静态 RAG 及相似度计算。
   * 运行 `/scratch/test_agent_memory.py` 验证 Agent 执行结束后的情节记忆自动保存。

---

## 5. Token 预算控制与 Agent 智能调优 (Token Budget & Optimization)

为了在生产环境中实现极致的高效能与低开销，AgentDeepDive 从底层构建了三级 Token 成本管理机制与 Agent 智能进化系统。

### 5.1 三级 Token 成本防御体系

系统在 [src/core/budget/manager.py](file:///path/to/AgentDeepDive/src/core/budget/manager.py) 中定义了三级限额防御，确保大模型调用成本始终在预算红线内：

1.  **L1 - 月度项目总额度红线 (Monthly Cap)**：
    *   在 `.env` 中通过 `monthly_budget_usd` 配置每月项目总额度（例如 `$50.00`）。
    *   一旦当月累计的 API 消费触及红线，系统将**自动切断云端付费模型**的路由，自动降级切换为本地免费模型（如 `qwen3.5:2b`）运行，从而绝不会产生超出预期的账单。
2.  **L2 - 任务级 Token 上限 (Task Budget Limit)**：
    *   根据不同的任务类型（如格式化、代码生成、Bug 修复）自动匹配模型等级，并对任务分配各自的 Token 上限（例如简单格式化限制 `4,000` tokens，Bug 修复限制 `20,000` tokens）。
    *   在剩余月度预算吃紧时，系统支持**降级路由**：若 Top-tier 模型额度不足，自动向下路由至 Mid-tier 模型，避免因超支直接抛出异常。
3.  **L3 - 步长级死循环拦截 (Per-Step Abort)**：
    *   为了防止大模型在复杂任务中因推理发散、复读机效应而陷入**无限死循环**导致巨额扣费，执行引擎 [AgentExecutor](file:///path/to/AgentDeepDive/src/core/agent/executor.py) 会在每次向 LLM 推理前进行实时 Token 累加校验。
    *   一旦单步总消耗（Input + Output）突破了该 Skill 的 `max_tokens` 额度，系统会**瞬间强行中断并抛出异常**，锁死计费泄漏。

### 5.2 查看实时 Token 预算账单

您可以通过 CLI 命令在终端实时查询当前项目的累计 Token 开销、美元消费和余额剩余情况：
```bash
python3 src/cli/main.py budget
```
*(系统会输出包含 L1 总额度、已用金额、剩余余额以及不同模型消费占比的精细报表。)*

### 5.3 Agent 智能与效率调优

1.  **自演进闭环 (Self-Evolution)**：
    系统通过多 Judge 盲审评测机制，将低分表现或测试失败的 Trace 输入 `DiagnosticsEngine`。自优化器会自动重写 Skill yaml（如 `skills/code_generator/skill.yaml`）中的 `system_prompt` 提示词模板并自动递增小版本号，使 Agent 具备自我反思和升级的能力。
2.  **动态上下文精简 (Context Pruning)**：
    在编排流转中，系统仅向下游 Agent 投喂上游产生的核心产物 `result.output`，剔除了开发 Trace 中的冗余过程，在输入端削减了近 80% 的无效 Token。
3.  **优先级抢占锁 (Preemption Locks)**：
    利用分布式锁，高优先级的修复任务可强制挂起低优先级任务的编辑锁，避免多个 Agent 产生逻辑覆盖冲突，减少因指令冲突造成的无意义大模型计算开销。

