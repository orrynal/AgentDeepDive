import os
import shutil
import pytest
from pathlib import Path
from sqlalchemy import text
from src.config import settings
from src.database import get_db, Base
from src.core.concurrency.lock_manager import FileLockManager

# Import all models to register them with Base.metadata
from src.core.auth.models import TenantModel, UserModel
from src.core.skill.models import SkillModel
from src.core.role.models import RoleModel
from src.core.scheduler.models import ScheduledTaskModel

@pytest.fixture(autouse=True)
def setup_lightweight_mode():
    # Save original system mode
    original_mode = settings.system_mode
    settings.system_mode = "lightweight"
    
    # Clean up lock directory and db file
    lock_dir = Path(".locks")
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
        
    db_file = Path("agentdeep.db")
    if db_file.exists():
        db_file.unlink()
        
    yield
    
    # Restore original system mode
    settings.system_mode = original_mode
    
    # Clean up lock directory and db file
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
    if db_file.exists():
        db_file.unlink()

@pytest.mark.anyio
async def test_database_lightweight_url():
    # 1. Verify URL is SQLite
    assert settings.database_url.startswith("sqlite")
    
    # 2. Test engine creation and simple query execution
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    engine = create_async_engine(settings.database_url, echo=False)
    
    async with engine.begin() as conn:
        # Create all tables on SQLite
        await conn.run_sync(Base.metadata.create_all)
        
        # Test basic query
        res = await conn.execute(text("SELECT 1"))
        assert res.scalar() == 1
        
    await engine.dispose()

@pytest.mark.anyio
async def test_file_lock_manager_lightweight():
    manager = FileLockManager()
    file_path = "src/core/agent/test_lock.py"
    
    # Ensure lock dir is created
    lock_dir = Path(".locks")
    
    # 1. Acquire direct lock
    res1 = await manager.acquire(file_path, "agent-1", "task-1", priority=50)
    assert res1.granted is True
    assert res1.holder_agent == "agent-1"
    
    # Check directory and files created
    assert lock_dir.exists()
    
    # Check lock info
    lock_info = await manager.get_lock_info(file_path)
    assert lock_info is not None
    assert lock_info.holder_agent == "agent-1"
    assert lock_info.priority == 50
    assert lock_info.file_path == file_path

    # 2. Lock contention: enqueue lower priority request
    res2 = await manager.acquire(file_path, "agent-2", "task-2", priority=60)
    assert res2.granted is False
    assert res2.holder_agent == "agent-1"
    assert res2.queue_position == 1

    # 3. Lock preemption: high priority request (diff > 30, e.g., 95 - 50 = 45)
    res3 = await manager.acquire(file_path, "agent-3", "task-3", priority=95)
    assert res3.granted is True
    assert res3.holder_agent == "agent-3"
    assert res3.preempted_agent == "agent-1"

    # 4. Release lock - should promote highest in queue (agent-2)
    next_holder = await manager.release(file_path, "agent-3")
    assert next_holder == "agent-2"
    
    # Check lock info again
    lock_info2 = await manager.get_lock_info(file_path)
    assert lock_info2 is not None
    assert lock_info2.holder_agent == "agent-2"

    # 5. Release promoted lock
    next_holder2 = await manager.release(file_path, "agent-2")
    assert next_holder2 is None
    assert await manager.get_lock_info(file_path) is None

@pytest.mark.anyio
async def test_file_lock_manager_lightweight_release_all():
    manager = FileLockManager()
    
    # Acquire multiple locks
    await manager.acquire("file1.py", "agent-100", "task-100")
    await manager.acquire("file2.py", "agent-100", "task-200")
    await manager.acquire("file3.py", "agent-200", "task-300")
    
    # Verify locks exist
    assert await manager.get_lock_info("file1.py") is not None
    assert await manager.get_lock_info("file2.py") is not None
    assert await manager.get_lock_info("file3.py") is not None
    
    # Release all for agent-100
    await manager.release_all_for_agent("agent-100")
    
    # Verify locks for agent-100 are released, while agent-200 lock remains
    assert await manager.get_lock_info("file1.py") is None
    assert await manager.get_lock_info("file2.py") is None
    assert await manager.get_lock_info("file3.py") is not None
