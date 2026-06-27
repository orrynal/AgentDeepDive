import time
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class FederatedCluster(BaseModel):
    cluster_id: str
    name: str
    region: str
    api_endpoint: str
    is_active: bool = True
    cpu_load: float = 0.0  # 0.0 to 100.0
    memory_usage: float = 0.0  # 0.0 to 100.0
    network_latency_ms: float = 10.0
    active_slots: int = 0
    max_slots: int = 10
    cached_vector_collections: List[str] = []
    last_heartbeat: float = 0.0

class FederatedAgentTask(BaseModel):
    task_id: str
    node_name: str
    required_cpu: float = 1.0
    required_memory_mb: float = 512.0
    required_vectors: List[str] = []
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED, DRIFTED
    assigned_cluster_id: Optional[str] = None
    drift_count: int = 0

class FederatedScheduler:
    def __init__(self):
        self.clusters: Dict[str, FederatedCluster] = {}
        self.tasks: Dict[str, FederatedAgentTask] = {}
        self.drift_history: List[dict] = []

    def register_cluster(self, cluster: FederatedCluster) -> None:
        """注册一个 Spoke 集群算力节点"""
        cluster.last_heartbeat = time.time()
        self.clusters[cluster.cluster_id] = cluster
        logger.info(f"Registered Federated Cluster: {cluster.name} ({cluster.cluster_id}) in {cluster.region}")

    def update_cluster_heartbeat(self, cluster_id: str, cpu: float, memory: float, active_slots: int) -> bool:
        """更新 Spoke 集群心跳和资源水位"""
        if cluster_id not in self.clusters:
            return False
        cluster = self.clusters[cluster_id]
        cluster.cpu_load = cpu
        cluster.memory_usage = memory
        cluster.active_slots = active_slots
        cluster.last_heartbeat = time.time()
        cluster.is_active = True
        return True

    def get_best_cluster(self, task: FederatedAgentTask, latency_weight: float = 0.3, resource_weight: float = 0.4, data_weight: float = 0.3) -> Optional[FederatedCluster]:
        """
        基于联邦调度算法对可用集群进行评分：
        Score = w1 * (1 - load) + w2 * (1 - latency) + w3 * (data_affinity)
        """
        best_score = -1.0
        best_cluster = None

        active_clusters = [c for c in self.clusters.values() if c.is_active]
        if not active_clusters:
            logger.warning("No active federated clusters available for scheduling.")
            return None

        for cluster in active_clusters:
            # 1. 过滤：插槽槽位是否已满
            if cluster.active_slots >= cluster.max_slots:
                continue

            # 2. 计算资源负载得分 (0 到 1)
            load_factor = (cluster.cpu_load + cluster.memory_usage) / 200.0
            resource_score = 1.0 - load_factor

            # 3. 计算网络时延得分 (0 到 1，以 200ms 为最差参考值)
            latency_score = max(0.0, 1.0 - (cluster.network_latency_ms / 200.0))

            # 4. 计算数据亲和性得分 (0 到 1)
            matched_vectors = set(task.required_vectors) & set(cluster.cached_vector_collections)
            data_affinity_score = len(matched_vectors) / len(task.required_vectors) if task.required_vectors else 1.0

            # 综合加权评分
            score = (resource_weight * resource_score +
                     latency_weight * latency_score +
                     data_weight * data_affinity_score)

            logger.debug(f"Evaluated cluster {cluster.name}: Resource={resource_score:.2f}, Latency={latency_score:.2f}, Data={data_affinity_score:.2f} -> Total Score={score:.4f}")

            if score > best_score:
                best_score = score
                best_cluster = cluster

        return best_cluster

    def schedule_task(self, task: FederatedAgentTask) -> Optional[str]:
        """将任务节点调度分配至最合适的 Spoke 集群"""
        best_cluster = self.get_best_cluster(task)
        if not best_cluster:
            task.status = "FAILED"
            logger.error(f"Failed to schedule task {task.task_id}: No matching active cluster available.")
            return None

        task.assigned_cluster_id = best_cluster.cluster_id
        task.status = "RUNNING"
        best_cluster.active_slots += 1
        self.tasks[task.task_id] = task
        logger.info(f"Scheduled task {task.task_id} to cluster {best_cluster.name} in {best_cluster.region}")
        return best_cluster.cluster_id

    def detect_and_handle_drift(self, heartbeat_timeout: float = 5.0) -> List[str]:
        """
        心跳守护进程，检测失联的 Spoke 集群，触发任务自动熔断与异地灾备漂移 (Failover Drifting)
        """
        current_time = time.time()
        drifted_tasks = []

        for cluster_id, cluster in self.clusters.items():
            if cluster.is_active and (current_time - cluster.last_heartbeat > heartbeat_timeout):
                # 判定集群失联
                cluster.is_active = False
                logger.error(f"Federated Cluster {cluster.name} ({cluster_id}) lost heartbeat. Initiating disaster recovery drift...")
                
                # 寻找该集群上所有运行中的任务并进行漂移
                for task_id, task in self.tasks.items():
                    if task.assigned_cluster_id == cluster_id and task.status == "RUNNING":
                        drifted_tasks.append(task_id)
                        self._trigger_drift(task)

        return drifted_tasks

    def _trigger_drift(self, task: FederatedAgentTask) -> None:
        """执行具体的任务漂移和重新分发"""
        old_cluster_id = task.assigned_cluster_id
        task.drift_count += 1
        task.status = "DRIFTED"
        
        # 释放旧集群槽位计数 (容错保护)
        if old_cluster_id in self.clusters:
            self.clusters[old_cluster_id].active_slots = max(0, self.clusters[old_cluster_id].active_slots - 1)

        logger.warning(f"Task {task.task_id} has drifted (Drift Count: {task.drift_count}) from lost cluster {old_cluster_id}")

        # 重新调用评分机制，漂移调度到新的健康节点
        new_cluster_id = self.schedule_task(task)
        if new_cluster_id:
            drift_record = {
                "task_id": task.task_id,
                "from_cluster": old_cluster_id,
                "to_cluster": new_cluster_id,
                "timestamp": time.time(),
                "success": True
            }
            self.drift_history.append(drift_record)
            logger.info(f"Successfully drifted task {task.task_id} to destination cluster {new_cluster_id}")
        else:
            task.status = "FAILED"
            logger.critical(f"Failover drift failed for task {task.task_id}: No other cluster available.")
