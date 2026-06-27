# AgentDeepDive 专属待办事项与未来技术演进规划 (ToDo & Future Roadmap)

> **专注范围**：仅针对 `AgentDeepDive` 项目（多智能体协同编排与治理平台）。
> **当前状态**：核心框架（Phase 0 - Phase 5）以及 P2-A/P2-B 性能优化已经全部完成并测试通过。本规划梳理了已完成的功能及走向生产环境仍需在明天或下一步实施的未完成任务。

---

## 一、 已完成任务清单 (Accomplished Tasks)

### 1. Phase 2A -- 生命周期与一键状态诊断 (Lifespan & Diagnostics)
*   **统一优雅生命周期关闭**：在 `lifespan` 退出阶段，级联调用了定时器 `scheduler_manager.shutdown()`、连接池 `close_redis_connections()` 和 `close_db_connections()`，彻底消除后台孤立定时任务及连接泄露问题。
*   **一键状态健康诊断 API**：新增 `/health/diagnostics` 接口，自适应收集物理系统 CPU/内存资源并测试 DB 与 Redis 的网络延迟，秒级嗅探 Sentinel 哨兵及 Scheduler 状态。
*   **防跨测试用例污染机制**：在所有单元测试的 `try-finally` 中还原对全局单例的 Mock 与属性变更，确保单元测试结果的一致性。

### 2. Phase 2B -- 内存和异步协程级联取消 (Memory & Coroutine Cancellation)
*   **物理长连接优雅注销**：在 `rag_manager.py` 中实现了 `close()` 方法，安全注销 Milvus default 长连接池并清空 active collection 句柄，并在 lifespan shutdown 时级联调用。
*   **DAGEngine 级联防悬空取消**：升级了 `DAGEngine` 的 `execute` 及 `_execute_node` 异常捕获机制，能完全在捕获 `CancelledError` 和 `Exception` 时对其正在进行的 `running_tasks` 子协程进行递归 `.cancel()` 并优雅等待消亡，在 `finally` 中主动调用 `gc.collect()` 回收 RSS 物理内存，杜绝 CPython 悬空任务关闭警报及协程僵尸态。
*   **新增一键垃圾回收与物理内存释放 API**：在 `src/api/routes/health.py` 中新增 `POST /health/cleanup`，清除 RAG Collection 的 active 句柄并主动 GC 垃圾回收，计算回显清理前后的系统 VmRSS 实际内存释放值。
*   **新增单元测试保障**：创建了针对上述功能完全隔离且防污染的单元测试 `tests/unit/test_phase2b_memory_coroutines.py`，全量单元/集成测试顺利通过。
### 3. Phase 2C -- Security Hardening & Performance Optimizations (Security & Cache)
*   **SSRF Webhook Protection (A-10)**: Implemented host and DNS validation on callback URLs (blocking private and loopback networks) for all incoming webhooks to prevent server-side request forgery.
*   **RAG Manager Lazy Loading (P-1)**: Deferred Milvus connection and embedding model instantiation to first query execution, eliminating cold startup delays during app import.
*   **DAG Store LRU Memory Cache (P-2)**: Replaced recursive file parsing with a thread-safe `TenantDAGCache` wrapper enforcing a capacity limit (500 items) and LRU eviction, avoiding physical memory leaks during prolonged runtimes.
*   **WebSocket Strict Handshake Authentication (S-5)**: Enforced JWT and X-API-Key handshake verification inside WebSocket connection routing to completely shut down anonymous/unauthorized access to execution telemetry streams.
*   **Password Hashing Hardening (S-8)**: Configured and verified native PBKDF2 hashing utilizing OWASP-recommended 600,000 iterations for newly generated user passwords.
*   **Redis Security & TLS Encryption (S-9)**: Added fallbacks to read standard environment variables (`REDIS_PASSWORD`, `REDIS_SSL`) directly from `.env`, and configured optional SSL/TLS connection parameters (`redis_ssl_cert_reqs`) in client pool builders.
*   **LockManager Strategy Decoupling (C-2)**: Refactored locking infrastructure into strategy pattern with `LocalFileLockStrategy` and `RedisLockStrategy` subclasses to eliminate conditional execution clutter.
*   **Executor.py Modular Submodules (C-1)**: Splitted the massive `executor.py` into cohesive submodules (`trace.py`, `utils.py`, `main.py` under `executor_logic/`) while preserving the backward-compatible entry point, decoupling LLM integration, tracing, and logging helpers.
*   **Comprehensive Testing**: Added full unit tests (`test_ssrf.py`, `test_dag_cache.py`, `test_redis_ssl.py`, and strategy-switching lock manager tests) with all suites passing.

