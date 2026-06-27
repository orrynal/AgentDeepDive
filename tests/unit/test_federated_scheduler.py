import pytest
import time
from src.core.scheduler.federated_scheduler import (
    FederatedScheduler,
    FederatedCluster,
    FederatedAgentTask
)

def test_cluster_registration_and_heartbeat():
    scheduler = FederatedScheduler()
    
    # 注册华东 Hub 节点
    cluster = FederatedCluster(
        cluster_id="cluster-east",
        name="East-Hub",
        region="china-east",
        api_endpoint="http://10.0.1.1:8500",
        cpu_load=20.0,
        memory_usage=30.0,
        network_latency_ms=5.0,
        cached_vector_collections=["knowledge-base"]
    )
    
    scheduler.register_cluster(cluster)
    
    assert len(scheduler.clusters) == 1
    assert scheduler.clusters["cluster-east"].is_active is True
    assert scheduler.clusters["cluster-east"].last_heartbeat > 0
    
    # 更新心跳负载
    success = scheduler.update_cluster_heartbeat("cluster-east", cpu=45.0, memory=50.0, active_slots=2)
    assert success is True
    assert scheduler.clusters["cluster-east"].cpu_load == 45.0
    assert scheduler.clusters["cluster-east"].active_slots == 2

def test_federated_weighted_scheduling():
    scheduler = FederatedScheduler()
    
    # 注册三个集群，模拟不同的指标差异
    # 1. 华东区：延迟极低，但 CPU 负载极高 (90%)
    cluster_east = FederatedCluster(
        cluster_id="east",
        name="East-Cluster",
        region="china-east",
        api_endpoint="http://10.1.1.1",
        cpu_load=90.0,
        memory_usage=90.0,
        network_latency_ms=5.0,
        cached_vector_collections=[]
    )
    # 2. 华北区：延迟中等 (30ms)，负载极低 (10%)，具有任务所需的 RAG 缓存
    cluster_north = FederatedCluster(
        cluster_id="north",
        name="North-Cluster",
        region="china-north",
        api_endpoint="http://10.2.1.1",
        cpu_load=10.0,
        memory_usage=15.0,
        network_latency_ms=30.0,
        cached_vector_collections=["industry-vector"]
    )
    # 3. 华南区：延迟高 (150ms)，负载极低 (5%)
    cluster_south = FederatedCluster(
        cluster_id="south",
        name="South-Cluster",
        region="china-south",
        api_endpoint="http://10.3.1.1",
        cpu_load=5.0,
        memory_usage=5.0,
        network_latency_ms=150.0,
        cached_vector_collections=[]
    )
    
    scheduler.register_cluster(cluster_east)
    scheduler.register_cluster(cluster_north)
    scheduler.register_cluster(cluster_south)
    
    # 创建一个需要 RAG 向量缓存的智能体节点
    task = FederatedAgentTask(
        task_id="task-001",
        node_name="RAG-Generation",
        required_vectors=["industry-vector"]
    )
    
    # 第一次调度：由于 North 集群既低负载，又匹配到了所要求的向量数据，得分应为最高
    best = scheduler.get_best_cluster(task)
    assert best is not None
    assert best.cluster_id == "north"
    
    # 执行分配
    assigned = scheduler.schedule_task(task)
    assert assigned == "north"
    assert task.status == "RUNNING"
    assert scheduler.clusters["north"].active_slots == 1

def test_heartbeat_timeout_and_failover_drifting():
    scheduler = FederatedScheduler()
    
    # 注册失联的主集群 (East) 和健康的备用集群 (North)
    east = FederatedCluster(
        cluster_id="east",
        name="East-Node",
        region="china-east",
        api_endpoint="http://10.1.1.1",
        max_slots=5,
        network_latency_ms=5.0
    )
    north = FederatedCluster(
        cluster_id="north",
        name="North-Node",
        region="china-north",
        api_endpoint="http://10.2.1.1",
        max_slots=5,
        network_latency_ms=40.0
    )
    
    scheduler.register_cluster(east)
    scheduler.register_cluster(north)
    
    # 派发任务到 east
    task = FederatedAgentTask(task_id="task-drifter", node_name="Heavy-Inference")
    scheduler.schedule_task(task)
    assert task.assigned_cluster_id == "east"
    assert task.status == "RUNNING"
    
    # 强制将 east 心跳过期 (假设 10 秒前最后一次心跳)
    scheduler.clusters["east"].last_heartbeat = time.time() - 10.0
    
    # 侦测漂移 (阈值设为 5.0 秒)
    drifted_list = scheduler.detect_and_handle_drift(heartbeat_timeout=5.0)
    
    # east 应被判定失联，任务 task-drifter 自动漂移至健康的 north 节点上运行
    assert "task-drifter" in drifted_list
    assert scheduler.clusters["east"].is_active is False
    assert task.assigned_cluster_id == "north"
    assert task.status == "RUNNING"
    assert task.drift_count == 1
    assert len(scheduler.drift_history) == 1
    assert scheduler.drift_history[0]["from_cluster"] == "east"
    assert scheduler.drift_history[0]["to_cluster"] == "north"
