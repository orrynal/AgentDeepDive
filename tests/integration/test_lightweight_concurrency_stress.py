import os
import shutil
import asyncio
import tempfile
import time
import random
import uuid
from pathlib import Path
import pytest
from sqlalchemy import select, func
from src.config import settings
from src.database import Base, async_session, engine
from src.core.concurrency.lock_manager import FileLockManager
from src.core.auth.models import TenantModel
from src.core.governance.models import AuditLogModel
from src.core.orchestrator.models import DAGDefinition, DAGNode, DAGEdge, NodeColor
from src.core.orchestrator.dag_engine import DAGEngine

# Import all models to register them with Base.metadata
from src.core.auth.models import UserModel
from src.core.skill.models import SkillModel
from src.core.role.models import RoleModel
from src.core.scheduler.models import ScheduledTaskModel


@pytest.fixture
async def setup_temp_sqlite_db():
    # Save original database URL and system mode
    original_db_url = settings.database_url_override
    original_mode = settings.system_mode
    
    # Create temp db file path
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "agentdeep_stress.db"
    temp_db_url = f"sqlite+aiosqlite:///{db_path}"
    
    settings.database_url_override = temp_db_url
    settings.system_mode = "lightweight"
    
    # Force rebuild the engine proxy
    # Since LazyEngineProxy initializes engine lazily, resetting current_url forces it
    from src.database import engine as db_engine
    db_engine._engine = None
    db_engine._current_url = None
    
    # Create tables
    async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    yield db_path
    
    # Clean up
    from src.database import engine as db_engine
    if db_engine._engine:
        await db_engine.dispose()
    
    settings.database_url_override = original_db_url
    settings.system_mode = original_mode
    db_engine._engine = None
    db_engine._current_url = None
    
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


@pytest.mark.anyio
async def test_sqlite_concurrent_writes_stress(setup_temp_sqlite_db):
    """Stress test SQLite database concurrently with multiple async writer sessions."""
    tenant_uuid = uuid.uuid4()
    
    # Seed a tenant first
    async with async_session() as session:
        tenant = TenantModel(
            id=tenant_uuid,
            name="Stress Tenant"
        )
        session.add(tenant)
        await session.commit()

    num_workers = 30
    writes_per_worker = 5

    async def worker_write(worker_id: int):
        for step in range(writes_per_worker):
            # Introduce slight random delay to interleave transactions
            await asyncio.sleep(random.uniform(0.005, 0.02))
            async with async_session() as session:
                log = AuditLogModel(
                    id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    event_type="write_stress",
                    task_id=f"task-{worker_id}-{step}",
                    agent_id=f"worker-{worker_id}",
                    details={"worker_id": worker_id, "step": step}
                )
                session.add(log)
                await session.commit()

    # Run concurrently
    tasks = [worker_write(i) for i in range(num_workers)]
    await asyncio.gather(*tasks)

    # Verify count
    async with async_session() as session:
        res = await session.execute(select(func.count()).select_from(AuditLogModel))
        total_count = res.scalar()
        assert total_count == num_workers * writes_per_worker


