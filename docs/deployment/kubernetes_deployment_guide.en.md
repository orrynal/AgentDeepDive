# AgentDeepDive Kubernetes Deployment and Troubleshooting Guide

This guide documents the complete installation, docker image build optimization, resource manifest application, verification, and common troubleshooting steps for deploying AgentDeepDive in a local Kubernetes (K8s) environment.

---

## 1. Deployment Platforms & Technical Selection

| Platform | Supported OS | Resource Overhead | Recommended Scenarios | Target Users |
| :--- | :--- | :--- | :--- | :--- |
| **Minikube** | Linux / macOS / Windows | Medium (depends on VM/container driver) | Local single-node development, integration testing, and prototyping | Developers, QA Engineers |
| **K3s** | Linux | Extremely Low (Single binary, ~512MB RAM) | Edge computing, lightweight production servers, single-node setup | DevOps Engineers, Lightweight Production Deployments |
| **MicroK8s** | Ubuntu / Linux (with Snap support) | Low | Fast, Ubuntu-integrated lightweight Kubernetes setup | Ubuntu enthusiasts, Developers & Administrators |

---

## 2. Basic Cluster Installation

### 1. Minikube Installation (Docker Driver)
1. **Install kubectl CLI**：
   ```bash
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
   ```
2. **Install Minikube**：
   ```bash
   curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
   sudo install minikube-linux-amd64 /usr/local/bin/minikube
   ```
3. **Start cluster with Docker driver**：
   ```bash
   minikube start --driver=docker
   ```

### 2. K3s Lightweight Cluster Installation
One-click deployment on a Linux server:
```bash
curl -sfL https://get.k3s.io | sh -
# Authorize the current user to run kubectl
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER ~/.kube/config
```

---

## 3. Image Building & Optimization

Because this project includes the heavy deep learning library `sentence-transformers`, a default installation of PyTorch with full CUDA support would blow up the image size to **nearly 10GB**. This is too large to load into a single-node local cluster and can trigger `DiskPressure` errors.

