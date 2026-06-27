import pytest
from unittest.mock import patch, MagicMock, AsyncMock, mock_open
from click.testing import CliRunner
from src.cli.main import cli

def test_doctor_command():
    runner = CliRunner()
    with patch("src.cli.commands.doctor.check_postgres", return_value=(True, "Connected")):
        with patch("src.cli.commands.doctor.check_redis", return_value=(True, "Connected")):
            with patch("src.cli.commands.doctor.check_socket_port", return_value=True):
                with patch("src.cli.commands.doctor.check_opa", return_value=(True, "Connected")):
                    with patch("src.cli.commands.doctor.check_jaeger", return_value=(True, "Connected")):
                        with patch("os.path.exists", return_value=True):
                            with patch("src.cli.commands.doctor.check_docker_environment", return_value=(True, "docker compose")):
                                result = runner.invoke(cli, ["doctor"])
                                assert result.exit_code == 0
                                assert "AgentDeepDive System Doctor" in result.output
                                assert "Python Version" in result.output
                                assert "PostgreSQL" in result.output
                                assert "Redis" in result.output

def test_infra_up_command():
    runner = CliRunner()
    with patch("src.cli.commands.infra.check_docker_environment", return_value=(True, "docker compose")):
        with patch("src.cli.commands.infra.run_compose_cmd") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["infra", "up"])
            assert result.exit_code == 0
            assert "Starting all infrastructure services" in result.output
            assert "Services started successfully" in result.output
            mock_run.assert_called_once_with(["up", "-d"], stream=True)

def test_infra_down_command():
    runner = CliRunner()
    with patch("src.cli.commands.infra.check_docker_environment", return_value=(True, "docker compose")):
        with patch("src.cli.commands.infra.run_compose_cmd") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = runner.invoke(cli, ["infra", "down"])
            assert result.exit_code == 0
            assert "Stopping and removing infrastructure containers..." in result.output
            assert "Services stopped and containers removed successfully!" in result.output
            mock_run.assert_called_once_with(["down"], stream=True)

def test_infra_status_command():
    runner = CliRunner()
    with patch("src.cli.commands.infra.check_docker_environment", return_value=(True, "docker compose")):
        with patch("src.cli.commands.infra.run_compose_cmd") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"Service": "postgres", "ID": "123456", "Status": "running", "Publishers": [{"PublishedPort": 5432, "Protocol": "tcp"}]}'
            )
            result = runner.invoke(cli, ["infra", "status"])
            assert result.exit_code == 0
            assert "Docker Infrastructure Status" in result.output
            assert "postgres" in result.output

def test_db_migrate_command():
    runner = CliRunner()
    with patch("src.cli.commands.db.run_alembic") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="upgrade completed")
        result = runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0
        assert "Running database migrations" in result.output
        assert "upgrade completed" in result.output
        assert "Database migrations applied successfully" in result.output
        mock_run.assert_called_once_with(["upgrade", "head"])

def test_lock_list_command():
    runner = CliRunner()
    mock_lock_info = MagicMock()
    mock_lock_info.file_path = "test_file.py"
    mock_lock_info.holder_agent = "agent-123"
    mock_lock_info.task_id = "task-456"
    mock_lock_info.priority = 50
    mock_lock_info.acquired_at = 1623580000.0
    mock_lock_info.ttl_sec = 300
    mock_lock_info.version = "1.0"

    with patch("src.cli.commands.lock.lock_manager.list_locks", return_value=[mock_lock_info]):
        result = runner.invoke(cli, ["lock", "list"])
        assert result.exit_code == 0
        assert "Active Concurrency Locks" in result.output
        assert "test_file.py" in result.output
        assert "agent-123" in result.output

def test_lock_show_command():
    runner = CliRunner()
    mock_lock_info = MagicMock()
    mock_lock_info.file_path = "test_file.py"
    mock_lock_info.holder_agent = "agent-123"
    mock_lock_info.task_id = "task-456"
    mock_lock_info.priority = 50
    mock_lock_info.acquired_at = 1623580000.0
    mock_lock_info.ttl_sec = 300
    mock_lock_info.version = "1.0"

    with patch("src.cli.commands.lock.lock_manager.get_lock_info", return_value=mock_lock_info):
        result = runner.invoke(cli, ["lock", "show", "test_file.py"])
        assert result.exit_code == 0
        assert "Lock Details: test_file.py" in result.output
        assert "agent-123" in result.output

