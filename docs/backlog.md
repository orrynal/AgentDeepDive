# AgentDeepDive 待构建功能与优化积压 (Backlog & Future Backlog)

本文档整理了系统在后续开发中需要逐步实现的高级功能，包括可视化控制仓 WebUI 以及 Agent 实例池健康检查与心跳监控系统。

---

## 1. 核心待构建功能一：工业级中控台 (WebUI Cockpit)

### 1.1 页面与交互设计
*   **定位**：融合前台任务提交与后台微服务治理能力的毛玻璃暗黑科技感中控台。
*   **DAG 并行编排画布**：使用 **React Flow**，实时通过呼吸灯和线条流动动画显示节点的 5 色状态机流转。
*   **CoT 思维链监视器**：支持右侧打字机动效呈现任何节点的实时步骤轨迹（Thought -> Tool -> Observation）。
*   **交互式审批拦截面板**：触发 L3 安全警告时，前台置顶拦截，支持管理员修改参数后放行或驳回。
*   **飞轮演进 diff 板块**：展示自演进优化历史和 Prompt 修改前后的红绿差异对比。

### 1.2 技术选型
*   **前端框架**：Next.js + React + TailwindCSS
*   **实时通信**：FastAPI WebSockets + Redis PubSub

---

## 2. 核心待构建功能二：Agent 心跳同步与健康监测守护 (Heartbeat Daemon)

### 2.1 设计背景
在分布式或多沙箱容器环境下，如果 Agent 容器因宿主机故障、死循环或网络隔离发生无响应，中枢控制需要能够秒级感知并重组队列，防范并发槽（concurrency slots）和文件锁被无限期占用。

### 2.2 具体架构设想
1.  **心跳上报机制 (Heartbeat Reporting)**：
    每个活跃的 Agent 实例在其执行线程/容器中，每隔固定周期（例如 3s）向 Redis 写入带生存时间（TTL = 8s）的心跳标识：
    `SETEX agentdeep:heartbeat:<agent_id> 8 <timestamp>`
2.  **健康哨兵协程 (Health Sentinel Daemon)**：
    在中枢的 `AgentPool` 模块中启动后台常驻协程，定期（如 5s）扫描活跃列表中的 Agent ID。
3.  **超时容灾逻辑**：
    如果判定某 Agent 的心跳时间超过设定的阈值：
    *   **销毁僵尸容器**：通过 Docker/gVisor 接口强行杀死对应的容器实例，避免资源泄漏。
    *   **清理死锁**：显式释放该 Agent 占用的全部 `FileLock`，避免下游节点被永久挂起。
    *   **状态标红与回滚**：将 DAG 对应的节点更新为 `RED` (Failed) 状态，并在消息总线广播事件。根据策略触发自动重试或归入诊断引擎。