### 4. Phase 2D -- RAG 多租户 Fallback 隔离强化与提交期安全防线 (Multi-Tenant & Security Scan)
*   **多租户向量隔离与本地 Mock 稳固**：重构了 `RAGManager`，将集合名称及本地 `rag_storage.json` 数据均绑定至租户后缀（UUID 或 "default"）实现逻辑与物理隔离；修复了 Mock 客户端中 UUID 后缀正则误判问题，添加了 zero-argument 降级兼容，并通过代理属性 (`__getattribute__`) 对历史断言与旧有测试保持完全兼容，测试通过率恢复至 100%。
*   **第三道防线拦截机制**：新建了基于 Git commit 触发的 `security_scan.py` 敏感扫描脚本，针对 AWS key、GitHub PAT、私钥等核心 credential 进行正则和 Shannon 熵值检测；设计了 `.pre-commit-config.yaml` 配置文件与一键部署脚本 `setup_security_hooks.sh`，实现开发生命周期的敏感防泄漏强制拦截。

### 6. Phase 2F -- 审计日志防篡改与签名自愈恢复机制 (Cryptographic Audit Trail & Self-Healing)
*   **密码学防篡改哈希链**：在 `AuditLogger` 底层逻辑中引入基于 SHA-256 的密码学哈希链。每条审计日志包含 `previous_hash` 指向上一条记录，并在写入时自动通过 `entry.calculate_hash()` 闭环锁定，确保在数据库级别一旦有记录被物理修改或整条删除，均能秒级识别断裂节点。
*   **HMAC-SHA256 签名双端备份**：在写入数据库的同时，系统同步使用基于 JWT 安全密钥（`jwt_secret`）的 HMAC-SHA256 签名追加将记录备份至本地只写保护文件（`.memory/audit_backup/{tenant_id}.jsonl` 和关联的签名 `.sig` 文件），对本地备份物理篡改进行密码学级阻断。
*   **拓扑追踪完整性校验引擎**：实现了 `verify_audit_integrity` 完整性校验。通过基于 hash 指针拓扑排序算法还原链条关系，彻底解决了在并发写入时由于数据库微秒级时间戳碰撞导致的误判；一旦校验到篡改或条目缺失，立即自动通过 `dispatch_workflow_notification` 发布 `audit.tampered` 的最高安全警报。
*   **Fail-Closed 防御自愈恢复机制**：实现了 `recover_audit_from_backup` 一键自愈接口。在本地备份未受污染时一键覆盖数据库恢复；若检测到备份文件与 `.sig` 签名不匹配（表明本地备份已被黑客二次污染），遵循 Fail-Closed 安全策略强行拒绝恢复并触发 `audit.backup_corrupted` 紧急警报，提示必须人工排障。
*   **API 路由与 CLI 运维命令支持**：在 FastAPI 挂载了 `/verify` 和 `/recover` 安全审计接口（受多租户 OPA 拦截保护）；同时在 CLI 终端追加了 `agentdeep audit verify` 和 `agentdeep audit recover` 命令，附带 `--confirm` 参数以及高画质的交互式表格展示。
*   **100% 覆盖率单元测试**：编写了针对上述功能的单元测试 `tests/unit/test_audit_tamper_proofing.py`，测试在轻量模式 (SQLite) 下独立稳定运行且绿灯通过。

### 7. Phase 2G -- OPA 规则静默热重载体验优化 (OPA Silent Hot-Reload)
*   **API 工作区切换 OPA 热重载联动**：在后端的 `POST /workspaces/active`（切换工作区）和 `POST /workspaces`（创建工作区）路由中，新增了 OPA 策略热载联动。当工作空间切换或初始化成功时，后端自动且静默调用 `GuardrailEngine._upload_policy_to_opa` 对所有 Rego 安全策略进行重新上传、编译和部署，无需人工重启或额外配置。
*   **前端静默异步拉取机制**：重构了 `OpaPolicyDialog.tsx`。通过 `useEffect` 侦听全局 `activeWorkspace` 状态变更。在检测到工作区切换时，在后台以无感静默方式重新拉取后端对应的最新 OPA 策略文件内容并进行无缝替换，无需重新加载整个 Web 页面，避免破坏用户的编辑状态和交互体验。
*   **草稿冲突智能合并与提示**：如果检测到工作区已发生切换，且用户当前在 Dialog 中已经进行了手工规则编辑（`isDirty === true`），系统会保留用户的编辑状态，并主动弹出一个醒目的绿色 Toast 提示：`Workspace changed & rules reloaded. Kept your unsaved draft.` 以防止草稿被强制覆盖；若没有脏数据则直接静默载入最新规则并提示 `Workspace changed. OPA rules hot-reloaded successfully.`。
*   **高水准视觉徽章与微动画**：在 OPA Editor 界面上新增了带微淡入动画的 `⚡ OPA Hot-Reloaded` 高颜值渐变徽章提示，提升了整体工业级中控台的响应式科技感。
*   **集成与健壮性测试**：编写了专门的 `tests/unit/test_opa_hot_reload.py` 单元测试，完全覆盖了切换/创建工作区自动触发热重载的断言。同时，测试包含优雅降级逻辑：即在 OPA 服务宕机或网络连接抛出异常时，捕获异常并保障工作区切换接口依然 100% 正常响应。