def test_audit_list_command():
    runner = CliRunner()
    mock_audit = {
        "id": "1",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "timestamp": "2026-06-13T06:52:20+00:00",
        "event_type": "tool_invoke",
        "agent_id": "agent-abc",
        "task_id": "task-xyz",
        "details": {"cmd": "ls"}
    }
    with patch("src.cli.commands.audit.fetch_audit_logs", return_value=([mock_audit], "Database (Active)")):
        result = runner.invoke(cli, ["audit", "list"], env={"COLUMNS": "200"})
        assert result.exit_code == 0
        assert "Security Audit Logs" in result.output
        assert "agent-abc" in result.output
        assert "tool_invoke" in result.output

def test_audit_purge_command():
    runner = CliRunner()
    with patch("src.cli.commands.audit.async_session") as mock_session_cls:
        mock_session = MagicMock()
        mock_execute_res = MagicMock(rowcount=5)
        mock_session.execute = AsyncMock(return_value=mock_execute_res)
        mock_session.commit = AsyncMock()
        
        mock_manager = MagicMock()
        mock_manager.__aenter__ = AsyncMock(return_value=mock_session)
        mock_manager.__aexit__ = AsyncMock()
        mock_session_cls.return_value = mock_manager

        with patch("os.path.exists", return_value=True):
            with patch("src.cli.commands.audit.open", mock_open(read_data='{"timestamp": 1000.0, "event_type": "tool_invoke", "tenant_id": "00000000-0000-0000-0000-000000000000"}\n')):
                with patch("os.replace") as mock_replace:
                    result = runner.invoke(cli, ["audit", "purge", "--before", "30", "--confirm"])
                    assert result.exit_code == 0
                    assert "Successfully deleted 5 records from PostgreSQL database" in result.output
                    assert "Successfully deleted 1 records" in result.output

def test_opa_status_command():
    runner = CliRunner()
    with patch("src.cli.commands.opa.settings") as mock_settings:
        mock_settings.opa_enabled = False
        mock_settings.opa_url = "http://localhost:8181"
        result = runner.invoke(cli, ["opa", "status"])
        assert result.exit_code == 0
        assert "OPA Enabled in Config: No" in result.output

def test_status_remote_command():
    runner = CliRunner()
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=MagicMock(value="remote")):
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"status": "healthy", "version": "0.1.0"}
            )
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Resolved: REMOTE" in result.output
            assert "API Server" in result.output

def test_status_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL):
        with patch("src.cli.commands.doctor.check_postgres", return_value=(True, "Connected")):
            with patch("src.cli.commands.doctor.check_redis", return_value=(True, "Connected")):
                result = runner.invoke(cli, ["status"])
                assert result.exit_code == 0
                assert "Resolved: LOCAL" in result.output
                assert "postgres" in result.output
                assert "redis" in result.output

def test_run_remote_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.REMOTE):
        with patch("httpx.AsyncClient.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "task_id": "task-123",
                    "status": "completed",
                    "skill_used": "bash_skill",
                    "result": "hello",
                    "trace": {
                        "trace_id": "tr-1",
                        "total_tokens_input": 10,
                        "total_tokens_output": 20
                    }
                }
            )
            result = runner.invoke(cli, ["run", "test task description"])
            assert result.exit_code == 0
            assert "Task Completed: task-123" in result.output
            assert "Status: completed" in result.output

def test_run_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_skill = {"skill_id": "local_skill"}
    mock_executor = MagicMock()
    mock_executor.execute = AsyncMock(return_value={
        "status": "completed",
        "result": "local output",
        "trace": {
            "trace_id": "tr-local",
            "total_tokens_input": 5,
            "total_tokens_output": 8
        }
    })
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL):
        with patch("src.cli.main.CLIContext.get_db") as mock_get_db:
            # Mock async context manager for get_db
            mock_session = MagicMock()
            mock_get_db.return_value.__aenter__.return_value = mock_session
            
            with patch("src.core.skill.router.SkillRouter") as mock_router_cls:
                mock_router = MagicMock()
                mock_router.route = AsyncMock(return_value=[mock_skill])
                mock_router_cls.return_value = mock_router
                
                with patch("src.core.agent.executor.AgentExecutor", return_value=mock_executor):
                    result = runner.invoke(cli, ["run", "test local task"])
                    assert result.exit_code == 0
                    assert "Task Completed (Local): task-" in result.output
                    assert "local output" in result.output

