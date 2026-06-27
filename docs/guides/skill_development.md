# 智能体技能开发与 DSL 编排指南 (Skill & DSL Developer Guide)

本指南旨在指导开发者如何在 AgentDeepDive 平台中创建自定义**智能体技能 (Skills)** 并通过**有向无环图 (DAG) DSL 编排**来构建复杂的自动化超级工程流水线。

---

## 一、 智能体技能 (Skills) 编写规范

技能是 Agent 执行特定领域任务的最小认知与工具单元。每个技能独立声明在 `skills/<skill_name>/skill.yaml` 文件中，由技能解析器动态加载并注册到全局技能库。

### 1. `skill.yaml` 字段详解

下面是一个典型的 `skill.yaml` 文件定义：

```yaml
skill_id: "code-generator-v1"                         # 全局唯一技能标识符
name: "代码生成与开发专家"                                # 技能显示名称
version: "1.0.0"                                      # 技能版本号
description: "根据需求设计生成高质量的 HTML, CSS, JS 源代码并写入指定文件" # 技能功能描述
tags:                                                 # 分类标签，用于语义检索
  - "code"
  - "development"
trigger_patterns:                                     # 触发正则/关键词列表（用于动态路由器激活）
  - "编写代码"
  - "生成代码"
  - "实现游戏"
context_budget: 16000                                 # 最大 Token 上下文预算限制
required_tools:                                       # 声明该技能允许调用的底层系统工具
  - "file_write"
  - "file_read"
  - "directory_list"
risk_level: "medium"                                  # 风险等级 (low / medium / high)，与 OPA 隔离策略挂钩
approval_required: true                               # 是否启用人工介入审批 (HITL L3 闸口)
estimated_tokens: 16000                               # 预计单次运行的最大 Token 消耗
estimated_duration_sec: 120                           # 预计单次运行执行时长（秒）
system_prompt: |                                      # 注入底层模型的系统提示词
  你是一个顶尖的前端与全栈开发专家。根据提供的需求和设计文档，生成高质量、结构良好且可以直接运行的源代码。
  
  核心执行规则:
  1. 必须使用 `file_write` 工具将生成的代码写入指定路径。
  2. 使用优雅的变量命名和清晰的注释。
  3. 逻辑完整，不允许出现 "TODO" 或未实现的占位代码。
```

### 2. 核心字段设计原则

* **触发模式 (`trigger_patterns`)**：当用户运行 `agentdeep run "目标任务"` 时，意图分析器将对输入进行关键词与语义空间比对。合理编写 `trigger_patterns` 可以确保意图被准确路由。
* **工具声明 (`required_tools`)**：Agent 只能调用在其技能配置中显式声明的工具。如果在 `system_prompt` 中要求 Agent 写文件，但 `required_tools` 中未包含 `file_write`，执行时会抛出未授权错误。
* **安全级别 (`risk_level` & `approval_required`)**：
  * `low`：常规读取或静态分析，直接运行，无需人工参与。
  * `medium`：涉及文件修改或只读命令执行。若 `approval_required: true`，平台会在修改前推送确认通知。
  * `high`：涉及系统 shell 执行等高危操作。必须通过 OPA 安全合规校验，并且必须在 Slack/Discord 等审批通道完成 L3 级人工授权才能继续执行。

---

## 二、 DAG 编排语法与 DSL 指南

对于多阶段、高确定性要求的超级工程（如：从架构设计、核心编码，到测试生成、安全合规审计的完整全生命周期），单步 Agent 会因为上下文过载而断裂。平台采用基于 YAML 描述的 **有向无环图 (DAG) 编排** 将长周期任务进行解耦和并行调度。

### 1. DAG DSL 文件结构实例

下面是一个经典的贪吃蛇构建流程 YAML 文件定义（通常存放在 `docs/examples/` 或通过命令行动态传入）：

```yaml
dag_id: "snake-builder-dag"
name: "贪吃蛇游戏构建流水线"
description: "使用多 Agent 并行编排完成贪吃蛇游戏的设计、编码与测试"
routing_tier: "medium"
nodes:
  - node_id: "design"
    name: "游戏架构设计"
    skill_id: "doc-writer-v1"
    description: >
      设计一个网页单文件 (Single-page HTML5) 贪吃蛇游戏的具体规则和功能架构。
      包含：10x10 格子、Canvas 渲染、分数面板、控制按键、以及现代暗黑科技感配色方案。
      生成设计规范并使用 file_write 写入到 examples/snake_game/design.md 中。

  - node_id: "code"
    name: "核心功能编码"
    skill_id: "code-generator-v1"
    dependencies: 
      - "design"
    description: >
      根据 examples/snake_game/design.md 中的设计规范，编写完整的 index.html 单文件游戏。
      将 HTML, CSS, JS 合并入此文件。使用 file_write 工具写入到 examples/snake_game/index.html 中。

  - node_id: "test"
    name: "自动验证与运行测试"
    skill_id: "test-generator-v1"
    dependencies: 
      - "code"
    description: >
      分析 examples/snake_game/index.html 的内容，编写一个验证脚本 verify.py，
      检查 HTML 标签闭合与 Canvas 节点。使用 shell_exec 执行该 python 脚本以确保基础语法完全正确。
```

