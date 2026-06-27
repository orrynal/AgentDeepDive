"""Docker compose helper utilities for AgentDeepDive CLI."""

import os
import subprocess
import shutil
from typing import List, Tuple

def get_project_root() -> str:
    """Get the absolute path to the project root directory."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def get_docker_compose_path() -> str:
    """Get the absolute path to docker-compose.yml."""
    return os.path.join(get_project_root(), "docker", "docker-compose.yml")

def check_docker_environment() -> Tuple[bool, str]:
    """Check if docker and docker compose are available.
    Returns (is_available, error_message).
    """
    if not shutil.which("docker"):
        return False, "Docker command not found in PATH."

    # Test running "docker compose version" or "docker-compose version"
    try:
        res = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
        if res.returncode == 0:
            return True, "docker compose"
    except Exception:
        pass

    try:
        res = subprocess.run(["docker-compose", "version"], capture_output=True, text=True)
        if res.returncode == 0:
            return True, "docker-compose"
    except Exception:
        pass

    return False, "Docker Compose plugin/command is not available."

def run_compose_cmd(args: List[str], stream: bool = False) -> subprocess.CompletedProcess:
    """Run docker compose command with given arguments."""
    is_avail, compose_cmd_name = check_docker_environment()
    if not is_avail:
        raise RuntimeError(compose_cmd_name)

    compose_file = get_docker_compose_path()
    if not os.path.exists(compose_file):
        raise FileNotFoundError(f"Docker Compose file not found at: {compose_file}")

    if compose_cmd_name == "docker compose":
        base_cmd = ["docker", "compose", "-f", compose_file]
    else:
        base_cmd = ["docker-compose", "-f", compose_file]

    cmd = base_cmd + args

    if stream:
        # Stream output directly to the terminal
        return subprocess.run(cmd)
    else:
        return subprocess.run(cmd, capture_output=True, text=True)