def test_completion_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["completion", "bash"])
    assert result.exit_code == 0
    assert "eval" in result.output
    assert "AGENTDEEP_COMPLETE" in result.output


def test_monitor_command():
    runner = CliRunner()
    
    mock_health = {
        "api": "Connected",
        "api_ms": 10,
        "postgres": "Connected",
        "redis": "Connected",
        "milvus": "Connected",
        "opa": "Connected"
    }
    mock_locks = []
    mock_pool = {
        "max_concurrency": 10,
        "active_count": 0,
        "agents": []
    }
    mock_audits = []

    async def mock_sleep_exit(secs):
        raise KeyboardInterrupt("exit loop")

    with patch("src.cli.commands.monitor.get_system_health", return_value=mock_health), \
         patch("src.cli.commands.monitor.get_active_locks", return_value=mock_locks), \
         patch("src.cli.commands.monitor.get_agent_pool_status", return_value=mock_pool), \
         patch("src.cli.commands.monitor.get_recent_audits", return_value=mock_audits), \
         patch("src.cli.commands.monitor.get_scheduler_tasks", return_value=[]), \
         patch("src.cli.commands.monitor.Live") as mock_live_cls, \
         patch("asyncio.sleep", side_effect=mock_sleep_exit), \
         patch("src.cli.commands.monitor.keyboard_input_loop"):
        
        result = runner.invoke(cli, ["monitor"])
        # KeyboardInterrupt will stop execution, but the loop was entered
        assert result.exit_code == 1 or isinstance(result.exception, KeyboardInterrupt)
        assert mock_live_cls.called


def test_skill_list_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_skills = [
        {
            "skill_id": "test-skill-1",
            "name": "Test Skill 1",
            "version": "1.0.0",
            "risk_level": "low",
            "tags": ["test"],
        }
    ]
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.skill.service.SkillService.list_all", return_value=mock_skills) as mock_list:
        
        mock_session = MagicMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["skill", "list"])
        assert result.exit_code == 0
        assert "Test Skill 1" in result.output
        assert "test-skill-1" in result.output
        mock_list.assert_called_once_with(active_only=True)


def test_skill_register_local_command(tmp_path):
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    # Create temp skill yaml file
    skill_file = tmp_path / "skill.yaml"
    skill_file.write_text("""
skill_id: test-skill-2
name: Test Skill 2
version: 1.0.0
risk_level: high
tags:
  - test2
""")
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.skill.service.SkillService.get_by_id", return_value=None) as mock_get, \
         patch("src.core.skill.service.SkillService.create", return_value={"skill_id": "test-skill-2"}) as mock_create:
        
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["skill", "register", "-f", str(skill_file)])
        assert result.exit_code == 0
        assert "successfully registered locally!" in result.output
        mock_create.assert_called_once()


def test_skill_delete_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.skill.service.SkillService.delete", return_value=True) as mock_delete:
        
        mock_session = MagicMock()
        mock_session.commit = AsyncMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["skill", "delete", "test-skill-2"])
        assert result.exit_code == 0
        assert "successfully deleted locally" in result.output
        mock_delete.assert_called_once_with("test-skill-2")


def test_skill_show_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_skill = {
        "skill_id": "test-skill-3",
        "name": "Test Skill 3",
        "version": "1.0.0",
        "risk_level": "medium",
        "tags": ["test3"],
    }
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.skill.service.SkillService.get_by_id", return_value=mock_skill) as mock_get:
        
        mock_session = MagicMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["skill", "show", "test-skill-3"])
        assert result.exit_code == 0
        assert "test-skill-3" in result.output
        assert "Test Skill 3" in result.output
        mock_get.assert_called_once_with("test-skill-3")


