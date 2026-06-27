#!/usr/bin/env python
"""AgentDeepDive Sandbox Cleanup Daemon.

Prunes zombie Docker containers and Kubernetes Pods managed by AgentDeepDive,
independent of the main FastAPI process.
Can be run as a daemon or via Cron.
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import redis
    from src.config import settings
except ImportError:
    print("Error: Please run this daemon within the virtual environment.")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "cleanup_daemon.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("sandbox_cleanup_daemon")


def get_active_agents(r_client) -> dict:
    """Fetch active agents and their task IDs from Redis heartbeats."""
    try:
        keys = r_client.keys("agentdeep:heartbeat:*")
        active = {}
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            agent_id = key.split(":")[-1]
            task_id = r_client.get(key)
            if task_id:
                if isinstance(task_id, bytes):
                    task_id = task_id.decode("utf-8")
                active[agent_id] = task_id
        return active
    except Exception as e:
        logger.error(f"Failed to query active agents from Redis: {e}")
        return {}


def prune_zombie_docker_containers(active_agents: dict):
    """Query docker for containers managed by AgentDeepDive and prune orphans or expired ones."""
    try:
        # Check if docker is installed and running
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=5)
    except Exception:
        logger.debug("Docker daemon is not available, skipping Docker cleanup.")
        return

    try:
        # Format: <id>|<agent_id>|<task_id>|<created_at_epoch>
        cmd = [
            "docker", "ps", "-a",
            "--filter", "label=agentdeep-managed=true",
            "--format", "{{.ID}}|{{.Label \"agentdeep-agent-id\"}}|{{.Label \"agentdeep-task-id\"}}|{{.CreatedAt}}"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            logger.error(f"Docker ps command failed: {res.stderr}")
            return

        lines = res.stdout.strip().splitlines()
        for line in lines:
            parts = line.strip().split("|")
            if len(parts) >= 1:
                container_id = parts[0]
                container_agent_id = parts[1] if len(parts) > 1 else ""
                container_task_id = parts[2] if len(parts) > 2 else ""
                created_str = parts[3] if len(parts) > 3 else ""

                should_prune = False
                reason = ""

                # 1. Orphan check: Agent ID not active
                if container_agent_id and container_agent_id not in active_agents:
                    should_prune = True
                    reason = f"Agent '{container_agent_id}' is no longer active"
                
                # 2. Expiration check: Age > 1 hour (3600 seconds)
                if not should_prune and created_str:
                    try:
                        # Docker CreatedAt format e.g. "2026-06-11 15:00:00 +0800 MST"
                        # Simple check: parse using date utility if needed, or check docker inspect
                        inspect_cmd = ["docker", "inspect", "-f", "{{.State.StartedAt}}", container_id]
                        inspect_res = subprocess.run(inspect_cmd, capture_output=True, text=True, timeout=5)
                        if inspect_res.returncode == 0:
                            # e.g., "2026-06-11T07:00:00.123456Z"
                            started_at = inspect_res.stdout.strip().split(".")[0]
                            # Simple parse: convert to timestamp
                            from datetime import datetime
                            # Python 3.11+ can parse ISO strings easily
                            # Replace Z with UTC offset
                            if started_at.endswith("Z"):
                                started_at = started_at[:-1] + "+00:00"
                            start_dt = datetime.fromisoformat(started_at)
                            age = (datetime.now(start_dt.tzinfo) - start_dt).total_seconds()
                            if age > 3600:
                                should_prune = True
                                reason = f"Container age {age:.0f}s exceeds maximum age of 3600s"
                    except Exception as parse_ex:
                        logger.warning(f"Failed to parse container age for {container_id}: {parse_ex}")

                if should_prune:
                    logger.info(f"Pruning Docker container {container_id} (Reason: {reason})")
                    prune_cmd = ["docker", "rm", "-f", container_id]
                    subprocess.run(prune_cmd, capture_output=True, timeout=10)
    except Exception as e:
        logger.error(f"Error while pruning Docker containers: {e}")


def prune_zombie_k8s_pods(active_agents: dict):
    """Query Kubernetes for pods managed by AgentDeepDive and prune orphans or expired ones."""
    if not settings.k8s_sandbox_enabled:
        return

    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            try:
                config.load_kube_config()
            except Exception:
                logger.warning("Kubernetes configuration not found. Skipping K8s cleanup.")
                return

        v1 = client.CoreV1Api()
        namespace = settings.k8s_namespace
        
        # Query pods with label selector
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector="agentdeep-managed=true"
        )

        for pod in pods.items:
            pod_name = pod.metadata.name
            pod_agent_id = pod.metadata.labels.get("agentdeep-agent-id", "")
            
            should_prune = False
            reason = ""

            # 1. Status check: Completed, Succeeded, or Failed
            phase = pod.status.phase
            if phase in ("Succeeded", "Failed"):
                should_prune = True
                reason = f"Pod completed with status: {phase}"

            # 2. Orphan check: Agent ID not active
            if not should_prune and pod_agent_id and pod_agent_id not in active_agents:
                should_prune = True
                reason = f"Agent '{pod_agent_id}' is no longer active"

            # 3. Expiration check: Age > 1 hour
            if not should_prune and pod.status.start_time:
                start_time = pod.status.start_time
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc) - start_time).total_seconds()
                if age > 3600:
                    should_prune = True
                    reason = f"Pod age {age:.0f}s exceeds maximum age of 3600s"

            if should_prune:
                logger.info(f"Pruning Kubernetes Pod {pod_name} (Reason: {reason})")
                try:
                    v1.delete_namespaced_pod(name=pod_name, namespace=namespace, grace_period_seconds=0)
                except client.exceptions.ApiException as api_ex:
                    if api_ex.status != 404:
                        logger.error(f"Failed to delete Pod {pod_name}: {api_ex}")
    except Exception as e:
        logger.error(f"Error while pruning Kubernetes Pods: {e}")


def run_cleanup():
    """Execute a single run of the cleanup daemon."""
    logger.info("Starting sandbox resource cleanup cycle.")
    
    # Connect to Redis
    try:
        r = redis.Redis.from_url(settings.redis_url)
        # Test ping
        r.ping()
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return

    active_agents = get_active_agents(r)
    logger.info(f"Active agents identified: {list(active_agents.keys())}")

    prune_zombie_docker_containers(active_agents)
    prune_zombie_k8s_pods(active_agents)

    logger.info("Sandbox resource cleanup cycle completed.")


if __name__ == "__main__":
    # If '--daemon' arg is passed, run in a continuous loop
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        logger.info("Running Sandbox Cleanup Daemon in loop mode (interval: 60s).")
        while True:
            try:
                run_cleanup()
            except KeyboardInterrupt:
                logger.info("Daemon stopped by user.")
                break
            except Exception as loop_ex:
                logger.error(f"Error in daemon loop: {loop_ex}")
            time.sleep(60)
    else:
        # Default: single run (cron mode)
        run_cleanup()
