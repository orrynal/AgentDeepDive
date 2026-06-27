import uuid
import pytest
import asyncio
from src.core.scheduler.models import ScheduledTaskModel
from src.core.scheduler.manager import SchedulerManager, execute_scheduled_task
from src.core.orchestrator.models import DAGDefinition

class MockConnection:
    async def run_sync(self, func, *args, **kwargs):
        pass

class MockEngineBegin:
    async def __aenter__(self):
        return MockConnection()
    async def __aexit__(self, exc_type, exc, tb):
        pass

class MockEngine:
    def begin(self):
        return MockEngineBegin()

class MockSession:
    async def execute(self, query):
        class MockResult:
            def scalars(self):
                class MockScalars:
                    def all(self):
                        return [
                            ScheduledTaskModel(
                                id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
                                name="test-task",
                                task_description="Execute test",
                                cron_expression="0 * * * *",
                                is_active=True
                            )
                        ]
                return MockScalars()
        return MockResult()

    async def commit(self):
        pass

    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        pass

@pytest.mark.anyio
async def test_scheduler_manager_lifecycle(monkeypatch):
    # Mock database connection and session
    monkeypatch.setattr("src.database.engine", MockEngine())
    monkeypatch.setattr("src.core.scheduler.manager.async_session", lambda: MockSession())

    manager = SchedulerManager()
    
    # 1. Initialize scheduler
    await manager.initialize()
    assert manager._initialized is True
    
    # Check that the job is registered in APScheduler
    job_id = "12345678-1234-5678-1234-567812345678"
    job = manager.scheduler.get_job(job_id)
    assert job is not None
    assert job.name == "test-task"

    # 2. Register updated task
    updated_task = ScheduledTaskModel(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        name="updated-test-task",
        task_description="Execute updated test",
        cron_expression="*/5 * * * *",
        is_active=True
    )
    manager.register_task(updated_task)
    job = manager.scheduler.get_job(job_id)
    assert job is not None
    assert job.name == "updated-test-task"

    # 3. Remove task
    manager.remove_task(job_id)
    assert manager.scheduler.get_job(job_id) is None

    # Shutdown APScheduler scheduler
    manager.scheduler.shutdown()

@pytest.mark.anyio
async def test_execute_scheduled_task(monkeypatch):
    # Mock split_task and DAGEngine.execute
    mock_dag = DAGDefinition(
        dag_id="scheduled-dag-123",
        name="Scheduled Task DAG",
        status="pending"
    )

    async def mock_split_task(desc):
        return mock_dag

    class MockDAGEngine:
        def __init__(self, skill_svc):
            pass
        async def execute(self, dag):
            dag.status = "completed"
            return dag

    # Patch modules
    monkeypatch.setattr("src.core.orchestrator.task_splitter.split_task", mock_split_task)
    monkeypatch.setattr("src.core.orchestrator.dag_engine.DAGEngine", MockDAGEngine)
    monkeypatch.setattr("src.core.scheduler.manager.async_session", lambda: MockSession())

    # Create dummy _dag_store
    mock_dag_store = {}
    monkeypatch.setattr("src.api.routes.dags._dag_store", mock_dag_store)

    await execute_scheduled_task("Execute diagnostic run")

    assert mock_dag_store["scheduled-dag-123"] is mock_dag
    assert mock_dag.status == "completed"