### 8. Phase 2H -- 智能体角色分配与自演进飞轮升级 (Bidding & Multi-Judge Flywheel)
*   **招投标动态打分重构**：对 FIPA-ACL 契约网招投标算法进行了多维度高精度重构，引入角色专属技能匹配度加分、最大预算占用平滑率打分、任务风险等级与模型能力/成本契合度打分，以及非线性动态负载均衡平滑罚分。
*   **多法官安全否决**：升级了 `Evaluator` 多法官共识评估模型，引入了专门负责沙箱及多租户安全合规的 **Judge D (Security & Compliance Auditor)**，一旦判定安全分低于 4.0 时，直接触发 Veto Power 一票否决并强行拦截/记录为 success=False。
*   **Meta-consensus 仲裁**：在多法官（A, B, D）两两评分分差 $\ge 3.0$ 时，调用 Judge C 进行 Meta-consensus 仲裁。
*   **AB Telemetry 联动晋级**：打通了评估打分与 A/B 灰度测试，将多法官评估分数传回至 `ab_manager` Telemetry 中，并在 Promotion 判定中基于平均质量分（avg_score）与耗用 token 效率等构成多维条件矩阵决策，实现了闭环的自主演进与安全熔断。

### 9. Phase 2I -- Celery 异步队列分布式双轨混合调度器 (Distributed Hybrid Scheduler)
*   **控制与计算彻底解耦**：在标准分布式部署下，将后台耗时的 DAG 任务编排与 LLM 工具链自愈等动作，通过 Celery 队列完全物理分发给后台 Worker 独立运行，使得 FastAPI API 进程的 Event Loop 阻塞时间为 0；
*   **无感双轨优雅降级**：实现 100% 向下兼容。当检测到 `settings.system_mode == 'lightweight'` 时，自动且完全透明回退至 APScheduler 进程内本地协程直接运行，不强求 Redis 连通；
*   **CLI 命令行一键支持**：在 CLI 中集成了 `agentdeep infra worker` 运维命令，方便开发者直接在本地前台一键拉起 Celery 异步 Worker；
*   **100% 覆盖率保障单元测试**：编写了针对本地 fallback 与分布式 delay 两种路径的单元测试 `tests/unit/test_celery_scheduler.py`，全量测试顺利通过。

### 10. Phase 2J -- Kubernetes 部署测试与镜像体积优化 (K8s Deployment & Image Optimization)
*   **Docker 镜像 CPU PyTorch 深度瘦身**：在 `Dockerfile` 中加入了直接指向官方 CPU 源安装轻量级 `torch` 依赖的指令，使得原本近 10GB 庞大的 GPU CUDA 镜像体积瞬间缩减至原物理大小 of **1/3（降至约 3.2GB，传输大小仅 1GB 左右）**，从根本上解决本地 K8s VM 的 `DiskPressure` 隐患。
*   **双语 Kubernetes 实战与排坑部署指南**：在 `docs/deployment/` 下分别创建了中文版 `kubernetes_deployment_guide.md` 和地道的英文版 `kubernetes_deployment_guide.en.md` 实战指南，涵盖 Minikube、K3s、MicroK8s 的安装配置、镜像物理加载、`port-forward` 黄金通道设计以及包含 `ErrImagePull`、`ImagePullBackOff`、`ModuleNotFoundError` 在内的常见故障排除（Troubleshooting）。
*   **主 README 微服务容器架构双语对齐**：修改了主 `README.md` 与 `README.en.md`，加入了专有的“系统微服务架构与容器角色 (System Microservices & Containers)”章节，梳理并科普了 API、Worker、Beat、Redis、PostgreSQL、Jaeger 的底层设计协作角色。
*   **容器启动硬编码冲突修复**：解决了 K8s YAML 及生产 Docker Compose 清单中硬编码启动命令 `uvicorn src.main:app` 覆盖镜像 CMD 的冲突，将其全部修正为平台真实的 FastAPI 入口点 `src.api.main:app`，保障了容器一次性 Running 部署成功。

---

