import uuid
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock, AsyncMock
from src.cli.main import cli
from src.cli.context import CLIMode
from src.core.scheduler.models import ScheduledTaskModel

@pytest.fixture
def mock_db():
    mock_session = AsyncMock()
    
    mock_db_ctx = AsyncMock()
    mock_db_ctx.__aenter__.return_value = mock_session
    
    return mock_session, mock_db_ctx

@pytest.fixture
def mock_http():
    mock_client = AsyncMock()
    
    mock_http_ctx = AsyncMock()
    mock_http_ctx.__aenter__.return_value = mock_client
    
    return mock_client, mock_http_ctx

def test_schedule_list_remote(mock_http):
    runner = CliRunner()
    mock_client, mock_http_ctx = mock_http
    
    dummy_tasks = [
        {
            "id": "12345678-1234-5678-1234-567812345678",
            "name": "remote-cron",
            "cron_expression": "0 * * * *",
            "is_active": True,
            "task_description": "Scan"
        }
    ]
    
    # Mock get response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json = lambda: dummy_tasks
    mock_client.get = AsyncMock(return_value=mock_response)
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.REMOTE), \
         patch("src.cli.context.CLIContext.get_http_client", return_value=mock_http_ctx), \
         patch("src.cli.context.CLIContext.get_auth_headers", return_value={}):
         
        result = runner.invoke(cli, ["schedule", "list"])
        assert result.exit_code == 0
        assert "remote-cron" in result.output
        assert "Scan" in result.output

def test_schedule_list_local(mock_db):
    runner = CliRunner()
    mock_session, mock_db_ctx = mock_db
    
    task_model = ScheduledTaskModel(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        name="local-cron",
        cron_expression="*/5 * * * *",
        is_active=False,
        task_description="Scan"
    )
    
    class MockResult:
        def scalars(self):
            class MockScalars:
                def all(self):
                    return [task_model]
            return MockScalars()

    mock_session.execute = AsyncMock(return_value=MockResult())
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.LOCAL), \
         patch("src.cli.context.CLIContext.get_db", return_value=mock_db_ctx), \
         patch("src.cli.context.CLIContext.resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()):
         
        result = runner.invoke(cli, ["schedule", "list"])
        assert result.exit_code == 0
        assert "local-cron" in result.output
        assert "Scan" in result.output

def test_schedule_add_remote(mock_http):
    runner = CliRunner()
    mock_client, mock_http_ctx = mock_http
    
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json = lambda: {"id": "123"}
    mock_client.post = AsyncMock(return_value=mock_response)
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.REMOTE), \
         patch("src.cli.context.CLIContext.get_http_client", return_value=mock_http_ctx), \
         patch("src.cli.context.CLIContext.get_auth_headers", return_value={}):
         
        result = runner.invoke(cli, ["schedule", "add", "-n", "new-task", "-c", "0 0 * * *", "-t", "Daily backup"])
        assert result.exit_code == 0
        assert "Successfully registered scheduled task 'new-task' remotely" in result.output

def test_schedule_add_local(mock_db):
    runner = CliRunner()
    mock_session, mock_db_ctx = mock_db
    
    class MockResult:
        def scalar_one_or_none(self):
            return None  # No duplicates

    mock_session.execute = AsyncMock(return_value=MockResult())
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.LOCAL), \
         patch("src.cli.context.CLIContext.get_db", return_value=mock_db_ctx), \
         patch("src.cli.context.CLIContext.resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()), \
         patch("src.core.scheduler.manager.scheduler_manager.register_task") as mock_reg:
         
        result = runner.invoke(cli, ["schedule", "add", "-n", "local-new", "-c", "12 * * * *", "-t", "Hourly log rotation"])
        assert result.exit_code == 0
        assert "Successfully registered scheduled task 'local-new' locally" in result.output
        mock_reg.assert_called_once()

def test_schedule_delete_remote(mock_http):
    runner = CliRunner()
    mock_client, mock_http_ctx = mock_http
    
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json = lambda: [{"id": "123", "name": "delete-me"}]
    
    mock_del_resp = MagicMock()
    mock_del_resp.status_code = 200
    
    mock_client.get = AsyncMock(return_value=mock_get_resp)
    mock_client.delete = AsyncMock(return_value=mock_del_resp)
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.REMOTE), \
         patch("src.cli.context.CLIContext.get_http_client", return_value=mock_http_ctx), \
         patch("src.cli.context.CLIContext.get_auth_headers", return_value={}):
         
        result = runner.invoke(cli, ["schedule", "delete", "delete-me"])
        assert result.exit_code == 0
        assert "Successfully deleted scheduled task 'delete-me' remotely" in result.output

