# 贡献指南 (Contributing to AgentDeepDive)

中文 | [English](CONTRIBUTING.md)

感谢您对贡献 AgentDeepDive 的关注与支持！作为一个面向大型超级工程的企业级多智能体编排平台，我们欢迎任何形式的贡献——无论是改进文档、修复缺陷，还是扩展核心引擎功能与加固安全沙箱。

参与本项目的贡献即代表您同意遵守我们的行为准则并遵循以下指南。

---

## 1. 开发流程与环境搭建

在开始为 AgentDeepDive 开发新功能之前：

### 步骤 1.1：克隆并配置开发环境
克隆代码库并初始化 Python 虚拟环境（需要 Python 3.11+）：
```bash
git clone <repository_url> agentdeepdive
cd agentdeepdive
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 步骤 1.2：启动本地基础设施服务
若要开发涉及容器隔离或多租户的特性，请拉起 PostgreSQL, Redis, Milvus 及 Jaeger 链路追踪服务：
```bash
agentdeep infra up
agentdeep db upgrade head
```
若要进行轻量化、零容器的快速本地离线调试，直接在运行任务时附加 `-l` 或 `--lightweight` 参数即可：
```bash
agentdeep run "您的测试提示词" -l
```

---

## 2. 编码规范与测试指南

我们保持着严苛的代码质量与安全校验底线：

### 2.1 代码风格与静态检查
我们使用 `ruff` 工具进行代码格式化与规范化校验。提交前请确保通过检查：
```bash
# 格式化检查
ruff format --check src/ tests/
# 静态代码扫描
ruff check src/ tests/
```

### 2.2 运行测试套件
在提交任何 Pull Request 之前，请务必在本地运行单元与集成测试，并确保全部通过：
```bash
pytest tests/unit/
```
若修改了涉及沙箱隔离和高危操作的功能，请运行集成测试：
```bash
pytest tests/integration/
```

---

## 3. 自定义技能与 OPA 策略提交规范

如果您希望为平台贡献新的技能或治理能力：

### 3.1 提交新的 Agent 技能 (Skills)
* 技能配置文件必须存放在 `skills/<skill_name>/skill.yaml`。
* 必须定义唯一的 `skill_id`（例如 `my-custom-skill-v1`）。
* 在 `required_tools` 中仅声明完成该任务所需的最小工具权限集，严禁越权声明。
* 配合安全评估，指定合理的风险等级 `risk_level`（`low`、`medium` 或 `high`）。

### 3.2 更新 OPA 策略规则
* 平台的核心治理规则定义在 `src/core/governance/policies/guardrails.rego` 中。
* 如果您引入了新的系统级工具，请在 Rego 策略中同步补充其对应的风险划分逻辑。
* 规则编写方法及 Input 数据契约请参考 [OPA 安全合规微隔离配置手册](docs/guides/security_opa_manual.md)。

---

## 4. Git 分支管理与 Commit 提交规范

我们严格遵守 **Angular Commit 提交规范**，以保障版本日志的自演进生成及 Git 树的整洁：

### 4.1 Commit 提交格式
每次 commit 的说明必须由类型（Type）和简短摘要（Subject）组成：
```text
<type>: <修改内容的简短摘要说明>
```

### 4.2 允许的提交类型 (Allowed Types)
* `feat`：新增功能或能力模块。
* `fix`：修复 Bug。
* `docs`：仅修改了文档（如 README, INSTALL 或各种操作手册）。
* `test`：增加或修正测试用例。
* `refactor`：代码重构（既不属于新增功能也不属于 Bug 修复的变更）。
* `security`：涉及安全加固、OPA 规则更新或沙箱逃逸防御的修改。
* `style`：代码格式化调整（不影响代码逻辑的变动，如空格、分号等）。

*示例 commit 消息*：`feat: integrate Telegram bot channel for L3 HITL approvals`

---

## 5. Pull Request 提交清单 (PR Checklist)

当您提交 Pull Request (PR) 时，请确认以下事项：
1. **创建功能分支**：基于 `main` 分支拉出开发分支（例如 `feature/hitl-slack-integration`）。
2. **补充测试**：为所有新增加的特性或 Bug 修复编写对应的测试用例。
3. **更新文档**：如果修改了技能定义、环境变量或命令行参数，请同步更新对应文档。
4. 确保本地所有静态检查（`ruff`）和测试（`pytest`）均无报错通过。
5. 提交 PR 时，请在描述中详细阐述实现逻辑，并关联对应的 GitHub Issue。