@pytest.mark.anyio
async def test_file_lock_concurrency_stress():
    """Stress test FileLockManager under lightweight mode with high concurrency, preemption and queuing."""
    # Ensure system_mode is lightweight
    original_mode = settings.system_mode
    settings.system_mode = "lightweight"
    
    lock_dir = Path(".locks")
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
    os.makedirs(lock_dir, exist_ok=True)
    
    manager = FileLockManager()
    file_path = "src/core/stress_shared_resource.py"
    
    num_tasks = 25
    execution_order = []
    
    async def lock_worker(worker_id: int, priority: int):
        # Stagger start slightly
        await asyncio.sleep(random.uniform(0.001, 0.01))
        
        task_id = f"task-{worker_id}"
        agent_id = f"agent-{worker_id}"
        
        acquired = False
        attempts = 0
        while not acquired and attempts < 100:
            res = await manager.acquire(
                file_path=file_path,
                agent_id=agent_id,
                task_id=task_id,
                priority=priority,
                ttl_sec=5  # Short TTL for stress test
            )
            if res.granted:
                acquired = True
                execution_order.append((worker_id, priority))
                # Simulate critical section work
                await asyncio.sleep(0.02)
                await manager.release(file_path, agent_id)
            else:
                # Wait for lock release or retry
                await asyncio.sleep(0.01)
                attempts += 1
                
        assert acquired, f"Worker {worker_id} failed to acquire lock after 100 attempts"

    # Run tasks with random priorities
    workers = [
        lock_worker(i, priority=random.choice([20, 50, 80, 95]))
        for i in range(num_tasks)
    ]
    await asyncio.gather(*workers)
    
    # Assert all tasks executed
    assert len(execution_order) == num_tasks
    
    # Clean up lock directory
    if lock_dir.exists():
        shutil.rmtree(lock_dir)
        
    settings.system_mode = original_mode


