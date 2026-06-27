# AgentDeepDive Kubernetes 部署与排坑实战指南

本指南记录了 AgentDeepDive 在本地 Kubernetes (K8s) 环境下的完整安装、镜像构建优化、配置资源清单应用、前台验证以及部署中遇到的常见故障与解决对策。

---

## 一、 部署平台适用场景与技术选型

| 平台方案 | 适用操作系统 | 资源消耗 | 推荐场景 | 适用用户群体 |
| :--- | :--- | :--- | :--- | :--- |
| **Minikube** | Linux / macOS / Windows | 中等 (依赖虚拟化/容器层) | 本地单机开发、联调测试与原型验证 | 开发人员、测试工程师 |
| **K3s** | Linux | 极低 (轻量二进制，约 512MB RAM) | 边缘计算、轻量化生产服务器、单机部署 | 运维工程师、轻量级线上生产部署 |
| **MicroK8s** | Ubuntu / Linux (Snap 支持) | 较低 | 快速与 Ubuntu 系统深度集成的轻量集群 | Ubuntu 爱好者、开发运维人员 |

---

## 二、 基础集群安装

### 1. Minikube 极简安装 (Docker 驱动)
1. **安装 kubectl 客户端**：
   ```bash
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
   ```
2. **安装 Minikube**：
   ```bash
   curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
   sudo install minikube-linux-amd64 /usr/local/bin/minikube
   ```
3. **以 Docker 作为驱动启动**：
   ```bash
   minikube start --driver=docker
   ```

### 2. K3s 轻量集群安装
在 Linux 服务器上一键部署：
```bash
curl -sfL https://get.k3s.io | sh -
# 授权当前用户运行 kubectl
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER ~/.kube/config
```

---

## 三、 镜像构建与瘦身实践

因为项目引入了深度学习库 `sentence-transformers`，如果不加控制，默认安装 CUDA 版 PyTorch 会使镜像体积攀升至 **近 10GB**，无法载入本地单机 K8s 节点（容易产生 `DiskPressure` 并撑爆 VM 磁盘）。