### 1. CPU-Only PyTorch Optimization (Dockerfile Modification)
In the [Dockerfile](file:///app/Dockerfile), we explicitly pull the CPU version of PyTorch before installing the project dependencies. This shrinks the unpacked image size from 10GB to **3.2GB (a 70% reduction)**:

```dockerfile
# Force-install CPU PyTorch from the official PyTorch source
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir .
```

### 2. Configure `.dockerignore` to Block Host Files
Create a [.dockerignore](file:///app/.dockerignore) file in the root directory to prevent local dev directories (`.venv`), `.git` histories, and database dumps from being sent to the Docker daemon build context:
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

## 4. Image Loading & Verification

To use local images without internet pull attempts, the built image must be loaded into the correct container runtime namespace within the Kubernetes cluster.

### 1. Minikube Image Loading
1. **Build image on Host OS (ordinary shell session)**:
   ```bash
   docker build -t agentdeepdive:v1.0 -f Dockerfile .
   ```
2. **Load the image into the Minikube registry cache**:
   ```bash
   minikube image load agentdeepdive:v1.0
   ```
3. **Verify the image was loaded**:
   ```bash
   minikube image list | grep agentdeepdive
   # Expected output: docker.io/library/agentdeepdive:v1.0
   ```

> [!TIP]
> **No-Load Option**:
> Run `eval $(minikube docker-env)` in the current terminal to redirect Docker client to the VM. Then run `docker build -t agentdeepdive:v1.0 -f Dockerfile .` inside that window. The image will be built directly inside the VM, skipping the load step entirely.

### 2. K3s / containerd Image Importing
K3s containerd runs separately from Host OS Docker. The default namespace K8s pulls from is `k8s.io`:
```bash
# 1. Save the image to tar
docker save agentdeepdive:v1.0 -o agentdeepdive.tar
# 2. Import into the containerd k8s.io namespace
sudo k3s ctr -n k8s.io images import agentdeepdive.tar
# 3. Clean up tar file
rm agentdeepdive.tar
```

---

## 5. K8s Deployment Configuration & PVC Mounts

The complete Kubernetes resource manifest is located at [k8s/agentdeep-k8s.yaml](file:///app/k8s/agentdeep-k8s.yaml). Make sure to configure these key parameters:

*   **`imagePullPolicy`**: Must be set to **`IfNotPresent`**. If set to `Always`, K8s will skip local check and try to download it from public registry.
*   **`image`**: Must use a **specific tag (e.g. `v1.0`)** and match the exact name returned by `minikube image list` (such as `docker.io/library/agentdeepdive:v1.0`).
*   **`command`**: The API container's startup entrypoint must point to the correct FastAPI app path: **`src.api.main:app`**.
*   **`AGENTDEEP_K8S_VOLUME_CLAIM_NAME`**: Set in ConfigMap to match your PVC name (defaults to `agentdeep-workspace-pvc`). Read by API and Worker instances to dynamically mount the same workspace volume (`/workspace`) inside sandbox Pods, enabling real-time file sharing and synchronization.
*   **Distributed High-Availability PersistentVolumeClaim (PVC)**:
    * Declares a PVC with **`ReadWriteMany` (RWX)** access mode. In production setups, it must back a distributed file system (e.g., NFS, CephFS, GlusterFS) to allow multiple API replicas, Celery workers, and dynamic sandbox Pods to concurrently read/write to `/workspace`.
    * This prevents filesystem inconsistencies, data loss in local episodic memories or cryptographic audit trails during Pod rescheduling or scaling operations.

---

## 6. Troubleshooting & Common Failure Scenarios

### 🚨 Scenario 1: `ErrImagePull / ImagePullBackOff`
*   **Symptom**: Pods for API and Worker remain stuck in `ImagePullBackOff`.
*   **Diagnostics**: Running `kubectl describe pod <pod_name> -n agentdeep` shows event messages like `Pulling... failed... Try again`.
*   **Root Cause**:
    1. The `imagePullPolicy` was not set to `IfNotPresent`.
    2. The `latest` tag was used. Kubelet treats `latest` as volatile and always attempts to pull from remote registry.
    3. The image name in the YAML does not match the loaded image name in containerd namespace (missing `docker.io/library/` prefix).
*   **Resolution**:
    - Match the exact tag and prefix in YAML: `image: docker.io/library/agentdeepdive:v1.0`.
    - Explicitly add `imagePullPolicy: IfNotPresent`.
    - Ensure `minikube image load agentdeepdive:v1.0` was executed on the host.

### 🚨 Scenario 2: `OSError: Readme file does not exist: README.md`
*   **Symptom**: `docker build` fails at the `pip install .` layer.
*   **Root Cause**: `pyproject.toml` declares metadata `readme = "README.md"`. The `hatchling` backend requires `README.md` to compile package metadata. However, the Dockerfile only copied `pyproject.toml`, missing the README file.
*   **Resolution**: Update the Dockerfile to copy both files:
    `COPY pyproject.toml README.md ./`.

### 🚨 Scenario 3: `ERROR: Error loading ASGI app. Could not import module "src.main"`
*   **Symptom**: Images are pulled successfully, but API Pods crash immediately with status `Error`. `kubectl logs` reports failure to import module `src.main`.
*   **Root Cause**:
    1. The FastAPI entrypoint is located at `src/api/main.py` (`src.api.main:app`).
    2. The deployment YAML had a hardcoded `command: ["uvicorn", "src.main:app", ...]` under `api-container`, overriding the Dockerfile's fixed CMD and leading to a startup crash.
*   **Resolution**: Update [k8s/agentdeep-k8s.yaml](file:///app/k8s/agentdeep-k8s.yaml) and `docker-compose.prod.yml` to use the correct ASGI path:
    `command: ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]`.

### 🚨 Scenario 4: `minikube tunnel` is active, but `NodeIP:30080` is still unreachable
*   **Symptom**: Cannot reach the Swagger interface via `minikube ip:30080` even when tunnel is active. Only `kubectl port-forward` works.
*   **Root Cause**: With `docker` driver on Linux, Minikube runs inside a docker container. Its internal IP (`192.168.49.x`) is isolated. If `minikube tunnel` is executed without root privileges, it cannot inject the required network routes into the host Linux routing tables.
*   **Resolution**: This is an expected isolation behavior. **Avoid complex routing tables** and use the standard port forwarding tunnel:
    `kubectl port-forward service/agentdeep-api-service 8000:8000 -n agentdeep`.

### 🚨 Scenario 5: `Multi-Attach error for volume` or Pod stuck in `ContainerCreating`
*   **Symptom**: Certain API or Worker Pods fail to boot, and `kubectl describe pod` outputs error: `Multi-Attach error for volume "pvc-..." Volume is already used by Pod ...`.
*   **Root Cause**:
    1. The default StorageClass of the cluster only supports `ReadWriteOnce` (RWO) instead of `ReadWriteMany` (RWX).
    2. When K8s spawns multiple replicas or reschedules worker pods across different physical nodes, the volume controller locks access exclusively, causing subsequent mounts to fail.
*   **Resolution**:
    - Ensure your Kubernetes cluster is configured with a CSI plugin that supports RWX (e.g., NFS-Client-Provisioner, Ceph-CSI, Rancher Longhorn).
    - Double check that the PVC manifest explicitly states `accessModes: - ReadWriteMany`.
    - Set the appropriate `storageClassName` backing RWX storage inside the PVC.

---

## 7. Common K8s Operation Cheat Sheet

*   **Deploy Manifests**: `kubectl apply -f k8s/agentdeep-k8s.yaml`
*   **View Cluster Container Status**: `kubectl get pods -n agentdeep -w`
*   **Gracefully Stop/Pause Services** (scales replicas to 0, preserves all deployment resource settings):
    `kubectl scale deployment/agentdeep-api deployment/agentdeep-worker --replicas=0 -n agentdeep`
*   **Resume Services** (scales replicas back to normal):
    `kubectl scale deployment/agentdeep-api --replicas=2 -n agentdeep`
    `kubectl scale deployment/agentdeep-worker --replicas=3 -n agentdeep`
*   **Rollout Restart (Trigger image update)**: `kubectl rollout restart deployment/agentdeep-api -n agentdeep`
*   **Trace Worker Background Logs**: `kubectl logs -f deployment/agentdeep-worker -n agentdeep --all-containers`
*   **Teardown Deployments (Delete containers and routing)**: `kubectl delete -f k8s/agentdeep-k8s.yaml`
*   **Safe Stop/Teardown of K8s and Minikube System Services**:
    *   **Minikube Cluster**:
        *   Stop the VM/cluster container (keeps pulled images and states for rapid cold start): `minikube stop`
        *   Tear down and delete the cluster (removes VM/containers to free memory and disk space): `minikube delete`
    *   **K3s Lightweight Cluster (Systemd)**:
        *   Stop K3s system daemon process: `sudo systemctl stop k3s`
        *   Disable K3s startup on boot: `sudo systemctl disable k3s`
        *   Completely uninstall K3s and clean mounts: `/usr/local/bin/k3s-uninstall.sh`
    *   **MicroK8s Cluster (Snap)**:
        *   Stop all MicroK8s service instances: `microk8s stop`

---

## 8. Appendix: Kubernetes Core Management Components

In a Kubernetes environment, besides your business containers, several system-level controllers manage the platform lifecycle:

1. **`kube-apiserver` (Cluster Gateway)**:
   - **Role & Function**: The primary gateway to the cluster control plane. It processes all incoming `kubectl` commands, API calls, and config templates (e.g., `agentdeep-k8s.yaml`), persisting cluster configurations and run states inside the etcd database.
2. **`kube-scheduler` (Resource Allocator)**:
   - **Role & Function**: Determines where newly created Pods should run. It inspects resource requests (CPU/Memory) of `agentdeep-worker` and `agentdeep-api` and evaluates node availability to schedule containers on the best hosts.
3. **`kube-controller-manager` (State Controller)**:
   - **Role & Function**: Continuously monitors the cluster, reconciling actual states with desired states. If it detects API deployment has replica count set to 2 but only 1 is alive, it instructs the kubelet to spawn a new pod.
4. **`k8s-etcd` (Cluster Database)**:
   - **Role & Function**: The single source of truth for all resource configurations and K8s internal metadata. Uses the Raft consensus protocol to secure high reliability.
5. **`kubelet` & `containerd` (Node Agent & Container Runtime)**:
   - **Role & Function**: `kubelet` is the agent process running on each host, receiving pod specifications and directing `containerd` to download images, set up storage mounts, and spin up container boundaries.
6. **`kube-proxy` & CNI (Network Controller & Plugin)**:
   - **Role & Function**: Manages network routing and packet forwarding rules (using iptables/IPVS). It enables service discovery and pod-to-pod routing, letting `agentdeep-worker` resolve the local cluster address `redis.agentdeep.svc`.
