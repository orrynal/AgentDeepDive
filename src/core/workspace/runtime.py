import os
import re
import uuid
import time
import subprocess
from pathlib import Path
from typing import Callable, Any, Tuple
import structlog
from src.config import settings

logger = structlog.get_logger()

class SandboxRuntimeManager:
    """Manages command execution environments, routing to Host, Docker, or Kubernetes."""

    def __init__(self):
        self._k8s_initialized = False

    def _init_k8s_client(self):
        if self._k8s_initialized:
            return
        from kubernetes import config
        try:
            config.load_in_cluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except Exception:
            try:
                config.load_kube_config()
                logger.info("Loaded local kubeconfig")
            except Exception as e:
                logger.error("Failed to load Kubernetes configuration", error=str(e))
                raise RuntimeError(f"Kubernetes client init failed: {e}")
        self._k8s_initialized = True

    async def execute_command(
        self,
        command: str,
        cwd: str,
        task_id: str = "unknown",
        agent_id: str = "unknown",
        timeout: int = 30,
        log_callback: Callable[[str], None] = None
    ) -> Tuple[int, str]:
        """Execute a shell command in the configured sandbox environment."""
        if settings.k8s_sandbox_enabled:
            return await self._execute_k8s(command, cwd, task_id, agent_id, timeout, log_callback)
        elif settings.docker_sandbox_enabled:
            return await self._execute_docker(command, cwd, task_id, agent_id, timeout, log_callback)
        else:
            return await self._execute_host(command, cwd, timeout, log_callback)

    async def _execute_k8s(
        self,
        command: str,
        cwd: str,
        task_id: str,
        agent_id: str,
        timeout: int,
        log_callback: Callable[[str], None] = None
    ) -> Tuple[int, str]:
        """Execute command in a Kubernetes Pod (with gVisor if enabled)."""
        self._init_k8s_client()
        from kubernetes import client, watch

        v1 = client.CoreV1Api()
        namespace = settings.k8s_namespace

        # Ensure namespace exists
        try:
            v1.read_namespace(namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.info("Creating Kubernetes namespace", namespace=namespace)
                v1.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace)))
            else:
                raise

        # Generate unique pod name
        safe_task_id = re.sub(r"[^a-zA-Z0-9-]", "-", task_id).lower()[:30].strip("-")
        if not safe_task_id:
            safe_task_id = "default"
        pod_name = f"agentdeep-sandbox-{safe_task_id}-{uuid.uuid4().hex[:6]}"

        # Setup Volume and VolumeMount
        volumes = []
        volume_mounts = []

        workspace_root = os.path.abspath(settings.resolved_workspace_path)
        rel_cwd = os.path.relpath(cwd, workspace_root)
        container_w = "/workspace" if rel_cwd == "." else f"/workspace/{rel_cwd}"

        # Workspace mount configuration
        if settings.k8s_volume_claim_name:
            volumes.append(client.V1Volume(
                name="workspace-volume",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=settings.k8s_volume_claim_name
                )
            ))
            volume_mounts.append(client.V1VolumeMount(
                name="workspace-volume",
                mount_path="/workspace"
            ))
        elif settings.k8s_host_path or os.path.exists(workspace_root):
            h_path = settings.k8s_host_path or workspace_root
            volumes.append(client.V1Volume(
                name="workspace-volume",
                host_path=client.V1HostPathVolumeSource(
                    path=h_path,
                    type="Directory"
                )
            ))
            volume_mounts.append(client.V1VolumeMount(
                name="workspace-volume",
                mount_path="/workspace"
            ))

        # Container specification
        container = client.V1Container(
            name="sandbox-runner",
            image=settings.docker_image,
            command=["sh", "-c", command],
            working_dir=container_w,
            volume_mounts=volume_mounts,
            env=[
                client.V1EnvVar(name="PYTHONUSERBASE", value="/workspace/.venv_sandbox"),
                client.V1EnvVar(name="PIP_USER", value="1"),
                client.V1EnvVar(name="PATH", value="/workspace/.venv_sandbox/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
            ],
            resources=client.V1ResourceRequirements(
                limits={"cpu": settings.k8s_cpu_limit, "memory": settings.k8s_memory_limit},
                requests={"cpu": settings.k8s_cpu_request, "memory": settings.k8s_memory_request}
            )
        )

        # Pod specification
        pod_spec = client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=volumes
        )

        if settings.k8s_gvisor_enabled:
            pod_spec.runtime_class_name = settings.k8s_runtime_class_name

        pod = client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={
                    "agentdeep-managed": "true",
                    "agentdeep-task-id": safe_task_id,
                    "agentdeep-agent-id": agent_id
                }
            ),
            spec=pod_spec
        )

        logger.info("Creating sandbox Pod in Kubernetes", pod_name=pod_name, namespace=namespace, gvisor=settings.k8s_gvisor_enabled)
        v1.create_namespaced_pod(namespace, pod)

        pod_output = []
        try:
            # Wait for Pod to run or succeed
            w = watch.Watch()
            pod_started = False
            for event in w.stream(v1.list_namespaced_pod, namespace=namespace, label_selector=f"agentdeep-task-id={safe_task_id}", timeout_seconds=timeout):
                obj = event['object']
                if obj.metadata.name != pod_name:
                    continue
                phase = obj.status.phase
                if phase in ["Running", "Succeeded", "Failed"]:
                    pod_started = True
                    w.stop()
                    break

            if not pod_started:
                return -1, "Pod start timeout"

            # Stream logs
            try:
                log_stream = v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    follow=True,
                    _preload_content=False
                )
                for chunk in log_stream:
                    text = chunk.decode("utf-8", errors="replace")
                    pod_output.append(text)
                    if log_callback:
                        log_callback(text)
            except Exception as log_err:
                logger.warning("Error streaming Pod logs", pod_name=pod_name, error=str(log_err))

            # Wait for pod termination to get exit code
            start_time = time.time()
            exit_code = 0
            while time.time() - start_time < timeout:
                p_status = v1.read_namespaced_pod_status(pod_name, namespace)
                phase = p_status.status.phase
                if phase in ["Succeeded", "Failed"]:
                    container_statuses = p_status.status.container_statuses
                    if container_statuses:
                        state = container_statuses[0].state
                        if state.terminated:
                            exit_code = state.terminated.exit_code
                    break
                time.sleep(0.5)

            return exit_code, "".join(pod_output)

        finally:
            # Cleanup Pod
            try:
                v1.delete_namespaced_pod(pod_name, namespace)
                logger.info("Cleaned up sandbox Pod", pod_name=pod_name)
            except Exception as clean_err:
                logger.error("Failed to delete sandbox Pod", pod_name=pod_name, error=str(clean_err))

    async def _execute_docker(
        self,
        command: str,
        cwd: str,
        task_id: str,
        agent_id: str,
        timeout: int,
        log_callback: Callable[[str], None] = None
    ) -> Tuple[int, str]:
        """Execute command in a Docker container."""
        workspace_root = os.path.abspath(settings.resolved_workspace_path)
        rel_cwd = os.path.relpath(cwd, workspace_root)
        container_w = "/workspace" if rel_cwd == "." else f"/workspace/{rel_cwd}"

        docker_cmd = [
            "docker", "run", "--rm",
            "--label", "agentdeep-managed=true",
            "--label", f"agentdeep-task-id={task_id}",
            "--label", f"agentdeep-agent-id={agent_id}",
            f"--memory={settings.docker_memory_limit}",
            f"--cpus={settings.docker_cpu_limit}",
            f"--pids-limit={settings.docker_pids_limit}",
        ]

        if settings.docker_security_no_new_privs:
            docker_cmd.append("--security-opt=no-new-privileges")

        docker_cmd.extend([
            "-v", f"{workspace_root}:/workspace",
            "-w", container_w,
            "-e", "PYTHONUSERBASE=/workspace/.venv_sandbox",
            "-e", "PIP_USER=1",
            "-e", "PATH=/workspace/.venv_sandbox/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            settings.docker_image,
            "sh", "-c", command
        ])

        logger.info("Executing command inside Docker Sandbox", image=settings.docker_image, command=command)
        return await self._run_subprocess(docker_cmd, cwd, timeout, log_callback)

    async def _execute_host(
        self,
        command: str,
        cwd: str,
        timeout: int,
        log_callback: Callable[[str], None] = None
    ) -> Tuple[int, str]:
        """Execute command directly on the host."""
        env = os.environ.copy()
        venv_dir = Path(__file__).parent.parent.parent.parent / ".venv"
        venv_bin = venv_dir / "bin"
        if venv_bin.exists():
            env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(venv_dir)

        return await self._run_subprocess(command, cwd, timeout, log_callback, env=env)

    async def _run_subprocess(
        self,
        cmd: Any,
        cwd: str,
        timeout: int,
        log_callback: Callable[[str], None] = None,
        env: dict = None
    ) -> Tuple[int, str]:
        """Run a subprocess and stream output."""
        try:
            process = subprocess.Popen(  # nosec B602
                cmd,
                shell=not isinstance(cmd, list),
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env
            )
        except Exception as e:
            logger.error("Failed to start subprocess", error=str(e))
            return -1, f"Failed to start execution: {str(e)}"

        stdout_lines = []
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stdout_lines.append(line)
                if log_callback:
                    log_callback(line)

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            return -1, "Command timed out."

        return process.returncode, "".join(stdout_lines)

    async def prune_zombie_resources(self):
        """GC orphaned Docker containers and Kubernetes Pods."""
        import asyncio
        from src.core.agent.pool import agent_pool
        active_agents = await agent_pool.get_active_agents()
        active_agent_ids = set(active_agents.keys())
        active_task_ids = set(active_agents.values())

        # 1. Clean Docker
        if settings.docker_sandbox_enabled:
            try:
                loop = asyncio.get_running_loop()
                # Query all containers with label agentdeep-managed=true
                # Format: <container_id> <agent_id> <task_id>
                def run_ps():
                    return subprocess.run(
                        [
                            "docker", "ps", "-a",
                            "--filter", "label=agentdeep-managed=true",
                            "--format", '{{.ID}} {{.Label "agentdeep-agent-id"}} {{.Label "agentdeep-task-id"}}'
                        ],
                        capture_output=True, text=True, timeout=10
                    )
                res = await loop.run_in_executor(None, run_ps)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.strip().split()
                        if len(parts) >= 1:
                            container_id = parts[0]
                            container_agent_id = parts[1] if len(parts) > 1 else ""
                            container_task_id = parts[2] if len(parts) > 2 else ""
                            
                            # If the agent ID or task ID is not active, prune it!
                            if container_agent_id not in active_agent_ids and container_task_id not in active_task_ids:
                                logger.info(
                                    "Pruning zombie Docker container",
                                    container_id=container_id,
                                    agent_id=container_agent_id,
                                    task_id=container_task_id
                                )
                                def run_rm(cid):
                                    return subprocess.run(["docker", "rm", "-f", cid], capture_output=True)
                                await loop.run_in_executor(None, run_rm, container_id)
            except Exception as e:
                logger.error("Error pruning zombie Docker containers", error=str(e))

        # 2. Clean Kubernetes
        if settings.k8s_sandbox_enabled:
            try:
                self._init_k8s_client()
                from kubernetes import client
                v1 = client.CoreV1Api()
                namespace = settings.k8s_namespace
                # List managed pods
                pods = v1.list_namespaced_pod(namespace, label_selector="agentdeep-managed=true")
                for pod in pods.items:
                    labels = pod.metadata.labels or {}
                    pod_agent_id = labels.get("agentdeep-agent-id")
                    pod_task_id = labels.get("agentdeep-task-id")
                    
                    is_active = (pod_agent_id in active_agent_ids) or (pod_task_id in active_task_ids)
                    if not is_active:
                        logger.info("Pruning zombie Kubernetes Pod", pod_name=pod.metadata.name)
                        v1.delete_namespaced_pod(pod.metadata.name, namespace)
            except Exception as e:
                logger.error("Error pruning zombie Kubernetes Pods", error=str(e))


sandbox_runtime_manager = SandboxRuntimeManager()