### 2. DAG 核心机制深度解析

#### A. 拓扑与并行调度
DAG 调度器在加载定义后，会首先解析节点间的依赖数组 `dependencies`。
* **并行执行**：若有多个节点不依赖任何前置节点（或其依赖已执行完毕且状态为 `green`），调度器将使用多线程或分布式沙箱**并行调度**这些节点。
* **拓扑排序**：计算出所有节点的可行路径，避免循环依赖，确保执行链路的确定性。

#### B. 数据传递与映射关系 (`input_mapping`)
在高级应用场景中，下游节点可以直接读取并消费上游节点的执行结果。可以通过配置节点的 `input_mapping` 字段实现：

```yaml
  - node_id: "code-review"
    name: "代码审计"
    skill_id: "code-reviewer-v1"
    dependencies:
      - "code"
    input_mapping:
      source_code: "code.result.file_content"  # 将 node_id 为 'code' 的执行结果中的 file_content 字段作为输入注入
    description: >
      对传入的 source_code 进行代码质量与安全漏洞审计。
```
`dag_engine.py` 会在执行该节点前，解析 `input_mapping` 中的表达式，在运行时将关联数据填入节点上下文，实现精确的跨节点参数传递。

#### C. 状态机与颜色编码定义
调度器使用状态颜色编码来管理每一个节点的生命周期，颜色状态变化由底层状态机严格管控：

* **灰色 (GRAY)**：未开始。节点尚处于初始等待状态。
* **蓝色 (BLUE)**：已排队。节点的前置依赖已全部完成，已推入调度队列等待资源。
* **黄色 (YELLOW)**：执行中。沙箱已经拉起，大模型正在驱动工具执行当前节点任务。
* **绿色 (GREEN)**：已完成。当前节点任务已成功执行，并且输出结果已保存。
* **橙色 (ORANGE)**：需人工审批。当前节点触发了高风险工具或高安全门槛，正在挂起等待 L3 人工审批。
* **红色 (RED)**：执行失败。节点执行过程中发生未捕获异常、测试门禁未通过或被 OPA 规则硬性拦截。
* **挂起 (SUSPENDED)**：手动或异常挂起。支持通过大屏或 CLI 对挂起节点进行恢复（Restore）与重试。

---

## 三、 开发与调试实践

### 1. 动态加载与自诊断

要将自定义技能或 DAG 投入测试，可遵循以下流程：

1. **技能注册**：在 `skills/` 下新建您的技能目录（如 `skills/my_skill/skill.yaml`）。
2. **连接诊断**：运行以下自诊断命令，确认本地环境与 API 接口是否正常畅通：
   ```bash
   agentdeep doctor
   ```
3. **测试技能逻辑**：您可以通过单步命令触发此技能来测试意图识别与工具执行情况：
   ```bash
   agentdeep run "请帮我执行 my_skill 相关的测试任务"
   ```

### 2. 提交并运行 DAG 流水线

若要提交您编写的 DAG 流水线文件（假设命名为 `my_pipeline.yaml`），请使用 CLI 编排工具执行：

```bash
# 执行指定的 YAML 编排流水线，默认使用标准容器模式
agentdeep dag execute -f my_pipeline.yaml

# 运行在零容器轻量模式下（适合离线快速调试）
agentdeep dag execute -f my_pipeline.yaml -l
```

### 3. 可视化监控与断点调试

1. 启动 Cockpit 大屏服务：
   ```bash
   cd dashboard && npm run dev
   ```
2. 浏览器打开 `http://localhost:5173`。
3. 在大屏中，您可以看到刚刚提交的 `snake-builder-dag` 的节点流动拓扑图。
4. **故障恢复调试**：
   * 如果 `code` 节点在执行时变成**红色 (RED)**（例如因为 API Key 瞬时超限或某工具报错），您可以点击该节点查看 Telemetry 遥测面板中的详细 Trace 日志。
   * 修复底层问题（或修改了中间代码）后，无需重新运行整个 DAG。您可以在大屏上点击 **"Restore Task"**，选择重试或跳过该节点，DAG 引擎会无缝恢复执行流。