### 1. CPU-Only PyTorch 瘦身原理 (Dockerfile 优化)
在 [Dockerfile](file:///app/Dockerfile) 中，我们在安装项目依赖前，强行指定安装 CPU 版本的轻量级 PyTorch 依赖包。这可以将镜像解压后的物理大小从 10GB 砍至 **3.2GB（减少 70% 冗余）**：

```dockerfile
# 强行指定拉取 PyTorch 官方的 CPU 轻量源
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir .
```

### 2. 配置 `.dockerignore` 彻底隔离开发冗余
在根目录下配置 [.dockerignore](file:///app/.dockerignore)，在执行 `docker build` 时，物理拦截宿主机本地的巨大虚拟环境目录（`.venv`）、`.git` 历史记录和临时数据缓存：
```text
.venv/
.venv_sandbox/
.git/
.pytest_cache/
*.db
docker-build.log
server.log
```

---

## 四、 镜像加载与匹配校验

为了让本地 K8s 能够无需联网拉取（使用本地镜像），必须将宿主机构建的镜像导入到 K8s 所使用的特定容器运行时命名空间中。

### 1. Minikube 环境镜像载入
1. **宿主机普通窗口构建镜像**：
   ```bash
   docker build -t agentdeepdive:v1.0 -f Dockerfile .
   ```
2. **通过 Control-Path 载入到 minikube 本地库**：
   ```bash
   minikube image load agentdeepdive:v1.0
   ```
3. **校验是否载入成功**：
   ```bash
   minikube image list | grep agentdeepdive
   # 预期输出: docker.io/library/agentdeepdive:v1.0
   ```

> [!TIP]
> **终极免导入方案**：
> 在当前终端中运行 `eval $(minikube docker-env)` 将 docker 重定向到虚拟机内部，直接在当前窗口执行 `docker build -t agentdeepdive:v1.0 -f Dockerfile .`。这样镜像直接产生在 VM 里，省去了 load 导出步骤。

### 2. K3s / containerd 本地镜像导入
宿主机 `docker` 与 k3s 内部 containerd 是物理隔离的，且 K8s 默认拉取的命名空间是 `k8s.io`：
```bash
# 1. 导出为本地 tar 包
docker save agentdeepdive:v1.0 -o agentdeepdive.tar
# 2. 物理导入到 k8s.io 命名空间中
sudo k3s ctr -n k8s.io images import agentdeepdive.tar
# 3. 清理临时 tar 包
rm agentdeepdive.tar
```

---

## 五、 平台 K8s 部署配置文件与高可用持久化卷 (PVC) 挂载

完整的 K8s 资源定义清单位于 [k8s/agentdeep-k8s.yaml](file:///app/k8s/agentdeep-k8s.yaml)。重点关注以下参数：

*   **`imagePullPolicy`**：必须设为 **`IfNotPresent`**。若设为 `Always`，K8s 每次都会强制联网拉取。
*   **`image`**：必须使用**具体的版本 Tag（如 `v1.0`）**，且需要与 `minikube image list` 里的全名（如 `docker.io/library/agentdeepdive:v1.0`）完美对齐。
*   **`command`**：API 容器的启动路径必须指向正确的 FastAPI 文件 **`src.api.main:app`**。
*   **`AGENTDEEP_K8S_VOLUME_CLAIM_NAME`**：在 ConfigMap 中需与 PVC 声明对齐（默认为 `agentdeep-workspace-pvc`）。该配置会由 API 和 Worker 读取，在其动态拉起 Sandbox 隔离 Pod 时，自动将沙箱容器内的 `/workspace` 挂载到相同的物理 PVC 共享卷，从而确保沙箱与宿主机工作区目录的实时数据同步。
*   **分布式高可用共享卷挂载 (PersistentVolumeClaim)**：
    * 声明了模式为 **`ReadWriteMany` (RWX)** 的 PVC。对于生产环境，必须挂载分布式网络存储（如 NFS, CephFS, GlusterFS 等），以允许多副本 API 控制面、多个 Celery 计算 Worker 以及被动态拉起的 Sandbox 沙箱 Pod 同时并发地读写同一个工作空间 `/workspace` 路径。
    * 这避免了容器漂移、重建或水平扩展计算节点时，各 Agent 间产生工作区文件冲突与历史情节记忆、审计日志备份文件损坏丢失的隐患。

---

## 六、 常见故障与排坑记录 (Troubleshooting)

### 🚨 故障 1：`ErrImagePull / ImagePullBackOff`
*   **问题表现**：部署后，API 和 Worker 的 Pod 一直卡在 `ImagePullBackOff`。
*   **排查命令**：`kubectl describe pod <pod_name> -n agentdeep` 发现事件日志中显示 `Pulling... failed... Try again`。
*   **根本原因**：
    1. 镜像拉取策略未显式指定为 `IfNotPresent`。
    2. 使用了 `latest` 标签。K8s 认为 `latest` 是不稳定的动态 tag，在默认策略下依然强制联网下载。
    3. 镜像名字与 Minikube 内部存入的全名不一致（缺少 `docker.io/library/` 前缀），containerd 无法命中本地缓存。
*   **解决方法**：
    - 在 YAML 中将镜像改为具体 Tag 且补全前缀：`image: docker.io/library/agentdeepdive:v1.0`。
    - 显式配置 `imagePullPolicy: IfNotPresent`。
    - 运行 `minikube image load agentdeepdive:v1.0` 载入镜像。

### 🚨 故障 2：`OSError: Readme file does not exist: README.md`
*   **问题表现**：在 `docker build` 执行到 `pip install .` 阶段时崩溃。
*   **根本原因**：`pyproject.toml` 中声明了元数据 `readme = "README.md"`，但在 Dockerfile 中，仅仅拷贝了 `pyproject.toml`，缺少对 `README.md` 的拷贝，导致 `hatchling` 构建包信息时抛出异常。
*   **解决方法**：修改 Dockerfile，在安装前同时复制两份文件：
    `COPY pyproject.toml README.md ./`。

### 🚨 故障 3：`ERROR: Error loading ASGI app. Could not import module "src.main"`
*   **问题表现**：镜像导入和拉取均正常，但 2 个 API Pod 启动后迅速 Crash，状态呈现为 `Error`。运行 `kubectl logs` 查看日志打印了无法导入 `src.main` 的信息。
*   **根本原因**：
    1. 平台的 FastAPI 入口点位于 `src/api/main.py`（对应 `src.api.main:app`）。
    2. `k8s/agentdeep-k8s.yaml` 文件的 `spec.template.spec.containers.command` 中硬编码了 `uvicorn src.main:app ...`，从而覆盖了 Dockerfile 里的 CMD 默认路径，导致容器一启动就因为找不到模块直接崩掉。
*   **解决方法**：将 [k8s/agentdeep-k8s.yaml](file:///app/k8s/agentdeep-k8s.yaml) 的 API Deployment 以及生产 docker-compose 文件中硬编码的启动参数修正为：
    `command: ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]`。

### 🚨 故障 4：启动 `minikube tunnel` 后，依然无法通过 `NodeIP:30080` 访问页面
*   **问题表现**：除了使用 `kubectl port-forward`，通过 `minikube service` 自动唤起的代理或者输入 `minikube ip` 配上 NodePort 均无法访问。
*   **根本原因**：在 Linux 环境下使用 `docker` 驱动启动 Minikube 时，集群其实只是一个名为 `minikube` 的 Docker 容器。它的 IP 对宿主机属于“物理隔离”状态。若在非 `root` 权限（无 `sudo` 授权提示）下执行 `minikube tunnel`，它根本无权修改 Linux 内核 of 路由表，因此数据包在宿主机网卡上无法被发送至 Docker 网段。
*   **解决方法**：这是本地 Docker-Driver 容器化集群的正常系统屏障。**无需折腾路由**，请直接使用 `kubectl port-forward` 作为开发验证的“黄金通道”，它完全不依赖操作系统路由表修改权限：
    `kubectl port-forward service/agentdeep-api-service 8000:8000 -n agentdeep`。

### 🚨 故障 5：`Multi-Attach error for volume` 或 Pod 挂载卷一直处于 `ContainerCreating`
*   **问题表现**：部署后，某些 API 或 Worker Pod 无法启动，`kubectl describe pod` 报错 `Multi-Attach error for volume "pvc-..." Volume is already used by Pod ...`。
*   **根本原因**：
    1. K8s 本地默认的存储类（StorageClass）不支持 `ReadWriteMany` (RWX) 模式，仅支持 `ReadWriteOnce` (RWO，只允许单节点挂载)。
    2. 当 K8s 尝试拉起多个 Replica 副本或被调度的 Worker Pod 漂移到其他物理节点时，存储控制器由于排他性锁机制强行拒绝并发挂载，导致挂载失败。
*   **解决方法**：
    - 确保 K8s 物理集群中部署并配置了支持多节点共享的存储插件（如 NFS-Client-Provisioner、Ceph-CSI、Rancher Longhorn 等）。
    - 确保在 PVC 声明中明确使用 `accessModes: - ReadWriteMany`。
    - 在生产环境的 PVC 中，需要正确指定支持 RWX 的 `storageClassName` 参数。

---

## 七、 平台常用 K8s 运维命令表

*   **一键应用部署**：`kubectl apply -f k8s/agentdeep-k8s.yaml`
*   **查看集群容器状态**：`kubectl get pods -n agentdeep -w`
*   **临时停止/暂停服务**（将副本缩容为 0，保留所有部署配置）：
    `kubectl scale deployment/agentdeep-api deployment/agentdeep-worker --replicas=0 -n agentdeep`
*   **恢复运行服务**（重新扩容至原副本数）：
    `kubectl scale deployment/agentdeep-api --replicas=2 -n agentdeep`
    `kubectl scale deployment/agentdeep-worker --replicas=3 -n agentdeep`
*   **滚动重启应用（加载新镜像）**：`kubectl rollout restart deployment/agentdeep-api -n agentdeep`
*   **实时查看 Worker 消费日志**：`kubectl logs -f deployment/agentdeep-worker -n agentdeep --all-containers`
*   **销毁全部容器资源**（彻底清除 Namespace 及项目下的所有 Pod/Service/PVC/ConfigMap）：
    `kubectl delete -f k8s/agentdeep-k8s.yaml`
*   **安全停止/释放 K8s 及 Minikube 相关系统服务**：
    *   **Minikube 本地集群**：
        *   停止虚拟机/集群（保留已拉取的镜像与配置状态，方便下次 `start` 极速启动）：`minikube stop`
        *   彻底删除集群（删除虚拟机/容器以完全释放物理内存和磁盘空间）：`minikube delete`
    *   **K3s 轻量化集群 (Systemd 托管)**：
        *   停止 K3s 系统服务守护进程：`sudo systemctl stop k3s`
        *   禁用 K3s 开机自启动：`sudo systemctl disable k3s`
        *   彻底物理卸载 K3s 并清理相关容器网卡与挂载：`/usr/local/bin/k3s-uninstall.sh`
    *   **MicroK8s 集群 (Snap 托管)**：
        *   停止 MicroK8s 本地服务运行：`microk8s stop`

---

## 八、 附录：Kubernetes 核心管理组件角色科普

在 K8s 环境下，除了项目自身拉起的业务容器外，Kubernetes 控制面自身也包含了一组系统级守护组件，它们协作管理着整个平台的生命周期：

1. **`kube-apiserver` (集群统一网关)**：
   - **角色功能**：K8s 集群控制面的核心入口。负责接收所有的 `kubectl` 指令、API 调用以及配置清单（如 `agentdeep-k8s.yaml`），并将集群的配置与运行时状态持久化存入 K8s 专属的 etcd 数据库中。
2. **`kube-scheduler` (智能调度器)**：
   - **角色功能**：负责决定将 Pod 调度到哪台物理节点上运行。它会根据 `agentdeep-worker` 与 `agentdeep-api` 的资源限制（CPU/内存），动态评估集群各个物理节点的健康度与空闲度，完成容器的最优分配。
3. **`kube-controller-manager` (状态监工控制器)**：
   - **角色功能**：持续检测集群的实际状态是否符合期望状态。例如，当检测到 API Deployment 的期望副本数为 2，但实际仅存活 1 个时，它会即刻向 Kubelet 下达命令重新拉起一个新容器以对齐副本数。
4. **`k8s-etcd` (集群分布式数据库)**：
   - **角色功能**：K8s 集群中所有资源定义与状态数据的唯一可信账本，采用 Raft 一致性协议，保证集群状态数据的高可靠与不丢失。
5. **`kubelet` & `containerd` (物理执行代理与容器运行时)**：
   - **角色功能**：`kubelet` 是安装在各计算节点上的代理进程，负责接收 API-Server 的指令，并通过容器运行时（如 `containerd`）在物理机器上真正拉起、监控并管理容器进程的生命周期。
6. **`kube-proxy` & CNI (网络通信代理与插件)**：
   - **角色功能**：维护整个 K8s 集群内的服务发现与网络路由规则（如 iptables/IPVS 规则）。正是有了它，`agentdeep-worker` 容器才能够通过 K8s Service 域名 `redis.agentdeep.svc` 自动路由并发现 Redis 消息队列。

