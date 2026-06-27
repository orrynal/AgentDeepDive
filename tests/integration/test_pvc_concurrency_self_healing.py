import os
import pytest
import asyncio
import time
import json
import shutil
from pathlib import Path
from src.core.concurrency.lock_manager import FileLockManager, LockResult
from src.core.redis_pool import get_async_redis_client
from src.config import settings

@pytest.fixture
def pvc_mock_dir():
    # Create a temporary directory representing the shared PVC storage
    pvc_path = Path("tmp_pvc_workspace_mock")
    if pvc_path.exists():
        shutil.rmtree(pvc_path)
    pvc_path.mkdir(parents=True, exist_ok=True)
    yield pvc_path
    if pvc_path.exists():
        shutil.rmtree(pvc_path)


@pytest.fixture
async def redis_lock_cleaner():
    r = get_async_redis_client()
    async for key in r.scan_iter("agentdeep:lock:pvc_test_*"):
        await r.delete(key)
    async for key in r.scan_iter("agentdeep:queue:pvc_test_*"):
        await r.delete(key)
    yield
    async for key in r.scan_iter("agentdeep:lock:pvc_test_*"):
        await r.delete(key)
    async for key in r.scan_iter("agentdeep:queue:pvc_test_*"):
        await r.delete(key)


@pytest.mark.anyio
async def test_pvc_concurrent_self_healing_sim(pvc_mock_dir, redis_lock_cleaner):
    """
    Simulate multiple Kubernetes Pods/Workers concurrently attempting self-healing
    on the same shared file in the PVC directory.
    We test both LocalFileLockStrategy and RedisLockStrategy to ensure:
    1. Only one agent modifies the file at any given moment.
    2. File content transitions through sequential self-healing states without corruption.
    3. Version tracking matches expected linear execution.
    """
    # Create a target codebase file inside the PVC mock directory
    codebase_file = pvc_mock_dir / "target_code.py"
    initial_content = "def hello():\n    return 'initial'\n"
    codebase_file.write_text(initial_content)

    # We will test both strategies
    from src.core.concurrency.lock_manager import LocalFileLockStrategy, RedisLockStrategy
    
    strategies = [
        ("LocalFileLock", LocalFileLockStrategy()),
        ("RedisLock", RedisLockStrategy())
    ]
    
    for strat_name, strategy in strategies:
        # Reset file content
        codebase_file.write_text(initial_content)
        
        # Initialize manager with the specific strategy
        manager = FileLockManager(strategy=strategy)
        
        # 10 concurrent agents trying to self-heal the target file
        num_agents = 10
        execution_order = []
        
        async def mock_self_healing_agent(agent_idx: int):
            agent_id = f"agent-pvc-heal-{agent_idx}"
            task_id = f"task-pvc-heal-{agent_idx}"
            file_path = str(codebase_file)
            
            # Request file lock
            acquired = False
            lock_res = None
            max_retries = 20
            
            for retry in range(max_retries):
                lock_res = await manager.acquire(
                    file_path=file_path,
                    agent_id=agent_id,
                    task_id=task_id,
                    priority=50,
                    ttl_sec=10
                )
                if lock_res.granted:
                    acquired = True
                    break
                # If not granted, wait briefly and retry (simulate event loop waiting)
                await asyncio.sleep(0.05)
                
            assert acquired, f"Agent {agent_id} failed to acquire lock on shared PVC file"
            
            try:
                # Critical Section: Simulate file reading, processing, and writing
                current_text = codebase_file.read_text()
                
                # Append healing log to content
                new_text = current_text + f"# Healed by {agent_id}\n"
                
                # Simulate LLM/diagnostic processing time
                await asyncio.sleep(0.02)
                
                codebase_file.write_text(new_text)
                execution_order.append(agent_id)
            finally:
                # Release lock
                await manager.release(file_path, agent_id)

        # Run all agents concurrently
        tasks = [mock_self_healing_agent(i) for i in range(num_agents)]
        await asyncio.gather(*tasks)
        
        # Verify result:
        # 1. All agents must have successfully executed sequentially
        assert len(execution_order) == num_agents
        assert len(set(execution_order)) == num_agents
        
        # 2. File content must show all healing comments sequentially
        final_content = codebase_file.read_text()
        for idx in range(num_agents):
            agent_id = f"agent-pvc-heal-{idx}"
            assert f"# Healed by {agent_id}" in final_content
            
        # 3. Ensure no partial writes or corruption occurred (exact length check)
        expected_lines = 2 + num_agents
        actual_lines = len(final_content.strip().split("\n"))
        assert actual_lines == expected_lines, f"Expected {expected_lines} lines, got {actual_lines}"
        
        # Clean up strategy
        await manager.close()
