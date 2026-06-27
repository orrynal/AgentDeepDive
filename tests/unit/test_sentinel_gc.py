import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from src.core.agent.pool import AgentPool
from src.core.workspace.runtime import sandbox_runtime_manager
from src.config import settings

@pytest.mark.asyncio
async def test_sandbox_runtime_manager_prune_zombie_resources():
    # Setup active agents via mocking agent_pool.get_active_agents
    mock_get_active = AsyncMock(return_value={"agent-active": "task-active"})
    
    # Mock settings
    mock_settings = MagicMock()
    mock_settings.docker_sandbox_enabled = True
    mock_settings.k8s_sandbox_enabled = False
    
    # Mock subprocess.run for docker ps and docker rm
    mock_docker_ps_output = (
        "cont-zombie agent-zombie task-zombie\n"
        "cont-active agent-active task-active\n"
    )
    mock_run = MagicMock()
    def side_effect(cmd, *args, **kwargs):
        if "ps" in cmd:
            return MagicMock(returncode=0, stdout=mock_docker_ps_output)
        elif "rm" in cmd:
            return MagicMock(returncode=0, stdout="deleted")
        return MagicMock(returncode=1)
    mock_run.side_effect = side_effect
    
    with patch("src.core.agent.pool.agent_pool.get_active_agents", mock_get_active), \
         patch("src.core.workspace.runtime.settings", mock_settings), \
         patch("subprocess.run", mock_run):
        
        await sandbox_runtime_manager.prune_zombie_resources()
        
        # Verify docker ps was called
        ps_calls = [call for call in mock_run.call_args_list if "ps" in call[0][0]]
        rm_calls = [call for call in mock_run.call_args_list if "rm" in call[0][0]]
        
        assert len(ps_calls) == 1
        assert len(rm_calls) == 1
        assert rm_calls[0][0][0] == ["docker", "rm", "-f", "cont-zombie"]
