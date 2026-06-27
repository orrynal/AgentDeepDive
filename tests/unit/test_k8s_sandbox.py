import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from src.config import settings
from src.core.workspace.runtime import sandbox_runtime_manager


class MockK8sObj:
    def __init__(self, name, phase, exit_code=0):
        self.metadata = MagicMock()
        self.metadata.name = name
        self.status = MagicMock()
        self.status.phase = phase
        container_status = MagicMock()
        container_status.state = MagicMock()
        container_status.state.terminated = MagicMock()
        container_status.state.terminated.exit_code = exit_code
        self.status.container_statuses = [container_status]


@pytest.mark.anyio
async def test_runtime_routing_host(monkeypatch):
    monkeypatch.setattr(settings, "k8s_sandbox_enabled", False)
    monkeypatch.setattr(settings, "docker_sandbox_enabled", False)

    # Mock _execute_host
    mock_host = AsyncMock(return_value=(0, "host output"))
    monkeypatch.setattr(sandbox_runtime_manager, "_execute_host", mock_host)

    exit_code, output = await sandbox_runtime_manager.execute_command("echo test", "/tmp")
    assert exit_code == 0
    assert output == "host output"
    mock_host.assert_called_once()


@pytest.mark.anyio
async def test_runtime_routing_docker(monkeypatch):
    monkeypatch.setattr(settings, "k8s_sandbox_enabled", False)
    monkeypatch.setattr(settings, "docker_sandbox_enabled", True)

    # Mock _execute_docker
    mock_docker = AsyncMock(return_value=(0, "docker output"))
    monkeypatch.setattr(sandbox_runtime_manager, "_execute_docker", mock_docker)

    exit_code, output = await sandbox_runtime_manager.execute_command("echo test", "/tmp")
    assert exit_code == 0
    assert output == "docker output"
    mock_docker.assert_called_once()


@pytest.mark.anyio
async def test_runtime_routing_k8s(monkeypatch):
    monkeypatch.setattr(settings, "k8s_sandbox_enabled", True)

    # Mock _execute_k8s
    mock_k8s = AsyncMock(return_value=(0, "k8s output"))
    monkeypatch.setattr(sandbox_runtime_manager, "_execute_k8s", mock_k8s)

    exit_code, output = await sandbox_runtime_manager.execute_command("echo test", "/tmp")
    assert exit_code == 0
    assert output == "k8s output"
    mock_k8s.assert_called_once()


@pytest.mark.anyio
async def test_k8s_execution_flow(monkeypatch):
    monkeypatch.setattr(settings, "k8s_sandbox_enabled", True)
    monkeypatch.setattr(settings, "k8s_gvisor_enabled", True)
    monkeypatch.setattr(settings, "k8s_runtime_class_name", "gvisor-class")
    monkeypatch.setattr(settings, "k8s_volume_claim_name", "my-pvc")

    # Mock kubernetes API
    mock_client = MagicMock()
    mock_v1 = MagicMock()
    mock_client.CoreV1Api.return_value = mock_v1
    
    # Mock namespace check
    mock_v1.read_namespace.return_value = True

    # Capture Pod creation arguments
    created_pods = []
    def mock_create_pod(ns, pod_obj):
        created_pods.append(pod_obj)
        return pod_obj
    mock_v1.create_namespaced_pod.side_effect = mock_create_pod

    # Mock Watch stream to simulate pod transitioning to Running/Succeeded
    class MockWatch:
        def stream(self, func, *args, **kwargs):
            # Find the pod name from arguments if possible or generate one
            # Yield event with Succeeded pod
            pod_name = created_pods[0].metadata.name if created_pods else "pod-123"
            yield {
                "type": "MODIFIED",
                "object": MockK8sObj(pod_name, "Succeeded", exit_code=0)
            }
        def stop(self):
            pass

    monkeypatch.setattr("kubernetes.client.CoreV1Api", lambda: mock_v1)
    monkeypatch.setattr("kubernetes.watch.Watch", MockWatch)
    monkeypatch.setattr("kubernetes.config.load_kube_config", lambda: None)
    sandbox_runtime_manager._k8s_initialized = True

    # Mock log stream
    mock_v1.read_namespaced_pod_log.return_value = [b"hello from k8s pod"]

    # Mock read pod status
    def mock_pod_status(name, ns):
        return MockK8sObj(name, "Succeeded", exit_code=0)
    mock_v1.read_namespaced_pod_status.side_effect = mock_pod_status

    log_received = []
    def log_cb(chunk):
        log_received.append(chunk)

    exit_code, output = await sandbox_runtime_manager.execute_command(
        command="python -c 'print(\"hello\")'",
        cwd="/workspace",
        task_id="task-123",
        agent_id="agent-abc",
        timeout=10,
        log_callback=log_cb
    )

    assert exit_code == 0
    assert "hello from k8s pod" in output
    assert "hello from k8s pod" in log_received

    # Verify Pod configurations
    assert len(created_pods) == 1
    pod = created_pods[0]
    assert pod.spec.restart_policy == "Never"
    assert pod.spec.runtime_class_name == "gvisor-class"
    assert pod.metadata.labels["agentdeep-task-id"] == "task-123"
    assert pod.metadata.labels["agentdeep-agent-id"] == "agent-abc"
    assert len(pod.spec.volumes) == 1
    assert pod.spec.volumes[0].persistent_volume_claim.claim_name == "my-pvc"


@pytest.mark.anyio
async def test_host_execution_actual():
    # Test real host execution using SandboxRuntimeManager
    exit_code, output = await sandbox_runtime_manager.execute_command(
        command="echo 'real host run'",
        cwd=".",
        timeout=5
    )
    assert exit_code == 0
    assert "real host run" in output