@pytest.mark.anyio
async def test_dag_execution_with_sqlite_and_lock_stress(setup_temp_sqlite_db, monkeypatch):
    """Stress test executing a DAG where nodes run concurrently, writing to SQLite and acquiring file locks."""
    tenant_uuid = uuid.uuid4()
    
    # 1. Seed Tenant, User, and Skills in the temp SQLite database
    async with async_session() as session:
        tenant = TenantModel(id=tenant_uuid, name="Stress DAG Tenant")
        session.add(tenant)
        
        # Add 2 mock skills that will be used by our nodes
        skill_a = SkillModel(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            skill_id="skill_read",
            name="Read Skill",
            version="1.0.0",
            description="read",
            tags=[],
            trigger_patterns=[],
            required_tools=[],
            input_schema={},
            output_schema={},
            system_prompt="read content",
            risk_level="low",
            approval_required=False,
            is_active=True
        )
        skill_b = SkillModel(
            id=uuid.uuid4(),
            tenant_id=tenant_uuid,
            skill_id="skill_write",
            name="Write Skill",
            version="1.0.0",
            description="write",
            tags=[],
            trigger_patterns=[],
            required_tools=[],
            input_schema={},
            output_schema={},
            system_prompt="write content",
            risk_level="low",
            approval_required=False,
            is_active=True
        )
        session.add_all([skill_a, skill_b])
        await session.commit()

    # 2. Build a DAG with 20 nodes in a wide, highly concurrent structure (2 layers, 10 nodes per layer)
    nodes = []
    edges = []
    
    # Layer 0: 10 parallel nodes
    for idx in range(10):
        nodes.append(DAGNode(
            node_id=f"L0N{idx}",
            name=f"Read node {idx}",
            skill_id="skill_read",
            dependencies=[]
        ))
        
    # Layer 1: 10 parallel nodes dependent on Layer 0 nodes
    for idx in range(10):
        deps = [f"L0N{i}" for i in range(10)]
        nodes.append(DAGNode(
            node_id=f"L1N{idx}",
            name=f"Write node {idx}",
            skill_id="skill_write",
            dependencies=deps
        ))
        for dep in deps:
            edges.append(DAGEdge(from_node=dep, to_node=f"L1N{idx}"))
            
    dag = DAGDefinition(
        dag_id="dag-stress-20",
        name="20 Node SQLite & Lock Stress DAG",
        tenant_id=str(tenant_uuid),
        nodes=nodes,
        edges=edges,
        routing_tier="small"  # small triggers lightweight direct routing bypass
    )

    # 3. Mock external services: LiteLLM, Verifiers, and Central Brain
    from src.core.evolution.ab_manager import ab_manager
    from src.core.orchestrator import persistence
    from src.core.orchestrator.central_brain import central_brain
    import litellm
    from unittest.mock import AsyncMock

    monkeypatch.setattr(central_brain, "check_budget_safety", AsyncMock(return_value=True))
    
    async def mock_get_routing_decision(skill_id):
        return skill_id
    monkeypatch.setattr(ab_manager, "get_routing_decision", mock_get_routing_decision)
    monkeypatch.setattr(persistence, "save_dag_to_disk", lambda d: None)
    
    # Mock LiteLLM
    class MockChoiceMessage:
        def __init__(self, content):
            self.content = content
            self.tool_calls = None
        def model_dump(self):
            return {"role": "assistant", "content": self.content}
            
    class MockChoice:
        def __init__(self, content):
            self.message = MockChoiceMessage(content)
            
    class MockUsage:
        def __init__(self):
            self.prompt_tokens = 5
            self.completion_tokens = 5
            self.total_tokens = 10
            
    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoice(content)]
            self.usage = MockUsage()
            
    async def mock_acompletion(*args, **kwargs):
        # Introduce a tiny sleep to simulate concurrent task execution
        await asyncio.sleep(0.01)
        return MockResponse('{"status": "completed", "result": "Success"}')
        
    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # Mock Multi-Layered Verification System
    from src.core import verification
    async def mock_verify_invariants(dag_def, node_def):
        return {"success": True, "details": "invariants pass"}
    async def mock_run_e2e_tests(dag_def, node_def):
        return {"success": True, "details": "e2e pass", "screenshot_path": None}
    async def mock_verify_visuals_with_vlm(dag_def, node_def, screenshot):
        return {"success": True, "details": "vlm pass"}

    monkeypatch.setattr(verification, "verify_invariants", mock_verify_invariants)
    monkeypatch.setattr(verification, "run_e2e_tests", mock_run_e2e_tests)
    monkeypatch.setattr(verification, "verify_visuals_with_vlm", mock_verify_visuals_with_vlm)

    # 4. Patch GeneralistAgent.execute_node to perform concurrent SQLite insert and file locking
    from src.core.agent.generalist import GeneralistAgent
    
    original_execute_node = GeneralistAgent.execute_node
    lock_manager = FileLockManager()
    
    async def patched_execute_node(self, *args, **kwargs):
        task_id = kwargs.get("task_id") or args[0]
        t_id = kwargs.get("tenant_id") or str(tenant_uuid)
        
        # a) Perform SQLite insert
        async with async_session() as session:
            log = AuditLogModel(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(t_id),
                event_type="node_execution",
                task_id=task_id,
                agent_id="dag_stress_agent",
                details={"node_info": task_id}
            )
            session.add(log)
            await session.commit()
            
        # b) Perform Lock acquire and release
        lock_acquired = False
        shared_file = "shared_lock_test_dag.py"
        for _ in range(50):
            res = await lock_manager.acquire(
                file_path=shared_file,
                agent_id=f"agent-{task_id}",
                task_id=task_id,
                priority=random.randint(10, 99)
            )
            if res.granted:
                lock_acquired = True
                await asyncio.sleep(0.01)  # critical section hold
                await lock_manager.release(shared_file, f"agent-{task_id}")
                break
            else:
                await asyncio.sleep(0.005)
                
        assert lock_acquired, f"Node {task_id} failed to acquire lock in DAG stress test"
        
        # Call original mock-wrapped response
        return {
            "status": "completed",
            "result": "Patched success",
            "trace": {}
        }
        
    monkeypatch.setattr(GeneralistAgent, "execute_node", patched_execute_node)

    # 5. Run DAG execution
    engine = DAGEngine(skill_service=None)
    result_dag = await engine.execute(dag)

    # 6. Assertions
    assert result_dag.status == "completed"
    assert all(n.color == NodeColor.GREEN for n in result_dag.nodes)
    
    # Check that database records exist for all 20 nodes
    async with async_session() as session:
        res = await session.execute(
            select(func.count()).select_from(AuditLogModel).where(AuditLogModel.event_type == "node_execution")
        )
        total_executions = res.scalar()
        assert total_executions == 20
        
    # Check lock directory is clean
    locks = await lock_manager.list_locks()
    assert len(locks) == 0
