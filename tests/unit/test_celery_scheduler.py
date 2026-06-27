import pytest
from unittest.mock import MagicMock, AsyncMock
from src.config import settings
from src.core.scheduler.manager import execute_scheduled_task

@pytest.mark.anyio
async def test_scheduler_local_fallback(monkeypatch):
    """Test that when celery is disabled, execute_scheduled_task runs locally."""
    # 1. Force disable celery
    monkeypatch.setattr(settings, "celery_enabled", False)
    
    # 2. Mock DAGEngine and split_task to prevent actual heavy execution
    mock_dag = MagicMock()
    mock_dag.dag_id = "test-dag-1"
    mock_dag.status = "SUCCESS"
    mock_dag.nodes = []
    
    mock_split = AsyncMock(return_value=mock_dag)
    monkeypatch.setattr("src.core.orchestrator.task_splitter.split_task", mock_split)
    
    # Mock DAGEngine
    mock_execute = AsyncMock(return_value=mock_dag)
    monkeypatch.setattr("src.core.orchestrator.dag_engine.DAGEngine.execute", mock_execute)
    
    # Mock database session updates
    mock_db = MagicMock()
    monkeypatch.setattr("src.core.scheduler.manager.async_session", mock_db)
    
    # Mock circuit breaker to allow execution
    mock_cb = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr("src.core.governance.circuit_breaker.resource_circuit_breaker.allow_execution", mock_cb)
    
    # 3. Call execute
    await execute_scheduled_task(task_description="Test Local Fallback", task_id=None)
    
    # 4. Assert local components were called
    mock_split.assert_called_once_with("Test Local Fallback")
    mock_execute.assert_called_once()

@pytest.mark.anyio
async def test_scheduler_celery_dispatch(monkeypatch):
    """Test that when celery is enabled, execute_scheduled_task dispatches to Celery queue."""
    # 1. Force enable celery
    monkeypatch.setattr(settings, "celery_enabled", True)
    
    # 2. Mock execute_dag_task_async.delay
    mock_delay = MagicMock()
    monkeypatch.setattr("src.core.celery_tasks.execute_dag_task_async.delay", mock_delay)
    
    # 3. Call execute
    await execute_scheduled_task(task_description="Test Celery Dispatch", task_id="00000000-0000-0000-0000-000000000001", force=True)
    
    # 4. Assert it was dispatched via delay and local execution did not happen
    mock_delay.assert_called_once_with("Test Celery Dispatch", "00000000-0000-0000-0000-000000000001", True)