def test_dag_split_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    from src.core.orchestrator.models import DAGDefinition, DAGNode
    
    mock_dag = DAGDefinition(
        dag_id="dag-test-123",
        name="Test DAG",
        nodes=[DAGNode(node_id="step-1", name="Step One", skill_id="test-skill-1")]
    )
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.orchestrator.task_splitter.split_task", return_value=mock_dag) as mock_split, \
         patch("src.core.orchestrator.persistence.save_dag_to_disk") as mock_save:
        
        mock_session = MagicMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["dag", "split", "Decompose this task"])
        assert result.exit_code == 0
        assert "DAG Created (Local): dag-test-123" in result.output
        assert "step-1" in result.output
        mock_split.assert_called_once_with("Decompose this task")
        mock_save.assert_called_once_with(mock_dag, tenant_id='00000000-0000-0000-0000-000000000000')


def test_dag_execute_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    from src.core.orchestrator.models import DAGDefinition
    
    mock_dag = DAGDefinition(dag_id="dag-test-456", name="Test Execute DAG")
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.core.orchestrator.persistence.load_dags_from_disk", return_value={"dag-test-456": mock_dag}), \
         patch("src.core.orchestrator.persistence.save_dag_to_disk") as mock_save, \
         patch("src.core.orchestrator.dag_engine.DAGEngine.execute", return_value=mock_dag) as mock_exec:
        
        mock_session = MagicMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, ["dag", "execute", "dag-test-456"])
        assert result.exit_code == 0
        assert "DAG Executed/Status updated (Local): dag-test-456" in result.output
        mock_exec.assert_called_once()
        mock_save.assert_called_once_with(mock_dag, tenant_id='00000000-0000-0000-0000-000000000000')


def test_dag_status_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    from src.core.orchestrator.models import DAGDefinition
    
    mock_dag = DAGDefinition(dag_id="dag-test-789", name="Test Status DAG")
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.orchestrator.persistence.load_dags_from_disk", return_value={"dag-test-789": mock_dag}):
        
        result = runner.invoke(cli, ["dag", "status", "dag-test-789"])
        assert result.exit_code == 0
        assert "DAG ID (Local): dag-test-789" in result.output


def test_budget_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_summary = {
        "monthly_limit_usd": 100.0,
        "spent_usd": 15.25,
        "remaining_usd": 84.75,
    }
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.budget.manager.budget_manager.get_summary", return_value=mock_summary):
        
        result = runner.invoke(cli, ["budget"])
        assert result.exit_code == 0
        assert "Token Budget Usage Summary" in result.output
        assert "Local" in result.output
        assert "$100.00" in result.output
        assert "$15.2500" in result.output


def test_pool_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.agent.pool.agent_pool.get_active_agents", return_value={"agent-1": "task-1"}), \
         patch("src.core.agent.pool.agent_pool.max_concurrency", 12):
        
        result = runner.invoke(cli, ["pool"])
        assert result.exit_code == 0
        assert "Agent Concurrency Pool Status" in result.output
        assert "Local" in result.output
        assert "12" in result.output
        assert "agent-1" in result.output


def test_approval_list_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_approvals = [
        {
            "approval_id": "app-123",
            "task_id": "task-123",
            "tool_name": "bash",
            "arguments": {"cmd": "ls"},
        }
    ]
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.governance.approval.approval_manager.get_pending_approvals", return_value=mock_approvals):
        
        result = runner.invoke(cli, ["approval", "list"])
        assert result.exit_code == 0
        assert "Pending Human Approvals (Local)" in result.output
        assert "app-123" in result.output


def test_approval_approve_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.governance.approval.approval_manager.approve") as mock_approve:
        
        result = runner.invoke(cli, ["approval", "approve", "app-123"])
        assert result.exit_code == 0
        assert "Approved (Local): app-123" in result.output
        mock_approve.assert_called_once_with("app-123")


def test_approval_reject_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.core.governance.approval.approval_manager.reject") as mock_reject:
        
        result = runner.invoke(cli, ["approval", "reject", "app-123"])
        assert result.exit_code == 0
        assert "Rejected (Local): app-123" in result.output
        mock_reject.assert_called_once_with("app-123")