### 11. Phase 2K -- 沙箱安全防护与 CPU/内存/PIDs 资源限额 (Sandbox Security Hardening & Resource Limits)
*   **Docker 安全策略与 Fork 炸弹拦截**：解除了 Docker 执行容器内存 `512m` 与 CPU `1.0` 的写死状态，重构至全局 settings 变量进行动态绑定；同时新增并默认开启了 `docker_pids_limit`（`--pids-limit=100`），在系统级别拦截 Fork 炸弹等 DoS 攻击行为，配合 `no-new-privileges` 提权安全拦截实现内核级的防逃逸安全防护。
*   **K8s 容器限制参数动态对接**：将 `SandboxRuntimeManager._execute_k8s` 中原硬编码的 K8s Pod 资源 limits / requests 重构为绑定全局 `settings.k8s_cpu_limit`, `settings.k8s_memory_limit` 等，大幅提高了云原生沙箱在多租户环境下的可用性与韧性。

### 12. Phase 2L -- Kubernetes 分布式高可用共享卷挂载 (K8s PVC Shared Storage Integration)
*   **分布式共享卷声明与 ConfigMap 联动**：在 `k8s/agentdeep-k8s.yaml` 资源清单中声明了模式为 `ReadWriteMany` (RWX) 的高可用 PersistentVolumeClaim (`agentdeep-workspace-pvc`)，并利用 ConfigMap 中的 `AGENTDEEP_K8S_VOLUME_CLAIM_NAME` 变量实现了与 API、Worker 以及动态生成的沙箱 Sandbox 隔离 Pod 的全局共享卷绑定。
*   **多节点漂移容灾与双语部署教程升级**：在 API 和 Worker 的 Deployment 清单中正式挂载了 PVC 至 `/workspace`，保障在容器因故障漂移、水平扩展或重建时，各 Agent 间的工作区文件能实时对齐，同时保护了本地情节记忆与安全审计日志的安全性；并在中英双语部署指南中追加了细致的 PVC 挂载参数说明和常见存储控制器多路挂载冲突排错（Scenario 5）。

### 13. Phase 2N -- PVC 并发自愈压力测试与 Celery 任务性能监测 (PVC Concurrency & Celery Monitoring)
*   **PVC 并发压力测试**：设计并实现了集成压力测试 `test_pvc_concurrency_self_healing.py`，模拟 10 个 Agent 进程对 PVC 分布式共享存储空间中的同一代码文件进行高并发自愈与修改，全面验证了 `LocalFileLockStrategy`（基于 OS 锁文件）和 `RedisLockStrategy`（基于原子 Lua 脚本）在文件锁并发争抢、乐观版本排序、故障重试 and 排队推进中的强一致性。
*   **Celery 定时与异步任务性能监控**：配置了 Celery 信号 `task_prerun`、`task_postrun` 与 `task_failure` 的无感拦截，在 Redis 中实时记录任务平均执行耗时（Average Latency）、最新耗时、总运行次数、成功率及最后报错调用栈。
*   **健康监控诊断 API 扩展**：在 FastAPI 后端路由中挂载了 `GET /health/celery-stats` 接口，支持拉取 Redis 中收集到的异步任务性能指标以对接 Cockpit 控制台，保证了异步队列状态的高可观测性。
*   **新增前端 Cockpit 直观时序监控面板**：开发了高颜值 `CeleryStatsDialog`，采用原生 SVG 双曲线图表实现对 Celery 任务平均延迟与运行吞吐量的时序曲线追踪与交互式悬停展示，提供了完善的错误堆栈回显支持。

---

## 二、 未完成计划任务列表（待明天或下一步实施） (Remaining Backlog)

### 1. 生产级运维与安全强化 (Production Operations & Hardening)
*   [x] **多节点沙箱的安全资源限制 (cgroups/kernel limit)** (已在 Phase 2K 完美完成)
*   [x] **高可用持久化卷 (PVC) 分布式存储对接** (已在 Phase 2L 完美完成)
*   [x] **Kubernetes 共享卷 PVC 在并发自愈下的压力测试** (已在 Phase 2N 完美完成)

### 2. 未来高阶规划 (Future Advanced Backlog)
*   [x] **多集群多区域控制面同步** (架构设计方案已于 Phase 2M 确立，详见 [multi_cluster_sync_design.md](file:///home/popos/Projects/AntigravityProjects/AgentDeepDive/docs/plans/multi_cluster_sync_design.md))
*   [x] **跨云多集群联邦调度器原型验证** (已在 Phase 2M 完美完成，编写并测试了 [federated_scheduler.py](file:///home/popos/Projects/AntigravityProjects/AgentDeepDive/src/core/scheduler/federated_scheduler.py) 以及测试套件 [test_federated_scheduler.py](file:///home/popos/Projects/AntigravityProjects/AgentDeepDive/tests/unit/test_federated_scheduler.py))
*   [x] **Celery 定时任务性能监测** (已在 Phase 2N 完美完成)

---
⏱️ 计划更新时间：2026年06月27日17时29分00秒

