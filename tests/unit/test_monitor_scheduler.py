import uuid
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.cli.context import CLIContext, CLIMode
from src.cli.commands.monitor import get_scheduler_tasks, make_layout, layout_has_node
from src.core.scheduler.models import ScheduledTaskModel

@pytest.mark.anyio
async def test_get_scheduler_tasks_remote():
    ctx = CLIContext(api_url="http://localhost:8000/api/v1")
    
    mock_tasks = [
        {
            "id": "12345678-1234-5678-1234-567812345678",
            "name": "remote-job",
            "cron_expression": "0 * * * *",
            "is_active": True,
            "next_run_time": "2026-06-22T10:00:00Z",
            "last_run_time": "2026-06-22T09:00:00Z",
            "last_run_status": "SUCCESS"
        }
    ]
    
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: mock_tasks
    mock_client.get = AsyncMock(return_value=mock_resp)
    
    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__.return_value = mock_client
    
    with patch.object(ctx, "get_http_client", return_value=mock_http_ctx), \
         patch.object(ctx, "get_auth_headers", return_value={}):
         
        tasks = await get_scheduler_tasks(ctx, is_remote=True)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "remote-job"
        assert tasks[0]["next_run_time"] == "2026-06-22T10:00:00Z"
        assert tasks[0]["last_run_status"] == "SUCCESS"


@pytest.mark.anyio
async def test_get_scheduler_tasks_local(monkeypatch):
    ctx = CLIContext()
    
    task_id = uuid.uuid4()
    task_model = ScheduledTaskModel(
        id=task_id,
        name="local-job",
        cron_expression="*/10 * * * *",
        is_active=True,
        task_description="Local test run",
        last_run_status="SUCCESS"
    )
    
    class MockResult:
        def scalars(self):
            class MockScalars:
                def all(self):
                    return [task_model]
            return MockScalars()
            
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MockResult())
    
    mock_db_ctx = AsyncMock()
    mock_db_ctx.__aenter__.return_value = mock_session
    
    # Mock scheduler_manager
    mock_job = MagicMock()
    mock_job.next_run_time = MagicMock()
    mock_job.next_run_time.isoformat.return_value = "2026-06-22T11:00:00Z"
    
    class DummyScheduler:
        def __init__(self):
            self.calls = []
        def get_job(self, job_id):
            self.calls.append(job_id)
            return mock_job
            
    mock_scheduler = DummyScheduler()
    
    monkeypatch.setattr("src.core.scheduler.manager.scheduler_manager.scheduler", mock_scheduler)
    
    with patch.object(ctx, "get_db", return_value=mock_db_ctx), \
         patch.object(ctx, "resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()):
         
        tasks = await get_scheduler_tasks(ctx, is_remote=False)
        assert len(tasks) == 1
        assert tasks[0]["name"] == "local-job"
        assert tasks[0]["next_run_time"] == "2026-06-22T11:00:00Z"
        assert tasks[0]["last_run_status"] == "SUCCESS"
        assert mock_scheduler.calls == [str(task_id)]


def test_monitor_scheduler_layout():
    # Test layout default splits
    layout = make_layout(show_locks=True, show_audits=True, show_schedules=True)
    assert layout_has_node(layout, "system_status")
    assert layout_has_node(layout, "active_locks")
    assert layout_has_node(layout, "agent_pool")
    assert layout_has_node(layout, "scheduler_tasks")
    assert layout_has_node(layout, "recent_audits")
    
    # Toggle schedules off
    layout_no_sched = make_layout(show_locks=True, show_audits=True, show_schedules=False)
    assert layout_has_node(layout_no_sched, "scheduler_tasks") is False
    assert layout_has_node(layout_no_sched, "system_status") is True


def test_schedule_trigger_command_remote():
    from click.testing import CliRunner
    from src.cli.main import cli

    runner = CliRunner()
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json = lambda: [{"id": "11111111-2222-3333-4444-555555555555", "name": "cron-test"}]
    
    mock_trigger_resp = MagicMock()
    mock_trigger_resp.status_code = 200
    mock_trigger_resp.json = lambda: {"status": "triggered"}
    
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.post = AsyncMock(return_value=mock_trigger_resp)
    
    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__.return_value = mock_client

    with patch("src.cli.context.CLIContext.detect_mode_async", return_value=CLIMode.REMOTE), \
         patch("src.cli.context.CLIContext.get_http_client", return_value=mock_http_ctx), \
         patch("src.cli.context.CLIContext.get_auth_headers", return_value={}):
         
        result = runner.invoke(cli, ["schedule", "trigger", "cron-test"])
        assert result.exit_code == 0
        assert "Successfully triggered" in result.output