def test_evolution_evaluate_local_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_eval = {
        "score": 0.85,
        "rule_score": 0.9,
        "judge_a_score": 0.8,
        "judge_b_score": 0.85,
        "feedback": "Good job",
    }
    
    with patch("src.cli.main.CLIContext.detect_mode_async", return_value=CLIMode.LOCAL), \
         patch("src.cli.main.CLIContext.get_db") as mock_get_db, \
         patch("src.evolution.evaluator.evaluator.evaluate_trace", return_value=mock_eval) as mock_evaluate:
        
        mock_session = MagicMock()
        mock_get_db.return_value.__aenter__.return_value = mock_session
        
        result = runner.invoke(cli, [
            "evolution", "evaluate",
            "--task-id", "task-123",
            "--task-desc", "description",
            "--skill-id", "skill-123",
            "--output", "agent output"
        ])
        assert result.exit_code == 0
        assert "Evaluation Completed (Local)" in result.output
        assert "Consensus Score: 85.0" in result.output
        mock_evaluate.assert_called_once()


def test_auth_register_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {
        "tenant": {"id": "12345"},
        "user": {"username": "admin_test"}
    }
    
    with patch("src.cli.commands.auth.CLIContext.detect_mode_async", return_value=CLIMode.REMOTE), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        
        result = runner.invoke(cli, ["auth", "register", "-t", "acme", "-u", "admin_test", "-p", "password123"])
        assert result.exit_code == 0
        assert "Successfully registered tenant 'acme' and user 'admin_test'" in result.output
        assert "Tenant ID: 12345" in result.output


def test_auth_login_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "mock-token",
        "tenant_id": "tenant-uuid",
        "role": "admin"
    }
    
    with patch("src.cli.commands.auth.CLIContext.detect_mode_async", return_value=CLIMode.REMOTE), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("src.cli.commands.auth.CLIContext.save_auth") as mock_save:
        mock_post.return_value = mock_resp
        
        result = runner.invoke(cli, ["auth", "login", "-u", "admin_test", "-p", "password123"])
        assert result.exit_code == 0
        assert "Successfully logged in as 'admin_test'" in result.output
        mock_save.assert_called_once_with("mock-token", "admin_test", "tenant-uuid", "admin")


def test_auth_logout_command():
    runner = CliRunner()
    with patch("src.cli.commands.auth.CLIContext.clear_auth") as mock_clear:
        result = runner.invoke(cli, ["auth", "logout"])
        assert result.exit_code == 0
        assert "Successfully logged out" in result.output
        mock_clear.assert_called_once()


def test_auth_me_command():
    runner = CliRunner()
    from src.cli.context import CLIMode
    
    mock_auth = {
        "username": "admin_test",
        "tenant_id": "tenant-uuid",
        "role": "admin",
        "access_token": "token"
    }
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "user-uuid",
        "username": "admin_test",
        "tenant_id": "tenant-uuid",
        "role": "admin"
    }
    
    with patch("src.cli.commands.auth.CLIContext.load_auth", return_value=mock_auth), \
         patch("src.cli.commands.auth.CLIContext.detect_mode_async", return_value=CLIMode.REMOTE), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        
        result = runner.invoke(cli, ["auth", "me"])
        assert result.exit_code == 0
        assert "Active Session Profile" in result.output
        assert "Remote" in result.output
        assert "admin_test" in result.output
        assert "tenant-uuid" in result.output


def test_cli_help_option_alias():
    runner = CliRunner()
    result = runner.invoke(cli, ["-h"])
    assert result.exit_code == 0
    assert "Show system status and connectivity." in result.output
    assert "Show this message and exit." in result.output


def test_status_channels_command():
    runner = CliRunner()
    from src.config import settings
    
    # Mock settings values to cover both configured and unconfigured paths
    with patch.object(settings, "telegram_bot_token", "mock-telegram-token"), \
         patch.object(settings, "telegram_chat_id", "mock-chat-id"), \
         patch.object(settings, "discord_bot_token", ""), \
         patch.object(settings, "wechat_webhook_url", "https://qyapi.weixin.qq.com/webhook-mock"), \
         patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
         
        # Mock telegram API response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": {"username": "AgentDeepBot"}}
        mock_get.return_value = mock_resp
        
        result = runner.invoke(cli, ["status", "--channels"])
        assert result.exit_code == 0
        assert "AgentDeepDive Third-Party Integrations Status" in result.output
        assert "Telegram Bot" in result.output
        assert "Connected" in result.output
        assert "@AgentDeepBot" in result.output
        assert "Discord Bot" in result.output
        assert "Unconfigured" in result.output
        assert "WeChat (WeCom)" in result.output
        assert "Webhook Ready" in result.output