def test_schedule_delete_local(mock_db):
    runner = CliRunner()
    mock_session, mock_db_ctx = mock_db
    
    task_model = ScheduledTaskModel(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        name="local-del",
        cron_expression="*/5 * * * *",
        is_active=True,
        task_description="Delete local task"
    )
    
    class MockResult:
        def scalar_one_or_none(self):
            return task_model

    mock_session.execute = AsyncMock(return_value=MockResult())
    mock_session.delete = AsyncMock()
    mock_session.commit = AsyncMock()
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.LOCAL), \
         patch("src.cli.context.CLIContext.get_db", return_value=mock_db_ctx), \
         patch("src.cli.context.CLIContext.resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()), \
         patch("src.core.scheduler.manager.scheduler_manager.remove_task") as mock_remove:
         
        result = runner.invoke(cli, ["schedule", "delete", "local-del"])
        assert result.exit_code == 0
        assert "Successfully deleted scheduled task 'local-del' locally" in result.output
        mock_remove.assert_called_once_with("12345678-1234-5678-1234-567812345678")

def test_schedule_toggle_local(mock_db):
    runner = CliRunner()
    mock_session, mock_db_ctx = mock_db
    
    task_model = ScheduledTaskModel(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        name="local-toggle",
        cron_expression="*/5 * * * *",
        is_active=True,
        task_description="Toggle task"
    )
    
    class MockResult:
        def scalar_one_or_none(self):
            return task_model

    mock_session.execute = AsyncMock(return_value=MockResult())
    mock_session.commit = AsyncMock()
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.LOCAL), \
         patch("src.cli.context.CLIContext.get_db", return_value=mock_db_ctx), \
         patch("src.cli.context.CLIContext.resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()), \
         patch("src.core.scheduler.manager.scheduler_manager.remove_task") as mock_remove:
         
        result = runner.invoke(cli, ["schedule", "toggle", "local-toggle", "--inactive"])
        assert result.exit_code == 0
        assert "Successfully disabled scheduled task 'local-toggle' locally" in result.output
        mock_remove.assert_called_once_with("12345678-1234-5678-1234-567812345678")


def test_schedule_trigger_remote(mock_http):
    runner = CliRunner()
    mock_client, mock_http_ctx = mock_http
    
    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json = lambda: [{"id": "123", "name": "trigger-me"}]
    
    mock_trigger_resp = MagicMock()
    mock_trigger_resp.status_code = 200
    
    mock_client.get = AsyncMock(return_value=mock_get_resp)
    mock_client.post = AsyncMock(return_value=mock_trigger_resp)
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.REMOTE), \
         patch("src.cli.context.CLIContext.get_http_client", return_value=mock_http_ctx), \
         patch("src.cli.context.CLIContext.get_auth_headers", return_value={}):
         
        # Test normal remote trigger
        result = runner.invoke(cli, ["schedule", "trigger", "trigger-me"])
        assert result.exit_code == 0
        assert "Successfully triggered scheduled task 'trigger-me' remotely" in result.output
        mock_client.post.assert_called_with(
            "http://localhost:8000/api/v1/schedules/123/trigger",
            params={"force": False},
            headers={},
            timeout=10
        )

        # Test forced remote trigger
        result_force = runner.invoke(cli, ["schedule", "trigger", "trigger-me", "--force"])
        assert result_force.exit_code == 0
        assert "Successfully triggered scheduled task 'trigger-me' remotely" in result_force.output
        mock_client.post.assert_called_with(
            "http://localhost:8000/api/v1/schedules/123/trigger",
            params={"force": True},
            headers={},
            timeout=10
        )


def test_schedule_trigger_local(mock_db, monkeypatch):
    import time
    runner = CliRunner()
    mock_session, mock_db_ctx = mock_db
    
    task_model = ScheduledTaskModel(
        id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        name="local-trigger",
        cron_expression="*/5 * * * *",
        is_active=True,
        task_description="Trigger task"
    )
    
    class MockResult:
        def scalar_one_or_none(self):
            return task_model

    mock_session.execute = AsyncMock(return_value=MockResult())
    
    # Mock circuit breaker to be closed
    from src.core.governance.circuit_breaker import resource_circuit_breaker
    monkeypatch.setattr(resource_circuit_breaker, "state", "CLOSED")
    
    with patch("src.cli.context.CLIContext.detect_mode_async", new_callable=AsyncMock, return_value=CLIMode.LOCAL), \
         patch("src.cli.context.CLIContext.get_db", return_value=mock_db_ctx), \
         patch("src.cli.context.CLIContext.resolve_tenant_id", new_callable=AsyncMock, return_value=uuid.uuid4()), \
         patch("src.core.scheduler.manager.execute_scheduled_task", new_callable=AsyncMock) as mock_exec:
         
        # 1. Closed state -> allowed
        result = runner.invoke(cli, ["schedule", "trigger", "local-trigger"])
        assert result.exit_code == 0
        assert "Successfully triggered scheduled task 'local-trigger' locally" in result.output
        mock_exec.assert_called_once_with("Trigger task", "12345678-1234-5678-1234-567812345678", force=False)
        mock_exec.reset_mock()

        # 2. Open state -> blocked
        monkeypatch.setattr(resource_circuit_breaker, "state", "OPEN")
        monkeypatch.setattr(resource_circuit_breaker, "tripped_at", time.time())
        result_blocked = runner.invoke(cli, ["schedule", "trigger", "local-trigger"])
        assert result_blocked.exit_code == 0
        assert "Circuit Breaker blocked manual trigger" in result_blocked.output
        mock_exec.assert_not_called()

        # 3. Forced in Open state -> allowed
        result_force = runner.invoke(cli, ["schedule", "trigger", "local-trigger", "--force"])
        assert result_force.exit_code == 0
        assert "Successfully triggered scheduled task 'local-trigger' locally" in result_force.output
        mock_exec.assert_called_once_with("Trigger task", "12345678-1234-5678-1234-567812345678", force=True)

