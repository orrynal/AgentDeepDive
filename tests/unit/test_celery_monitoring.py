import pytest
import asyncio
import time
from unittest.mock import MagicMock
from src.core.celery_monitoring import (
    on_task_prerun,
    on_task_postrun,
    on_task_failure,
    get_celery_task_stats,
    STATS_PREFIX,
)
from src.core.redis_pool import get_async_redis_client, get_redis_client
from src.api.routes.health import get_celery_stats


@pytest.fixture
async def redis_stats_cleaner():
    r = get_async_redis_client()
    async for key in r.scan_iter(f"{STATS_PREFIX}*"):
        await r.delete(key)
    yield
    async for key in r.scan_iter(f"{STATS_PREFIX}*"):
        await r.delete(key)


@pytest.mark.anyio
async def test_celery_monitoring_signals_and_api(redis_stats_cleaner):
    """
    Test that Celery signal triggers update Redis statistics,
    and the API health route returns the correct stats payload.
    """
    # 1. Create a mock Celery task instance
    mock_task = MagicMock()
    mock_task.name = "test.mock_celery_task"
    task_id = "test-task-id-123"

    # 2. Trigger prerun signal
    on_task_prerun(task_id=task_id, task=mock_task, args=(), kwargs={})
    assert hasattr(mock_task, "start_time")

    # Simulate some execution duration
    mock_task.start_time = time.perf_counter() - 0.05  # 50ms ago

    # 3. Trigger postrun signal with SUCCESS status
    on_task_postrun(
        task_id=task_id,
        task=mock_task,
        args=(),
        kwargs={},
        retval="success_output",
        state="SUCCESS",
    )

    # 4. Trigger failure signal for a second task run
    mock_failed_task = MagicMock()
    mock_failed_task.name = "test.mock_celery_task"
    on_task_failure(
        task_id="failed-id-456",
        exception=ValueError("Mock task failure exception"),
        args=(),
        kwargs={},
        traceback_obj=None,
        sender=mock_failed_task,
    )

    # 5. Verify data in Redis directly
    r = get_redis_client()
    key = f"{STATS_PREFIX}test.mock_celery_task"
    assert r.exists(key)
    
    total_runs = r.hget(key, "total_runs")
    success_runs = r.hget(key, "success_runs")
    failure_runs = r.hget(key, "failure_runs")
    last_status = r.hget(key, "last_run_status")
    last_error = r.hget(key, "last_error")

    # Wait, the failure signal doesn't trigger postrun directly unless Celery fires it.
    # But we triggered failure which increments/sets last_error.
    # Since we didn't call postrun on the failed task, it is not marked as failed run.
    # Let's call postrun for failure too to simulate real Celery lifecycle.
    mock_failed_task.start_time = time.perf_counter() - 0.1  # 100ms ago
    on_task_postrun(
        task_id="failed-id-456",
        task=mock_failed_task,
        args=(),
        kwargs={},
        retval=None,
        state="FAILURE",
    )

    total_runs = r.hget(key, "total_runs")
    success_runs = r.hget(key, "success_runs")
    failure_runs = r.hget(key, "failure_runs")
    
    assert total_runs == "2"
    assert success_runs == "1"
    assert failure_runs == "1"
    assert r.hget(key, "last_error") == "Mock task failure exception"

    # 6. Verify via async function
    stats = await get_celery_task_stats()
    assert "test.mock_celery_task" in stats
    task_stats = stats["test.mock_celery_task"]
    assert task_stats["total_runs"] == 2
    assert task_stats["success_runs"] == 1
    assert task_stats["failure_runs"] == 1
    assert task_stats["last_run_status"] == "FAILURE"
    assert task_stats["last_error"] == "Mock task failure exception"
    assert task_stats["avg_duration_ms"] > 0.0

    # 7. Verify via API endpoint
    api_response = await get_celery_stats()
    assert api_response["status"] == "ok"
    assert "stats" in api_response
    assert "test.mock_celery_task" in api_response["stats"]