def test_lazy_group_help_optimization():
    # Verify that get_command returns a lightweight click.Command with help string
    # when printing top-level help (i.e. no subcommand in sys.argv),
    # but returns the real command when a subcommand is in sys.argv.
    from src.cli.main import LazyGroup
    import click
    import sys
    import os

    group = LazyGroup()
    ctx = click.Context(group)

    # 1. Test top-level help case: sys.argv contains no subcommands
    with patch("sys.argv", ["agentdeep", "--help"]), \
         patch.dict(os.environ, {"AGENTDEEP_TESTING_LAZY_HELP": "1"}):
        cmd = group.get_command(ctx, "doctor")
        assert isinstance(cmd, click.Command)
        assert cmd.help == "Diagnose local environment health and service dependencies."
        # Verify it is not the actual doctor_cmd object (which has a callback)
        assert cmd.callback is None

    # 2. Test execution case: sys.argv contains a subcommand
    with patch("sys.argv", ["agentdeep", "doctor"]):
        cmd = group.get_command(ctx, "doctor")
        assert cmd is not None
        assert cmd.callback is not None  # The real command has a callback function


def test_monitor_sqlalchemy_log_suppression():
    # Verify that running monitor_command sets sqlalchemy.engine logger level to WARNING
    from src.cli.commands.monitor import monitor_command
    import logging
    import click

    # Get the logger and reset its level for the test
    logger = logging.getLogger("sqlalchemy.engine")
    original_level = logger.level
    logger.setLevel(logging.INFO)

    ctx = click.Context(monitor_command)
    ctx.obj = MagicMock()
    from src.cli.context import CLIMode
    ctx.obj.detect_mode_async = AsyncMock(return_value=CLIMode.LOCAL)
    ctx.obj.resolved_mode = CLIMode.LOCAL

    # Mock Live and asyncio.sleep to return immediately, and mock monitor dashboard data fetches
    dummy_health = {
        "api": "Disconnected",
        "api_ms": None,
        "postgres": "Disconnected",
        "redis": "Disconnected",
        "milvus": "Disconnected",
        "opa": "Disconnected"
    }
    dummy_pool = {
        "max_concurrency": 10,
        "active_count": 0,
        "agents": []
    }
    with patch("src.cli.commands.monitor.Live") as mock_live, \
         patch("asyncio.sleep", side_effect=[None, KeyboardInterrupt()]), \
         patch("src.cli.commands.monitor.keyboard_input_loop", return_value=None), \
         patch("src.cli.commands.monitor.get_system_health", new_callable=AsyncMock, return_value=dummy_health), \
         patch("src.cli.commands.monitor.get_active_locks", new_callable=AsyncMock, return_value=[]), \
         patch("src.cli.commands.monitor.get_agent_pool_status", new_callable=AsyncMock, return_value=dummy_pool), \
         patch("src.cli.commands.monitor.get_recent_audits", new_callable=AsyncMock, return_value=[]), \
         patch("src.cli.commands.monitor.get_scheduler_tasks", new_callable=AsyncMock, return_value=[]):
        try:
            # Invoke the wrapped click callback synchronously inside context scope
            with ctx:
                monitor_command.callback(2.0)
        except KeyboardInterrupt:
            pass

    assert logger.level == logging.WARNING
    # Restore original level
    logger.setLevel(original_level)


def test_lightweight_option():
    runner = CliRunner()
    from src.config import settings
    from src.cli.context import CLIContext

    original_mode = settings.system_mode
    original_override = CLIContext.mode_override

    try:
        # We invoke status with --lightweight option
        result = runner.invoke(cli, ["--lightweight", "status"])
        assert result.exit_code == 0
        assert settings.system_mode == "lightweight"
        assert CLIContext.mode_override == "local"
    finally:
        settings.system_mode = original_mode
        CLIContext.mode_override = original_override







